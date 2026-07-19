(ns lg-animeka.graphs.generate-script
  "animeka `generateScript` graph — LLM screenplay generation for an episode.
  NSID: com.etzhayyim.animeka.generateScript. Faithful clj port of `generate_script.py`.
  Topology: START → fetch_episode → llm_script → insert → audit → END."
  (:require [clojure.string :as str]
            [langgraph.graph :as g]
            [lg-animeka.audit :as audit]
            [lg-animeka.llm :as llm]
            [lg-animeka.store :as store]
            [lg-animeka.util :as u]))

;; (episode-rkey) → {:title t :synopsis s} | nil
(def ^:dynamic *fetch-episode*
  (fn [_rkey] nil))

(defn node-fetch-episode [state]
  (let [episode-id (or (:episode_id state) "")]
    (cond
      (not (seq episode-id)) {:error "episode_id required"}
      (seq (:synopsis state)) {}
      (not (store/configured?)) {}
      :else
      (let [rkey (u/rkey-from-id episode-id)
            row (*fetch-episode* rkey)]
        (if row
          {:synopsis (or (:synopsis row) (str "Episode: " (or (:title row) "")))}
          {})))))

(defn script-system [scene-count]
  (str "You are an anime screenwriter. Given a synopsis, write a compact "
       "screenplay with exactly " scene-count " scenes. For each scene output:\n"
       "SCENE N: [location, time]\n"
       "ACTION: [1-2 sentences of action/visuals]\n"
       "DIALOGUE: [key line(s) or '(no dialogue)']\n\n"
       "Keep each scene under 80 words. Output only the screenplay, no preamble."))

(defn count-scenes [body] (count (re-seq #"SCENE " (str body))))

(defn node-llm-script [state]
  (if (:error state)
    {}
    (let [synopsis (or (:synopsis state) "An original anime episode.")
          scene-count (long (or (:scene_count state) 5))
          res (llm/chat (script-system scene-count) (str "Synopsis: " synopsis)
                        {:max-tokens 1200 :temperature 0.7})]
      (if (:error res)
        {:error (:error res)}
        (let [body (str/trim (str (:content res)))
              actual (count-scenes body)]
          {:body body :scene_count_actual (if (pos? actual) actual scene-count)})))))

(defn node-insert [state]
  (cond
    (or (:error state) (not (seq (:body state)))) {}
    (not (store/configured?)) {:error "RW_URL not set"}
    :else
    (let [rkey (u/gen-rkey "script")
          vertex-id (u/at-uri u/repo-did "com.etzhayyim.animeka.script" rkey)]
      (try
        (store/exec! :insert-script
                     [vertex-id u/repo-did rkey u/app-did (or (:episode_id state) "")
                      (:scene_count_actual state) (:body state) (u/now-iso)])
        {:script_id rkey :script_uri vertex-id}
        (catch #?(:clj Exception :default :default) e
          {:error (u/clip (str "insert: " #?(:clj (.getMessage e) :default e)) 300)})))))

(defn node-audit [state]
  (audit/emit-audit-bg!
   :actor u/app-did :activity "animeka.generateScript"
   :object-id (str "script:" (or (:script_id state) "") ":" (u/now-iso))
   :object-type "animeka.script"
   :attributes {:episodeId (:episode_id state) :ok (not (boolean (:error state)))})
  {})

(defn build []
  (-> (g/state-graph)
      (g/add-node :fetch_episode node-fetch-episode)
      (g/add-node :llm_script node-llm-script)
      (g/add-node :insert node-insert)
      (g/add-node :audit node-audit)
      (g/add-edge :fetch_episode :llm_script)
      (g/add-edge :llm_script :insert)
      (g/add-edge :insert :audit)
      (g/set-entry-point :fetch_episode)
      (g/set-finish-point :audit)
      (g/compile-graph)))

(def GRAPH (build))
