(ns lg-animeka.smoke-test
  "Smoke + behaviour tests for the lg-animeka clj port (ADR-2606280030).

  Beyond the Python `tests/test_smoke.py` (registry parity), this verifies the
  pure node logic the original could not run offline: row→item mappings,
  validation guards, stage-status derivation, JSON breakdown parsing, the
  Murakumo endpoint guard, the autopilot conditional route, and the ComfyUI
  quality-workflow shape — all under bb with the DB/LLM/render seams stubbed."
  (:require [clojure.test :refer [deftest is testing]]
            [clojure.set :as set]
            [clojure.string :as str]
            #?(:clj [cheshire.core :as json])
            [langgraph.graph :as g]
            [lg-animeka.server :as server]
            [lg-animeka.util :as u]
            [lg-animeka.store :as store]
            [lg-animeka.llm :as llm]
            [lg-animeka.render :as render]
            [lg-animeka.audit :as audit]
            [lg-animeka.graphs.health :as health]
            [lg-animeka.graphs.list-works :as lw]
            [lg-animeka.graphs.list-cuts :as lc]
            [lg-animeka.graphs.list-episodes :as le]
            [lg-animeka.graphs.get-cut :as gc]
            [lg-animeka.graphs.create-work :as cw]
            [lg-animeka.graphs.add-episode :as ae]
            [lg-animeka.graphs.add-cut :as ac]
            [lg-animeka.graphs.update-cut-stage :as ucs]
            [lg-animeka.graphs.resolve-retake :as rr]
            [lg-animeka.graphs.agent-chat :as chat]
            [lg-animeka.graphs.generate-script :as gs]
            [lg-animeka.graphs.breakdown-scene :as bs]
            [lg-animeka.graphs.autopilot :as ap]))

(def expected-graphs
  #{"health" "list_works" "agent_chat" "get_cut" "list_cuts" "list_episodes"
    "list_retakes" "create_work" "add_episode" "add_cut" "update_cut_stage"
    "submit_retake" "resolve_retake" "generate_script" "generate_storyboard"
    "generate_layout" "generate_keyframe" "generate_inbetween" "generate_background"
    "design_color_model" "autopilot" "cut_runner" "auto_trace_cut" "breakdown_scene"
    "generate_audio" "assemble_episode" "publish_episode"})

;; ── registry parity (mirrors test_smoke.py) ─────────────────────────────────

(deftest graphs-match-expected-set
  (is (= 27 (count server/GRAPHS)))
  (is (= expected-graphs (set (keys server/GRAPHS)))))

(deftest nsid-map-complete-and-resolvable
  (is (= 27 (count server/NSID-MAP)))
  (doseq [[nsid gname] server/NSID-MAP]
    (is (contains? server/GRAPHS gname) (str nsid " → " gname " not in GRAPHS"))))

(deftest all-graphs-non-nil
  (doseq [[nm graph] server/GRAPHS]
    (is (some? graph) (str "GRAPHS[" nm "] nil"))))

;; ── dispatch surface ────────────────────────────────────────────────────────

(deftest ok-endpoint
  (let [r (server/ok)]
    (is (= 200 (:status r)))
    (is (true? (get-in r [:body :ok])))
    (is (= expected-graphs (set (get-in r [:body :graphs]))))))

(deftest unknown-assistant-404
  (is (= 404 (:status (server/dispatch-run {:assistant_id "nope" :input {}})))))

(deftest unknown-nsid-404
  (is (= 404 (:status (server/dispatch-xrpc "com.etzhayyim.animeka.unknownMethod" {})))))

(deftest api-key-guard
  (testing "no key configured → pass" (is (nil? (server/check-api-key ""))))
  (testing "configured key mismatch → 401"
    (binding [server/*api-key* "secret"]
      (is (= 401 (:status (server/dispatch-run {:assistant_id "health"} {:x-api-key "wrong"})))))))

(deftest xrpc-camel-to-snake
  (is (= {:cut_id "x" :work_id "y"}
         (server/xrpc-input->graph-input {:cutId "x" :workId "y"}))))

(deftest xrpc-dispatch-tags-assistant
  (let [r (server/dispatch-xrpc "com.etzhayyim.animeka.health" {})]
    (is (= 200 (:status r)))
    (is (= "health" (get-in r [:body :assistantId])))))

;; ── util ────────────────────────────────────────────────────────────────────

(deftest util-rkey-from-id
  (is (= "cut-1" (u/rkey-from-id "at://did:web:x/com.etzhayyim.animeka.cut/cut-1")))
  (is (= "cut-1" (u/rkey-from-id "cut-1"))))

(deftest util-camel-snake-and-clamp
  (is (= "generate_keyframe" (u/camel->snake "generateKeyframe")))
  (is (= 200 (u/clamp 9999 200 1 200)))
  (is (= 1 (u/clamp -5 200 1 200)))
  (is (= 42 (u/clamp "42" 50 1 200)))
  (is (= 1 (u/clamp "-9" 50 1 200)))
  (is (= 50 (u/clamp "#=(System/exit 1)" 50 1 200)))
  (is (= 50 (u/clamp nil 50 1 200))))

;; ── health graph end-to-end ─────────────────────────────────────────────────

(deftest health-graph-runs
  (let [out (g/invoke health/GRAPH {})]
    (is (contains? out :ok))
    (is (= false (:rw_ok out)) "no RW configured → rw_ok false")))

;; ── list_works mapping ──────────────────────────────────────────────────────

(deftest list-works-unconfigured
  (is (= "RW_URL not set" (:error (g/invoke lw/GRAPH {})))))

(deftest list-works-rows->works
  (binding [store/*rw-url* "stub://rw"
            lw/*fetch* (fn [filters]
                         (is (= 200 (:limit filters)) "limit clamped to 200")
                         [["did:web:owner" "work-1" 1700 (apply str (repeat 2000 "x"))]])]
    (let [out (g/invoke lw/GRAPH {:limit 9999})]
      (is (= 1 (:total out)))
      (is (= "at://did:web:owner/com.etzhayyim.animeka.work/work-1" (-> out :works first :uri)))
      (is (= 1700 (-> out :works first :tsMs)))
      (is (= 1000 (count (-> out :works first :raw))) "raw capped at 1000"))))

;; ── list_cuts row mapping (dual camel/snake keys) ───────────────────────────

(deftest list-cuts-row->item
  (let [item (lc/row->item ["at://x" "cut-1" 3 48 24 "normal" "note"
                            "layout" "{}" "ep1" "wk1" "tc" "ic" "2026"])]
    (is (= 3 (:cutNum item))) (is (= 3 (:cut_num item)))
    (is (= 48 (:durationFrames item))) (is (= 24 (:fps item)))
    (is (= "note" (:dialogueSummary item)))))

(deftest list-episodes-cut-counts
  (binding [store/*rw-url* "stub://rw"
            le/*fetch* (fn [_]
                         {:rows [["at://ep-v" "ep-1" 1 "Pilot" "planning" 1410.0 24 "t" "2026"]]
                          :cut-counts {"at://ep-v" 7}})]
    (let [out (g/invoke le/GRAPH {:work_id "wk-1"})]
      (is (= 1 (:total out)))
      (is (= 7 (-> out :items first :cutCount)))
      (is (= "Pilot" (-> out :items first :titleJP))))))

(deftest list-episodes-requires-work
  (binding [store/*rw-url* "stub://rw"]
    (is (= "work_id is required" (:error (g/invoke le/GRAPH {}))))))

;; ── get_cut grouping ────────────────────────────────────────────────────────

(deftest get-cut-groups-children
  (binding [store/*rw-url* "stub://rw"
            gc/*fetch*
            (fn [_rkey]
              {:cut (into ["at://cut" "repo" "cut-1" "com.etzhayyim.animeka.cut" "T"]
                          (repeat 12 nil))
               :children [(into ["at://kf" "repo" "kf-1" "com.etzhayyim.animeka.keyframe"]
                                (repeat 20 nil))
                          (into ["at://rt" "repo" "rt-1" "com.etzhayyim.animeka.retake"]
                                (repeat 20 nil))]})]
    (let [out (g/invoke gc/GRAPH {:cut_id "cut-1"})]
      (is (= "cut-1" (-> out :cut :rkey)))
      (is (= 1 (count (:keyframes out))))
      (is (= 1 (count (:retakes out))))
      (is (= [] (:layouts out))))))

(deftest get-cut-not-found
  (binding [store/*rw-url* "stub://rw" gc/*fetch* (fn [_] nil)]
    (is (re-find #"cut not found" (:error (g/invoke gc/GRAPH {:cut_id "missing"}))))))

;; ── create_work validation + happy path ─────────────────────────────────────

(deftest create-work-validation
  (binding [store/*rw-url* "stub://rw"]
    (is (= "title is required" (:error (g/invoke cw/GRAPH {}))))))

(deftest create-work-happy
  (let [saved (atom nil)]
    (binding [store/*rw-url* "stub://rw" store/*exec* (fn [_ params] (reset! saved params) nil)]
      (let [out (g/invoke cw/GRAPH {:title "My Work" :id "work-x"})]
        (is (= "work-x" (:result_id out)))
        (is (= "did:web:animeka.etzhayyim.com:work:work-x" (:result_did out)))
        (is (= "planning" (:result_status out)))
        (is (some? @saved))))))

;; ── add_episode / add_cut validation ────────────────────────────────────────

(deftest add-episode-validation
  (binding [store/*rw-url* "stub://rw"]
    (is (= "work_id is required" (:error (g/invoke ae/GRAPH {}))))
    (is (= "title_jp is required" (:error (g/invoke ae/GRAPH {:work_id "w"}))))
    (is (= "episode_num is required" (:error (g/invoke ae/GRAPH {:work_id "w" :title_jp "t"}))))))

(deftest add-episode-happy
  (binding [store/*rw-url* "stub://rw"
            ae/*resolve-work* (fn [_] {:vertex-id "at://wv" :fps 30})
            store/*exec* (fn [_ _] nil)]
    (let [out (g/invoke ae/GRAPH {:work_id "wk-1" :title_jp "第1話" :episode_num 1})]
      (is (re-find #"com.etzhayyim.animeka.episode" (:result_uri out)))
      (is (some? (:result_convo_id out))))))

(deftest add-cut-auto-increments
  (binding [store/*rw-url* "stub://rw"
            ac/*resolve-scene* (fn [_] {:vertex-id "at://sv" :episode-id "ep-1" :fps 24})
            ac/*max-cut-num* (fn [_] 4)
            store/*exec* (fn [_ _] nil)]
    (let [out (g/invoke ac/GRAPH {:scene_id "sc-1" :duration_frames 48})]
      (is (= 5 (:result_cut_num out)) "auto-incremented to max+1"))))

;; ── update_cut_stage priority derivation ────────────────────────────────────

(deftest derive-priority-cases
  (is (= "retake"   (ucs/derive-priority ["pending" "retake" "approved"])))
  (is (= "approved" (ucs/derive-priority ["approved" "approved"])))
  (is (= "approved" (ucs/derive-priority [])) "all-approved over empty → approved (py parity)")
  (is (= "normal"   (ucs/derive-priority ["pending" "approved"]))))

(deftest update-cut-stage-patches-and-saves
  (let [saved (atom nil)]
    (binding [store/*rw-url* "stub://rw"
              ucs/*fetch-cut* (fn [_] {:vertex-id "at://cv" :stage-status {"layout" "approved"} :assignees {}})
              ucs/*save* (fn [v ss as pr] (reset! saved {:v v :ss ss :pr pr}) nil)]
      (let [out (g/invoke ucs/GRAPH {:cut_id "cut-1" :stage "keyframe" :status "approved"})]
        (is (= "keyframe" (:result_stage out)))
        (is (= "approved" (:pr @saved)) "both stages approved → approved")
        (is (= "approved" (get-in @saved [:ss "keyframe"])))))))

;; ── resolve_retake cut-priority logic ───────────────────────────────────────

(deftest resolve-retake-clears-when-no-open
  (binding [store/*rw-url* "stub://rw"
            rr/*fetch-retake* (fn [_] {:vertex-id "at://rv" :cut-id "at://cv"})
            rr/*update-retake* (fn [& _] nil)
            rr/*open-count* (fn [_] 0)
            rr/*clear-cut-priority* (fn [_] nil)]
    (let [out (g/invoke rr/GRAPH {:retake_id "rt-1" :status "resolved"})]
      (is (= "normal" (:result_cut_priority out))))))

(deftest resolve-retake-keeps-retake-when-open
  (binding [store/*rw-url* "stub://rw"
            rr/*fetch-retake* (fn [_] {:vertex-id "at://rv" :cut-id "at://cv"})
            rr/*update-retake* (fn [& _] nil)
            rr/*open-count* (fn [_] 2)]
    (is (= "retake" (:result_cut_priority (g/invoke rr/GRAPH {:retake_id "rt-1" :status "acknowledged"}))))))

;; ── agent_chat ──────────────────────────────────────────────────────────────

(deftest agent-chat-blank-message-errors
  (is (= "message required" (:error (g/invoke chat/GRAPH {:message "  "})))))

(deftest agent-chat-happy-and-persona
  (binding [llm/*chat* (fn [system _user _opts]
                         (is (re-find #"director AI" system) "default persona = director")
                         {:content "Vision set." :model "tier0-general"
                          :prompt-tokens 5 :completion-tokens 3 :total-tokens 8})]
    (let [out (g/invoke chat/GRAPH {:message "What's the vibe?" :work_id "wk-1"})]
      (is (= "Vision set." (:reply out)))
      (is (= 8 (:total_tokens out)))
      (is (= "did:web:animeka.etzhayyim.com:actor:director" (:actor_did out))))))

;; ── generate_script ─────────────────────────────────────────────────────────

(deftest script-count-scenes
  (is (= 3 (gs/count-scenes "SCENE 1:..\nSCENE 2:..\nSCENE 3:.."))))

(deftest generate-script-happy
  (binding [store/*rw-url* "stub://rw"
            gs/*fetch-episode* (fn [_] {:title "Ep" :synopsis "A synopsis"})
            llm/*chat* (fn [_ _ _] {:content "SCENE 1: x\nSCENE 2: y"})
            store/*exec* (fn [_ _] nil)]
    (let [out (g/invoke gs/GRAPH {:episode_id "ep-1"})]
      (is (= 2 (:scene_count_actual out)))
      (is (re-find #"com.etzhayyim.animeka.script" (:script_uri out))))))

(deftest generate-script-requires-episode
  (is (= "episode_id required" (:error (g/invoke gs/GRAPH {})))))

;; ── breakdown_scene JSON parsing ────────────────────────────────────────────

(deftest breakdown-strip-fences
  (is (= "[{\"a\":1}]" (bs/strip-fences "```json\n[{\"a\":1}]\n```"))))

(deftest breakdown-parse-array
  (is (= 2 (count (bs/parse-breakdown "[{\"cutNum\":1},{\"cutNum\":2}]" "scene"))))
  (testing "invalid JSON → single-cut fallback"
    (let [fb (bs/parse-breakdown "not json" "a scene")]
      (is (= 1 (count fb)))
      (is (= "MS" (:shotType (first fb)))))))

(deftest breakdown-happy-clamps-max
  (binding [store/*rw-url* "stub://rw"
            llm/*chat* (fn [_ _ _] {:content "[{\"cutNum\":1},{\"cutNum\":2},{\"cutNum\":3}]"})
            store/*exec* (fn [_ _] nil)]
    (let [out (g/invoke bs/GRAPH {:scene_text "A tense standoff." :episode_id "ep-1" :max_cuts 2})]
      (is (= 2 (count (:cut_ids out))) "clamped to max_cuts=2"))))

;; ── Murakumo endpoint guard ─────────────────────────────────────────────────

(deftest murakumo-guard
  (testing "off-fleet refused"
    (is (thrown? #?(:clj clojure.lang.ExceptionInfo :default :default)
                 (llm/assert-murakumo "https://api.openai.com/v1"))))
  (testing "malformed endpoints are refused"
    (is (thrown? #?(:clj clojure.lang.ExceptionInfo :default :default)
                 (llm/assert-murakumo "not-a-url"))))
  (testing "loopback gateway allowed"
    (is (nil? (llm/assert-murakumo "http://127.0.0.1:4000/v1")))))

(deftest outward-capabilities-fail-closed
  (is (thrown-with-msg? clojure.lang.ExceptionInfo
                        #"explicit chat capability"
                        (llm/chat "system" "user")))
  (is (thrown-with-msg? clojure.lang.ExceptionInfo
                        #"explicit run-server capability"
                        (server/run-server! 2027))))

(deftest injected-murakumo-http-capability-preserves-wire-contract
  (let [seen (atom nil)
        result (llm/chat-with
                (fn [url opts]
                  (reset! seen {:url url :opts opts})
                  {:status 200
                   :body "{\"model\":\"m\",\"choices\":[{\"message\":{\"content\":\" ok \"}}],\"usage\":{\"total_tokens\":3}}"})
                {:url "http://127.0.0.1:4000/v1" :model "m" :timeout-sec 2}
                "system" "user" {:max-tokens 9 :temperature 0.2})]
    (is (= "http://127.0.0.1:4000/v1/chat/completions" (:url @seen)))
    (is (= 2000 (get-in @seen [:opts :timeout])))
    (is (= "ok" (:content result)))
    (is (= 3 (:total-tokens result)))))

(deftest injected-server-capability-receives-portable-handler
  (let [seen (atom nil)
        stop (fn [] :stopped)]
    (is (identical? stop
                    (server/run-server!
                     (fn [handler opts]
                       (reset! seen {:handler handler :opts opts})
                       stop)
                     0)))
    (is (fn? (:handler @seen)))
    (is (= {:port 0} (:opts @seen)))))

;; ── ComfyUI quality-workflow shape (autopilot) ──────────────────────────────

(deftest quality-workflow-shape
  (let [wf (render/quality-workflow {:prompt "p" :w 1024 :h 768 :steps 30 :cfg 6.0})]
    (is (= "CLIPSetLastLayer" (get-in wf ["1" :class_type])))
    (is (= -2 (get-in wf ["1" :inputs :stop_at_clip_layer])) "CLIP skip 2")
    (is (= 30 (get-in wf ["3" :inputs :steps])))
    (is (= 6.0 (get-in wf ["3" :inputs :cfg])))
    (is (= render/ckpt (get-in wf ["4" :inputs :ckpt_name])))
    (is (= 1024 (get-in wf ["5" :inputs :width])))))

;; ── autopilot conditional route + end-to-end with stubbed render ────────────

(deftest autopilot-route-after-storyboard
  (is (= :storyboard_retry (ap/route-after-storyboard {:sb_cid ""})))
  (is (= :layout (ap/route-after-storyboard {:sb_cid "cid123"}))))

(deftest autopilot-runs-with-stubs
  (binding [llm/*chat* (fn [_ _ _] {:content "a calm scene"})
            render/*render-png* (fn [_ _] {:cid "blob-cid"})
            render/*pds-post* (fn [_] {:status "posted"})
            render/*composite* (fn [_] {:output-cid "out-cid"})
            audit/*emit* (fn [_] nil)]
    (let [out (g/invoke ap/GRAPH {})]
      (is (= "blob-cid" (:sb_cid out)) "storyboard rendered → no retry path needed")
      (is (= "blob-cid" (:kf_cid out)))
      (is (= "posted" (:post_status out)))
      (is (true? (:ok out))))))

;; ── cross-tree claims that README.md / docs/operator-quickstart.md make ─────
;;
;; This repo carries four trees (lg/ Python, lg-clj/ this port, kotoba/ TS,
;; appview/ Cloudflare) and only one of them runs here. README.md says so with
;; numbers. Prose rots silently, so each load-bearing number gets an assertion
;; next to the tree it describes — the same discipline the langgraph
;; operator-quickstart uses (superproject scripts/maturity-loop/mutations.edn).
;;
;; These are deliberately two-way: they go red if the situation DEGRADES (a
;; graph is declared that nothing implements) and equally red if it IMPROVES
;; (the missing Python modules get landed, the appview aliases get fixed). Red
;; on improvement is not a false alarm — it means README.md is now wrong and
;; must be corrected. A doc claim nobody can break is a doc claim nobody
;; maintains.
;;
;; :clj only: they read the repo from disk. The rest of this suite is pure.

#?(:clj
   (def repo-root
     "The repo root, found by walking up from the process cwd. The suite is
     started both from lg-clj/ (`bb test`) and from the repo root
     (`bb lg-clj/run_tests.clj`), so neither cwd can be assumed."
     (loop [d (.getCanonicalFile (java.io.File. (System/getProperty "user.dir")))]
       (cond
         (nil? d) nil
         (and (.isFile (java.io.File. d "migration.edn"))
              (.isDirectory (java.io.File. d "lg-clj"))) d
         :else (recur (.getParentFile d))))))

#?(:clj
   (defn- declared-graphs
     "{graph-name module-path} as `lg/langgraph.json` declares them."
     []
     (-> (slurp (java.io.File. repo-root "lg/langgraph.json"))
         (json/parse-string)
         (get "graphs"))))

#?(:clj
   (defn- python-graph-modules []
     (->> (.listFiles (java.io.File. repo-root "lg/lg_animeka/graphs"))
          (map #(.getName %))
          (filter #(str/ends-with? % ".py"))
          (remove #{"__init__.py"})
          (map #(subs % 0 (- (count %) 3)))
          set)))

#?(:clj
   (deftest repo-root-is-findable
     ;; The three tests below silently pass on an empty file set if this is nil,
     ;; which is exactly the "a check that could not run looks like a check that
     ;; found nothing" failure. Assert it separately so that mode is loud.
     (is (some? repo-root) "walked up from cwd without finding migration.edn + lg-clj/")))

#?(:clj
   (deftest python-tree-is-a-stub-not-a-runtime-in-this-repo
     ;; README.md §"What actually runs" says: langgraph.json declares 27 graphs,
     ;; 4 of them exist here, and lg_animeka/server.py — the uvicorn target in
     ;; lg/Dockerfile — is not in this repo at all. Land the missing modules and
     ;; this goes red so the README stops saying "stub".
     (let [declared (set (keys (declared-graphs)))
           present (python-graph-modules)]
       (is (= 27 (count declared)) "lg/langgraph.json no longer declares 27 graphs")
       (is (= 23 (count (remove present declared)))
           (str "declared-but-absent Python modules changed: "
                (sort (remove present declared))))
       (is (= #{"assemble_episode" "autopilot" "generate_audio" "publish_episode"}
              (set/intersection declared present))
           "the set of declared graphs that actually have a module changed")
       (is (not (.exists (java.io.File. repo-root "lg/lg_animeka/server.py")))
           "lg/lg_animeka/server.py appeared — the Dockerfile's uvicorn target is no longer missing"))))

#?(:clj
   (deftest cljc-tree-implements-exactly-the-declared-graph-set
     ;; README.md §"What actually runs" says lg-clj is the complete tree: the
     ;; .cljc files, the dispatch registry, and langgraph.json name the same 27
     ;; graphs. Three sources, one set — drift in any of them is a bug in that
     ;; one, and this says which.
     (let [declared (declared-graphs)
           declared-names (set (keys declared))
           files (->> (.listFiles (java.io.File. repo-root "lg-clj/src/lg_animeka/graphs"))
                      (map #(.getName %))
                      (filter #(str/ends-with? % ".cljc"))
                      (map #(subs % 0 (- (count %) 5)))
                      set)]
       (is (= declared-names files)
           "langgraph.json and lg-clj/src/lg_animeka/graphs/ name different graphs")
       (is (= declared-names (set (keys server/GRAPHS)))
           "langgraph.json and the clj dispatch registry name different graphs")
       ;; ...and each declaration points at the module named after its own key.
       (doseq [[nm modpath] declared]
         (is (= (str "./lg_animeka/graphs/" nm ".py:GRAPH") modpath)
             (str "langgraph.json entry " nm " points at " modpath))))))

#?(:clj
   (deftest appview-cannot-be-built-from-this-repo
     ;; README.md §"What actually runs" says the appview is not buildable here:
     ;; every alias in its wrangler config is an absolute path, so none of them
     ;; resolves against this repo whatever machine it is cloned onto. Asserted
     ;; as "absolute", not as "missing on my laptop" — the defect belongs to the
     ;; file, not to one checkout.
     (let [f (java.io.File. repo-root "appview/etzhayyim-wasm-animeka-an1m3k4x/wrangler.jsonc")
           cfg (-> (slurp f)
                   (str/replace #"(?m)^\s*//.*$" "")
                   (json/parse-string))
           aliases (get cfg "alias")]
       (is (seq aliases) "wrangler.jsonc has no alias map any more")
       (is (= 8 (count aliases)) "the alias count changed")
       (is (every? #(str/starts-with? % "/") (vals aliases))
           (str "an alias is no longer an absolute path — the appview may now be buildable: "
                (remove #(str/starts-with? % "/") (vals aliases)))))))
