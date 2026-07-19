(ns lg-animeka.server
  "lg-animeka dispatch surface — clj port of `lg/lg_animeka/server.py` (ADR-2606280030).

  The Python FastAPI app exposes:
    POST /runs              → invoke a graph synchronously
    POST /runs/stream       → stream graph events as SSE
    POST /xrpc/{nsid}       → XRPC shim (NSID → assistant_id, camelCase→snake_case input)
    GET  /threads/{tid}/state → fetch latest checkpoint
    GET  /ok | /health      → liveness / readiness

  This namespace ports the load-bearing routing + registry (GRAPHS / NSID-MAP)
  and the invoke/serialize logic as plain clj functions (`dispatch-run`,
  `dispatch-xrpc`, `dispatch-stream`, `health`, `ok`). A concrete HTTP server is
  provided by `run-server!` on org.httpkit.server (the same pattern the wave-1
  twins use); the 27 StateGraphs + dispatch are the load-bearing port. The
  Python FastAPI server (`lg/`) remains the deployed runtime and COEXISTS."
  (:require #?(:clj [cheshire.core :as json])
            [clojure.string :as str]
            [langgraph.graph :as g]
            [lg-animeka.util :as u]
            [lg-animeka.graphs.health :as health]
            [lg-animeka.graphs.list-works :as list-works]
            [lg-animeka.graphs.list-cuts :as list-cuts]
            [lg-animeka.graphs.list-episodes :as list-episodes]
            [lg-animeka.graphs.list-retakes :as list-retakes]
            [lg-animeka.graphs.get-cut :as get-cut]
            [lg-animeka.graphs.create-work :as create-work]
            [lg-animeka.graphs.add-episode :as add-episode]
            [lg-animeka.graphs.add-cut :as add-cut]
            [lg-animeka.graphs.update-cut-stage :as update-cut-stage]
            [lg-animeka.graphs.submit-retake :as submit-retake]
            [lg-animeka.graphs.resolve-retake :as resolve-retake]
            [lg-animeka.graphs.agent-chat :as agent-chat]
            [lg-animeka.graphs.generate-script :as generate-script]
            [lg-animeka.graphs.generate-storyboard :as generate-storyboard]
            [lg-animeka.graphs.generate-layout :as generate-layout]
            [lg-animeka.graphs.generate-keyframe :as generate-keyframe]
            [lg-animeka.graphs.generate-inbetween :as generate-inbetween]
            [lg-animeka.graphs.generate-background :as generate-background]
            [lg-animeka.graphs.design-color-model :as design-color-model]
            [lg-animeka.graphs.autopilot :as autopilot]
            [lg-animeka.graphs.cut-runner :as cut-runner]
            [lg-animeka.graphs.auto-trace-cut :as auto-trace-cut]
            [lg-animeka.graphs.breakdown-scene :as breakdown-scene]
            [lg-animeka.graphs.generate-audio :as generate-audio]
            [lg-animeka.graphs.assemble-episode :as assemble-episode]
            [lg-animeka.graphs.publish-episode :as publish-episode]))

(def GRAPHS
  {"health"              health/GRAPH
   "list_works"          list-works/GRAPH
   "agent_chat"          agent-chat/GRAPH
   "get_cut"             get-cut/GRAPH
   "list_cuts"           list-cuts/GRAPH
   "list_episodes"       list-episodes/GRAPH
   "list_retakes"        list-retakes/GRAPH
   "create_work"         create-work/GRAPH
   "add_episode"         add-episode/GRAPH
   "add_cut"             add-cut/GRAPH
   "update_cut_stage"    update-cut-stage/GRAPH
   "submit_retake"       submit-retake/GRAPH
   "resolve_retake"      resolve-retake/GRAPH
   "generate_script"     generate-script/GRAPH
   "generate_storyboard" generate-storyboard/GRAPH
   "generate_layout"     generate-layout/GRAPH
   "generate_keyframe"   generate-keyframe/GRAPH
   "generate_inbetween"  generate-inbetween/GRAPH
   "generate_background" generate-background/GRAPH
   "design_color_model"  design-color-model/GRAPH
   "autopilot"           autopilot/GRAPH
   "cut_runner"          cut-runner/GRAPH
   "auto_trace_cut"      auto-trace-cut/GRAPH
   "breakdown_scene"     breakdown-scene/GRAPH
   "generate_audio"      generate-audio/GRAPH
   "assemble_episode"    assemble-episode/GRAPH
   "publish_episode"     publish-episode/GRAPH})

(def NSID-MAP
  {"com.etzhayyim.animeka.health"            "health"
   "com.etzhayyim.animeka.listWorks"         "list_works"
   "com.etzhayyim.animeka.chat"              "agent_chat"
   "com.etzhayyim.animeka.getCut"            "get_cut"
   "com.etzhayyim.animeka.listCuts"          "list_cuts"
   "com.etzhayyim.animeka.listEpisodes"      "list_episodes"
   "com.etzhayyim.animeka.listRetakes"       "list_retakes"
   "com.etzhayyim.animeka.createWork"        "create_work"
   "com.etzhayyim.animeka.addEpisode"        "add_episode"
   "com.etzhayyim.animeka.addCut"            "add_cut"
   "com.etzhayyim.animeka.updateCutStage"    "update_cut_stage"
   "com.etzhayyim.animeka.submitRetake"      "submit_retake"
   "com.etzhayyim.animeka.resolveRetake"     "resolve_retake"
   "com.etzhayyim.animeka.generateScript"     "generate_script"
   "com.etzhayyim.animeka.generateStoryboard" "generate_storyboard"
   "com.etzhayyim.animeka.generateLayout"     "generate_layout"
   "com.etzhayyim.animeka.generateKeyframe"   "generate_keyframe"
   "com.etzhayyim.animeka.generateInbetween"  "generate_inbetween"
   "com.etzhayyim.animeka.generateBackground" "generate_background"
   "com.etzhayyim.animeka.designColorModel"   "design_color_model"
   "com.etzhayyim.animeka.autopilot"          "autopilot"
   "com.etzhayyim.animeka.cutRunner"          "cut_runner"
   "com.etzhayyim.animeka.autoTraceCut"       "auto_trace_cut"
   "com.etzhayyim.animeka.breakdownScene"     "breakdown_scene"
   "com.etzhayyim.animeka.generateAudio"      "generate_audio"
   "com.etzhayyim.animeka.assembleEpisode"    "assemble_episode"
   "com.etzhayyim.animeka.publishEpisode"     "publish_episode"})

(def ^:dynamic *api-key* "")

(defn check-api-key
  "Mirrors `_require_api_key`: if LG_API_KEY is set, x-api-key must match."
  [x-api-key]
  (if (and (seq *api-key*) (not= x-api-key *api-key*))
    {:status 401 :body {:error "invalid x-api-key"}}
    nil))

(defn xrpc-input->graph-input
  "camelCase keys → snake_case keyword keys (server._xrpc_input_to_graph_input)."
  [body]
  (reduce-kv (fn [m k v] (assoc m (keyword (u/camel->snake (name k))) v))
             {} (or body {})))

(defn- run-graph [graph input]
  (try
    {:status 200 :body {:ok true :result (g/invoke graph (or input {}))}}
    (catch #?(:clj Exception :default :default) e
      {:status 200 :body {:ok false
                          :error (u/clip (str #?(:clj (.getMessage e) :default e)) 500)}})))

(defn ok
  "GET /ok → {:ok true :graphs [...] :version \"0.1.0\"}"
  []
  {:status 200 :body {:ok true :graphs (vec (keys GRAPHS)) :version "0.1.0"}})

(defn health
  "GET /health → {:ok bool} (liveness; the clj twin has no checkpointer wired)."
  []
  {:status 200 :body {:ok true :checkpointer false}})

(defn dispatch-run
  "POST /runs body → {:status :body}. body keys: :assistant_id :input.
  Enforces the optional x-api-key (pass via opts {:x-api-key ...})."
  ([body] (dispatch-run body {}))
  ([body {:keys [x-api-key]}]
   (or (check-api-key x-api-key)
       (let [aid (str (or (:assistant_id body) ""))
             graph (get GRAPHS aid)]
         (if (nil? graph)
           {:status 404 :body {:error (str "unknown graph: " aid)}}
           (run-graph graph (or (:input body) {})))))))

(defn dispatch-stream
  "POST /runs/stream — returns the superstep events (parity with the SSE stream)."
  ([body] (dispatch-stream body {}))
  ([body {:keys [x-api-key]}]
   (or (check-api-key x-api-key)
       (let [aid (str (or (:assistant_id body) ""))
             graph (get GRAPHS aid)]
         (if (nil? graph)
           {:status 404 :body {:error (str "unknown graph: " aid)}}
           {:status 200 :body {:events (g/stream graph (or (:input body) {}))}})))))

(defn dispatch-xrpc
  "POST /xrpc/{nsid} body → {:status :body}. NSID → graph; body camelCase→snake.
  /xrpc is unauthenticated (parity with the Python server)."
  [nsid body]
  (let [gname (get NSID-MAP nsid)]
    (if (nil? gname)
      {:status 404 :body {:error (str "unknown NSID: " nsid)}}
      (let [graph (get GRAPHS gname)
            input (xrpc-input->graph-input body)
            res (run-graph graph input)
            result (get-in res [:body :result])]
        {:status 200
         :body (assoc (if (map? result) result {:result result})
                      :assistantId gname)}))))

;; ── optional concrete HTTP server (httpkit) ─────────────────────────────────

(defn- json-response [{:keys [status body]}]
  #?(:clj {:status status
           :headers {"Content-Type" "application/json"}
           :body (json/generate-string body)}
     :default {:status status :body body}))

(defn handler
  "Ring handler mirroring the FastAPI routes."
  [{:keys [request-method uri body headers] :as _req}]
  #?(:clj
     (let [api-h (get headers "x-api-key")
           json-body (fn [] (try (json/parse-string (slurp body) true) (catch Exception _ {})))]
       (json-response
        (cond
          (and (= :get request-method) (= uri "/ok")) (ok)
          (and (= :get request-method) (= uri "/health")) (health)
          (and (= :post request-method) (= uri "/runs"))
          (dispatch-run (json-body) {:x-api-key api-h})
          (and (= :post request-method) (= uri "/runs/stream"))
          (dispatch-stream (json-body) {:x-api-key api-h})
          (and (= :post request-method) (str/starts-with? uri "/xrpc/"))
          (dispatch-xrpc (subs uri 6) (json-body))
          :else {:status 404 :body {:error "not found"}})))
     :default {:status 404 :body {:error "not found"}}))

(defn run-server!
  "Start an org.httpkit.server on :port (default 2027). Returns the stop fn."
  ([] (run-server! nil 2027))
  ([port] (run-server! nil port))
  ([run-server port]
   #?(:clj (do
             (when-not (fn? run-server)
               (throw (ex-info "Animeka server requires an explicit run-server capability"
                               {:capability :animeka/run-server})))
             (let [run (run-server handler {:port port})]
             (println (str "lg-animeka clj server up on :" port " — graphs=" (count GRAPHS)))
             run))
      :default nil)))
