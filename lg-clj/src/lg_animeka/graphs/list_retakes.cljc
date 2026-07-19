(ns lg-animeka.graphs.list-retakes
  "animeka `listRetakes` graph — multi-axis retake filtering.
  NSID: com.etzhayyim.animeka.listRetakes. Faithful clj port of `list_retakes.py`.
  Topology: START → query → emit_audit → END."
  (:require [langgraph.graph :as g]
            [lg-animeka.audit :as audit]
            [lg-animeka.store :as store]
            [lg-animeka.util :as u]))

(def ^:dynamic *fetch*
  (fn [_filters] (throw (ex-info "store not configured" {}))))

(defn row->item
  "vertex_id rkey target_uri cut_id stage severity status comment timecode_frame author assignees created_at"
  [[vertex-id rkey target-uri cut-id stage severity status comment
    timecode-frame author assignees created-at]]
  {:uri vertex-id :rkey rkey :targetUri target-uri :cutUri cut-id
   :stage stage :severity severity :status status :comment comment
   :timecodeFrame (when (some? timecode-frame) (long timecode-frame))
   :author author :assignee assignees :createdAt created-at})

(defn node-query [state]
  (if-not (store/configured?)
    {:error "RW_URL not set" :items [] :total 0}
    (let [filters {:episode-id (when (seq (:episode_id state)) (u/rkey-from-id (:episode_id state)))
                   :cut-id (when (seq (:cut_id state)) (u/rkey-from-id (:cut_id state)))
                   :stage (:stage state)
                   :status (or (:status state) "open")
                   :assignee (:assignee state)
                   :limit (u/clamp (:limit state) 50 1 200)
                   :offset (u/clamp (:offset state) 0 0 2147483647)}
          items (mapv row->item (*fetch* filters))]
      {:items items :total (count items)})))

(defn node-emit-audit [state]
  (audit/emit-audit-bg!
   :actor u/app-did :activity "animeka.listRetakes"
   :object-id (str "listRetakes:" (u/now-iso)) :object-type "animeka.retake"
   :attributes {:cutId (or (:cut_id state) "")
                :episodeId (or (:episode_id state) "")
                :status (or (:status state) "open")
                :returned (int (:total state 0))})
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
