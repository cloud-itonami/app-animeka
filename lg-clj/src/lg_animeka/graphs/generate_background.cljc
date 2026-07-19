(ns lg-animeka.graphs.generate-background
  "animeka `generateBackground` graph — LLM environment description + ComfyUI
  widescreen background painting (no characters).
  NSID: com.etzhayyim.animeka.generateBackground. Faithful clj port of
  `generate_background.py`.
  Topology: START → fetch_context → llm_bg → render → insert → audit → END."
  (:require [clojure.string :as str]
            [langgraph.graph :as g]
            [lg-animeka.audit :as audit]
            [lg-animeka.llm :as llm]
            [lg-animeka.render :as render]
            [lg-animeka.store :as store]
            [lg-animeka.util :as u]))

;; (cut-id cut-rkey) → {:lighting-mood m :scene-summary s} | nil
(def ^:dynamic *fetch-context* (fn [_cut-id] nil))

(defn node-fetch-context [state]
  (if (or (not (seq (:cut_id state)))
          (not (store/configured?))
          (and (seq (:lighting_mood state)) (seq (:scene_summary state))))
    {}
    (let [row (*fetch-context* (:cut_id state))]
      (cond-> {:lighting_mood (or (:lighting-mood row) (:lighting_mood state) "soft warm light")}
        (seq (:scene-summary row)) (assoc :scene_summary (str (:scene-summary row)))))))

(def bg-system
  (str "You are an anime background artist. Output a SINGLE evocative environment "
       "description (max 50 words) for a widescreen background painting with "
       "NO characters. Focus on setting, lighting, and atmosphere."))

(defn node-llm-bg [state]
  (if (:error state)
    {}
    (let [scene-summary (or (:scene_summary state) "a peaceful scene")
          bg-mood (or (:lighting_mood state) "soft warm light")
          res (llm/chat bg-system (str "Scene: " scene-summary "\nLighting mood: " bg-mood)
                        {:max-tokens 200 :temperature 0.6})
          content (str/trim (llm/content res))
          bg-prompt (if (seq content) content (str "anime background, " bg-mood ", no characters"))]
      {:bg_prompt (str bg-prompt ", anime background painting, painterly, no characters, widescreen cinematic")})))

(defn node-render [state]
  (if (or (:error state) (not (seq (:bg_prompt state))))
    {}
    (let [res (render/render-png (:bg_prompt state)
                                 {:w 1344 :h 768 :steps 28 :cfg 7.0 :negative render/neg-bg})]
      (cond
        (:error res) {:error (str "comfy render: " (:error res))}
        (not (seq (:cid res))) {:error "blob upload failed"}
        :else {:blob_cid (:cid res)}))))

(defn node-insert [state]
  (cond
    (or (:error state) (not (seq (:blob_cid state)))) {}
    (not (store/configured?)) {:error "RW_URL not set"}
    :else
    (let [rkey (u/gen-rkey "bg")
          vertex-id (u/at-uri u/repo-did "com.etzhayyim.animeka.background" rkey)]
      (try
        (store/exec! :insert-background
                     [vertex-id u/repo-did rkey u/app-did (or (:cut_id state) "")
                      (:blob_cid state) (:bg_prompt state) (u/now-iso)])
        {:background_id rkey :background_uri vertex-id}
        (catch #?(:clj Exception :default :default) e
          {:error (u/clip (str "insert: " #?(:clj (.getMessage e) :default e)) 300)})))))

(defn node-audit [state]
  (audit/emit-audit-bg!
   :actor u/app-did :activity "animeka.generateBackground"
   :object-id (str "bg:" (or (:background_id state) "") ":" (u/now-iso))
   :object-type "animeka.background"
   :attributes {:cutId (:cut_id state) :blobCid (:blob_cid state)
                :ok (not (boolean (:error state)))})
  {})

(defn build []
  (-> (g/state-graph)
      (g/add-node :fetch_context node-fetch-context)
      (g/add-node :llm_bg node-llm-bg)
      (g/add-node :render node-render)
      (g/add-node :insert node-insert)
      (g/add-node :audit node-audit)
      (g/add-edge :fetch_context :llm_bg)
      (g/add-edge :llm_bg :render)
      (g/add-edge :render :insert)
      (g/add-edge :insert :audit)
      (g/set-entry-point :fetch_context)
      (g/set-finish-point :audit)
      (g/compile-graph)))

(def GRAPH (build))
