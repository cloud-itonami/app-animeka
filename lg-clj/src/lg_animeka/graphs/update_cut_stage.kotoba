(ns lg-animeka.graphs.update-cut-stage
  "animeka `updateCutStage` graph — patch a cut's stage_status JSON + assignees,
  and re-derive the overall cut priority.
  NSID: com.etzhayyim.animeka.updateCutStage. Faithful clj port of
  `update_cut_stage.py`. Topology: START → update → emit_audit → END.

  `derive-priority` is the load-bearing, tested logic. The cut fetch + UPDATE are
  injectable seams (`*fetch-cut*` returns the cut with already-parsed JSON maps;
  `*save*` persists the patched maps + priority)."
  (:require [langgraph.graph :as g]
            [lg-animeka.audit :as audit]
            [lg-animeka.store :as store]
            [lg-animeka.util :as u]))

(defn derive-priority
  "any retake → 'retake'; else all approved → 'approved'; else 'normal'.
  (parity: Python `all(... 'approved')` over an empty seq yields 'approved')."
  [stage-statuses]
  (cond
    (some #{"retake"} stage-statuses) "retake"
    (every? #(= "approved" %) stage-statuses) "approved"
    :else "normal"))

;; (rkey) → {:vertex-id v :stage-status {..} :assignees {..}} | nil
(def ^:dynamic *fetch-cut*
  (fn [_rkey] (throw (ex-info "store not configured" {}))))
;; (vertex-id stage-status assignees priority) → nil
(def ^:dynamic *save*
  (fn [& _] (throw (ex-info "store not configured" {}))))

(defn node-update [state]
  (let [cut-id (or (:cut_id state) "")
        stage (or (:stage state) "")]
    (cond
      (not (store/configured?)) {:error "RW_URL not set"}
      (or (not (seq cut-id)) (not (seq stage))) {:error "cut_id and stage are required"}
      :else
      (let [cut-rkey (u/rkey-from-id cut-id)
            new-status (or (:status state) "in_progress")
            assignee (:assignee_did state)]
        (try
          (let [row (*fetch-cut* cut-rkey)]
            (if (nil? row)
              {:error (str "cut not found: " cut-rkey)}
              (let [stage-status (assoc (or (:stage-status row) {}) stage new-status)
                    assignees (cond-> (or (:assignees row) {})
                                (seq assignee) (assoc stage assignee))
                    priority (derive-priority (vals stage-status))]
                (*save* (:vertex-id row) stage-status assignees priority)
                {:result_cut_id cut-rkey :result_stage stage
                 :result_status new-status :derived_count 0})))
          (catch #?(:clj Exception :default :default) e
            {:error (u/clip (str "update: " #?(:clj (.getMessage e) :default e)) 300)}))))))

(defn node-emit-audit [state]
  (audit/emit-audit-bg!
   :actor u/app-did :activity "animeka.updateCutStage"
   :object-id (str "updateCutStage:" (or (:cut_id state) "") ":" (u/now-iso))
   :object-type "animeka.cut"
   :attributes {:cutId (or (:cut_id state) "")
                :stage (or (:stage state) "")
                :status (or (:result_status state) "")})
  {})

(defn build []
  (-> (g/state-graph)
      (g/add-node :update node-update)
      (g/add-node :emit_audit node-emit-audit)
      (g/add-edge :update :emit_audit)
      (g/set-entry-point :update)
      (g/set-finish-point :emit_audit)
      (g/compile-graph)))

(def GRAPH (build))
