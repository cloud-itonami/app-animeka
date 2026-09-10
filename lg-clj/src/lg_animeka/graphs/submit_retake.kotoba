(ns lg-animeka.graphs.submit-retake
  "animeka `submitRetake` graph — file a retake against a cut layer and flip the
  parent cut's stage to 'retake'.
  NSID: com.etzhayyim.animeka.submitRetake. Faithful clj port of `submit_retake.py`.
  Topology: START → insert → emit_audit → END."
  (:require [langgraph.graph :as g]
            [lg-animeka.audit :as audit]
            [lg-animeka.store :as store]
            [lg-animeka.util :as u]))

(def collection "com.etzhayyim.animeka.retake")

;; (cut-rkey) → {:vertex-id v :stage-status {..}} | nil
(def ^:dynamic *resolve-cut*
  (fn [_cut-rkey] (throw (ex-info "store not configured" {}))))
;; insert the retake record
(def ^:dynamic *insert-retake*
  (fn [& _] (throw (ex-info "store not configured" {}))))
;; (cut-vertex-id stage-status) — flip parent cut to retake
(def ^:dynamic *flip-cut*
  (fn [& _] nil))

(defn node-insert [state]
  (let [target-uri (or (:target_uri state) "")
        stage (or (:stage state) "")
        comment (or (:comment state) "")]
    (cond
      (not (store/configured?)) {:error "RW_URL not set"}
      (or (not (seq target-uri)) (not (seq stage)) (not (seq comment)))
      {:error "targetUri, stage and comment are required"}
      :else
      (let [owner u/app-did
            rkey (u/gen-rkey "rt")
            vertex-id (u/at-uri owner collection rkey)
            cut-id-input (or (:cut_id state) target-uri)
            cut-rkey (u/rkey-from-id cut-id-input)]
        (try
          (let [crow (*resolve-cut* cut-rkey)
                cut-vertex-id (or (:vertex-id crow)
                                  (u/at-uri owner "com.etzhayyim.animeka.cut" cut-rkey))]
            (*insert-retake*
             [vertex-id owner rkey collection owner target-uri cut-vertex-id
              stage (or (:severity state) "minor") comment
              (:timecode_frame state) (:region_x state) (:region_y state)
              (:region_w state) (:region_h state) (:assignee state) owner (u/now-iso)])
            (when crow
              (*flip-cut* cut-vertex-id (assoc (or (:stage-status crow) {}) stage "retake")))
            {:result_uri vertex-id :result_cid (u/cid-stub vertex-id)})
          (catch #?(:clj Exception :default :default) e
            {:error (u/clip (str "insert: " #?(:clj (.getMessage e) :default e)) 300)}))))))

(defn node-emit-audit [state]
  (audit/emit-audit-bg!
   :actor u/app-did :activity "animeka.submitRetake"
   :object-id (str "submitRetake:" (or (:result_uri state) "") ":" (u/now-iso))
   :object-type "animeka.retake"
   :attributes {:targetUri (or (:target_uri state) "")
                :stage (or (:stage state) "")
                :severity (or (:severity state) "minor")
                :uri (or (:result_uri state) "")})
  {})

(defn build []
  (-> (g/state-graph)
      (g/add-node :insert node-insert)
      (g/add-node :emit_audit node-emit-audit)
      (g/add-edge :insert :emit_audit)
      (g/set-entry-point :insert)
      (g/set-finish-point :emit_audit)
      (g/compile-graph)))

(def GRAPH (build))
