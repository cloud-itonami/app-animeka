(ns lg-animeka.graphs.breakdown-scene
  "animeka `breakdownScene` graph — LLM scene → numbered cut records.
  NSID: com.etzhayyim.animeka.breakdownScene. Faithful clj port of `breakdown_scene.py`.
  Topology: START → llm_breakdown → insert_cuts → audit → END.

  The JSON-array parse (with markdown-fence stripping + single-cut fallback) and
  the clamp to max_cuts are ported faithfully and tested; inserts go through the
  injectable store seam."
  (:require #?(:clj [cheshire.core :as json])
            [clojure.string :as str]
            [langgraph.graph :as g]
            [lg-animeka.audit :as audit]
            [lg-animeka.graphs.add-cut :as add-cut]
            [lg-animeka.llm :as llm]
            [lg-animeka.store :as store]
            [lg-animeka.util :as u]))

(defn breakdown-system [max-cuts fps]
  (str "You are an anime director breaking down a scene into cuts. "
       "Output a JSON array of up to " max-cuts " objects, each with keys: "
       "cutNum (integer, 1-based), shotType (string: WS/MS/CU/ECU/OTS/POV/INSERT), "
       "durationFrames (integer, at " fps "fps; typical 24-96), "
       "cameraNote (string, max 40 words: composition, character pose, action). "
       "No code fences, no preamble, array only."))

(defn strip-fences
  "Remove a leading ```lang fence and trailing ``` (parity with the Python)."
  [content]
  (let [c (str/trim content)]
    (if (str/starts-with? c "```")
      (-> c (str/split #"\n" 2) second (or "") (str/replace #"```\s*$" "") str/trim)
      c)))

(defn- parse-json [s]
  #?(:clj (try (json/parse-string s true)
               (catch Exception _ ::fail))
     :default ::fail))

(defn parse-breakdown
  "content + fallback scene-text → vector of cut spec maps. Mirrors the Python
  try(json.loads)/JSONDecodeError(fallback single cut) flow."
  [content scene-text]
  (let [parsed (parse-json (strip-fences content))]
    (cond
      (vector? parsed) parsed
      (sequential? parsed) (vec parsed)
      (= ::fail parsed) [{:cutNum 1 :shotType "MS" :durationFrames 48
                          :cameraNote (u/clip scene-text 120)}]
      :else [])))

(defn node-llm-breakdown [state]
  (let [scene-text (or (:scene_text state) "")]
    (if-not (seq scene-text)
      {:error "scene_text required"}
      (let [max-cuts (long (or (:max_cuts state) 8))
            fps (long (or (:fps state) 24))
            res (llm/chat (breakdown-system max-cuts fps)
                          (str "Scene:\n" (u/clip scene-text 1500))
                          {:max-tokens 1200 :temperature 0.4})]
        (if (:error res)
          {:error (:error res)}
          {:breakdown (vec (take max-cuts (parse-breakdown (str (:content res)) scene-text)))})))))

(defn node-insert-cuts [state]
  (cond
    (or (:error state) (empty? (:breakdown state))) {}
    (not (store/configured?)) {:error "RW_URL not set"}
    :else
    (let [episode-id (or (:episode_id state) "")
          scene-id (or (:scene_id state) "")
          fps (long (or (:fps state) 24))]
      (try
        (let [recs (map-indexed
                    (fn [idx spec]
                      (let [rkey (u/gen-rkey "cut")
                            vertex-id (u/at-uri u/repo-did "com.etzhayyim.animeka.cut" rkey)
                            cut-num (long (or (:cutNum spec) (inc idx)))
                            duration (long (or (:durationFrames spec) 48))
                            camera-note (u/clip (or (:cameraNote spec) "") 255)
                            shot-type (u/clip (or (:shotType spec) "MS") 16)]
                        (store/exec! :insert-cut
                                     [vertex-id u/repo-did rkey u/app-did episode-id scene-id
                                      cut-num duration fps shot-type camera-note
                                      add-cut/default-stage-status (u/now-iso)])
                        [rkey vertex-id]))
                    (:breakdown state))]
          {:cut_ids (mapv first recs) :cut_uris (mapv second recs)})
        (catch #?(:clj Exception :default :default) e
          {:error (u/clip (str "insert: " #?(:clj (.getMessage e) :default e)) 300)})))))

(defn node-audit [state]
  (audit/emit-audit-bg!
   :actor u/app-did :activity "animeka.breakdownScene"
   :object-id (str "breakdown:" (or (:episode_id state) "") "," (or (:scene_id state) "") ":" (u/now-iso))
   :object-type "animeka.cut"
   :attributes {:episodeId (:episode_id state) :sceneId (:scene_id state)
                :cutsCreated (count (:cut_ids state))
                :ok (not (boolean (:error state)))})
  {})

(defn build []
  (-> (g/state-graph)
      (g/add-node :llm_breakdown node-llm-breakdown)
      (g/add-node :insert_cuts node-insert-cuts)
      (g/add-node :audit node-audit)
      (g/add-edge :llm_breakdown :insert_cuts)
      (g/add-edge :insert_cuts :audit)
      (g/set-entry-point :llm_breakdown)
      (g/set-finish-point :audit)
      (g/compile-graph)))

(def GRAPH (build))
