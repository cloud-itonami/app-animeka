(ns lg-animeka.graphs.generate-storyboard
  "animeka `generateStoryboard` graph — LLM visual prompt + ComfyUI 512×512
  monochrome storyboard sketch. NSID: com.etzhayyim.animeka.generateStoryboard.
  Faithful clj port of `generate_storyboard.py`.
  Topology: START → fetch_cut → llm_prompt → render → insert → audit → END."
  (:require [clojure.string :as str]
            [langgraph.graph :as g]
            [lg-animeka.audit :as audit]
            [lg-animeka.llm :as llm]
            [lg-animeka.render :as render]
            [lg-animeka.store :as store]
            [lg-animeka.util :as u]))

(def character-desc "high-school girl, navy blazer, dark long hair, introspective")

;; (cut-rkey) → camera_note string | nil
(def ^:dynamic *fetch-cut* (fn [_rkey] nil))

(defn node-fetch-cut [state]
  (if (or (seq (:cut_summary state))
          (not (seq (:cut_id state)))
          (not (store/configured?)))
    {}
    (let [note (*fetch-cut* (u/rkey-from-id (:cut_id state)))]
      (if (seq note) {:cut_summary note} {}))))

(def storyboard-system
  (str "You are a storyboard artist for a moody anime short. "
       "Given a scene description, output ONE concise visual prompt (max 60 words) "
       "for a monochrome storyboard sketch. Describe composition, camera angle, "
       "and character pose. No dialogue, no preamble."))

(defn node-llm-prompt [state]
  (if (:error state)
    {}
    (let [cut-summary (or (:cut_summary state)
                          "An anime scene with characters in an evocative setting.")
          res (llm/chat storyboard-system
                        (str "Scene: " cut-summary "\nCharacters: " character-desc)
                        {:max-tokens 200 :temperature 0.7})]
      (if (:error res)
        {:error (:error res)}
        {:visual_prompt (str (str/trim (str (:content res)))
                             ", storyboard sketch, monochrome pencil lineart, "
                             "loose confident strokes, story panel")}))))

(defn node-render [state]
  (if (or (:error state) (not (seq (:visual_prompt state))))
    {}
    (let [res (render/render-png (:visual_prompt state)
                                 {:w 512 :h 512 :steps 22})]
      (cond
        (:error res) {:error (str "comfy render: " (:error res))}
        (not (seq (:cid res))) {:error "blob upload failed"}
        :else {:blob_cid (:cid res)}))))

(defn node-insert [state]
  (cond
    (or (:error state) (not (seq (:blob_cid state)))) {}
    (not (store/configured?)) {:error "RW_URL not set"}
    :else
    (let [rkey (u/gen-rkey "sb")
          vertex-id (u/at-uri u/repo-did "com.etzhayyim.animeka.storyboard" rkey)]
      (try
        (store/exec! :insert-storyboard
                     [vertex-id u/repo-did rkey u/app-did (or (:cut_id state) "")
                      (:blob_cid state) (:visual_prompt state) (u/now-iso)])
        {:storyboard_id rkey :storyboard_uri vertex-id}
        (catch #?(:clj Exception :default :default) e
          {:error (u/clip (str "insert: " #?(:clj (.getMessage e) :default e)) 300)})))))

(defn node-audit [state]
  (audit/emit-audit-bg!
   :actor u/app-did :activity "animeka.generateStoryboard"
   :object-id (str "sb:" (or (:storyboard_id state) "") ":" (u/now-iso))
   :object-type "animeka.storyboard"
   :attributes {:cutId (:cut_id state) :blobCid (:blob_cid state)
                :ok (not (boolean (:error state)))})
  {})

(defn build []
  (-> (g/state-graph)
      (g/add-node :fetch_cut node-fetch-cut)
      (g/add-node :llm_prompt node-llm-prompt)
      (g/add-node :render node-render)
      (g/add-node :insert node-insert)
      (g/add-node :audit node-audit)
      (g/add-edge :fetch_cut :llm_prompt)
      (g/add-edge :llm_prompt :render)
      (g/add-edge :render :insert)
      (g/add-edge :insert :audit)
      (g/set-entry-point :fetch_cut)
      (g/set-finish-point :audit)
      (g/compile-graph)))

(def GRAPH (build))
