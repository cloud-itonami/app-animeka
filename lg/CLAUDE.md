# lg-animeka — LangGraph Server actor for animeka.etzhayyim.com

**P3+P4+P5 complete** of the OSS LangGraph migration. Mirrors lg-shinshi
(production live since 2026-05-08). 27 graphs total (publishEpisode added 2026-05-15).

## Why

Same root cause as lg-shinshi: the LangServer-based animeka pool
(`mitama-animeka-pool`, 3 replicas) suffers from the same shared-queue
saturation pattern (registers `generic.{db.insert,db.select,...}` along
with 13 `animeka.*` task types). Per CLAUDE.md "Recent Completion:
animeka.etzhayyim.com worker isolation" the BPMN E2E was always pending.

LangGraph Server gives us:
- Per-graph checkpointing → mid-render recovery
- Threads → idempotent re-invocation
- In-process cron (no LangServer broker dependency)
- $0 license (no `langchain/langgraph-api` paid image)

## Layout

```
lg/
├── langgraph.json                       # graph manifest (26 graphs)
├── pyproject.toml                       # langgraph + kotodama
├── Dockerfile                           # OSS, no licensed base
├── .gitignore
├── lg_animeka/
│   ├── __init__.py
│   ├── state.py                         # WorkState / EpisodeState / CutState / GenerateState / ChatState
│   ├── audit.py                         # fire-and-forget BPMN generic.audit.emit
│   ├── checkpointer.py                  # _RwAsyncPostgresSaver (shared lg-shinshi RW tables)
│   ├── cron.py                          # APScheduler (autopilot cron every 15 min)
│   ├── server.py                        # FastAPI: /runs /xrpc/{nsid} /ok /health
│   └── graphs/
│       ├── health.py                    # ✅ com.etzhayyim.animeka.health     (P3a)
│       ├── list_works.py                # ✅ com.etzhayyim.animeka.listWorks  (P3a)
│       ├── agent_chat.py                # ✅ com.etzhayyim.animeka.chat       (P3a, blocked by vLLM upstream)
│       ├── autopilot.py                 # ✅ com.etzhayyim.animeka.autopilot  (P3d)
│       ├── cut_runner.py                # ✅ com.etzhayyim.animeka.cutRunner  (P3d)
│       ├── auto_trace_cut.py            # ✅ com.etzhayyim.animeka.autoTraceCut (P3d)
│       └── breakdown_scene.py           # ✅ com.etzhayyim.animeka.breakdownScene (P3d)
└── tests/
    └── test_smoke.py                    # ✅ 16 smoke tests (P4)
```

## Phases

| Phase | Scope | Status |
|---|---|---|
| **P3a** scaffold | dirs / langgraph.json / Dockerfile / 3 simplest graphs | ✅ this turn |
| **P3a** local langgraph dev smoke | uv venv + import compile | ✅ — 3 graphs + 10 nodes |
| **P3a** build + push amd64 | `docker buildx … --push` to ghcr | ✅ |
| **P3a** Helm chart + install | mirror lg-shinshi-pool (under `50-infra/vultr/lg-animeka-pool/`) | ✅ |
| **P3a** CF tunnel route for animeka NSIDs | extend cloudflared-bpmn-dispatcher ConfigMap (or new tunnel) | ✅ dispatcher nginx Ingress |
| **P3b** Generation graphs | port generateScript / generateStoryboard / generateLayout / generateKeyframe / generateInbetween / generateBackground / designColorModel | ✅ |
| **P3c** CRUD graphs | port createWork / addEpisode / addCut / getCut / listEpisodes / listRetakes / submitRetake / resolveRetake / updateCutStage | ✅ |
| **P3d** Auto-pilot | port autopilot / cutRunner / autoTraceCut / breakdownScene | ✅ |
| **P4** Audio + Assembly | generateAudio (BGM synthesis + TTS + ffmpeg mix) + assembleEpisode (cut concat → episode MP4) | ✅ |
| **P5** Social Publish | publishEpisode (HMAC → Bun PDS pod internal → app.bsky.feed.post) + daily crons (assemble 3am, publish 3:30am UTC) | ✅ |

## Conventions

- Reuses `kotodama` (editable install) for shared helpers (`_post_scene`,
  `_upload_blob_to_pds`, etc.) — no fork.
- Same RW checkpointer schema (`lg_checkpoints*` tables) as lg-shinshi —
  thread_ids are namespaced (`xrpc:{nsid_tail}:...`).
- Audit shim emits `animeka.*` activities to bpmn-dispatcher (fire-and-
  forget). OCEL trail preserved per ADR-0056.
- `VLLM_URL` defaults to RunPod unified pod `vyp99t9px7h4dl-4000`. Per
  ADR-2605010000 there is no Murakumo fallback.
- `ANIMEKA_APP_DID` env defaults to `did:web:animeka.etzhayyim.com`.

## NSID coverage map (27 of 27)

| NSID | assistant_id | graph file | status |
|---|---|---|---|
| `com.etzhayyim.animeka.health` | `health` | health.py | ✅ |
| `com.etzhayyim.animeka.listWorks` | `list_works` | list_works.py | ✅ |
| `com.etzhayyim.animeka.chat` | `agent_chat` | agent_chat.py | ✅ (vLLM upstream) |
| `com.etzhayyim.animeka.generateScript` | `generate_script` | generate_script.py | ✅ P3b |
| `com.etzhayyim.animeka.generateStoryboard` | `generate_storyboard` | generate_storyboard.py | ✅ P3b |
| `com.etzhayyim.animeka.generateLayout` | `generate_layout` | generate_layout.py | ✅ P3b |
| `com.etzhayyim.animeka.generateKeyframe` | `generate_keyframe` | generate_keyframe.py | ✅ P3b |
| `com.etzhayyim.animeka.generateInbetween` | `generate_inbetween` | generate_inbetween.py | ✅ P3b |
| `com.etzhayyim.animeka.generateBackground` | `generate_background` | generate_background.py | ✅ P3b |
| `com.etzhayyim.animeka.designColorModel` | `design_color_model` | design_color_model.py | ✅ P3b |
| `com.etzhayyim.animeka.createWork` | `create_work` | create_work.py | ✅ P3c |
| `com.etzhayyim.animeka.addEpisode` | `add_episode` | add_episode.py | ✅ P3c |
| `com.etzhayyim.animeka.addCut` | `add_cut` | add_cut.py | ✅ P3c |
| `com.etzhayyim.animeka.getCut` | `get_cut` | get_cut.py | ✅ P3c |
| `com.etzhayyim.animeka.listEpisodes` | `list_episodes` | list_episodes.py | ✅ P3c |
| `com.etzhayyim.animeka.listRetakes` | `list_retakes` | list_retakes.py | ✅ P3c |
| `com.etzhayyim.animeka.submitRetake` | `submit_retake` | submit_retake.py | ✅ P3c |
| `com.etzhayyim.animeka.resolveRetake` | `resolve_retake` | resolve_retake.py | ✅ P3c |
| `com.etzhayyim.animeka.updateCutStage` | `update_cut_stage` | update_cut_stage.py | ✅ P3c |
| `com.etzhayyim.animeka.autopilot` | `autopilot` | autopilot.py | ✅ P3d |
| `com.etzhayyim.animeka.cutRunner` | `cut_runner` | cut_runner.py | ✅ P3d |
| `com.etzhayyim.animeka.autoTraceCut` | `auto_trace_cut` | auto_trace_cut.py | ✅ P3d |
| `com.etzhayyim.animeka.breakdownScene` | `breakdown_scene` | breakdown_scene.py | ✅ P3d |
| `com.etzhayyim.animeka.generateAudio` | `generate_audio` | generate_audio.py | ✅ P4 |
| `com.etzhayyim.animeka.assembleEpisode` | `assemble_episode` | assemble_episode.py | ✅ P4 |
| `com.etzhayyim.animeka.publishEpisode` | `publish_episode` | publish_episode.py | ✅ P5 |
