(ns lg-animeka.graphs.auto-trace-cut
  "animeka `autoTraceCut` graph — LLM color prompt + ComfyUI colored cel frame +
  colorTrace record. NSID: com.etzhayyim.animeka.autoTraceCut. Faithful clj port
  of `auto_trace_cut.py`.
  Topology: START → fetch_keyframe → llm_color_prompt → render_trace → insert → audit → END."
  (:require [clojure.string :as str]
            [langgraph.graph :as g]
            [lg-animeka.audit :as audit]
            [lg-animeka.llm :as llm]
            [lg-animeka.render :as render]
            [lg-animeka.store :as store]
            [lg-animeka.util :as u]))

(def character-desc "high-school girl, navy blazer, dark long hair, introspective")

;; (cut-rkey) → {:keyframe-cid c :camera-note n} | {:camera-note n} | nil
(def ^:dynamic *fetch-keyframe* (fn [_rkey] nil))

(defn node-fetch-keyframe [state]
  (if (or (seq (:keyframe_cid state))
          (not (seq (:cut_id state)))
          (not (store/configured?)))
    {}
    (let [row (*fetch-keyframe* (u/rkey-from-id (:cut_id state)))]
      (cond-> {}
        (:keyframe-cid row) (assoc :keyframe_cid (:keyframe-cid row))
        (:camera-note row) (assoc :camera_note (:camera-note row))))))

(def color-system
  (str "You are an anime color designer. Given a scene description, output ONE "
       "concise positive ComfyUI prompt (max 60 words) for a fully colored "
       "cel-shaded anime frame. Include: character description, color palette "
       "mood (warm/cool/neutral), lighting direction. "
       "No preamble, no code fences."))

(defn node-llm-color-prompt [state]
  (if (:error state)
    {}
    (let [scene (or (:camera_note state) "anime character in a scene")
          res (llm/chat color-system
                        (str "Scene: " scene "\nCharacters: " character-desc)
                        {:max-tokens 150 :temperature 0.5})
          content (str/trim (llm/content res))]
      {:color_prompt (if (seq content) content scene)})))

(defn node-render-trace [state]
  (if (or (:error state) (not (seq (:color_prompt state))))
    {}
    (let [res (render/render-png (:color_prompt state) {:w 1024 :h 1024 :steps 28})]
      (cond
        (:error res) {:error (str "comfy render: " (:error res))}
        (not (seq (:cid res))) {:error "blob upload failed"}
        :else {:color_layers_cid (:cid res)}))))

(defn node-insert [state]
  (cond
    (or (:error state) (not (seq (:color_layers_cid state)))) {}
    (not (store/configured?)) {:error "RW_URL not set"}
    :else
    (let [rkey-cut (u/rkey-from-id (or (:cut_id state) ""))
          rkey (u/gen-rkey "ct")
          vertex-id (u/at-uri u/repo-did "com.etzhayyim.animeka.colorTrace" rkey)]
      (try
        (store/exec! :insert-color-trace
                     [vertex-id u/repo-did rkey u/app-did rkey-cut
                      (:color_layers_cid state) (u/now-iso)])
        {:color_trace_id rkey :color_trace_uri vertex-id}
        (catch #?(:clj Exception :default :default) e
          {:error (u/clip (str "insert: " #?(:clj (.getMessage e) :default e)) 300)})))))

(defn node-audit [state]
  (audit/emit-audit-bg!
   :actor u/app-did :activity "animeka.autoTraceCut"
   :object-id (str "ct:" (or (:color_trace_id state) "") ":" (u/now-iso))
   :object-type "animeka.colorTrace"
   :attributes {:cutId (:cut_id state) :colorLayersCid (:color_layers_cid state)
                :ok (not (boolean (:error state)))})
  {})

(defn build []
  (-> (g/state-graph)
      (g/add-node :fetch_keyframe node-fetch-keyframe)
      (g/add-node :llm_color_prompt node-llm-color-prompt)
      (g/add-node :render_trace node-render-trace)
      (g/add-node :insert node-insert)
      (g/add-node :audit node-audit)
      (g/add-edge :fetch_keyframe :llm_color_prompt)
      (g/add-edge :llm_color_prompt :render_trace)
      (g/add-edge :render_trace :insert)
      (g/add-edge :insert :audit)
      (g/set-entry-point :fetch_keyframe)
      (g/set-finish-point :audit)
      (g/compile-graph)))

(def GRAPH (build))
