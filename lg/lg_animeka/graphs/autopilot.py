"""animeka `autopilot` graph — fully autonomous cut generation (R/PT15M cron).

NSID: com.etzhayyim.animeka.autopilot

Ports kotodama.langgraph_graphs.animeka_autopilot to proper async
LangGraph nodes. Each cron fire:
  1. LLM generates a fresh scene description
  2. LLM → visual prompt → ComfyUI 512×512 storyboard sketch
  3. LLM → layout plan → ComfyUI 1024×1024 layout drawing
  4. ComfyUI 1024×1024 keyframe
  5. LLM → bg prompt → ComfyUI 1344×768 background painting
  6. Social post (PDS dispatch) with all blobs embedded
  7. Emit OCEL audit

Conditional retry: if storyboard CID is empty, regenerate once before
continuing (preserves the existing BPMN retry gate).
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Literal, TypedDict

import httpx
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from lg_animeka.audit import emit_audit_bg

_log = logging.getLogger(__name__)

_RW_URL = os.environ.get("RW_URL") or os.environ.get("LG_CHECKPOINTER_URL", "")
# Inference edge — murakumo fleet (ADR-2607173100).
#
# Resolution order, per the ADR:
#   1. env override — VLLM_URL / VLLM_MODEL still win, unchanged.
#   2. alias resolution — handled *server-side*. `api.murakumo.cloud` resolves
#      the `murakumo-main` KV alias entry itself, so we send the alias name as
#      the model and never learn (or pin) the concrete id behind it. No startup
#      GET of /infer/models/murakumo-main is needed: it would add a failure
#      mode without changing the answer.
#   3. fallback bakes the ENDPOINT ONLY. No concrete model id appears below,
#      so a fleet-side model switch is picked up on the next call from this
#      cron fire, with no release here.
#
# The previous default was `https://vyp99t9px7h4dl-4000.proxy.runpod.net/v1`,
# an ephemeral RunPod pod id. RunPod releases those hostnames and can reassign
# them to another tenant, so the default named a host someone else may come to
# own. `_chat` below sends only Content-Type — no credential reaches this
# endpoint — so what was exposed is scene text and prompts, not secrets.
_VLLM_URL = os.environ.get("VLLM_URL", "https://api.murakumo.cloud/v1").rstrip("/")
_VLLM_MODEL = os.environ.get("VLLM_MODEL", "murakumo-main")
_VLLM_TIMEOUT = float(os.environ.get("VLLM_TIMEOUT_SEC", "60"))
_PDS_BASE = os.environ.get("PDS_URL", "https://atproto.etzhayyim.com")
_APP_DID = os.environ.get("ANIMEKA_APP_DID", "did:web:animeka.etzhayyim.com")
_REPO = os.environ.get("ANIMEKA_REPO_DID", "did:web:an1m3k4x.etzhayyim.com")
_CKPT = "animagine-xl-4.0.safetensors"
_CHAR = "high-school girl, navy blazer, dark long hair, introspective expression"


class _State(TypedDict, total=False):
    cut_id: str
    scene_text: str
    visual_prompt: str
    sb_cid: str
    ly_cid: str
    kf_cid: str
    bg_cid: str
    bg_mood: str
    output_cid: str
    post_status: Literal["posted", "skipped", "error"]
    ok: bool
    error: str | None


# ── shared render helper ────────────────────────────────────────────────────

def _build_quality_workflow(
    prompt: str, negative: str, ckpt: str, w: int, h: int,
    steps: int, cfg: float, sampler: str, scheduler: str,
) -> dict:
    """animagine-xl-4.0 / Illustrious workflow with CLIP skip=2 and tunable cfg."""
    import time as _time
    seed = int(_time.time() * 1000) & 0xFFFFFFFF
    return {
        # CLIPSetLastLayer → CLIP skip 2 (required for animagine-xl-4.0)
        "1": {"class_type": "CLIPSetLastLayer", "inputs": {"clip": ["4", 1], "stop_at_clip_layer": -2}},
        "3": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": steps, "cfg": cfg,
            "sampler_name": sampler, "scheduler": scheduler, "denoise": 1.0,
            "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
            "latent_image": ["5", 0],
        }},
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 0]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["1", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "animeka"}},
    }


_NEG_CHAR = (
    "lowres, worst quality, low quality, bad anatomy, bad hands, missing fingers, "
    "extra digit, fewer digits, cropped, text, signature, watermark, username, blurry, "
    "jpeg artifacts, ugly, duplicate, mutated, deformed, monochrome, nsfw"
)
_NEG_BG = (
    "lowres, worst quality, low quality, blurry, jpeg artifacts, watermark, signature, "
    "people, characters, person, human, nsfw"
)


async def _render(
    prompt: str, w: int, h: int, steps: int,
    cfg: float = 7.0, sampler: str = "dpmpp_2m", scheduler: str = "karras",
    negative: str = _NEG_CHAR,
) -> tuple[str, str]:
    """ComfyUI render → PDS blob upload. Returns (cid, error)."""
    try:
        from kotodama.primitives.shinshi_image import (
            _comfy_render_png, _upload_blob_to_pds,
        )
        wf = _build_quality_workflow(prompt, negative, _CKPT, w, h, steps, cfg, sampler, scheduler)
        png, err = await _comfy_render_png(wf)
        if not png:
            return "", f"render:{err}"
        cid = await _upload_blob_to_pds(png, _REPO)
        return (cid or "", "") if cid else ("", "blob-upload-failed")
    except Exception as exc:
        return "", f"{type(exc).__name__}:{exc!s}"[:150]


# ── vLLM helper ─────────────────────────────────────────────────────────────

async def _chat(system: str, user: str, max_tokens: int = 300, temp: float = 0.7) -> str:
    try:
        async with httpx.AsyncClient(timeout=_VLLM_TIMEOUT) as c:
            r = await c.post(
                f"{_VLLM_URL}/chat/completions",
                json={"model": _VLLM_MODEL,
                      "messages": [{"role": "system", "content": system},
                                   {"role": "user", "content": user}],
                      "max_tokens": max_tokens, "temperature": temp},
                headers={"Content-Type": "application/json"},
            )
        if r.status_code >= 400:
            return ""
        return (((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    except Exception:
        return ""


# ── nodes ───────────────────────────────────────────────────────────────────

async def _node_scene_text(state: _State) -> dict[str, Any]:
    cut_id = f"auto-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    text = await _chat(
        "You are an anime scene writer. Write SHORT (1-3 sentence) evocative scene "
        "descriptions for an anime short. Vary mood: calm mornings, wistful afternoons, "
        "introspective evenings. Output only the scene description, no preamble.",
        "Generate a fresh scene now.",
        max_tokens=300, temp=0.85,
    )
    if not text:
        text = "Misaki stands quietly by the window, watching the world outside."
    return {"cut_id": cut_id, "scene_text": text}


async def _node_storyboard(state: _State) -> dict[str, Any]:
    if state.get("error"):
        return {}
    vp = await _chat(
        "You are a storyboard artist. Given a scene, output ONE concise visual prompt "
        "(max 60 words) for a monochrome storyboard sketch. Camera angle, character "
        "pose. No dialogue, no preamble.",
        f"Scene: {state.get('scene_text', '')}\nCharacters: {_CHAR}",
        max_tokens=150, temp=0.7,
    )
    prompt = (vp or state.get("scene_text", "anime scene")) + \
             ", storyboard sketch, monochrome pencil lineart, loose confident strokes, story panel"
    cid, err = await _render(prompt, 512, 512, 22, cfg=5.0, sampler="euler_ancestral", scheduler="normal")
    return {"visual_prompt": vp or prompt, "sb_cid": cid,
            **({"error": f"storyboard:{err}"} if err and not cid else {})}


async def _node_storyboard_retry(state: _State) -> dict[str, Any]:
    """Second attempt with variant=2 prompt wording."""
    vp = await _chat(
        "You are a storyboard artist. Output ONE concise visual prompt (max 60 words) "
        "for a monochrome storyboard sketch. Different angle from before.",
        f"Scene: {state.get('scene_text', '')}\nCharacters: {_CHAR}\nVariant: 2",
        max_tokens=150, temp=0.75,
    )
    prompt = (vp or state.get("scene_text", "anime scene")) + \
             ", storyboard sketch, monochrome pencil lineart, loose confident strokes"
    cid, err = await _render(prompt, 512, 512, 22, cfg=5.0, sampler="euler_ancestral", scheduler="normal")
    return {"sb_cid": cid, **({"error": f"sb_retry:{err}"} if err and not cid else {})}


async def _node_layout(state: _State) -> dict[str, Any]:
    if state.get("error"):
        return {}
    import json as _json
    plan_str = await _chat(
        'Output ONE JSON: {"prompt":"...","bgMood":"..."}. Layout plan for anime cut.',
        f"Storyboard: {state.get('visual_prompt','')}\nChars: {_CHAR}",
        max_tokens=300, temp=0.3,
    )
    layout_prompt = state.get("visual_prompt", "anime layout")
    bg_mood = "soft warm light"
    try:
        plan = _json.loads(plan_str)
        layout_prompt = plan.get("prompt", layout_prompt)
        bg_mood = plan.get("bgMood", bg_mood)
    except Exception:
        pass
    full = layout_prompt + ", anime layout paper, production key drawing, clean linework, flat colour"
    cid, err = await _render(full, 1024, 1024, 28, cfg=5.0, sampler="euler_ancestral", scheduler="normal")
    return {"ly_cid": cid, "bg_mood": bg_mood,
            **({"error": f"layout:{err}"} if err and not cid else {})}


async def _node_keyframe(state: _State) -> dict[str, Any]:
    if state.get("error"):
        return {}
    base = state.get("visual_prompt") or state.get("scene_text") or "anime character scene"
    prompt = (
        f"{base}, {_CHAR}, "
        "anime production cel art, full color illustration, vibrant cel shading, "
        "detailed shading and highlights, character on-model, expressive face, "
        "detailed eyes with catchlights, perfect anatomy, sharp focus, "
        "masterpiece, best quality, very aesthetic, absurdres, highres, newest, "
        "1girl, solo, looking at viewer"
    )
    cid, err = await _render(prompt, 1024, 1024, 35)
    return {"kf_cid": cid, **({"error": f"keyframe:{err}"} if err and not cid else {})}


async def _node_background(state: _State) -> dict[str, Any]:
    if state.get("error"):
        return {}
    bg_mood = state.get("bg_mood") or "soft warm light"
    desc = await _chat(
        "You are an anime background artist. Output a SINGLE environment description "
        "(max 50 words) for a widescreen background painting. NO characters.",
        f"Scene: {state.get('scene_text','')}\nMood: {bg_mood}",
        max_tokens=150, temp=0.6,
    ) or f"anime background, {bg_mood}, early spring"
    full = desc + ", anime background painting, painterly, no characters, widescreen cinematic"
    cid, err = await _render(full, 1344, 768, 28, cfg=7.0, negative=_NEG_BG)
    return {"bg_cid": cid, **({"error": f"background:{err}"} if err and not cid else {})}


async def _node_composite(state: _State) -> dict[str, Any]:
    if state.get("error") or not state.get("kf_cid") or not state.get("bg_cid"):
        return {}
    try:
        from lg_animeka.graphs.compositor import COMPOSITOR_GRAPH
        result = await COMPOSITOR_GRAPH.ainvoke(
            {
                "cut_rkey": state.get("cut_id"),
                "kf_cid": state.get("kf_cid"),
                "bg_cid": state.get("bg_cid"),
                "fps": 12,
                "duration_sec": 4,
            },
            config={"configurable": {"thread_id": f"composite-{state.get('cut_id')}"}},
        )
        return {"output_cid": result.get("output_cid") or ""}
    except Exception as exc:
        _log.warning("composite: %s", exc)
        return {}


async def _node_generate_audio(state: _State) -> dict[str, Any]:
    """Replace compositor's sine-wave BGM with mood-matched BGM + scene narration TTS."""
    if not state.get("output_cid") or not state.get("cut_id"):
        return {}
    try:
        from lg_animeka.graphs.generate_audio import GRAPH as AUDIO_GRAPH
        result = await AUDIO_GRAPH.ainvoke(
            {"rkeys": [state.get("cut_id")], "max_cuts": 1},
            config={"configurable": {"thread_id": f"audio-{state.get('cut_id')}"}},
        )
        processed = (result.get("processed") or [])
        if processed and processed[0].get("new_output_cid"):
            return {"output_cid": processed[0]["new_output_cid"]}
    except Exception as exc:
        _log.warning("generate_audio: %s", exc)
    return {}


async def _node_insert_cut(state: _State) -> dict[str, Any]:
    """Persist the generated cut record to vertex_animeka."""
    if not _RW_URL:
        return {}
    cut_id = state.get("cut_id") or f"auto-{secrets.token_hex(4)}"
    rkey = cut_id
    vertex_id = f"at://{_REPO}/com.etzhayyim.animeka.cut/{rkey}"
    try:
        import psycopg
        conn = await psycopg.AsyncConnection.connect(_RW_URL, autocommit=True)
        try:
            await conn.execute(
                "DELETE FROM vertex_animeka WHERE vertex_id = %s",
                [vertex_id],
            )
            await conn.execute(
                """INSERT INTO vertex_animeka
                   (vertex_id, repo, rkey, collection, kind, owner_did,
                    camera_note, thumb_cid, flat_cid, image_cid, bg_cid,
                    output_cid, status, created_at)
                   VALUES (%s,%s,%s,'com.etzhayyim.animeka.cut','cut',%s,
                           %s,%s,%s,%s,%s,%s,'autopilot',%s)""",
                [vertex_id, _REPO, rkey, _APP_DID,
                 state.get("scene_text"), state.get("sb_cid"),
                 state.get("ly_cid"), state.get("kf_cid"), state.get("bg_cid"),
                 state.get("output_cid") or None,
                 datetime.now(tz=timezone.utc).isoformat()],
            )
        finally:
            await conn.close()
    except Exception as exc:
        _log.warning("insert_cut: %s", exc)
    return {}


async def _node_post(state: _State) -> dict[str, Any]:
    cut_id = state.get("cut_id") or ""
    scene_text = state.get("scene_text") or ""
    images = [c for c in [state.get("bg_cid"), state.get("ly_cid"),
                           state.get("kf_cid"), state.get("sb_cid")] if c]
    if not images:
        return {"post_status": "skipped", "ok": True}
    embed = {
        "$type": "app.bsky.embed.images",
        "images": [
            {"image": {"$type": "blob", "ref": {"$link": cid},
                       "mimeType": "image/png", "size": 0},
             "alt": f"animeka frame {i+1}"}
            for i, cid in enumerate(images[:4])
        ],
    }
    record = {
        "$type": "app.bsky.feed.post",
        "text": f"✦ animeka autopilot — cut {cut_id}\n{scene_text[:200]}",
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "embed": embed,
    }
    try:
        from kotodama.zeebe_worker_main import task_generic_pds_dispatch
        import asyncio
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: asyncio.run(task_generic_pds_dispatch(
                type="com.atproto.repo.createRecord",
                payload={"repo": _REPO, "collection": "app.bsky.feed.post", "record": record},
            )),
        )
        return {"post_status": "posted", "ok": True}
    except Exception as exc:
        _log.warning("post: %s", exc)
        # Try direct PDS call as fallback
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(
                    f"{_PDS_BASE}/xrpc/com.atproto.repo.createRecord",
                    json={"repo": _REPO, "collection": "app.bsky.feed.post", "record": record},
                    headers={"Content-Type": "application/json",
                             "x-kotodama-verified": "true",
                             "x-etzhayyim-org-id": "anon"},
                )
            if r.status_code < 400:
                return {"post_status": "posted", "ok": True}
        except Exception:
            pass
        return {"post_status": "error", "ok": bool(state.get("sb_cid") or state.get("kf_cid"))}


async def _node_audit(state: _State) -> dict[str, Any]:
    emit_audit_bg(
        actor=_APP_DID,
        activity="animeka.autopilot",
        object_id=f"autopilot:{state.get('cut_id', '')}:{int(time.time())}",
        object_type="animeka.cut",
        attributes={
            "cutId": state.get("cut_id"),
            "sbCid": state.get("sb_cid"),
            "lyCid": state.get("ly_cid"),
            "kfCid": state.get("kf_cid"),
            "bgCid": state.get("bg_cid"),
            "outputCid": state.get("output_cid"),
            "postStatus": state.get("post_status"),
            "ok": state.get("ok", True),
        },
    )
    return {}


def _route_after_storyboard(state: _State) -> str:
    return "storyboard_retry" if not state.get("sb_cid") else "layout"


def _build() -> StateGraph:
    g: StateGraph = StateGraph(_State)
    g.add_node("scene_text",       _node_scene_text)
    g.add_node("storyboard",       _node_storyboard,
               retry_policy=RetryPolicy(max_attempts=2, backoff_factor=2.0))
    g.add_node("storyboard_retry", _node_storyboard_retry,
               retry_policy=RetryPolicy(max_attempts=2, backoff_factor=2.0))
    g.add_node("layout",           _node_layout,
               retry_policy=RetryPolicy(max_attempts=2, backoff_factor=2.0))
    g.add_node("keyframe",         _node_keyframe,
               retry_policy=RetryPolicy(max_attempts=2, backoff_factor=2.0))
    g.add_node("background",       _node_background,
               retry_policy=RetryPolicy(max_attempts=2, backoff_factor=2.0))
    g.add_node("composite",        _node_composite)
    g.add_node("generate_audio",   _node_generate_audio)
    g.add_node("insert_cut",       _node_insert_cut)
    g.add_node("post",             _node_post)
    g.add_node("audit",            _node_audit)

    g.add_edge(START, "scene_text")
    g.add_edge("scene_text", "storyboard")
    g.add_conditional_edges("storyboard", _route_after_storyboard,
                            {"storyboard_retry": "storyboard_retry", "layout": "layout"})
    g.add_edge("storyboard_retry", "layout")
    g.add_edge("layout", "keyframe")
    g.add_edge("keyframe", "background")
    g.add_edge("background", "composite")
    g.add_edge("composite", "generate_audio")
    g.add_edge("generate_audio", "insert_cut")
    g.add_edge("insert_cut", "post")
    g.add_edge("post", "audit")
    g.add_edge("audit", END)
    return g


GRAPH = _build().compile(name="autopilot")
