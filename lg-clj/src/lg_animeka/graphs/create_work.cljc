(ns lg-animeka.graphs.create-work
  "animeka `createWork` graph — insert a work record.
  NSID: com.etzhayyim.animeka.createWork. Faithful clj port of `create_work.py`.
  Topology: START → insert → emit_audit → END.

  The INSERT is the injectable `store/*exec*` seam; the rkey/slug/did derivation
  + validation are ported faithfully and tested."
  (:require [langgraph.graph :as g]
            [lg-animeka.audit :as audit]
            [lg-animeka.store :as store]
            [lg-animeka.util :as u]))

(def collection "com.etzhayyim.animeka.work")

(defn node-insert [state]
  (let [title (or (:title state) "")]
    (cond
      (not (store/configured?)) {:error "RW_URL not set"}
      (not (seq title)) {:error "title is required"}
      :else
      (let [rkey (or (:id state) (u/gen-rkey "work"))
            slug (or (:slug state) rkey)
            owner u/app-did
            vertex-id (u/at-uri owner collection rkey)
            work-status (or (:status state) "planning")
            work-did (str "did:web:animeka.etzhayyim.com:work:" slug)]
        (try
          (store/exec!
           :insert-work
           [vertex-id owner rkey collection owner title title slug
            (:synopsis state) work-status (or (:fps state) 24)
            (:cover_cid state) (u/now-iso)])
          {:result_id rkey :result_did work-did
           :result_title title :result_status work-status}
          (catch #?(:clj Exception :default :default) e
            {:error (u/clip (str "insert: " #?(:clj (.getMessage e) :default e)) 300)}))))))

(defn node-emit-audit [state]
  (audit/emit-audit-bg!
   :actor u/app-did :activity "animeka.createWork"
   :object-id (str "createWork:" (or (:result_id state) "") ":" (u/now-iso))
   :object-type "animeka.work"
   :attributes {:workId (or (:result_id state) "")
                :title (or (:result_title state) "")
                :status (or (:result_status state) "")})
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
