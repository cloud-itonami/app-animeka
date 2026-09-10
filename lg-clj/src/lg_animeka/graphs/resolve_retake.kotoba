(ns lg-animeka.graphs.resolve-retake
  "animeka `resolveRetake` graph — mark a retake resolved/acknowledged and
  un-flip the cut priority when no open retakes remain.
  NSID: com.etzhayyim.animeka.resolveRetake. Faithful clj port of `resolve_retake.py`.
  Topology: START → update → emit_audit → END.

  `cut-priority` derivation (open-count → 'normal' | 'retake') is the tested logic."
  (:require [langgraph.graph :as g]
            [lg-animeka.audit :as audit]
            [lg-animeka.store :as store]
            [lg-animeka.util :as u]))

;; (retake-rkey) → {:vertex-id v :cut-id c} | nil
(def ^:dynamic *fetch-retake*
  (fn [_rkey] (throw (ex-info "store not configured" {}))))
;; (retake-vertex-id status resolved-by-uri) — persist new status
(def ^:dynamic *update-retake*
  (fn [& _] nil))
;; (cut-vertex-id) → count of remaining open/acknowledged/inProgress retakes
(def ^:dynamic *open-count*
  (fn [_cut-vertex-id] 0))
;; (cut-vertex-id) — reset priority to normal
(def ^:dynamic *clear-cut-priority*
  (fn [_cut-vertex-id] nil))

(defn node-update [state]
  (let [retake-id (or (:retake_id state) "")
        new-status (or (:status state) "")]
    (cond
      (not (store/configured?)) {:error "RW_URL not set"}
      (or (not (seq retake-id)) (not (seq new-status)))
      {:error "retakeId and status are required"}
      :else
      (let [retake-rkey (u/rkey-from-id retake-id)]
        (try
          (let [row (*fetch-retake* retake-rkey)]
            (if (nil? row)
              {:error (str "retake not found: " retake-rkey)}
              (let [{:keys [vertex-id cut-id]} row]
                (*update-retake* vertex-id new-status (:resolved_by_uri state))
                (let [cut-priority
                      (if (seq cut-id)
                        (let [open (long (or (*open-count* cut-id) 0))]
                          (if (zero? open)
                            (do (*clear-cut-priority* cut-id) "normal")
                            "retake"))
                        "normal")]
                  {:result_retake_id retake-rkey
                   :result_status new-status
                   :result_cut_priority cut-priority}))))
          (catch #?(:clj Exception :default :default) e
            {:error (u/clip (str "update: " #?(:clj (.getMessage e) :default e)) 300)}))))))

(defn node-emit-audit [state]
  (audit/emit-audit-bg!
   :actor u/app-did :activity "animeka.resolveRetake"
   :object-id (str "resolveRetake:" (or (:retake_id state) "") ":" (u/now-iso))
   :object-type "animeka.retake"
   :attributes {:retakeId (or (:retake_id state) "")
                :status (or (:result_status state) "")
                :cutPriority (or (:result_cut_priority state) "")})
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
