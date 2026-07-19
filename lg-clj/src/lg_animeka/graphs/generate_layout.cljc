(ns lg-animeka.graphs.generate-layout
  "animeka `generateLayout` graph — LLM layout plan (JSON) + ComfyUI layout draw.
  NSID: com.etzhayyim.animeka.generateLayout. Faithful clj port of `generate_layout.py`.
  Topology: START → fetch_context → llm_plan → render → insert → audit → END."
  (:require #?(:clj [cheshire.core :as json])
            [clojure.string :as str]
            [langgraph.graph :as g]
            [lg-animeka.audit :as audit]
            [lg-animeka.llm :as llm]
            [lg-animeka.render :as render]
            [lg-animeka.store :as store]
            [lg-animeka.util :as u]))

(def character-desc "high-school girl, navy blazer, dark long hair, introspective")

;; (cut-id) → {:camera-note s :thumb-cid c} | nil
(def ^:dynamic *fetch-context* (fn [_cut-id] nil))

(defn node-fetch-context [state]
  (if (or (not (seq (:cut_id state)))
          (not (store/configured?))
          (seq (:visual_prompt state)))
    {}
    (let [row (*fetch-context* (:cut_id state))]
      (if row
        {:visual_prompt (or (:camera-note row) "") :storyboard_cid (or (:thumb-cid row) "")}
        {}))))

(def layout-system
  (str "You are an anime layout artist. Output ONE JSON object with exactly these keys: "
       "prompt (string, positive ComfyUI prompt for the full-colour layout drawing), "
       "bgMood (string, one short phrase for background atmosphere). "
       "No code fences, no extra keys, no preamble."))

(defn- parse-json [s]
  #?(:clj (try (json/parse-string (str/trim (str s)) true)
               (catch Exception _ nil))
     :default nil))

(defn node-llm-plan [state]
  (if (:error state)
    {}
    (let [visual-prompt (or (:visual_prompt state) "anime scene with characters")
          res (llm/chat layout-system
                        (str "Storyboard concept: " visual-prompt "\nCharacters: " character-desc)
                        {:max-tokens 300 :temperature 0.3})
          plan (parse-json (llm/content res))
          layout-prompt (or (:prompt plan) visual-prompt)
          bg-mood (or (:bgMood plan) "soft warm light")]
      {:layout_prompt (str layout-prompt ", anime layout paper, production key drawing, "
                           "clean linework, flat colour")
       :bg_mood bg-mood})))

(defn node-render [state]
  (if (or (:error state) (not (seq (:layout_prompt state))))
    {}
    (let [res (render/render-png (:layout_prompt state)
                                 {:w 1024 :h 1024 :steps 28})]
      (cond
        (:error res) {:error (str "comfy render: " (:error res))}
        (not (seq (:cid res))) {:error "blob upload failed"}
        :else {:blob_cid (:cid res)}))))

(defn node-insert [state]
  (cond
    (or (:error state) (not (seq (:blob_cid state)))) {}
    (not (store/configured?)) {:error "RW_URL not set"}
    :else
    (let [rkey (u/gen-rkey "ly")
          vertex-id (u/at-uri u/repo-did "com.etzhayyim.animeka.layout" rkey)]
      (try
        (store/exec! :insert-layout
                     [vertex-id u/repo-did rkey u/app-did (or (:cut_id state) "")
                      (:blob_cid state) (:layout_prompt state) (:bg_mood state) (u/now-iso)])
        {:layout_id rkey :layout_uri vertex-id}
        (catch #?(:clj Exception :default :default) e
          {:error (u/clip (str "insert: " #?(:clj (.getMessage e) :default e)) 300)})))))

(defn node-audit [state]
  (audit/emit-audit-bg!
   :actor u/app-did :activity "animeka.generateLayout"
   :object-id (str "ly:" (or (:layout_id state) "") ":" (u/now-iso))
   :object-type "animeka.layout"
   :attributes {:cutId (:cut_id state) :blobCid (:blob_cid state)
                :ok (not (boolean (:error state)))})
  {})

(defn build []
  (-> (g/state-graph)
      (g/add-node :fetch_context node-fetch-context)
      (g/add-node :llm_plan node-llm-plan)
      (g/add-node :render node-render)
      (g/add-node :insert node-insert)
      (g/add-node :audit node-audit)
      (g/add-edge :fetch_context :llm_plan)
      (g/add-edge :llm_plan :render)
      (g/add-edge :render :insert)
      (g/add-edge :insert :audit)
      (g/set-entry-point :fetch_context)
      (g/set-finish-point :audit)
      (g/compile-graph)))

(def GRAPH (build))
