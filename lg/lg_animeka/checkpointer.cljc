;; ported from 60-apps/etzhayyim-project-animeka/lg/lg_animeka/checkpointer.py
;; RisingWave-compatible LangGraph checkpoint saver.
;;
;; LangGraph's stock `AsyncPostgresSaver` uses `INSERT ... ON CONFLICT DO
;; UPDATE`, which RisingWave PG :4566 does NOT support. RW does support
;; PK-implicit overwrite, so a plain INSERT is enough, falling back to
;; delete-then-insert for the writes table. We exploit that here.
;;
;; The actual checkpoint saver subclasses `langgraph.checkpoint.postgres.aio
;; .AsyncPostgresSaver`, an external Python/LangGraph dependency that has no
;; Clojure/JVM equivalent. The faithful port therefore preserves the
;; RW-compat SQL strings (pure data, the only host-independent content) and
;; keeps the saver constructor behind a #?(:clj ...) host gate: it cannot be
;; satisfied without the langgraph runtime, so it raises with the same
;; precondition (CHECKPOINTER_URL must be set) the Python code enforces.
(ns lg.lg-animeka.checkpointer
  (:require [clojure.string]))

;; ── env: LG_CHECKPOINTER_URL or RW_URL ───────────────────────────────
(defn checkpointer-url
  "Normalize a checkpointer URL supplied by an explicit host adapter."
  ([] "")
  ([url] (or url "")))

;; ── RW-compat queries (override the stock LangGraph SQL strings) ──────
;;
;; Stock PostgresSaver uses `... ON CONFLICT (...) DO UPDATE SET ...`.
;; RW silently overwrites on PK collision, so a plain INSERT is enough
;; IF every column appears in the INSERT (we never want partial updates).

(def rw-insert-checkpoint
  "
    INSERT INTO lg_checkpoints
        (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id,
         type, checkpoint, metadata, created_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
")

(def rw-insert-blob
  "
    INSERT INTO lg_checkpoint_blobs
        (thread_id, checkpoint_ns, channel, version, type, blob, created_at)
    VALUES (%s, %s, %s, %s, %s, %s, NOW())
")

;; checkpoint_writes uses delete-then-insert because the stock
;; implementation expects to ignore (NO UPDATE) on conflict — we
;; replicate with explicit DELETE.
(def rw-delete-writes
  "
    DELETE FROM lg_checkpoint_writes
    WHERE thread_id = %s
      AND checkpoint_ns = %s
      AND checkpoint_id = %s
      AND task_id = %s
      AND idx = %s
")

(def rw-insert-writes
  "
    INSERT INTO lg_checkpoint_writes
        (thread_id, checkpoint_ns, checkpoint_id, task_id, idx,
         channel, type, blob, task_path, created_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
")

(defn build-checkpointer
  "Yield a LangGraph checkpoint saver bound to RW PG.

  Strategy (Python): subclass `AsyncPostgresSaver` and override the three
  write methods to use the RW-compat SQL above; reads (`aget_tuple`,
  `alist`) are unmodified plain SELECTs that work as-is on RW.

  This depends on the external langgraph/psycopg runtime, which has no
  Clojure host. The precondition is preserved (CHECKPOINTER_URL must be
  set); the saver itself is unavailable on this host."
  [& [supplied-url]]
  (let [url (checkpointer-url supplied-url)]
    (when (clojure.string/blank? url)
      (throw (ex-info
               (str "LG_CHECKPOINTER_URL or RW_URL must be set "
                    "for the lg-animeka checkpointer")
               {:from "build_checkpointer"})))
    (throw (ex-info
             (str "build-checkpointer requires the langgraph "
                  "AsyncPostgresSaver runtime, which has no Clojure host")
             {:from "build_checkpointer" :url-set true}))))

;; ── Convenience for langgraph.json declarative config ────────────────
;;
;; `langgraph.json` `checkpointer.type=postgres` invokes the stock saver.
;; To use this RW-compat subclass, the LangGraph Server entry script must
;; import `build-checkpointer` and inject it explicitly (a bootstrap lives
;; in `lg_animeka/_runtime.py` in the Python tree).
