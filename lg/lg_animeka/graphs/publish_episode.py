"""publish_episode — post Bluesky social announcement for a completed episode.

LangGraph Pregel (3 supersteps):
  SP0  fetch_episode    SELECT latest published episode (status='published', output_cid set)
  SP1  post_social      POST /_internal/create-social-post (HMAC auth, no user session needed)
  SP2  update_status    UPDATE vertex_animeka episode status='announced'

Idempotent: skips without error if episode already has status='announced'.
Auth: HMAC-SHA256(PDS_SERVICE_AUTH_MINT_SECRET, request_body) via x-bpmn-auth header.

XRPC: com.etzhayyim.animeka.publishEpisode
Input:
  episode_rkey   str   (optional; defaults to latest published episode)
Output:
  social_uri     str   (at://did/app.bsky.feed.post/rkey)
  episode_rkey   str
  skipped        bool  (true if already announced)
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Any

import httpx
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

_log = logging.getLogger(__name__)

_PDS_BASE       = os.environ.get("PDS_BASE", "https://atproto.etzhayyim.com")
# Internal Bun PDS pod has HYPERDRIVE (RISINGWAVE_URL) and can write AT records.
# CF Worker at PDS_BASE is edge-only (no HYPERDRIVE, ADR-2605111200).
_PDS_INTERNAL   = os.environ.get(
    "PDS_INTERNAL_URL",
    "http://atproto-pds.atproto.svc.cluster.local:8787",
)
_APP_DID        = os.environ.get("ANIMEKA_APP_DID", "did:web:an1m3k4x.etzhayyim.com")
_MINT_SECRET    = os.environ.get("PDS_SERVICE_AUTH_MINT_SECRET", "")
_RW_URL         = os.environ.get("RW_URL") or os.environ.get("LG_CHECKPOINTER_URL", "")


def _compute_hmac(secret: str, body: str) -> str:
    """HMAC-SHA256(secret, body_text) → hex digest — matches verifyInternalMintHmac."""
    return hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()


class PublishEpisodeState(TypedDict, total=False):
    episode_rkey: str
    # intermediates
    output_cid: str
    work_title: str
    # output
    social_uri: str
    skipped: bool
    error: str | None


# ── SP0: fetch episode ────────────────────────────────────────────────────────

async def _sp0_fetch_episode(state: PublishEpisodeState) -> dict[str, Any]:
    if not _RW_URL:
        return {"error": "RW_URL not set"}
    episode_rkey = (state.get("episode_rkey") or "").strip()
    try:
        import asyncpg
        db = await asyncpg.connect(_RW_URL)
        try:
            if episode_rkey:
                rows = await db.fetch(
                    """
                    SELECT rkey, output_cid, status, _seq
                    FROM vertex_animeka
                    WHERE collection = 'com.etzhayyim.animeka.episode' AND rkey = $1
                    ORDER BY _seq DESC LIMIT 1
                    """,
                    episode_rkey,
                )
            else:
                rows = await db.fetch(
                    """
                    SELECT rkey, output_cid, status, _seq
                    FROM vertex_animeka
                    WHERE collection = 'com.etzhayyim.animeka.episode'
                      AND output_cid IS NOT NULL
                    ORDER BY _seq DESC LIMIT 8
                    """,
                )
                # Deduplicate by rkey, keep latest _seq
                seen: dict[str, Any] = {}
                for r in rows:
                    rk = r["rkey"]
                    if rk not in seen or (r["_seq"] or 0) > (seen[rk]["_seq"] or 0):
                        seen[rk] = dict(r)
                candidates = [
                    v for v in seen.values()
                    if v["status"] == "published" and v["output_cid"]
                ]
                rows = candidates[:1] if candidates else []

            if not rows:
                _log.info("SP0: no publishable episode found")
                return {"skipped": True}

            row = dict(rows[0])
            if row.get("status") == "announced":
                _log.info("SP0: episode %s already announced", row["rkey"])
                return {"skipped": True, "episode_rkey": row["rkey"]}

            episode_rkey = row["rkey"]

            # Fetch work title from latest work record
            work_title = "animeka.etzhayyim.com"
            work_rows = await db.fetch(
                """
                SELECT title, _seq FROM vertex_animeka
                WHERE collection = 'com.etzhayyim.animeka.work'
                ORDER BY _seq DESC LIMIT 4
                """,
            )
            if work_rows:
                seen_w: dict[str, Any] = {}
                for wr in work_rows:
                    if not seen_w or (wr["_seq"] or 0) > (seen_w.get("_seq") or 0):
                        seen_w = dict(wr)
                t = (seen_w.get("title") or "").strip()
                if t:
                    work_title = t

            _log.info("SP0: episode=%s work=%s", episode_rkey, work_title)
            return {
                "episode_rkey": episode_rkey,
                "output_cid": row["output_cid"] or "",
                "work_title": work_title,
            }
        finally:
            await db.close()
    except Exception as exc:
        return {"error": f"SP0: {exc}"}


# ── SP1: post social via /_internal/create-social-post ───────────────────────

async def _sp1_post_social(state: PublishEpisodeState) -> dict[str, Any]:
    if state.get("error") or state.get("skipped"):
        return {}
    if not _MINT_SECRET:
        _log.warning("SP1: PDS_SERVICE_AUTH_MINT_SECRET not set — skipping social post")
        return {"skipped": True}

    episode_rkey = state.get("episode_rkey") or ""
    work_title = state.get("work_title") or "animeka.etzhayyim.com"
    episode_url = f"https://animeka.etzhayyim.com/episodes/{episode_rkey}"

    # Post text ≤ 300 chars
    text = f"🎬 新エピソード公開！\n『{work_title}』\nBGM・SFX・ナレーション付きで全カット完成。\n{episode_url}\n#animeka #etzhayyimai"
    if len(text) > 300:
        text = f"🎬 New episode — 『{work_title}』\n{episode_url}\n#animeka"

    import json as _json
    payload = _json.dumps({
        "repo": _APP_DID,
        "text": text,
        "embedUri": episode_url,
        "embedTitle": f"『{work_title}』— animeka.etzhayyim.com",
        "embedDescription": "BGM + SFX + ナレーション付きアニメエピソード",
    }, ensure_ascii=False, separators=(",", ":"))

    bpmn_auth = _compute_hmac(_MINT_SECRET, payload)
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post(
                f"{_PDS_INTERNAL}/_internal/create-social-post",
                content=payload.encode(),
                headers={
                    "content-type": "application/json",
                    "x-bpmn-auth": bpmn_auth,
                },
            )
            r.raise_for_status()
            data = r.json()
        social_uri = data.get("uri") or ""
        _log.info("SP1: social post created uri=%s", social_uri)
        return {"social_uri": social_uri}
    except Exception as exc:
        return {"error": f"SP1 create-social-post: {exc}"}


# ── SP2: update status ────────────────────────────────────────────────────────

async def _sp2_update_status(state: PublishEpisodeState) -> dict[str, Any]:
    if state.get("error") or state.get("skipped"):
        return {}
    episode_rkey = state.get("episode_rkey") or ""
    social_uri = state.get("social_uri") or ""
    if not (episode_rkey and social_uri and _RW_URL):
        return {}
    try:
        import psycopg as _psycopg
        conn = await _psycopg.AsyncConnection.connect(_RW_URL, autocommit=True)
        try:
            await conn.execute(
                "UPDATE public.vertex_animeka SET status = 'announced'"
                " WHERE collection = 'com.etzhayyim.animeka.episode' AND rkey = %s",
                [episode_rkey],
            )
            _log.info("SP2: episode %s status=announced social_uri=%s", episode_rkey, social_uri)
        finally:
            await conn.close()
    except Exception as exc:
        _log.warning("SP2 DB update: %s", exc)
    return {}


# ── Graph ─────────────────────────────────────────────────────────────────────

def _build_graph() -> StateGraph:
    g = StateGraph(PublishEpisodeState)
    g.add_node("fetch_episode",  _sp0_fetch_episode)
    g.add_node("post_social",    _sp1_post_social)
    g.add_node("update_status",  _sp2_update_status)
    g.add_edge(START, "fetch_episode")
    g.add_edge("fetch_episode", "post_social")
    g.add_edge("post_social", "update_status")
    g.add_edge("update_status", END)
    return g


GRAPH = _build_graph().compile(name="publish_episode")
