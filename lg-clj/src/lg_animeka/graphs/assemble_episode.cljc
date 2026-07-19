(ns lg-animeka.graphs.assemble-episode
  "animeka `assembleEpisode` graph — concat per-cut MP4 blobs into one episode
  video and upload it. NSID: com.etzhayyim.animeka.assembleEpisode. Faithful clj
  port of `assemble_episode.py` (topology).
  Topology: START → fetch_cuts → download → concat → upload → END.

  DEVIATION (noted): SA1 downloads blobs, SA2 shells out to ffmpeg concat, SA3
  uploads the assembled MP4 to PDS — all native/remote edges with no bb host.
  They are injectable seams (`*fetch-cuts*`, `*download*`, `render/*ffmpeg-concat*`,
  `*upload*`); the linear topology + error short-circuit are ported faithfully."
  (:require [langgraph.graph :as g]
            [lg-animeka.audit :as audit]
            [lg-animeka.render :as render]
            [lg-animeka.store :as store]
            [lg-animeka.util :as u]))

;; (limit) → seq of cut maps {:rkey :output_cid :created_at}
(def ^:dynamic *fetch-cuts* (fn [_limit] (throw (ex-info "store not configured" {}))))
;; (cut-rows) → seq of local paths
(def ^:dynamic *download* (fn [_cut-rows] []))
;; (episode-rkey episode-cid cut-count duration-sec) — persist episode output_cid
(def ^:dynamic *save-episode* (fn [& _] nil))

(defn node-fetch-cuts [state]
  (if-not (store/configured?)
    {:error "RW_URL not set"}
    (let [limit (long (or (:limit state) 999))]
      {:cut_rows (vec (*fetch-cuts* limit))})))

(defn node-download [state]
  (if (:error state)
    {}
    (let [cut-rows (or (:cut_rows state) [])]
      (if (empty? cut-rows)
        {:error "no cuts to assemble"}
        {:local_paths (vec (*download* cut-rows))}))))

(defn node-concat [state]
  (if (:error state)
    {}
    (let [paths (or (:local_paths state) [])]
      (if (empty? paths)
        {:error "SA2: no local paths"}
        (let [res (render/*ffmpeg-concat* paths nil 24)]
          (if (:error res)
            {:error (str "SA2 ffmpeg: " (:error res))}
            {:concat_path (:path res) :duration_sec (:duration-sec res)}))))))

(defn node-upload [state]
  (if (:error state)
    {}
    (if-not (seq (:concat_path state))
      {:error "SA3: no concat file"}
      (let [res (render/*pds-post* {:kind :episode-blob :path (:concat_path state)})]
        (if (:error res)
          {:error (str "SA3 upload: " (:error res))}
          (let [episode-rkey (or (:episode_rkey state) "")
                cut-count (count (:local_paths state))
                episode-cid (:cid res)]
            (when (store/configured?)
              (*save-episode* episode-rkey episode-cid cut-count (:duration_sec state)))
            (audit/emit-audit-bg!
             :actor u/app-did :activity "animeka.assembleEpisode"
             :object-id (str "assemble:" episode-rkey ":" (u/now-iso))
             :object-type "animeka.episode"
             :attributes {:episodeRkey episode-rkey :cutCount cut-count :episodeCid episode-cid})
            {:episode_cid episode-cid :cut_count cut-count}))))))

(defn build []
  (-> (g/state-graph)
      (g/add-node :fetch_cuts node-fetch-cuts)
      (g/add-node :download node-download)
      (g/add-node :concat node-concat)
      (g/add-node :upload node-upload)
      (g/add-edge :fetch_cuts :download)
      (g/add-edge :download :concat)
      (g/add-edge :concat :upload)
      (g/set-entry-point :fetch_cuts)
      (g/set-finish-point :upload)
      (g/compile-graph)))

(def GRAPH (build))
