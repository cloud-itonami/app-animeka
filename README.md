# app-animeka

Team-based anime production actor — 27 LangGraph StateGraphs covering the
12-stage pipeline (原作 → 脚本 → 絵コンテ → レイアウト → 原画 → 動画 → 色指定 →
仕上げ → 背景 → 撮影 → 編集 → 音響), with the *cut* (shot) as the atom rather
than the page/panel of its manga sibling.

Machine-readable identity is `README.edn`; this file is the operator's map.
**`CLAUDE.md` describes the target design, not the current state** — it names a
single TS-native Cloudflare Worker on `animeka.etzhayyim.com` as the runtime.
That is not what runs in this repo today. What runs is below.

## What actually runs

The repo carries four trees. One of them works here.

| Tree | What it is | State in this repo |
|---|---|---|
| **`lg-clj/`** | clj/cljc port of the graph server (ADR-2606280030) | **Complete and green.** 27 graphs, dispatch surface, 47 tests / 193 assertions |
| `lg/` | Python LangGraph + FastAPI server | **Stub.** `langgraph.json` declares 27 graphs; 4 have modules. `lg_animeka/server.py` — the uvicorn target in `Dockerfile` — is not here |
| `kotoba/` | TypeScript publication catalog (works + episodes on AT PDS) | Source is present; the suite did not run in this pass (see below) |
| `appview/` | Cloudflare Worker + SvelteKit facade | **Not buildable from this repo.** All 8 `wrangler.jsonc` aliases are absolute paths outside it |

Start here: [`docs/operator-quickstart.md`](docs/operator-quickstart.md).

```bash
bb lg-clj/run_tests.clj              # 47 tests, 193 assertions, 0 failures
bb lg-clj/run_tests.clj --server 2027
curl -s localhost:2027/ok            # {"ok":true,"graphs":[...27...],"version":"0.1.0"}
```

### Why `lg/` is a stub and not the runtime

`server.cljc` still describes itself as a port of a Python server that "remains
the deployed runtime and COEXISTS". That was true in the monorepo this repo was
split out of (`etzhayyim/root/60-apps/etzhayyim-project-animeka`, see
`migration.edn`); it is not true here. Three things are missing, each of them
load-bearing:

- **23 of the 27 declared graph modules.** `lg/langgraph.json` maps every graph
  to `./lg_animeka/graphs/<name>.py`; only `assemble_episode`, `autopilot`,
  `generate_audio` and `publish_episode` exist. (Two modules that *do* exist,
  `compositor` and `kaizen_compositor`, are not declared.)
- **`lg_animeka/server.py`**, which `lg/Dockerfile` starts with
  `uvicorn lg_animeka.server:app`.
- **The `kotodama` dependency.** `langgraph.json` points at
  `../../../40-engine/kotoba/crates/kotoba-kotodama/py`, which resolves outside
  this repo.

`lg/tests/test_murakumo_alias_defaults.py` covers one property of one module
(the inference endpoint defaults to the `murakumo-main` alias, ADR-2607173100).
It is not a suite for the tree.

These counts are asserted, not just claimed — see
`lg-clj/test/lg_animeka/smoke_test.cljc`, "cross-tree claims". Those assertions
go red if the gap closes as well as if it widens, because either way this page
is then wrong.

### `kotoba/` was not verified in this pass

`npm install` fails while preparing the two git-URL dependencies
(`@etzhayyim/sdk`, `@etzhayyim/sdk-mock`) on npm 11.16.0 / Node v26.3.0:

```
npm error code EALLOWSCRIPTS
npm error --allow-scripts is not allowed in project-scoped installs.
```

Both git remotes resolve, so this is the local npm's policy for git deps that
run a prepare script, not a missing dependency. `npm test` (`vitest run`) was
therefore never reached. Treat the tree as unverified rather than broken.

## Layout

```
README.edn                  machine-readable identity (etzhayyim.repository/readme-v1)
migration.edn               where this repo was split from, and at which revision
CLAUDE.md                   target design — read as intent, not as description
MIGRATION-TODO.md           substrate-boundary checklist inherited at the split; open
lg-clj/                     the working tree — see docs/operator-quickstart.md
lg/                         Python graph server (stub)
kotoba/                     TS publication catalog
appview/                    Cloudflare Worker + SvelteKit facade (unbuildable here)
```

## Notes

`lg-clj/` is driven by Babashka. ADR-2607173000 retires `bb` as this
workspace's script host in favour of `nbb`, so `lg-clj/bb.edn` is inherited
rather than exemplary — do not copy the pattern into new work. It is documented
here because it is what runs today.
