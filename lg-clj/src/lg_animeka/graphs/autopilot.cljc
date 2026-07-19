(ns lg-animeka.graphs.autopilot
  "animeka `autopilot` graph — fully autonomous single-cut generation + social
  post. NSID: com.etzhayyim.animeka.autopilot. Faithful clj port of `autopilot.py`.

  Topology (note the conditional edge after `storyboard`):
    START → scene_text → storyboard
            storyboard --(no sb_cid)--> storyboard_retry → layout
            storyboard --(sb_cid)------------------------> layout
    layout → keyframe → background → composite → generate_audio
           → insert_cut → post → audit → END

  This is the only animeka graph with a conditional edge; langgraph-clj's
  `add-conditional-edges` carries it faithfully. The ComfyUI quality-workflow
  builder (`render/quality-workflow`) is the pure, tested piece; LLM/render/
  composite/audio/PDS are injectable seams."
  (:require #?(:clj [cheshire.core :as json])
            [clojure.string :as str]
            [langgraph.graph :as g]
            [lg-animeka.audit :as audit]
            [lg-animeka.graphs.generate-audio :as audio]
            [lg-animeka.llm :as llm]
            [lg-animeka.render :as render]
            [lg-animeka.store :as store]
            [lg-animeka.util :as u]))

(def char-desc "high-school girl, navy blazer, dark long hair, introspective expression")

(defn- render* [prompt opts]
  (let [res (render/render-png prompt (merge {:negative render/neg-char} opts))]
    (if (:error res) ["" (str "render:" (:error res))] [(or (:cid res) "") ""])))

(defn node-scene-text [_state]
  (let [cut-id (str "auto-" (str/replace (u/now-iso) #"[:.]" ""))
        text (llm/content
              (llm/chat (str "You are an anime scene writer. Write SHORT (1-3 sentence) evocative scene "
                             "descriptions for an anime short. Vary mood: calm mornings, wistful afternoons, "
                             "introspective evenings. Output only the scene description, no preamble.")
                        "Generate a fresh scene now." {:max-tokens 300 :temperature 0.85}))]
    {:cut_id cut-id
     :scene_text (if (seq text) text "Misaki stands quietly by the window, watching the world outside.")}))

(defn node-storyboard [state]
  (if (:error state)
    {}
    (let [vp (llm/content
              (llm/chat (str "You are a storyboard artist. Given a scene, output ONE concise visual prompt "
                             "(max 60 words) for a monochrome storyboard sketch. Camera angle, character "
                             "pose. No dialogue, no preamble.")
                        (str "Scene: " (:scene_text state "") "\nCharacters: " char-desc)
                        {:max-tokens 150 :temperature 0.7}))
          prompt (str (if (seq vp) vp (:scene_text state "anime scene"))
                      ", storyboard sketch, monochrome pencil lineart, loose confident strokes, story panel")
          [cid err] (render* prompt {:w 512 :h 512 :steps 22 :cfg 5.0
                                     :sampler "euler_ancestral" :scheduler "normal"})]
      (cond-> {:visual_prompt (if (seq vp) vp prompt) :sb_cid cid}
        (and (seq err) (not (seq cid))) (assoc :error (str "storyboard:" err))))))

(defn node-storyboard-retry [state]
  (let [vp (llm/content
            (llm/chat (str "You are a storyboard artist. Output ONE concise visual prompt (max 60 words) "
                           "for a monochrome storyboard sketch. Different angle from before.")
                      (str "Scene: " (:scene_text state "") "\nCharacters: " char-desc "\nVariant: 2")
                      {:max-tokens 150 :temperature 0.75}))
        prompt (str (if (seq vp) vp (:scene_text state "anime scene"))
                    ", storyboard sketch, monochrome pencil lineart, loose confident strokes")
        [cid err] (render* prompt {:w 512 :h 512 :steps 22 :cfg 5.0
                                   :sampler "euler_ancestral" :scheduler "normal"})]
    (cond-> {:sb_cid cid}
      (and (seq err) (not (seq cid))) (assoc :error (str "sb_retry:" err)))))

(defn- parse-json [s]
  #?(:clj (try (json/parse-string (str s) true)
               (catch Exception _ nil))
     :default nil))

(defn node-layout [state]
  (if (:error state)
    {}
    (let [plan-str (llm/content
                    (llm/chat "Output ONE JSON: {\"prompt\":\"...\",\"bgMood\":\"...\"}. Layout plan for anime cut."
                              (str "Storyboard: " (:visual_prompt state "") "\nChars: " char-desc)
                              {:max-tokens 300 :temperature 0.3}))
          plan (parse-json plan-str)
          layout-prompt (or (:prompt plan) (:visual_prompt state "anime layout"))
          bg-mood (or (:bgMood plan) "soft warm light")
          full (str layout-prompt ", anime layout paper, production key drawing, clean linework, flat colour")
          [cid err] (render* full {:w 1024 :h 1024 :steps 28 :cfg 5.0
                                   :sampler "euler_ancestral" :scheduler "normal"})]
      (cond-> {:ly_cid cid :bg_mood bg-mood}
        (and (seq err) (not (seq cid))) (assoc :error (str "layout:" err))))))

(defn node-keyframe [state]
  (if (:error state)
    {}
    (let [base (or (:visual_prompt state) (:scene_text state) "anime character scene")
          prompt (str base ", " char-desc ", "
                      "anime production cel art, full color illustration, vibrant cel shading, "
                      "detailed shading and highlights, character on-model, expressive face, "
                      "detailed eyes with catchlights, perfect anatomy, sharp focus, "
                      "masterpiece, best quality, very aesthetic, absurdres, highres, newest, "
                      "1girl, solo, looking at viewer")
          [cid err] (render* prompt {:w 1024 :h 1024 :steps 35})]
      (cond-> {:kf_cid cid}
        (and (seq err) (not (seq cid))) (assoc :error (str "keyframe:" err))))))

(defn node-background [state]
  (if (:error state)
    {}
    (let [bg-mood (or (:bg_mood state) "soft warm light")
          desc (let [d (llm/content
                        (llm/chat (str "You are an anime background artist. Output a SINGLE environment description "
                                       "(max 50 words) for a widescreen background painting. NO characters.")
                                  (str "Scene: " (:scene_text state "") "\nMood: " bg-mood)
                                  {:max-tokens 150 :temperature 0.6}))]
                 (if (seq d) d (str "anime background, " bg-mood ", early spring")))
          full (str desc ", anime background painting, painterly, no characters, widescreen cinematic")
          [cid err] (render* full {:w 1344 :h 768 :steps 28 :cfg 7.0 :negative render/neg-bg})]
      (cond-> {:bg_cid cid}
        (and (seq err) (not (seq cid))) (assoc :error (str "background:" err))))))

(defn node-composite [state]
  (if (or (:error state) (not (seq (:kf_cid state))) (not (seq (:bg_cid state))))
    {}
    (let [res (render/*composite* {:cut-rkey (:cut_id state) :kf-cid (:kf_cid state)
                                   :bg-cid (:bg_cid state) :fps 12 :duration-sec 4})]
      (if (and (map? res) (:output-cid res)) {:output_cid (:output-cid res)} {}))))

(defn node-generate-audio [state]
  (if (or (not (seq (:output_cid state))) (not (seq (:cut_id state))))
    {}
    (let [res (try (g/invoke audio/GRAPH {:rkeys [(:cut_id state)] :max_cuts 1})
                   (catch #?(:clj Exception :default :default) _ {}))
          processed (:processed res)]
      (if (and (seq processed) (:new_output_cid (first processed)))
        {:output_cid (:new_output_cid (first processed))}
        {}))))

(defn node-insert-cut [state]
  (if-not (store/configured?)
    {}
    (let [cut-id (or (:cut_id state) (u/gen-rkey "auto"))
          vertex-id (u/at-uri u/repo-did "com.etzhayyim.animeka.cut" cut-id)]
      (try
        (store/exec! :autopilot-upsert-cut
                     [vertex-id u/repo-did cut-id u/app-did (:scene_text state)
                      (:sb_cid state) (:ly_cid state) (:kf_cid state) (:bg_cid state)
                      (when (seq (:output_cid state)) (:output_cid state)) (u/now-iso)])
        {}
        (catch #?(:clj Exception :default :default) _ {})))))

(defn node-post [state]
  (let [images (filterv seq [(:bg_cid state) (:ly_cid state) (:kf_cid state) (:sb_cid state)])]
    (if (empty? images)
      {:post_status "skipped" :ok true}
      (let [res (render/*pds-post* {:cut-id (:cut_id state) :scene-text (:scene_text state)
                                    :images (vec (take 4 images))})]
        (cond
          (and (map? res) (= "posted" (:status res))) {:post_status "posted" :ok true}
          (and (map? res) (:uri res)) {:post_status "posted" :ok true}
          :else {:post_status "error" :ok (boolean (or (seq (:sb_cid state)) (seq (:kf_cid state))))})))))

(defn node-audit [state]
  (audit/emit-audit-bg!
   :actor u/app-did :activity "animeka.autopilot"
   :object-id (str "autopilot:" (or (:cut_id state) "") ":" (u/now-iso))
   :object-type "animeka.cut"
   :attributes {:cutId (:cut_id state) :sbCid (:sb_cid state) :lyCid (:ly_cid state)
                :kfCid (:kf_cid state) :bgCid (:bg_cid state) :outputCid (:output_cid state)
                :postStatus (:post_status state) :ok (:ok state true)})
  {})

(defn route-after-storyboard [state]
  (if-not (seq (:sb_cid state)) :storyboard_retry :layout))

(defn build []
  (-> (g/state-graph)
      (g/add-node :scene_text node-scene-text)
      (g/add-node :storyboard node-storyboard)
      (g/add-node :storyboard_retry node-storyboard-retry)
      (g/add-node :layout node-layout)
      (g/add-node :keyframe node-keyframe)
      (g/add-node :background node-background)
      (g/add-node :composite node-composite)
      (g/add-node :generate_audio node-generate-audio)
      (g/add-node :insert_cut node-insert-cut)
      (g/add-node :post node-post)
      (g/add-node :audit node-audit)
      (g/add-edge :scene_text :storyboard)
      (g/add-conditional-edges :storyboard route-after-storyboard
                               {:storyboard_retry :storyboard_retry :layout :layout})
      (g/add-edge :storyboard_retry :layout)
      (g/add-edge :layout :keyframe)
      (g/add-edge :keyframe :background)
      (g/add-edge :background :composite)
      (g/add-edge :composite :generate_audio)
      (g/add-edge :generate_audio :insert_cut)
      (g/add-edge :insert_cut :post)
      (g/add-edge :post :audit)
      (g/set-entry-point :scene_text)
      (g/set-finish-point :audit)
      (g/compile-graph)))

(def GRAPH (build))
