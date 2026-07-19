"""assemble_episode — download all composited cut MP4s → ffmpeg concat → upload episode video.

Pregel (LangGraph):
  SA0  fetch_cuts      SELECT cuts with output_cid ordered by _seq
  SA1  download        Download each MP4 blob from PDS blob store
  SA2  concat          ffmpeg concat demuxer → single episode MP4
  SA3  upload          Upload episode MP4 → PDS blob → UPDATE vertex_animeka episode row

XRPC: com.etzhayyim.animeka.assembleEpisode
Input:
  episode_rkey   str   (default: latest published episode)
  limit          int   (max cuts to include, default 999)
Output:
  episode_cid    str
  cut_count      int
  duration_sec   float
  episode_rkey   str
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import httpx
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

_log = logging.getLogger(__name__)

_PDS_BASE = os.environ.get("ANIMEKA_PDS_BASE", "https://atproto.etzhayyim.com")
_BLOB_DID = "anonymous"
_RW_URL   = os.environ.get("RW_URL") or os.environ.get("LG_CHECKPOINTER_URL", "")
_REPO     = os.environ.get("ANIMEKA_REPO_DID", "did:web:an1m3k4x.etzhayyim.com")


class EpisodeAssemblyState(TypedDict, total=False):
    episode_rkey: str
    limit: int
    # intermediates
    cut_rows: list[dict]        # [{rkey, output_cid, created_at}]
    local_paths: list[str]      # downloaded tmp file paths
    _tmpdir: str                # temp directory shared across SA1/SA2/SA3
    concat_path: str            # assembled episode mp4
    duration_sec: float
    # output
    episode_cid: str
    cut_count: int
    error: str | None


# ── SA0: fetch cuts ───────────────────────────────────────────────────────────

async def _sa0_fetch_cuts(state: EpisodeAssemblyState) -> dict[str, Any]:
    limit = state.get("limit") or 999
    if not _RW_URL:
        return {"error": "RW_URL not set"}
    try:
        import asyncpg
        db = await asyncpg.connect(_RW_URL)
        try:
            rows = await db.fetch(
                f"""
                SELECT rkey, output_cid, created_at, _seq
                FROM vertex_animeka
                WHERE collection = 'com.etzhayyim.animeka.cut'
                  AND output_cid IS NOT NULL
                ORDER BY _seq
                LIMIT {int(limit) * 4}
                """,
            )
            # Deduplicate by rkey, keep latest _seq (RisingWave UPDATEs append rows)
            seen: dict[str, dict] = {}
            for r in rows:
                rkey = r["rkey"]
                seq = r["_seq"] or 0
                if rkey not in seen or seq > seen[rkey]["_seq"]:
                    seen[rkey] = {
                        "rkey": rkey,
                        "output_cid": r["output_cid"],
                        "created_at": r.get("created_at", ""),
                        "_seq": seq,
                    }
            # Sort by _seq (insertion order) then truncate
            cut_rows = sorted(seen.values(), key=lambda x: x["_seq"])[:int(limit)]
            for row in cut_rows:
                del row["_seq"]
            _log.info("SA0 fetched %d cuts", len(cut_rows))
            return {"cut_rows": cut_rows}
        finally:
            await db.close()
    except Exception as exc:
        return {"error": f"SA0 fetch: {exc}"}


# ── SA1: download MP4 blobs ───────────────────────────────────────────────────

async def _download_blob(cid: str, dest: Path, client: httpx.AsyncClient) -> bool:
    url = f"{_PDS_BASE}/xrpc/com.atproto.sync.getBlob?did={_BLOB_DID}&cid={cid}"
    try:
        r = await client.get(url, timeout=60)
        r.raise_for_status()
        dest.write_bytes(r.content)
        return True
    except Exception as exc:
        _log.warning("download %s: %s", cid[:16], exc)
        return False


async def _sa1_download(state: EpisodeAssemblyState) -> dict[str, Any]:
    if state.get("error"):
        return {}
    cut_rows = state.get("cut_rows") or []
    if not cut_rows:
        return {"error": "no cuts to assemble"}

    tmpdir = Path(tempfile.mkdtemp(prefix="ep_assemble_"))
    local_paths: list[str] = []

    async with httpx.AsyncClient(timeout=90) as client:
        tasks = []
        paths = []
        for i, row in enumerate(cut_rows):
            dest = tmpdir / f"cut_{i:04d}_{row['rkey']}.mp4"
            paths.append((str(dest), row))
            tasks.append(_download_blob(row["output_cid"], dest, client))

        results = await asyncio.gather(*tasks)

    for (path, row), ok in zip(paths, results):
        if ok and Path(path).exists() and Path(path).stat().st_size > 1000:
            local_paths.append(path)
        else:
            _log.warning("SA1 skip cut %s (download failed)", row["rkey"])

    _log.info("SA1 downloaded %d/%d cuts", len(local_paths), len(cut_rows))
    if not local_paths:
        return {"error": "SA1: no cuts downloaded"}
    return {"local_paths": local_paths, "_tmpdir": str(tmpdir)}


# ── SA2: ffmpeg concat ────────────────────────────────────────────────────────

async def _sa2_concat(state: EpisodeAssemblyState) -> dict[str, Any]:
    if state.get("error"):
        return {}
    local_paths = state.get("local_paths") or []
    if not local_paths:
        return {"error": "SA2: no local paths"}

    tmpdir = Path(state.get("_tmpdir", tempfile.mkdtemp()))
    concat_list = tmpdir / "concat.txt"
    episode_mp4 = tmpdir / "episode.mp4"

    # Write ffmpeg concat list
    lines = [f"file '{p}'\n" for p in local_paths]
    concat_list.write_text("".join(lines))

    try:
        from imageio_ffmpeg import get_ffmpeg_exe
    except ImportError:
        import subprocess as _sp
        _sp.check_call(["pip", "install", "-q", "imageio", "imageio-ffmpeg"])
        from imageio_ffmpeg import get_ffmpeg_exe
    ffmpeg = get_ffmpeg_exe()
    try:
        # Re-encode: scale to 480p, CRF 30 to keep episode file ~20-30 MB
        result = subprocess.run(
            [
                ffmpeg, "-y",
                "-f", "concat", "-safe", "0", "-i", str(concat_list),
                "-vf", "scale=854:480:force_original_aspect_ratio=decrease,pad=854:480:(ow-iw)/2:(oh-ih)/2",
                "-c:v", "libx264", "-preset", "fast", "-crf", "30",
                "-c:a", "aac", "-b:a", "96k",
                "-movflags", "+faststart",
                str(episode_mp4),
            ],
            capture_output=True,
            timeout=600,
        )
        if result.returncode != 0:
            err = result.stderr.decode()[-300:]
            _log.error("SA2 ffmpeg: %s", err)
            return {"error": f"SA2 ffmpeg rc={result.returncode}: {err[-100:]}"}

        size = episode_mp4.stat().st_size
        _log.info("SA2 concat done: %d cuts → %.1f MB", len(local_paths), size / 1e6)

        # Get duration via ffmpeg -i (ffprobe may not be bundled)
        dur_result = subprocess.run(
            [ffmpeg, "-i", str(episode_mp4)],
            capture_output=True, text=True, timeout=30,
        )
        import re as _re
        m = _re.search(r"Duration: (\d+):(\d+):([\d.]+)", dur_result.stderr)
        duration_sec = 0.0
        if m:
            duration_sec = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))

        return {"concat_path": str(episode_mp4), "duration_sec": duration_sec}
    except Exception as exc:
        return {"error": f"SA2: {exc}"}


# ── SA3: upload + DB update ───────────────────────────────────────────────────

async def _sa3_upload(state: EpisodeAssemblyState) -> dict[str, Any]:
    if state.get("error"):
        return {}
    concat_path = state.get("concat_path")
    if not concat_path or not Path(concat_path).exists():
        return {"error": "SA3: no concat file"}

    episode_rkey = state.get("episode_rkey") or "ep-1776928323916-1"
    mp4_bytes = Path(concat_path).read_bytes()
    cut_count = len(state.get("local_paths") or [])

    # Upload to PDS blob store (retry on 502/timeout)
    _log.info("SA3 uploading %.1f MB episode...", len(mp4_bytes) / 1e6)
    episode_cid: str | None = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=600) as client:
                r = await client.post(
                    f"{_PDS_BASE}/xrpc/com.atproto.repo.uploadBlob",
                    content=mp4_bytes,
                    headers={
                        "content-type": "video/mp4",
                        "x-kotodama-verified": "true",
                        "x-etzhayyim-org-id": "anon",
                    },
                )
                r.raise_for_status()
                episode_cid = r.json()["blob"]["ref"]["$link"]
            _log.info("SA3 uploaded episode: cid=%s size=%.1fMB", episode_cid[:16], len(mp4_bytes) / 1e6)
            break
        except Exception as exc:
            _log.warning("SA3 upload attempt %d: %s", attempt + 1, exc)
            if attempt == 2:
                return {"error": f"SA3 upload: {exc}"}
            await asyncio.sleep(5)

    # Update episode vertex in RisingWave
    if _RW_URL:
        try:
            import psycopg as _psycopg
            conn = await _psycopg.AsyncConnection.connect(_RW_URL, autocommit=True)
            try:
                await conn.execute(
                    "UPDATE public.vertex_animeka SET output_cid = %s, status = 'published'"
                    " WHERE collection = 'com.etzhayyim.animeka.episode' AND rkey = %s",
                    [episode_cid, episode_rkey],
                )
                _log.info("SA3 episode %s updated output_cid", episode_rkey)
            finally:
                await conn.close()
        except Exception as exc:
            _log.warning("SA3 DB update: %s", exc)

    # Cleanup temp files
    try:
        tmpdir = Path(state.get("_tmpdir", ""))
        if tmpdir.exists():
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception:
        pass

    return {
        "episode_cid": episode_cid,
        "cut_count": cut_count,
        "episode_rkey": episode_rkey,
    }


# ── Graph ─────────────────────────────────────────────────────────────────────

def _build_graph() -> StateGraph:
    g = StateGraph(EpisodeAssemblyState)
    g.add_node("fetch_cuts", _sa0_fetch_cuts)
    g.add_node("download", _sa1_download)
    g.add_node("concat", _sa2_concat)
    g.add_node("upload", _sa3_upload)

    g.add_edge(START, "fetch_cuts")
    g.add_edge("fetch_cuts", "download")
    g.add_edge("download", "concat")
    g.add_edge("concat", "upload")
    g.add_edge("upload", END)
    return g


GRAPH = _build_graph().compile(name="assemble_episode")
