(ns lg-animeka.graphs.list-episodes
  "animeka `listEpisodes` graph — list episodes by work (+ per-episode cut count).
  NSID: com.etzhayyim.animeka.listEpisodes. Faithful clj port of `list_episodes.py`.
  Topology: START → query → emit_audit → END."
  (:require [langgraph.graph :as g]
            [lg-animeka.audit :as audit]
            [lg-animeka.store :as store]
            [lg-animeka.util :as u]))

;; (filters) → {:rows [[vertex_id rkey ep_num title status dur fps thumb created_at] ..]
;;             :cut-counts {vertex_id n}}
(def ^:dynamic *fetch*
  (fn [_filters] (throw (ex-info "store not configured" {}))))

(defn rows->items [rows cut-counts]
  (mapv (fn [[vertex-id rkey ep-num title st dur fps thumb created-at]]
          {:uri vertex-id :rkey rkey
           :episodeNum (when (some? ep-num) (long ep-num))
           :titleJP title :status st
           :durationSec (when (some? dur) (double dur))
           :fps (when (some? fps) (long fps))
           :thumbCid thumb
           :cutCount (get cut-counts vertex-id 0)
           :createdAt created-at})
        rows))

(defn node-query [state]
  (cond
    (not (store/configured?)) {:error "RW_URL not set" :items [] :total 0}
    (not (seq (:work_id state))) {:error "work_id is required" :items [] :total 0}
    :else
    (let [filters {:work-rkey (u/rkey-from-id (:work_id state))
                   :status (:status state)
                   :limit (u/clamp (:limit state) 50 1 200)
                   :offset (u/clamp (:offset state) 0 0 2147483647)}
          {:keys [rows cut-counts]} (*fetch* filters)
          items (rows->items rows (or cut-counts {}))]
      {:items items :total (count items)})))

(defn node-emit-audit [state]
  (audit/emit-audit-bg!
   :actor u/app-did :activity "animeka.listEpisodes"
   :object-id (str "listEpisodes:" (u/now-iso)) :object-type "animeka.episode"
   :attributes {:workId (or (:work_id state) "")
                :limit (u/clamp (:limit state) 50 1 200)
                :offset (u/clamp (:offset state) 0 0 2147483647)
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
