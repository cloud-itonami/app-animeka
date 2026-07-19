(ns lg-animeka.graphs.agent-chat
  "animeka `agent_chat` graph — director-AI persona chat.
  NSID: com.etzhayyim.animeka.chat. Faithful clj port of `agent_chat.py`.
  Topology: START → resolve_actor → llm_call → emit_audit → END.

  DEVIATION: langgraph-clj has no RetryPolicy. The vLLM edge is the Murakumo
  loopback (`llm/chat`); actor personas + message assembly are ported verbatim."
  (:require [clojure.string :as str]
            [langgraph.graph :as g]
            [lg-animeka.audit :as audit]
            [lg-animeka.llm :as llm]
            [lg-animeka.util :as u]))

(def actor-prompts
  {"director"
   (str "You are the director AI for an animation studio. Your job is to set the "
        "creative vision: pacing, character beats, visual language. Keep replies "
        "short (≤120 words), decisive, and respectful of the writer/storyboarder "
        "who will execute. Always reference the cut/episode context when given.")
   "screenwriter"
   (str "You are the screenwriter AI. You write taut, character-driven scenes. "
        "Output dialogue + action lines in standard screenplay format. Stay within "
        "the director's brief unless explicitly asked to push back.")
   "storyboarder"
   (str "You are the storyboarder AI. You break a scene into cuts: shot type, "
        "duration, key composition notes. Reply with a numbered cut list, max 12 "
        "cuts per scene. Keep frame composition descriptions to 1 sentence each.")
   "layout"
   (str "You are the layout artist AI. You compose the rough camera, character "
        "blocking, and background framing for a cut. Reply with a structured "
        "description: camera (wide/medium/close), character positions, BG layers.")
   "key_animator"
   (str "You are the key animator (genga) AI. You sketch the keyframes for a cut. "
        "Reply with a numbered keyframe list: each entry has a frame number and "
        "a 1-sentence pose/expression description.")})

(defn system-prompt [role]
  (or (get actor-prompts role) (get actor-prompts "director")))

(defn node-resolve-actor [state]
  (let [role (or (:actor_role state) "director")]
    {:actor_did (str u/app-did ":actor:" role) :actor_role role}))

(defn build-user-system
  "Compose the (system, user-text-or-nil) for the LLM call. Returns nil when the
  message is blank (parity with the 'message required' early error)."
  [state]
  (let [user-text (str/trim (or (:message state) ""))]
    (when (seq user-text)
      (let [role (or (:actor_role state) "director")
            work-id (or (:work_id state) "")
            episode-id (or (:episode_id state) "")
            system (cond-> (system-prompt role)
                     (or (seq work-id) (seq episode-id))
                     (str "\n\nContext: work_id="
                          (if (seq work-id) work-id "<none>")
                          ", episode_id="
                          (if (seq episode-id) episode-id "<none>") "."))]
        {:system system :user (u/clip user-text 4000)}))))

(defn node-llm-call [state]
  (let [su (build-user-system state)]
    (if (nil? su)
      {:error "message required"}
      (let [res (llm/chat (:system su) (:user su)
                          {:max-tokens (or (:max_tokens state) 384)
                           :temperature (or (:temperature state) 0.7)})]
        (if (:error res)
          {:error (:error res)}
          {:reply (str (:content res))
           :model (or (:model res) llm/llm-model)
           :prompt_tokens (:prompt-tokens res 0)
           :completion_tokens (:completion-tokens res 0)
           :total_tokens (:total-tokens res 0)})))))

(defn node-emit-audit [state]
  (audit/emit-audit-bg!
   :actor (or (:actor_did state) u/app-did)
   :activity "animeka.chat.reply"
   :object-id (str "chat:" (or (:actor_role state) "director") ":" (u/now-iso))
   :object-type "animeka.chat"
   :attributes {:actorRole (:actor_role state)
                :userDid (:user_did state)
                :totalTokens (:total_tokens state 0)
                :model (:model state)
                :ok (not (boolean (:error state)))})
  {})

(defn build []
  (-> (g/state-graph)
      (g/add-node :resolve_actor node-resolve-actor)
      (g/add-node :llm_call node-llm-call)
      (g/add-node :emit_audit node-emit-audit)
      (g/add-edge :resolve_actor :llm_call)
      (g/add-edge :llm_call :emit_audit)
      (g/set-entry-point :resolve_actor)
      (g/set-finish-point :emit_audit)
      (g/compile-graph)))

(def GRAPH (build))
