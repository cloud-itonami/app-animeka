(ns lg-animeka.graphs.list-works
  "animeka `listWorks` graph — read-only work query.
  NSID: com.etzhayyim.animeka.listWorks.

  Faithful clj port of `list_works.py`. Topology: START → query → emit_audit → END.
  The SELECT is the injectable `*fetch*` seam (filters → row-vectors
  [repo rkey ts_ms value_json]); `rows->works` is the pure, tested mapping."
  (:require [langgraph.graph :as g]
            [lg-animeka.audit :as audit]
            [lg-animeka.store :as store]
            [lg-animeka.util :as u]))

(def ^:dynamic *fetch*
  (fn [_filters] (throw (ex-info "store not configured" {}))))

(defn rows->works
  "Row-vectors [repo rkey ts_ms value_json] → work maps (parity with the Python
  list comprehension: at-uri build, ts coercion, 1000-char envelope cap)."
  [rows]
  (mapv (fn [[repo rkey ts-ms value-json]]
          {:uri (u/at-uri repo "com.etzhayyim.animeka.work" rkey)
           :rkey rkey
           :ownerDid repo
           :tsMs (long (or ts-ms 0))
           :raw (u/clip (or value-json "") 1000)})
        rows))

(defn node-query [state]
  (if-not (store/configured?)
    {:error "RW_URL not set" :works []}
    (let [filters {:limit (u/clamp (:limit state) 50 1 200)
                   :offset (u/clamp (:offset state) 0 0 #?(:clj Integer/MAX_VALUE :default 2147483647))
                   :owner-did (:owner_did state)}
          works (rows->works (*fetch* filters))]
      {:works works :total (count works)})))

(defn node-emit-audit [state]
  (audit/emit-audit-bg!
   :actor u/app-did :activity "animeka.listWorks"
   :object-id (str "listWorks:" (u/now-iso)) :object-type "animeka.work"
   :attributes {:limit (u/clamp (:limit state) 50 1 200)
                :offset (u/clamp (:offset state) 0 0 2147483647)
                :ownerDid (or (:owner_did state) "*")
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
