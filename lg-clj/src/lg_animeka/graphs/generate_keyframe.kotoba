(ns lg-animeka.graphs.generate-keyframe
  "animeka `generateKeyframe` graph — ComfyUI 1024×1024 cel-shaded keyframe.
  NSID: com.etzhayyim.animeka.generateKeyframe. Faithful clj port of `generate_keyframe.py`.
  Topology: START → fetch_prompt → render → insert → audit → END.
  The insert also patches the parent cut's image_cid (via *update-cut-image*)."
  (:require [langgraph.graph :as g]
            [lg-animeka.audit :as audit]
            [lg-animeka.render :as render]
            [lg-animeka.store :as store]
            [lg-animeka.util :as u]))

(def anime-style
  (str ", anime production cel art, full color illustration, vibrant cel shading, "
       "detailed shading and highlights, character on-model, expressive face, "
       "detailed eyes with catchlights, perfect anatomy, sharp focus, "
       "masterpiece, best quality, very aesthetic, absurdres, highres, newest, "
       "1girl or 1boy, solo, looking at viewer"))

(def negative
  (str "lowres, worst quality, low quality, bad anatomy, bad hands, missing fingers, "
       "extra digit, fewer digits, cropped, text, signature, watermark, username, blurry, "
       "jpeg artifacts, ugly, duplicate, mutated, deformed, normal quality, monochrome, "
       "gray background, placeholder, solid color background, sketch, lineart only, "
       "unfinished, rough sketch, wireframe"))

;; (cut-rkey) → visual prompt string | nil  (layout.description → cut.description → camera_note)
(def ^:dynamic *fetch-prompt* (fn [_rkey] nil))
;; (cut-rkey blob-cid) — patch the parent cut's image_cid
(def ^:dynamic *update-cut-image* (fn [& _] nil))

(defn node-fetch-prompt [state]
  (if (or (seq (:visual_prompt state))
          (not (seq (:cut_id state)))
          (not (store/configured?)))
    {}
    (let [p (*fetch-prompt* (u/rkey-from-id (:cut_id state)))]
      (if (seq p) {:visual_prompt (str p)} {}))))

(defn node-render [state]
  (if (:error state)
    {}
    (let [base (or (:visual_prompt state) "anime character in scenic environment")
          full (str base anime-style)
          res (render/render-png full {:w 1024 :h 1024 :steps 35 :cfg 7.0 :negative negative})]
      (cond
        (:error res) {:error (str "comfy render: " (:error res))}
        (not (seq (:cid res))) {:error "blob upload failed"}
        :else {:blob_cid (:cid res)}))))

(defn node-insert [state]
  (cond
    (or (:error state) (not (seq (:blob_cid state)))) {}
    (not (store/configured?)) {:error "RW_URL not set"}
    :else
    (let [rkey (u/gen-rkey "kf")
          vertex-id (u/at-uri u/repo-did "com.etzhayyim.animeka.keyframe" rkey)
          frame-num (long (or (:frame_num state) 1))
          cut-rkey (u/rkey-from-id (or (:cut_id state) ""))]
      (try
        (store/exec! :insert-keyframe
                     [vertex-id u/repo-did rkey u/app-did (or (:cut_id state) "")
                      (:blob_cid state) frame-num (u/now-iso)])
        (*update-cut-image* cut-rkey (:blob_cid state))
        {:keyframe_id rkey :keyframe_uri vertex-id}
        (catch #?(:clj Exception :default :default) e
          {:error (u/clip (str "insert: " #?(:clj (.getMessage e) :default e)) 300)})))))

(defn node-audit [state]
  (audit/emit-audit-bg!
   :actor u/app-did :activity "animeka.generateKeyframe"
   :object-id (str "kf:" (or (:keyframe_id state) "") ":" (u/now-iso))
   :object-type "animeka.keyframe"
   :attributes {:cutId (:cut_id state) :frameNum (:frame_num state)
                :ok (not (boolean (:error state)))})
  {})

(defn build []
  (-> (g/state-graph)
      (g/add-node :fetch_prompt node-fetch-prompt)
      (g/add-node :render node-render)
      (g/add-node :insert node-insert)
      (g/add-node :audit node-audit)
      (g/add-edge :fetch_prompt :render)
      (g/add-edge :render :insert)
      (g/add-edge :insert :audit)
      (g/set-entry-point :fetch_prompt)
      (g/set-finish-point :audit)
      (g/compile-graph)))

(def GRAPH (build))
