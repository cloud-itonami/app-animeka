(ns lg-animeka.graphs.cut-runner
  "animeka `cutRunner` graph — orchestrate the full per-cut production pipeline.
  NSID: com.etzhayyim.animeka.cutRunner. Faithful clj port of `cut_runner.py`.
  Topology: START → fetch_cut → storyboard → layout → keyframe → background →
            update_cut → audit → END.

  Each stage delegates to the compiled sub-graph (generate_storyboard etc.) so
  retry/audit/insert semantics are inherited without duplication — exactly as the
  Python invokes the sub-GRAPHs. Sub-graph invocation failures are swallowed
  (parity with the Python try/except returning {})."
  (:require [langgraph.graph :as g]
            [lg-animeka.audit :as audit]
            [lg-animeka.graphs.generate-storyboard :as sb]
            [lg-animeka.graphs.generate-layout :as ly]
            [lg-animeka.graphs.generate-keyframe :as kf]
            [lg-animeka.graphs.generate-background :as bg]
            [lg-animeka.store :as store]
            [lg-animeka.util :as u]))

;; (cut-rkey) → {:camera-note s :status st} | nil
(def ^:dynamic *fetch-cut* (fn [_rkey] nil))
;; (cut-rkey stage-status-map) — persist stage_status + status='ready_for_review'
(def ^:dynamic *update-cut* (fn [& _] nil))

(defn- safe-invoke [graph input]
  (try (g/invoke graph input) (catch #?(:clj Exception :default :default) _ {})))

(defn node-fetch-cut [state]
  (let [cut-id (or (:cut_id state) "")]
    (cond
      (not (seq cut-id)) {:error "cut_id required"}
      (not (store/configured?)) {:status "running"}
      :else
      (let [row (*fetch-cut* (u/rkey-from-id cut-id))]
        (if (nil? row)
          {:error (str "cut not found: " (u/rkey-from-id cut-id))}
          {:camera_note (:camera-note row) :status "running"})))))

(defn node-storyboard [state]
  (if (:error state)
    {}
    (let [out (safe-invoke sb/GRAPH {:cut_id (:cut_id state) :cut_summary (:camera_note state)})]
      {:storyboard_uri (:storyboard_uri out) :storyboard_cid (:blob_cid out)})))

(defn node-layout [state]
  (if (:error state)
    {}
    (let [out (safe-invoke ly/GRAPH {:cut_id (:cut_id state) :visual_prompt (:camera_note state)
                                     :storyboard_cid (:storyboard_cid state)})]
      {:layout_uri (:layout_uri out) :layout_cid (:blob_cid out)})))

(defn node-keyframe [state]
  (if (:error state)
    {}
    (let [out (safe-invoke kf/GRAPH {:cut_id (:cut_id state) :visual_prompt (:camera_note state)})]
      {:keyframe_uri (:keyframe_uri out) :keyframe_cid (:blob_cid out)})))

(defn node-background [state]
  (if (:error state)
    {}
    (let [out (safe-invoke bg/GRAPH {:cut_id (:cut_id state) :scene_description (:camera_note state)})]
      {:background_uri (:background_uri out) :background_cid (:blob_cid out)})))

(defn node-update-cut [state]
  (if-not (store/configured?)
    {:status "ready_for_review"}
    (let [cut-rkey (u/rkey-from-id (or (:cut_id state) ""))
          stage-status {"storyboard" (if (:storyboard_uri state) "done" "error")
                        "layout"     (if (:layout_uri state) "done" "error")
                        "keyframe"   (if (:keyframe_uri state) "done" "error")
                        "background" (if (:background_uri state) "done" "error")}]
      (try (*update-cut* cut-rkey stage-status) (catch #?(:clj Exception :default :default) _ nil))
      {:status "ready_for_review"})))

(defn node-audit [state]
  (audit/emit-audit-bg!
   :actor u/app-did :activity "animeka.cutRunner"
   :object-id (str "cutRunner:" (or (:cut_id state) "") ":" (u/now-iso))
   :object-type "animeka.cut"
   :attributes {:cutId (:cut_id state)
                :storyboardUri (:storyboard_uri state)
                :layoutUri (:layout_uri state)
                :keyframeUri (:keyframe_uri state)
                :backgroundUri (:background_uri state)
                :ok (not (boolean (:error state)))
                :status (:status state)})
  {})

(defn build []
  (-> (g/state-graph)
      (g/add-node :fetch_cut node-fetch-cut)
      (g/add-node :storyboard node-storyboard)
      (g/add-node :layout node-layout)
      (g/add-node :keyframe node-keyframe)
      (g/add-node :background node-background)
      (g/add-node :update_cut node-update-cut)
      (g/add-node :audit node-audit)
      (g/add-edge :fetch_cut :storyboard)
      (g/add-edge :storyboard :layout)
      (g/add-edge :layout :keyframe)
      (g/add-edge :keyframe :background)
      (g/add-edge :background :update_cut)
      (g/add-edge :update_cut :audit)
      (g/set-entry-point :fetch_cut)
      (g/set-finish-point :audit)
      (g/compile-graph)))

(def GRAPH (build))
