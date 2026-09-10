(ns lg-animeka.audit
  "Fire-and-forget BPMN `generic.audit.emit` shim — clj port of `audit.py`.

  The Python emits one OCEL event per node to bpmn-dispatcher's
  `com.etzhayyim.generic.audit.emit`. The dispatch is fire-and-forget: a
  failure to emit MUST NOT block the graph node (audit loss is logged, never
  raised — the LangGraph state checkpoint is the source of truth).

  Here `*emit*` is an injectable seam: the default is a no-op (audit disabled
  unless a dispatcher is wired). The host owns the HTTP implementation. Graph nodes
  call `emit-audit-bg!` exactly where the Python calls `emit_audit_bg(...)`.")

(def ^:dynamic *disabled?* false)

;; Default seam = no-op (audit disabled unless a dispatcher emitter is injected).
;; Rebind to a host emitter (or a stub in tests) to capture emissions.
(def ^:dynamic *emit* (fn [_event] nil))

(defn emit-audit-bg!
  "Fire-and-forget OCEL emission. Returns nil. Honours LG_AUDIT_DISABLED.
  Keyword args mirror the Python `emit_audit_bg(actor=,activity=,object_id=,
  object_type=,attributes=)`."
  [& {:keys [actor activity object-id object-type attributes]}]
  (when-not *disabled?*
    (try (*emit* {:actor actor :activity activity :object-id object-id
                  :object-type object-type :attributes (or attributes {})})
         (catch #?(:clj Exception :default :default) _ nil)))
  nil)
