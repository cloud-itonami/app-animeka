(ns lg-animeka.graphs.add-cut
  "animeka `addCut` graph — create a cut under a scene, auto-incrementing cutNum
  within the episode and initializing stage_status to all 'pending'.
  NSID: com.etzhayyim.animeka.addCut. Faithful clj port of `add_cut.py`.
  Topology: START → insert → emit_audit → END."
  (:require [langgraph.graph :as g]
            [lg-animeka.audit :as audit]
            [lg-animeka.store :as store]
            [lg-animeka.util :as u]))

(def collection "com.etzhayyim.animeka.cut")

(def stages
  ["script" "storyboard" "layout" "keyAnim"
   "inbetween" "colorDesign" "finish" "background"
   "composite" "edit" "sound" "delivery"])

(def default-stage-status (zipmap stages (repeat "pending")))

;; (scene-rkey) → {:vertex-id v :episode-id e :fps n} | nil
(def ^:dynamic *resolve-scene*
  (fn [_scene-rkey] (throw (ex-info "store not configured" {}))))
;; (episode-id) → current max cut_num (int)
(def ^:dynamic *max-cut-num*
  (fn [_episode-id] 0))

(defn node-insert [state]
  (let [scene-id (or (:scene_id state) "")
        duration-frames (:duration_frames state)]
    (cond
      (not (store/configured?)) {:error "RW_URL not set"}
      (not (seq scene-id)) {:error "scene_id is required"}
      (nil? duration-frames) {:error "durationFrames is required"}
      :else
      (let [owner u/app-did
            scene-rkey (u/rkey-from-id scene-id)
            rkey (or (:id state) (u/gen-rkey "cut"))]
        (try
          (let [srow (*resolve-scene* scene-rkey)
                scene-vertex-id (or (:vertex-id srow)
                                    (u/at-uri owner "com.etzhayyim.animeka.scene" scene-rkey))
                scene-episode-id (or (:episode-id srow) (:episode_id state) "")
                inherited-fps (or (:fps srow) 24)
                fps (or (:fps state) (long inherited-fps))
                cut-num (cond
                          (some? (:cut_num state)) (:cut_num state)
                          (seq scene-episode-id) (inc (long (or (*max-cut-num* scene-episode-id) 0)))
                          :else nil)
                vertex-id (u/at-uri owner collection rkey)
                cut-did (str "did:web:animeka.etzhayyim.com:cut:" rkey)]
            (store/exec!
             :insert-cut
             [vertex-id owner rkey collection owner scene-vertex-id scene-episode-id
              (when (some? cut-num) (long cut-num))
              (long duration-frames) (long fps)
              (:camera_mode state) (:camera_note state)
              default-stage-status (u/now-iso)])
            {:result_uri vertex-id
             :result_cid (u/cid-stub vertex-id)
             :result_did cut-did
             :result_cut_num cut-num})
          (catch #?(:clj Exception :default :default) e
            {:error (u/clip (str "insert: " #?(:clj (.getMessage e) :default e)) 300)}))))))

(defn node-emit-audit [state]
  (audit/emit-audit-bg!
   :actor u/app-did :activity "animeka.addCut"
   :object-id (str "addCut:" (or (:result_uri state) "") ":" (u/now-iso))
   :object-type "animeka.cut"
   :attributes {:sceneId (or (:scene_id state) "")
                :cutNum (:result_cut_num state)
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
