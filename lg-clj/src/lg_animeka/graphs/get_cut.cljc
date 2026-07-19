(ns lg-animeka.graphs.get-cut
  "animeka `getCut` graph — fetch a cut + its full layer tree.
  NSID: com.etzhayyim.animeka.getCut. Faithful clj port of `get_cut.py`.
  Topology: START → query → emit_audit → END."
  (:require [langgraph.graph :as g]
            [lg-animeka.audit :as audit]
            [lg-animeka.store :as store]
            [lg-animeka.util :as u]))

(def coll->key
  {"com.etzhayyim.animeka.storyboard" :storyboards
   "com.etzhayyim.animeka.layout"     :layouts
   "com.etzhayyim.animeka.keyframe"   :keyframes
   "com.etzhayyim.animeka.inbetween"  :inbetweens
   "com.etzhayyim.animeka.colorTrace" :colorTraces
   "com.etzhayyim.animeka.background" :backgrounds
   "com.etzhayyim.animeka.composite"  :composites
   "com.etzhayyim.animeka.soundCue"   :soundCues
   "com.etzhayyim.animeka.retake"     :retakes})

;; (rkey) → {:cut <17-col row> :children [<24-col rows>]} | nil
(def ^:dynamic *fetch*
  (fn [_rkey] (throw (ex-info "store not configured" {}))))

(defn cut-row->map
  [[vertex-id repo rkey collection title cut-num dur-frames fps camera-mode
    camera-note stage-status assignees priority status episode-id scene-id created-at]]
  {:uri vertex-id :repo repo :rkey rkey :collection collection :title title
   :cutNum cut-num :durationFrames dur-frames :fps fps
   :cameraMode camera-mode :cameraNote camera-note
   :stageStatus stage-status :assignees assignees :priority priority :status status
   :episodeId episode-id :sceneId scene-id :createdAt created-at})

(defn child-row->map
  [[vertex-id _repo rkey collection frame-num image-cid thumb-cid body-cid
    bg-cid output-cid asset-cid color-layers-cid track-type in-frame out-frame
    target-uri stage severity status comment timecode-frame author assignees created-at]]
  {:uri vertex-id :rkey rkey :collection collection
   :frameNum frame-num :imageCid image-cid :thumbCid thumb-cid :bodyCid body-cid
   :bgCid bg-cid :outputCid output-cid :assetCid asset-cid :colorLayersCid color-layers-cid
   :trackType track-type :inFrame in-frame :outFrame out-frame
   :targetUri target-uri :stage stage :severity severity :status status :comment comment
   :timecodeFrame timecode-frame :author author :assignees assignees :createdAt created-at})

(defn group-children
  "Group child rows by collection → keyed lists (parity with _COLL_TO_KEY)."
  [child-rows]
  (let [base (zipmap (vals coll->key) (repeat []))]
    (reduce (fn [acc row]
              (let [coll (nth row 3)
                    k (coll->key coll)]
                (if k (update acc k conj (child-row->map row)) acc)))
            base child-rows)))

(defn node-query [state]
  (let [cut-id (or (:cut_id state) "")]
    (cond
      (not (store/configured?)) {:error "RW_URL not set" :cut nil}
      (not (seq cut-id)) {:error "cut_id is required" :cut nil}
      :else
      (let [rkey (u/rkey-from-id cut-id)
            res (*fetch* rkey)]
        (if (or (nil? res) (nil? (:cut res)))
          {:error (str "cut not found: " rkey) :cut nil}
          (let [grouped (group-children (:children res))]
            (merge {:cut (cut-row->map (:cut res))
                    :color_traces (:colorTraces grouped)
                    :sound_cues (:soundCues grouped)}
                   (select-keys grouped [:storyboards :layouts :keyframes :inbetweens
                                         :backgrounds :composites :retakes]))))))))

(defn node-emit-audit [state]
  (audit/emit-audit-bg!
   :actor u/app-did :activity "animeka.getCut"
   :object-id (str "getCut:" (or (:cut_id state) "") ":" (u/now-iso))
   :object-type "animeka.cut"
   :attributes {:cutId (or (:cut_id state) "")})
  {})

(defn build []
  (-> (g/state-graph)
      (g/add-node :query node-query)
      (g/add-node :emit_audit node-emit-audit)
      (g/add-edge :query :emit_audit)
      (g/set-entry-point :query)
      (g/set-finish-point :emit_audit)
      (g/compile-graph)))

(def GRAPH (build))
