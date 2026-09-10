(ns lg-animeka.graphs.health
  "animeka `health` graph — liveness probe. NSID: com.etzhayyim.animeka.health.

  Faithful clj port of `lg/lg_animeka/graphs/health.py` (ADR-2606280030).
  Topology: START → check_rw → summarize → emit_audit → END.

  DEVIATION: langgraph-clj has no RetryPolicy (the Python `check_rw` carries
  max_attempts=2); the topology/behaviour is otherwise identical. The RW
  `SELECT 1` is an injectable seam (`*rw-ping*`) — default reports not-configured
  exactly like the Python `if not _RW_URL` branch."
  (:require [langgraph.graph :as g]
            [lg-animeka.audit :as audit]
            [lg-animeka.store :as store]
            [lg-animeka.util :as u]))

;; (rw-url) → {:rw_ok true :rw_latency_ms n} | {:rw_ok false :error ".."}
(def ^:dynamic *rw-ping*
  (fn [_url] {:rw_ok false :error "rw ping not configured"}))

(defn node-check-rw [_state]
  (if-not (store/configured?)
    {:rw_ok false :error "RW_URL not set"}
    (*rw-ping* store/*rw-url*)))

(defn node-summarize [state]
  {:ok (boolean (:rw_ok state))
   :server_now (u/now-iso)})

(defn node-emit-audit [state]
  (audit/emit-audit-bg!
   :actor u/app-did
   :activity "animeka.health.check"
   :object-id (str "health:" (u/now-iso))
   :object-type "animeka.health"
   :attributes {:ok (:ok state false)
                :rwOk (:rw_ok state false)
                :rwLatencyMs (:rw_latency_ms state 0)})
  {})

(defn build []
  (-> (g/state-graph)
      (g/add-node :check_rw node-check-rw)
      (g/add-node :summarize node-summarize)
      (g/add-node :emit_audit node-emit-audit)
      (g/add-edge :check_rw :summarize)
      (g/add-edge :summarize :emit_audit)
      (g/set-entry-point :check_rw)
      (g/set-finish-point :emit_audit)
      (g/compile-graph)))

(def GRAPH (build))
