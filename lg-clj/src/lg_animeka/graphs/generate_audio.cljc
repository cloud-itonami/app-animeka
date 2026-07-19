(ns lg-animeka.graphs.generate-audio
  "animeka `generateAudio` graph — mood-matched BGM + narration TTS muxed onto a
  cut's composite video. NSID: com.etzhayyim.animeka.generateAudio. Faithful clj
  port of `generate_audio.py` (topology + gating).

  Topology (two conditional edges):
    START → fetch_cuts → infer_mood --(no moods|error)--> END
                         infer_mood --(moods)----------> gen_audio
            gen_audio --(no processed|error)--> END
            gen_audio --(processed)----------> persist → END

  DEVIATION (noted): the Python (~844 lines) synthesises BGM and TTS narration
  and muxes via native audio/ffmpeg pipelines with no bb host. Following the
  actor-swap pattern those native edges are injectable seams (`*infer-moods*`,
  `*gen-audio*`, `*persist*`); the topology, routing, and gating are ported
  faithfully and tested. fetch_cuts uses the standard store seam."
  (:require [langgraph.graph :as g]
            [lg-animeka.audit :as audit]
            [lg-animeka.store :as store]
            [lg-animeka.util :as u]))

;; (filters {:max-cuts :rkeys}) → seq of cut maps {:rkey :output_cid :title ..}
(def ^:dynamic *fetch-cuts* (fn [_filters] (throw (ex-info "store not configured" {}))))
;; (cut-rows) → {rkey mood}
(def ^:dynamic *infer-moods* (fn [_cut-rows] {}))
;; (cut-rows moods) → seq of processed maps {:rkey :new_output_cid ..}
(def ^:dynamic *gen-audio* (fn [_cut-rows _moods] []))
;; (processed) → nil   (persist new output CIDs back to the store)
(def ^:dynamic *persist* (fn [_processed] nil))

(defn node-fetch-cuts [state]
  (if-not (store/configured?)
    {:error "RW_URL not configured"}
    (let [max-cuts (long (or (:max_cuts state) 5))
          rkeys (or (:rkeys state) [])]
      {:cut_rows (vec (*fetch-cuts* {:max-cuts max-cuts :rkeys rkeys}))})))

(defn node-infer-mood [state]
  (if (:error state)
    {}
    {:moods (or (*infer-moods* (:cut_rows state)) {})}))

(defn node-gen-audio [state]
  (if (:error state)
    {}
    {:processed (vec (*gen-audio* (:cut_rows state) (:moods state)))}))

(defn node-persist [state]
  (when (seq (:processed state)) (*persist* (:processed state)))
  (audit/emit-audit-bg!
   :actor u/app-did :activity "animeka.generateAudio"
   :object-id (str "audio:" (u/now-iso)) :object-type "animeka.audio"
   :attributes {:processed (count (:processed state)) :ok (not (boolean (:error state)))})
  {:summary {:processed (count (:processed state))}})

(defn route-after-mood [state]
  (if (or (:error state) (empty? (:moods state))) g/END :gen_audio))

(defn route-after-audio [state]
  (if (or (:error state) (empty? (:processed state))) g/END :persist))

(defn build []
  (-> (g/state-graph)
      (g/add-node :fetch_cuts node-fetch-cuts)
      (g/add-node :infer_mood node-infer-mood)
      (g/add-node :gen_audio node-gen-audio)
      (g/add-node :persist node-persist)
      (g/add-edge :fetch_cuts :infer_mood)
      (g/add-conditional-edges :infer_mood route-after-mood)
      (g/add-conditional-edges :gen_audio route-after-audio)
      (g/set-entry-point :fetch_cuts)
      (g/set-finish-point :persist)
      (g/compile-graph)))

(def GRAPH (build))
