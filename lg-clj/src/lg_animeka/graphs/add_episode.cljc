(ns lg-animeka.graphs.add-episode
  "animeka `addEpisode` graph — insert an episode under a work.
  NSID: com.etzhayyim.animeka.addEpisode. Faithful clj port of `add_episode.py`.
  Topology: START → insert → emit_audit → END."
  (:require [langgraph.graph :as g]
            [lg-animeka.audit :as audit]
            [lg-animeka.store :as store]
            [lg-animeka.util :as u]))

(def collection "com.etzhayyim.animeka.episode")

;; (work-rkey) → {:vertex-id v :fps n} | nil
(def ^:dynamic *resolve-work*
  (fn [_work-rkey] (throw (ex-info "store not configured" {}))))

(defn node-insert [state]
  (let [work-id (or (:work_id state) "")
        title-jp (or (:title_jp state) "")
        episode-num (:episode_num state)]
    (cond
      (not (store/configured?)) {:error "RW_URL not set"}
      (not (seq work-id)) {:error "work_id is required"}
      (not (seq title-jp)) {:error "title_jp is required"}
      (nil? episode-num) {:error "episode_num is required"}
      :else
      (let [owner u/app-did
            work-rkey (u/rkey-from-id work-id)
            rkey (or (:id state) (u/gen-rkey "ep"))]
        (try
          (let [wrow (*resolve-work* work-rkey)
                work-vertex-id (or (:vertex-id wrow)
                                   (u/at-uri owner "com.etzhayyim.animeka.work" work-rkey))
                inherited-fps (or (:fps wrow) 24)
                fps (or (:fps state) inherited-fps)
                vertex-id (u/at-uri owner collection rkey)
                convo-id rkey]
            (store/exec!
             :insert-episode
             [vertex-id owner rkey collection owner work-vertex-id
              (long episode-num) title-jp (long fps)
              (:duration_sec state) (:thumb_cid state) convo-id (u/now-iso)])
            {:result_uri vertex-id
             :result_cid (u/cid-stub vertex-id)
             :result_convo_id convo-id})
          (catch #?(:clj Exception :default :default) e
            {:error (u/clip (str "insert: " #?(:clj (.getMessage e) :default e)) 300)}))))))

(defn node-emit-audit [state]
  (audit/emit-audit-bg!
   :actor u/app-did :activity "animeka.addEpisode"
   :object-id (str "addEpisode:" (or (:result_convo_id state) "") ":" (u/now-iso))
   :object-type "animeka.episode"
   :attributes {:workId (or (:work_id state) "")
                :episodeNum (:episode_num state)
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
