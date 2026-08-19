# Operator quickstart

Every command here was run end to end on 2026-08-19 against
`fa78cae` (macOS 15 / arm64, Babashka v1.12.218). Where something does not
work, that is recorded too, with the error — a step you cannot walk is worse
than no step.

Only `lg-clj/` is exercised. The other three trees and why they are not here
are in [`../README.md`](../README.md).

## 1. Prerequisites

```bash
bb --version    # v1.12.218 here; any 1.12.x should do
```

Nothing else. The suite stubs the DB, LLM and render seams, so there is no
Postgres, no GPU and no network call in it. First run resolves two git deps
(`langchain-clj`, `langgraph-clj`, pinned in `lg-clj/bb.edn`) and takes about a
minute; later runs are seconds.

## 2. Run the suite

From the repo root:

```bash
bb lg-clj/run_tests.clj
```

```
Testing lg-animeka.smoke-test
lg-animeka clj server up on :0 — graphs=27

Ran 47 tests containing 193 assertions.
0 failures, 0 errors.
```

`cd lg-clj && bb test` is equivalent — the same file behind the `bb.edn` task.
Both work; the tests locate the repo root themselves rather than assuming a
working directory.

Exit code is 0 on green and 1 on red (`run_tests.clj` calls `System/exit`), so
it is usable as a gate.

## 3. Start the server

```bash
bb lg-clj/run_tests.clj --server 2027
```

It prints `lg-animeka clj server up on :2027 — graphs=27` and serves on
http-kit. The port argument is optional and defaults to 2027.

```bash
curl -s localhost:2027/ok
# {"ok":true,"graphs":["assemble_episode",...,"submit_retake"],"version":"0.1.0"}

curl -s localhost:2027/health
# {"ok":true,"checkpointer":false}
```

`checkpointer: false` is correct for a local run: no store is configured. The
routes are `POST /runs`, `POST /runs/stream` (SSE), `POST /xrpc/{nsid}`,
`GET /threads/{tid}/state`, and `GET /ok` | `/health`.

## 4. Invoke a graph

```bash
curl -s -X POST localhost:2027/runs \
  -H 'Content-Type: application/json' \
  -d '{"assistant_id":"health","input":{}}'
```

```json
{"ok":true,"result":{"rw_ok":false,"error":"RW_URL not set","ok":false,
                     "server_now":"2026-08-19T05:42:12.748817Z"}}
```

**Read those two `ok`s separately.** The outer one is dispatch: the graph was
found and ran. The inner one is the graph's own verdict, and it is `false`
because `RW_URL` is unset — the health graph is reporting an unconfigured
store, which is the truthful answer for a bare checkout. A 200 here does not
mean the pipeline is wired.

`assistant_id` is any of the 27 names in `/ok`. Unknown names return 404, as
does an unknown NSID on `/xrpc/`.

## 5. Configuration

All optional; all read from the environment at startup by
`lg-clj/run_tests.clj`, which is the host adapter (it binds the seams and then
starts the server).

| Variable | Effect when unset |
|---|---|
| `RW_URL` / `LG_CHECKPOINTER_URL` | no store; graphs that read one report `rw_ok: false` |
| `VLLM_URL` / `VLLM_MODEL` | `http://127.0.0.1:4000/v1` and `tier0-general` (`lg_animeka.llm/default-config`) |
| `LG_API_KEY` | `/runs` and `/xrpc/` are unauthenticated |
| `BPMN_DISPATCHER_INTERNAL_URL` / `_SECRET` | audit events are attempted and swallowed; set `LG_AUDIT_DISABLED=1` to skip them |
| `ANIMEKA_APP_DID` / `ANIMEKA_REPO_DID` | the defaults in `lg_animeka.util` |

`VLLM_URL` is not free-form: `lg_animeka.llm/assert-murakumo` throws unless the
endpoint is `http` on one of six loopback/fleet host:port pairs (ADR-2605215000),
so an `https://` URL is refused before any request goes out. Note that the
`murakumo-main` alias of ADR-2607173100 lives in the *Python* tree's
`autopilot`, not here — this tree's baked default is the tier name above.

## 6. What this does not cover

- **Deployment.** Nothing here deploys. The `appview/` Worker config aliases
  eight absolute paths outside this repo, so `wrangler` cannot resolve them
  from a clone.
- **The generation pipeline.** ComfyUI, USD scene building and the GPU render
  path are stubbed in the suite (`render/*render-png*` and friends are bound to
  fixtures). Green here says the graph logic holds, not that a frame renders.
- **The Python tree.** See `../README.md`; 23 of its 27 declared graph modules
  and its server module are not in this repo.
