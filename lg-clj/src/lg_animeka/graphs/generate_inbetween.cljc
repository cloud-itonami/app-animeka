(ns lg-animeka.graphs.generate-inbetween
  "animeka `generateInbetween` graph — render N transitional frames between two
  keyframes. NSID: com.etzhayyim.animeka.generateInbetween. Faithful clj port of
  `generate_inbetween.py`.
  Topology: START → fetch_keyframes → generate → insert → audit → END."
  (:require [langgraph.graph :as g]
            [lg-animeka.audit :as audit]
            [lg-animeka.render :as render]
            [lg-animeka.store :as store]
            [lg-animeka.util :as u]))

;; (cut-id) → {:prev-cid c :next-cid c :visual-prompt p} | nil
(def ^:dynamic *fetch-keyframes* (fn [_cut-id] nil))

(defn node-fetch-keyframes [state]
  (if (or (and (seq (:prev_frame_cid state)) (seq (:next_frame_cid state)))
          (not (seq (:cut_id state)))
          (not (store/configured?)))
    {}
    (let [row (*fetch-keyframes* (:cut_id state))]
      (cond-> {}
        (:prev-cid row) (assoc :prev_frame_cid (:prev-cid row))
        (:next-cid row) (assoc :next_frame_cid (:next-cid row))
        (:visual-prompt row) (assoc :visual_prompt (:visual-prompt row))))))

(defn node-generate [state]
  (if (:error state)
    {}
    (let [frame-count (long (or (:frame_count state) 3))
          base (str (or (:visual_prompt state) "anime character motion")
                    ", anime inbetween frame, clean lineart, consistent character design, smooth motion")
          cids (->> (range frame-count)
                    (map (fn [i]
                           (let [mp (str base ", motion frame " (inc i) " of " frame-count ", transitional pose")
                                 res (render/render-png mp {:w 768 :h 768 :steps 18})]
                             (when (and (not (:error res)) (seq (:cid res))) (:cid res)))))
                    (remove nil?)
                    vec)]
      (if (empty? cids)
        {:error "no inbetween frames generated"}
        {:blob_cids cids}))))

(defn node-insert [state]
  (cond
    (or (:error state) (empty? (:blob_cids state))) {}
    (not (store/configured?)) {:error "RW_URL not set"}
    :else
    (try
      (let [recs (map-indexed
                  (fn [idx cid]
                    (let [rkey (u/gen-rkey "ib")
                          vertex-id (u/at-uri u/repo-did "com.etzhayyim.animeka.inbetween" rkey)]
                      (store/exec! :insert-inbetween
                                   [vertex-id u/repo-did rkey u/app-did (or (:cut_id state) "")
                                    cid (inc idx) (u/now-iso)])
                      [rkey vertex-id]))
                  (:blob_cids state))]
        {:inbetween_ids (mapv first recs) :inbetween_uris (mapv second recs)})
      (catch #?(:clj Exception :default :default) e
        {:error (u/clip (str "insert: " #?(:clj (.getMessage e) :default e)) 300)}))))

(defn node-audit [state]
  (audit/emit-audit-bg!
   :actor u/app-did :activity "animeka.generateInbetween"
   :object-id (str "ib:" (or (:cut_id state) "") ":" (u/now-iso))
   :object-type "animeka.inbetween"
   :attributes {:cutId (:cut_id state) :count (count (:blob_cids state))
                :ok (not (boolean (:error state)))})
  {})

(defn build []
  (-> (g/state-graph)
      (g/add-node :fetch_keyframes node-fetch-keyframes)
      (g/add-node :generate node-generate)
      (g/add-node :insert node-insert)
      (g/add-node :audit node-audit)
      (g/add-edge :fetch_keyframes :generate)
      (g/add-edge :generate :insert)
      (g/add-edge :insert :audit)
      (g/set-entry-point :fetch_keyframes)
      (g/set-finish-point :audit)
      (g/compile-graph)))

(def GRAPH (build))
