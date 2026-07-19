(ns lg-animeka.graphs.design-color-model
  "animeka `designColorModel` graph — LLM palette JSON + ComfyUI character color
  reference sheet. NSID: com.etzhayyim.animeka.designColorModel. Faithful clj
  port of `design_color_model.py`.
  Topology: START → llm_palette → render → insert → audit → END."
  (:require #?(:clj [cheshire.core :as json])
            [clojure.string :as str]
            [langgraph.graph :as g]
            [lg-animeka.audit :as audit]
            [lg-animeka.llm :as llm]
            [lg-animeka.render :as render]
            [lg-animeka.store :as store]
            [lg-animeka.util :as u]))

(def palette-system
  (str "You are an anime color designer. Given a character description, output ONE JSON object with these keys: "
       "primary (hex, main costume color), secondary (hex, accent/trim), "
       "hair (hex, hair color), eyes (hex, eye color), "
       "shadow (hex, shadow tone for cel shading), highlight (hex), "
       "renderPrompt (string, 60-word ComfyUI prompt for a full-body color reference sheet). "
       "No code fences, no preamble."))

(def palette-keys [:primary :secondary :hair :eyes :shadow :highlight])

(defn- parse-json [s]
  #?(:clj (try (json/parse-string (str/trim (str s)) true)
               (catch Exception _ nil))
     :default nil))

(defn node-llm-palette [state]
  (if (:error state)
    {}
    (let [character-name (or (:character_name state) "anime character")
          description (or (:description state) (str "anime character named " character-name))
          default-prompt (str character-name ", anime character, full body, color reference sheet, "
                               "front view, clean design")
          res (llm/chat palette-system (str "Character: " character-name "\nDescription: " description)
                        {:max-tokens 500 :temperature 0.4})
          plan (parse-json (llm/content res))
          palette (when plan (select-keys plan (filter #(contains? plan %) palette-keys)))
          render-prompt (or (:renderPrompt plan) default-prompt)]
      {:palette (or palette {})
       :render_prompt (str render-prompt ", anime color model, turnaround sheet, flat cel colors, "
                           "character design reference")})))

(defn node-render [state]
  (if (or (:error state) (not (seq (:render_prompt state))))
    {}
    (let [res (render/render-png (:render_prompt state) {:w 768 :h 1024 :steps 28})]
      (cond
        (:error res) {:error (str "comfy render: " (:error res))}
        (not (seq (:cid res))) {:error "blob upload failed"}
        :else {:blob_cid (:cid res)}))))

(defn node-insert [state]
  (cond
    (:error state) {}
    (not (store/configured?)) {:error "RW_URL not set"}
    :else
    (let [rkey (u/gen-rkey "cm")
          vertex-id (u/at-uri u/repo-did "com.etzhayyim.animeka.colorModel" rkey)]
      (try
        (store/exec! :insert-color-model
                     [vertex-id u/repo-did rkey u/app-did (:character_name state)
                      (:blob_cid state) (or (:palette state) {}) (:work_id state) (u/now-iso)])
        {:color_model_id rkey :color_model_uri vertex-id}
        (catch #?(:clj Exception :default :default) e
          {:error (u/clip (str "insert: " #?(:clj (.getMessage e) :default e)) 300)})))))

(defn node-audit [state]
  (audit/emit-audit-bg!
   :actor u/app-did :activity "animeka.designColorModel"
   :object-id (str "cm:" (or (:color_model_id state) "") ":" (u/now-iso))
   :object-type "animeka.colorModel"
   :attributes {:characterName (:character_name state) :blobCid (:blob_cid state)
                :ok (not (boolean (:error state)))})
  {})

(defn build []
  (-> (g/state-graph)
      (g/add-node :llm_palette node-llm-palette)
      (g/add-node :render node-render)
      (g/add-node :insert node-insert)
      (g/add-node :audit node-audit)
      (g/add-edge :llm_palette :render)
      (g/add-edge :render :insert)
      (g/add-edge :insert :audit)
      (g/set-entry-point :llm_palette)
      (g/set-finish-point :audit)
      (g/compile-graph)))

(def GRAPH (build))
