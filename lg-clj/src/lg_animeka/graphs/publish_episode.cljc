(ns lg-animeka.graphs.publish-episode
  "animeka `publishEpisode` graph — announce a finished episode to social + mark
  it announced. NSID: com.etzhayyim.animeka.publishEpisode. Faithful clj port of
  `publish_episode.py`.
  Topology: START → fetch_episode → post_social → update_status → END.

  The `skipped`/`error` short-circuit and the ≤300-char post-text fallback are
  ported faithfully; the episode lookup, social-post mint, and status UPDATE are
  injectable seams (no PDS/mint host under bb)."
  (:require [langgraph.graph :as g]
            [lg-animeka.audit :as audit]
            [lg-animeka.store :as store]
            [lg-animeka.util :as u]))

(def app-did u/app-did)

;; (episode-rkey-or-blank) → {:episode-rkey r :output-cid c :work-title t}
;;                          | {:skipped true} | {:skipped true :episode-rkey r}
(def ^:dynamic *fetch-episode* (fn [_rkey] {:skipped true}))
;; (episode-rkey work-title episode-url text) → {:uri u} | {:error e} | {:skipped true}
(def ^:dynamic *post-social* (fn [_args] {:skipped true}))
;; (episode-rkey) — mark status='announced'
(def ^:dynamic *mark-announced* (fn [_rkey] nil))

(defn post-text
  "≤300-char announcement, with the English fallback (parity with SP1)."
  [work-title episode-url]
  (let [full (str "🎬 新エピソード公開！\n『" work-title "』\n"
                  "BGM・SFX・ナレーション付きで全カット完成。\n" episode-url
                  "\n#animeka #etzhayyimai")]
    (if (> (count full) 300)
      (str "🎬 New episode — 『" work-title "』\n" episode-url "\n#animeka")
      full)))

(defn node-fetch-episode [state]
  (if-not (store/configured?)
    {:error "RW_URL not set"}
    (let [res (*fetch-episode* (when (seq (:episode_rkey state)) (:episode_rkey state)))]
      (cond
        (:skipped res) (cond-> {:skipped true} (:episode-rkey res) (assoc :episode_rkey (:episode-rkey res)))
        :else {:episode_rkey (:episode-rkey res)
               :output_cid (or (:output-cid res) "")
               :work_title (or (:work-title res) "animeka.etzhayyim.com")}))))

(defn node-post-social [state]
  (if (or (:error state) (:skipped state))
    {}
    (let [episode-rkey (or (:episode_rkey state) "")
          work-title (or (:work_title state) "animeka.etzhayyim.com")
          episode-url (str "https://animeka.etzhayyim.com/episodes/" episode-rkey)
          res (*post-social* {:episode-rkey episode-rkey :work-title work-title
                              :episode-url episode-url :text (post-text work-title episode-url)})]
      (cond
        (:skipped res) {:skipped true}
        (:error res) {:error (str "SP1 create-social-post: " (:error res))}
        :else {:social_uri (or (:uri res) "")}))))

(defn node-update-status [state]
  (if (or (:error state) (:skipped state))
    {}
    (let [episode-rkey (or (:episode_rkey state) "")
          social-uri (or (:social_uri state) "")]
      (when (and (seq episode-rkey) (seq social-uri) (store/configured?))
        (*mark-announced* episode-rkey)
        (audit/emit-audit-bg!
         :actor app-did :activity "animeka.publishEpisode"
         :object-id (str "publish:" episode-rkey ":" (u/now-iso))
         :object-type "animeka.episode"
         :attributes {:episodeRkey episode-rkey :socialUri social-uri}))
      {})))

(defn build []
  (-> (g/state-graph)
      (g/add-node :fetch_episode node-fetch-episode)
      (g/add-node :post_social node-post-social)
      (g/add-node :update_status node-update-status)
      (g/add-edge :fetch_episode :post_social)
      (g/add-edge :post_social :update_status)
      (g/set-entry-point :fetch_episode)
      (g/set-finish-point :update_status)
      (g/compile-graph)))

(def GRAPH (build))
