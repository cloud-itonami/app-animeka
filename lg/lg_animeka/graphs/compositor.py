"""animeka compositor — BG × keyframe → Ken Burns + breathing char → BGM MP4.

Pregel superstep model (LangGraph Pregel engine):

  SS0  load_assets      asyncio.gather([fetch(bg_cid), fetch(kf_cid)])
                        ← true parallel I/O; both vertex programs run in
                          the same superstep, barrier before SS1
  SS1  _ss1_gen_frames  Ken Burns BG + character breathing/sway per frame
                        Reads: bg_bytes, kf_bytes, fps, duration_sec
                        Writes: frames (list[H×W×3])
  SS3  encode_upload    imageio-ffmpeg libx264 silent video → ffmpeg lavfi
                        C-major pentatonic BGM synthesis → mux → PDS uploadBlob
                        → output_cid; concurrent: UPDATE vertex_animeka
  END

Batch variant: wrap in outer Send() loop so N cuts run SS0–SS3 in
parallel (each cut = independent Pregel vertex program).

KAMI Engine counterpart (browser side):
  AnimeCutCompositorAdapter (planned, kami-pipelines) → WebGPU layer stack
    BG → CharLayer → FXLayer → kami-postfx → canvas output (real-time preview)
  Offline Pregel compositor → archived MP4 → <video> Gallery player
"""

from __future__ import annotations

import asyncio
import io
import logging
import math
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from PIL import Image
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

_log = logging.getLogger(__name__)

_PDS_BASE = os.environ.get("ANIMEKA_PDS_BASE", "https://atproto.etzhayyim.com")
_BLOB_DID = "anonymous"  # blobs uploaded via legacy-trust header land under anonymous/
_RW_URL = os.environ.get("RW_URL") or os.environ.get("LG_CHECKPOINTER_URL", "")

_DEFAULT_FPS = 12
_DEFAULT_DURATION_SEC = 4


class CompositorState(TypedDict, total=False):
    # ── inputs ──────────────────────────────────────────────────────
    cut_rkey: str
    bg_cid: str
    kf_cid: str
    fps: int
    duration_sec: int
    # ── kaizen parameters ───────────────────────────────────────────
    gamma: float
    brightness_boost: float
    saturation_boost: float
    contrast_boost: float
    sharpen: bool
    breath_amp: int
    sway_amp: int
    breath_freq: float
    motion_arc: bool
    char_scale: float
    char_y_offset: int
    ken_burns_style: str
    add_rim_light: bool
    # ── superstep intermediates ─────────────────────────────────────
    bg_bytes: bytes | None
    kf_bytes: bytes | None
    frames: list
    # ── output ─────────────────────────────────────────────────────
    output_cid: str
    error: str | None


# ── helpers ─────────────────────────────────────────────────────────────────

async def _fetch_blob(cid: str) -> bytes | None:
    try:
        url = f"{_PDS_BASE}/xrpc/com.atproto.sync.getBlob?did={_BLOB_DID}&cid={cid}"
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(url)
            r.raise_for_status()
            return r.content
    except Exception as exc:
        _log.warning("fetch_blob %s: %s", cid, exc)
        return None


# ── SS0: load assets (parallel I/O superstep) ───────────────────────────────

async def _ss0_load_assets(state: CompositorState) -> dict[str, Any]:
    """Pregel SS0 — two vertex programs run simultaneously, barrier here."""
    bg_cid = state.get("bg_cid") or ""
    kf_cid = state.get("kf_cid") or ""

    bg_bytes, kf_bytes = await asyncio.gather(
        _fetch_blob(bg_cid) if bg_cid else asyncio.sleep(0, result=None),
        _fetch_blob(kf_cid) if kf_cid else asyncio.sleep(0, result=None),
    )
    _log.info("SS0 loaded bg=%s kf=%s", bool(bg_bytes), bool(kf_bytes))
    return {"bg_bytes": bg_bytes, "kf_bytes": kf_bytes}


# ── SS1: per-frame composite with Ken Burns BG + character breathing ─────────

def _ss1_gen_frames(state: CompositorState) -> dict[str, Any]:
    """Pregel SS1 — Ken Burns BG + character breathing/sway composite per frame.

    Reads:  bg_bytes, kf_bytes, fps, duration_sec, kaizen params
    Writes: frames (list of H×W×3 lists, JSON-serialisable for checkpointer)
    """
    from PIL import ImageEnhance, ImageFilter

    bg_bytes = state.get("bg_bytes")
    kf_bytes = state.get("kf_bytes")

    if not bg_bytes and not kf_bytes:
        return {"error": "no_assets"}

    fps = int(state.get("fps") or _DEFAULT_FPS)
    dur = int(state.get("duration_sec") or _DEFAULT_DURATION_SEC)
    n = fps * dur

    # ── Kaizen parameters (defaults = original behaviour) ────────────────────
    gamma          = float(state.get("gamma") or 1.0)
    brightness_mul = float(state.get("brightness_boost") or 1.0)
    saturation_mul = float(state.get("saturation_boost") or 1.0)
    contrast_mul   = float(state.get("contrast_boost") or 1.0)
    do_sharpen     = bool(state.get("sharpen") or False)
    breath_amp     = int(state.get("breath_amp") or 3)
    sway_amp       = int(state.get("sway_amp") or 2)
    breath_freq    = float(state.get("breath_freq") or 2.5)
    do_arc         = bool(state.get("motion_arc") or False)
    char_scale_pct = float(state.get("char_scale") or 0.85)
    char_y_off     = int(state.get("char_y_offset") or 0)
    kb_style       = str(state.get("ken_burns_style") or "default")
    add_rim        = bool(state.get("add_rim_light") or False)

    # ── Load background ──────────────────────────────────────────────────────
    bg = (Image.open(io.BytesIO(bg_bytes)).convert("RGBA")
          if bg_bytes else Image.new("RGBA", (1344, 768), (20, 22, 30, 255)))

    # Apply kaizen colour corrections to background
    if gamma != 1.0 or brightness_mul != 1.0 or saturation_mul != 1.0 or contrast_mul != 1.0:
        bg_rgb = bg.convert("RGB")
        if gamma != 1.0:
            import numpy as _np
            arr = _np.array(bg_rgb, dtype=_np.float32) / 255.0
            arr = _np.power(arr, 1.0 / gamma)
            bg_rgb = Image.fromarray((_np.clip(arr, 0, 1) * 255).astype(_np.uint8))
        if brightness_mul != 1.0:
            bg_rgb = ImageEnhance.Brightness(bg_rgb).enhance(brightness_mul)
        if saturation_mul != 1.0:
            bg_rgb = ImageEnhance.Color(bg_rgb).enhance(saturation_mul)
        if contrast_mul != 1.0:
            bg_rgb = ImageEnhance.Contrast(bg_rgb).enhance(contrast_mul)
        if do_sharpen:
            bg_rgb = bg_rgb.filter(ImageFilter.SHARPEN)
        bg = bg_rgb.convert("RGBA")

    cw, ch = bg.size

    # ── Rim-light overlay (warm gradient on lower-left) ──────────────────────
    if add_rim:
        rim = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        import numpy as _np
        arr = _np.zeros((ch, cw, 4), dtype=_np.uint8)
        for y in range(ch):
            for x in range(cw // 2):  # left half gradient
                alpha = int(40 * (1 - x / (cw // 2)) * (y / ch))
                arr[y, x] = [255, 200, 150, alpha]  # warm amber
        rim = Image.fromarray(arr, "RGBA")
        bg = Image.alpha_composite(bg, rim)

    # ── Load + scale character ────────────────────────────────────────────────
    char: Image.Image | None = None
    base_x = 0
    base_y = 0

    if kf_bytes:
        char = Image.open(io.BytesIO(kf_bytes)).convert("RGBA")
        scale = min(cw / char.width, ch / char.height) * char_scale_pct
        new_w = int(char.width * scale)
        new_h = int(char.height * scale)
        char = char.resize((new_w, new_h), Image.LANCZOS)
        base_x = (cw - new_w) // 2
        base_y = ch - new_h + char_y_off

    # ── Generate frames ──────────────────────────────────────────────────────
    out: list = []
    for i in range(n):
        t = i / max(n - 1, 1)  # 0.0 → 1.0

        # Ken Burns style
        if kb_style == "zoom_in_fast":
            zoom = 1.0 + 0.18 * t
            drift_y = int(ch * 0.03 * t)
            x_drift = 0
        elif kb_style == "diagonal_pan":
            zoom = 1.0 + 0.08 * t
            drift_y = int(ch * 0.04 * t)
            x_drift = int(cw * 0.03 * t)
        else:
            zoom = 1.0 + 0.10 * t
            drift_y = int(ch * 0.02 * t)
            x_drift = 0

        nw = int(cw * zoom)
        nh = int(ch * zoom)
        zoomed_bg = bg.resize((nw, nh), Image.BILINEAR)
        x0 = max(0, (nw - cw) // 2 - x_drift)
        y0 = max(0, (nh - ch) // 2 - drift_y)
        bg_frame = zoomed_bg.crop((x0, y0, x0 + cw, y0 + ch)).convert("RGBA")

        # Character with breathing + sway + optional arc
        if char is not None:
            breath_y = int(breath_amp * math.sin(2 * math.pi * t * breath_freq))
            sway_x   = int(sway_amp  * math.sin(2 * math.pi * t * 1.2 + 0.7))
            arc_y    = int(-8 * math.sin(math.pi * t)) if do_arc else 0
            frame = bg_frame.copy()
            frame.paste(char, (base_x + sway_x, base_y + breath_y + arc_y), char)
        else:
            frame = bg_frame

        out.append(np.array(frame.convert("RGB"), dtype=np.uint8))

    _log.info("SS1 generated %d frames (%dx%d @%dfps)", n, cw, ch, fps)
    # Store as compact bytes to avoid Python-list explosion in LangGraph state
    import io as _io
    buf = _io.BytesIO()
    np.save(buf, np.stack(out))
    return {"frames": [buf.getvalue().hex()]}


# ── SS3: encode → BGM synthesis → mux → upload → persist ────────────────────

async def _ss3_encode_upload(state: CompositorState) -> dict[str, Any]:
    """Pregel SS3 — libx264 encode, lavfi BGM synthesis, mux, PDS uploadBlob, RW UPDATE."""
    frame_lists = state.get("frames") or []
    if not frame_lists or state.get("error"):
        return {}

    fps = int(state.get("fps") or _DEFAULT_FPS)
    dur = int(state.get("duration_sec") or _DEFAULT_DURATION_SEC)
    cut_rkey = state.get("cut_rkey") or ""

    # Decode from compact bytes format (saved by gen_frames to avoid memory explosion)
    if len(frame_lists) == 1 and isinstance(frame_lists[0], str) and len(frame_lists[0]) > 100:
        import io as _io
        frames_np = list(np.load(_io.BytesIO(bytes.fromhex(frame_lists[0]))))
    else:
        frames_np = [np.array(f, dtype=np.uint8) for f in frame_lists]

    # Auto-install imageio / imageio-ffmpeg if absent from base image
    try:
        import imageio  # noqa: F401
    except ImportError:
        import subprocess as _sp
        _sp.check_call(["pip", "install", "-q", "imageio", "imageio-ffmpeg"])

    from imageio_ffmpeg import get_ffmpeg_exe
    ffmpeg = get_ffmpeg_exe()

    tmpdir = Path(tempfile.mkdtemp())
    video_path = tmpdir / "silent.mp4"
    bgm_path   = tmpdir / "bgm.wav"
    final_path = tmpdir / "output.mp4"

    # ── Encode silent video ──────────────────────────────────────────────────
    try:
        import imageio as iio
        writer = iio.get_writer(
            str(video_path), fps=fps, codec="libx264", quality=7,
            pixelformat="yuv420p",
            ffmpeg_params=["-movflags", "+faststart"],
        )
        for frame in frames_np:
            writer.append_data(frame)
        writer.close()
    except Exception as exc:
        _log.error("encode: %s", exc)
        return {"error": str(exc)}

    _log.info("SS3 encoded silent video: %d bytes", video_path.stat().st_size)

    # ── Synthesise C-major pentatonic BGM via ffmpeg lavfi ───────────────────
    bgm_expr = (
        "0.10*sin(2*PI*261.63*t)"   # C4
        "+0.07*sin(2*PI*329.63*t)"  # E4
        "+0.05*sin(2*PI*392.00*t)"  # G4
        "+0.03*sin(2*PI*523.25*t)"  # C5
        "+0.02*sin(2*PI*783.99*t)"  # G5
    )
    try:
        subprocess.run(
            [
                ffmpeg, "-y", "-f", "lavfi",
                "-i", f"aevalsrc={bgm_expr}:s=44100:c=stereo",
                "-t", str(dur + 0.5),
                "-af", f"afade=t=in:st=0:d=0.8,afade=t=out:st={dur - 0.5}:d=0.8",
                str(bgm_path),
            ],
            capture_output=True, timeout=30, check=True,
        )
        _log.info("SS3 synthesised BGM: %d bytes", bgm_path.stat().st_size)
    except Exception as exc:
        _log.warning("BGM synthesis failed (%s) — uploading silent video", exc)
        bgm_path = None  # type: ignore[assignment]

    # ── Mux video + audio ────────────────────────────────────────────────────
    if bgm_path is not None and bgm_path.exists():
        try:
            subprocess.run(
                [
                    ffmpeg, "-y",
                    "-i", str(video_path), "-i", str(bgm_path),
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "96k", "-shortest",
                    str(final_path),
                ],
                capture_output=True, timeout=30, check=True,
            )
            _log.info("SS3 muxed final: %d bytes", final_path.stat().st_size)
            upload_path = final_path
        except Exception as exc:
            _log.warning("mux failed (%s) — uploading silent video", exc)
            upload_path = video_path
    else:
        upload_path = video_path

    mp4_bytes = upload_path.read_bytes()

    # ── Upload to PDS ────────────────────────────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post(
                f"{_PDS_BASE}/xrpc/com.atproto.repo.uploadBlob",
                content=mp4_bytes,
                headers={
                    "content-type": "video/mp4",
                    "x-kotodama-verified": "true",
                    "x-etzhayyim-org-id": "anon",
                },
            )
            r.raise_for_status()
            output_cid: str = r.json()["blob"]["ref"]["$link"]
    except Exception as exc:
        _log.error("upload: %s", exc)
        return {"error": str(exc)}
    finally:
        for p in (video_path, bgm_path, final_path):
            if p is not None:
                Path(p).unlink(missing_ok=True)
        tmpdir.rmdir()

    _log.info("SS3 uploaded output_cid=%s", output_cid)

    # ── Update vertex_animeka.output_cid (non-fatal) ─────────────────────────
    if cut_rkey and _RW_URL:
        try:
            import psycopg
            conn = await psycopg.AsyncConnection.connect(_RW_URL, autocommit=True)
            await conn.execute(
                "UPDATE public.vertex_animeka SET output_cid = %s "
                "WHERE rkey = %s AND collection = 'com.etzhayyim.animeka.cut'",
                [output_cid, cut_rkey],
            )
            await conn.close()
            _log.info("SS3 persisted output_cid for rkey=%s", cut_rkey)
        except Exception as exc:
            _log.warning("db update: %s", exc)

    return {"output_cid": output_cid}


# ── conditional routing ──────────────────────────────────────────────────────

def _route_after_gen_frames(state: CompositorState) -> str:
    return END if state.get("error") or not state.get("frames") else "encode_upload"


# ── graph assembly ───────────────────────────────────────────────────────────

def build_compositor_graph() -> StateGraph:
    g = StateGraph(CompositorState)
    g.add_node("load_assets",   _ss0_load_assets)
    g.add_node("gen_frames",    _ss1_gen_frames)
    g.add_node("encode_upload", _ss3_encode_upload)

    g.add_edge(START, "load_assets")
    g.add_edge("load_assets", "gen_frames")
    g.add_conditional_edges("gen_frames", _route_after_gen_frames,
                            ["encode_upload", END])
    g.add_edge("encode_upload", END)
    return g


COMPOSITOR_GRAPH = build_compositor_graph().compile(name="compositor")


# ── convenience: run inline (called from autopilot's final node) ─────────────

async def composite_cut(
    cut_rkey: str,
    bg_cid: str,
    kf_cid: str,
    fps: int = _DEFAULT_FPS,
    duration_sec: int = _DEFAULT_DURATION_SEC,
) -> str | None:
    """Run the full Pregel compositor for a single cut; return output_cid or None."""
    result = await COMPOSITOR_GRAPH.ainvoke({
        "cut_rkey": cut_rkey,
        "bg_cid": bg_cid,
        "kf_cid": kf_cid,
        "fps": fps,
        "duration_sec": duration_sec,
    })
    cid = result.get("output_cid")
    if not cid:
        _log.warning("compositor returned no output_cid for %s", cut_rkey)
    return cid

GRAPH = COMPOSITOR_GRAPH  # alias for kaizen_compositor import
