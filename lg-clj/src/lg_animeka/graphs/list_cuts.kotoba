(ns lg-animeka.graphs.list-cuts
  "animeka `listCuts` graph — list cuts by episode/work/stage.
  NSID: com.etzhayyim.animeka.listCuts. Faithful clj port of `list_cuts.py`.
  Topology: START → query → audit → END."
  (:require [langgraph.graph :as g]
            [lg-animeka.audit :as audit]
            [lg-animeka.store :as store]
            [lg-animeka.util :as u]))

(def ^:dynamic *fetch*
  (fn [_filters] (throw (ex-info "store not configured" {}))))

(defn- int-or-nil [v] (when (some? v) (long v)))

(defn row->item
  "Faithful map of one vertex_animeka cut row (14 cols, see list_cuts.py)."
  [[vertex-id rkey cut-num dur-frames fps priority camera-note stage
    stage-status ep-id wk-id thumb-cid image-cid created-at]]
  {:uri vertex-id :rkey rkey
   :cutNum (int-or-nil cut-num) :cut_num (int-or-nil cut-num)
   :durationFrames (int-or-nil dur-frames) :duration_frames (int-or-nil dur-frames)
   :fps (if (some? fps) (long fps) 24)
   :priority priority
   :dialogueSummary camera-note :dialogue_summary camera-note
   :stage stage :stageStatus stage-status :stage_status stage-status
   :episodeId ep-id :workId wk-id :thumbCid thumb-cid :imageCid image-cid
   :createdAt created-at})

(defn node-query [state]
  (if-not (store/configured?)
    {:error "RW_URL not set" :items [] :total 0}
    (let [filters {:episode-id (when (seq (:episode_id state)) (u/rkey-from-id (:episode_id state)))
                   :work-id (when (and (seq (:work_id state)) (not (seq (:episode_id state))))
                              (u/rkey-from-id (:work_id state)))
                   :stage (:stage state)
                   :limit (u/clamp (:limit state) 200 1 500)
                   :offset (u/clamp (:offset state) 0 0 2147483647)}
          items (mapv row->item (*fetch* filters))]
      {:items items :total (count items)})))

(defn node-audit [state]
  (audit/emit-audit-bg!
   :actor u/app-did :activity "animeka.listCuts"
   :object-id (str "listCuts:" (u/now-iso)) :object-type "animeka.cut"
   :attributes {:episodeId (or (:episode_id state) "")
                :workId (or (:work_id state) "")
                :limit (u/clamp (:limit state) 200 1 500)
                :offset (u/clamp (:offset state) 0 0 2147483647)
                :returned (int (:total state 0))})
  {})

(defn build []
  (-> (g/state-graph)
      (g/add-node :query node-query)
      (g/add-node :audit node-audit)
      (g/add-edge :query :audit)
      (g/set-entry-point :query)
      (g/set-finish-point :audit)
      (g/compile-graph)))

(def GRAPH (build))
