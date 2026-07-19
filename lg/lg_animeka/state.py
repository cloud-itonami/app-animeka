"""Typed state schemas for animeka graphs.

Animeka state is more entity-oriented than shinshi's per-scene state:
work → episode → scene → cut → layer (background, layout, keyframe,
inbetween, color, composite). Most graphs operate on a (work_id,
episode_id, cut_id) tuple.
"""

from __future__ import annotations

from typing import Literal, TypedDict


CutStage = Literal[
    "ideation", "script", "storyboard", "layout",
    "keyframe", "inbetween", "color", "background",
    "composite", "sound", "edit", "delivered",
]


class WorkState(TypedDict, total=False):
    """One work (series). Used by createWork / listWorks / addEpisode."""
    work_id: str
    work_did: str           # did:web:animeka.etzhayyim.com:work:{id}
    title: str
    description: str
    owner_did: str
    error: str | None


class EpisodeState(TypedDict, total=False):
    """One episode."""
    work_id: str
    episode_id: str
    episode_did: str
    title: str
    duration_sec: int
    error: str | None


class CutState(TypedDict, total=False):
    """One cut (shot). Used by addCut / getCut / updateCutStage / cutRunner."""
    work_id: str
    episode_id: str
    cut_id: str
    cut_did: str
    stage: CutStage
    duration_frames: int
    storyboard_url: str
    layout_url: str
    keyframe_urls: list[str]
    inbetween_url: str
    composite_url: str
    error: str | None


class GenerateState(TypedDict, total=False):
    """Generation pipeline state — used by generateScript /
    generateStoryboard / generateLayout / generateKeyframe / etc."""
    work_id: str
    episode_id: str
    cut_id: str
    actor_did: str          # the AI actor performing this generation
    stage: CutStage
    prompt: str
    context: dict           # prior cut outputs as input
    output_url: str
    output_blob_cid: str
    posted_uri: str
    error: str | None
    latency_ms: int


class ChatState(TypedDict, total=False):
    """Per-cut creative chat (director ↔ humans)."""
    work_id: str
    episode_id: str
    cut_id: str
    actor_did: str          # which animeka actor responds (default: director)
    user_did: str
    message: str
    history: list[dict]
    reply: str
    error: str | None
