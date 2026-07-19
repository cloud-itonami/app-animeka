(ns lg-animeka.store
  "Injectable persistence seam — clj port of the RisingWave/psycopg DB edge that
  every animeka graph node uses (ADR-2606280030).

  DEVIATION (noted, per CLAUDE.md substrate boundary + ADR-2605262130): the
  Python nodes open psycopg/asyncpg connections to RisingWave (`RW_URL`) and run
  raw SQL against `vertex_animeka` / `vertex_repo_record`. RisingWave is
  deprecated and the substrate boundary forbids it; the repo's canonical state
  is the kotoba Datom log. This port therefore keeps the DB strictly behind an
  injectable seam:

    *query*  (sql params) → seq of row-vectors   (SELECT)
    *exec*   (sql params) → nil                   (INSERT / UPDATE / DELETE)

  `configured?` mirrors the `if not _RW_URL: return {error 'RW_URL not set'}`
  guard at the top of each node. The default seams are NOT configured (they
  throw), so offline the graphs reproduce the exact `RW_URL not set` early
  returns. A real deployment injects a kotoba-Datom-log-backed `*query*`/`*exec*`
  (or, transitionally, a psycopg shim) without touching any graph topology.
  Tests rebind `*query*`/`*exec*` to in-memory stubs."
  (:require [clojure.string :as str]))

(def ^:dynamic *rw-url* "")

(defn configured?
  "True when a store URL is set (mirrors the `if not _RW_URL` node guard)."
  []
  (not (str/blank? *rw-url*)))

(defn- not-configured [& _]
  (throw (ex-info "animeka store not configured (inject store/*query* / store/*exec*)"
                  {:store :not-configured})))

(def ^:dynamic *query* not-configured)
(def ^:dynamic *exec*  not-configured)

(defn query [sql params] (*query* sql params))
(defn exec! [sql params] (*exec* sql params))
