(ns lg-animeka.host
  "Existing host-only entrypoint for Animeka tests and the explicit server adapter.
  Reused in place because ADR-2607171100 freezes new files under numbered layers."
  (:require [babashka.http-client :as http]
            [cheshire.core :as json]
            [clojure.string :as str]
            [clojure.test :as t]
            [org.httpkit.server :as httpkit]
            [lg-animeka.audit :as audit]
            [lg-animeka.llm :as llm]
            [lg-animeka.store :as store]
            [lg-animeka.util :as util]
            [lg-animeka.server :as server]
            [lg-animeka.smoke-test]))

(defn- env [name default]
  (or (System/getenv name) default))

(def murakumo-config
  {:url (env "VLLM_URL" (:url llm/default-config))
   :model (env "VLLM_MODEL" (:model llm/default-config))
   :timeout-sec (Double/parseDouble
                 (env "VLLM_TIMEOUT_SEC" (str (:timeout-sec llm/default-config))))})

(def audit-config
  {:url (env "BPMN_DISPATCHER_INTERNAL_URL"
             "http://bpmn-dispatcher.mitama-udf.svc.cluster.local:8080")
   :secret (env "BPMN_DISPATCHER_INTERNAL_SECRET" "")
   :timeout-sec (Double/parseDouble (env "LG_AUDIT_TIMEOUT_SEC" "3.0"))
   :disabled? (= "1" (env "LG_AUDIT_DISABLED" "0"))})

(def api-key (env "LG_API_KEY" ""))
(def store-url (or (System/getenv "RW_URL")
                   (System/getenv "LG_CHECKPOINTER_URL")
                   ""))
(def app-did (env "ANIMEKA_APP_DID" util/app-did))
(def repo-did (env "ANIMEKA_REPO_DID" util/repo-did))

(defn murakumo-chat [system user opts]
  (llm/chat-with http/post murakumo-config system user opts))

(defn audit-emit [{:keys [actor activity object-id object-type attributes]}]
  (try
    (http/post (str (str/replace (:url audit-config) #"/+$" "")
                    "/xrpc/com.etzhayyim.generic.audit.emit")
               {:headers (cond-> {"Content-Type" "application/json"}
                           (seq (:secret audit-config))
                           (assoc "x-internal-trust" (:secret audit-config)))
                :timeout (long (* 1000 (:timeout-sec audit-config)))
                :body (json/generate-string
                       {:actor actor :activity activity :objectId object-id
                        :objectType object-type :attributes (or attributes {})})})
    nil
    (catch Exception _ nil)))

(defn handler [request]
  (binding [llm/*chat* murakumo-chat
            audit/*emit* audit-emit
            audit/*disabled?* (:disabled? audit-config)
            store/*rw-url* store-url
            util/app-did app-did
            util/repo-did repo-did
            server/*api-key* api-key]
    (server/handler request)))

(defn start-server! [port]
  (server/run-server! (fn [_portable-handler options]
                        (httpkit/run-server handler options))
                      port))

(defn run-tests! []
  (let [{:keys [fail error]} (t/run-tests 'lg-animeka.smoke-test)]
    (when (pos? (+ (or fail 0) (or error 0)))
      (System/exit 1))))

(if (= "--server" (first *command-line-args*))
  (let [port (if-let [value (second *command-line-args*)]
               (Long/parseLong value)
               2027)]
    (start-server! port)
    @(promise))
  (run-tests!))
