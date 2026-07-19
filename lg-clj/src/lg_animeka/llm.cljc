(ns lg-animeka.llm
  "Injectable LLM chat seam — clj port of the vLLM (`httpx` → RunPod) edge shared
  by the generation/chat graphs (ADR-2606280030).

  DEVIATION (noted): the Python posts to a RunPod vLLM proxy URL
  (`https://…proxy.runpod.net/v1`). Per ADR-2605215000 / ADR-2606172359
  (Murakumo DEFAULT-PREFERRED) the host supplies a purpose-bound HTTP capability
  and endpoint configuration. The portable layer asserts the endpoint is on the
  Murakumo fleet allowlist before use. The chat call is the injectable `*chat*`
  seam so tests run offline with deterministic stubs.

  `*chat*` contract:  (system user opts) →
      {:content <str> :model <str>
       :prompt-tokens <int> :completion-tokens <int> :total-tokens <int>
       :latency-ms <int>}
    | {:error <str> :latency-ms <int>}"
  (:require #?(:clj [cheshire.core :as json])
            [clojure.string :as str]))

;; Murakumo fleet (ADR-2605215000) — the ONLY inference endpoints representable.
(def murakumo-allowed-hosts
  #{"127.0.0.1:4000" "localhost:4000"
    "192.168.1.70:8077" "192.168.1.70:11434"
    "127.0.0.1:11434" "localhost:11434"})

(def default-config
  {:url "http://127.0.0.1:4000/v1"
   :model "tier0-general"
   :timeout-sec 60.0})

(def llm-model (:model default-config))

(defn assert-murakumo
  "Refuse any LLM endpoint outside the Murakumo fleet (http only)."
  [endpoint]
  (let [[_ scheme host] (or (re-find #"^([A-Za-z][A-Za-z0-9+.\-]*)://([^/?#]*)"
                                     (str endpoint))
                            [nil nil nil])]
    (when-not (and (= "http" (some-> scheme str/lower-case))
                   (contains? murakumo-allowed-hosts (some-> host str/lower-case)))
      (throw (ex-info (str "inference endpoint " (pr-str endpoint)
                           " is outside the Murakumo fleet (ADR-2605215000)")
                      {:murakumo-only-violation true :endpoint endpoint})))))

(defn- clip [s n] (let [s (str s)] (subs s 0 (min n (count s)))))

(defn chat-with
  "POST a chat-completions request through an explicit HTTP capability to the Murakumo loopback
  gateway. opts: {:max-tokens :temperature}. Returns the response map or
  {:error ...} (parity with each node's httpx try/except)."
  [http-post {:keys [url model timeout-sec] :or {url (:url default-config)
                                                 model (:model default-config)
                                                 timeout-sec (:timeout-sec default-config)}}
   system user {:keys [max-tokens temperature] :or {max-tokens 300 temperature 0.7}}]
  (when-not (fn? http-post)
    (throw (ex-info "live Animeka inference requires an explicit HTTP POST capability"
                    {:capability :animeka/murakumo-http-post})))
  (let [url (str/replace (str url) #"/+$" "")]
    (assert-murakumo url)
  #?(:clj
     (try
       (let [resp  (http-post (str url "/chat/completions")
                         {:headers {"Content-Type" "application/json"}
                          :timeout (long (* 1000 (double timeout-sec)))
                          :throw false
                          :body (json/generate-string {:model model
                                      :messages [{:role "system" :content system}
                                                 {:role "user" :content user}]
                                      :max_tokens max-tokens
                                      :temperature temperature})})
             status (:status resp)]
         (if (>= status 400)
           {:error (str "vllm " status ": " (clip (:body resp) 200))}
           (let [body   (json/parse-string (:body resp) true)
                 choice (get-in body [:choices 0])
                 usage  (or (:usage body) {})]
             {:content (str/trim (str (get-in choice [:message :content])))
              :model (or (:model body) model)
              :prompt-tokens (int (or (:prompt_tokens usage) 0))
              :completion-tokens (int (or (:completion_tokens usage) 0))
              :total-tokens (int (or (:total_tokens usage) 0))})))
       (catch Exception e {:error (clip (.getMessage e) 200)}))
     :default {:error "llm not available on this host"})))

(def ^:dynamic *chat* nil)

(defn chat
  "Convenience: (chat system user) | (chat system user opts). Always returns a
  map (never throws to the node)."
  ([system user] (chat system user {}))
  ([system user opts]
   (when-not (fn? *chat*)
     (throw (ex-info "Animeka inference requires an explicit chat capability"
                     {:capability :animeka/chat})))
   (*chat* system user opts)))

(defn content
  "Best-effort content string from a chat result ('' on error)."
  [res]
  (if (and (map? res) (not (:error res))) (str (:content res)) ""))
