"""animeka.etzhayyim.com LangGraph Server actor.

P3 of the OSS LangGraph migration (after lg-shinshi reached production
2026-05-08). Mirrors the same OSS FastAPI wrapper pattern: no
LangSmith license required, in-server cron, RW-compat checkpointer,
fire-and-forget BPMN audit shim.

Replaces (when fully ported):
  - mitama-animeka-pool (animeka-zeebe-worker, 3 replicas)
  - 20+ animeka.* BPMN process_defs
  - All animeka.* task handlers in kotodama.zeebe_worker_main

Keeps:
  - CF Worker (animeka.etzhayyim.com) as XRPC entry — proxies to this server
  - RunPod ComfyUI (vyp99t9px7h4dl:8188) for image gen
  - RunPod vLLM (vyp99t9px7h4dl:4000) for script/storyboard generation
  - PDS (atproto.etzhayyim.com) for `app.bsky.*` social + `chat.bsky.convo.*` DM
  - Hyperdrive RW for `com.etzhayyim.animeka.*` domain rows
  - bpmn-dispatcher receives fire-and-forget OCEL audit only

Per the design doc in /lg/CLAUDE.md, animeka has 16 actor sub-DIDs
(director, screenwriter, storyboarder, layout, keyAnimator, etc.) —
the per-actor workflow lives in graphs/ and dispatches to the
appropriate vLLM tier + ComfyUI based on the production stage.
"""

__version__ = "0.1.0"
