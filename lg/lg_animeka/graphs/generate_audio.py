"""generate_audio — per-cut audio pipeline: mood inference → BGM synthesis → TTS → MP4 replace.

Pregel (LangGraph):
  SS0  fetch_cuts     SELECT composited cuts needing audio refresh
  SS1  infer_mood     OpenRouter LLM infers mood from work title + storyboard context
  SS2  gen_bgm        scipy/numpy musical BGM synthesis (per mood)
  SS3  gen_dialogue   edge-tts TTS for any dialogue lines (Japanese voices)
  SS4  apply_audio    ffmpeg replace audio in existing MP4 → PDS upload → DB UPDATE

XRPC: com.etzhayyim.animeka.generateAudio
Input:
  max_cuts   int  (default 5)
  rkeys      list[str]  (optional — target specific cuts)
Output:
  processed  list[dict]  (rkey, new_output_cid, latency_ms)
  summary    dict
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import math
import os
import random
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

_log = logging.getLogger(__name__)

_PDS_BASE   = os.environ.get("ANIMEKA_PDS_BASE", "https://atproto.etzhayyim.com")
_BLOB_DID   = "anonymous"
_RW_URL     = os.environ.get("RW_URL") or os.environ.get("LG_CHECKPOINTER_URL", "")
_OR_KEY     = os.environ.get("OPENROUTER_API_KEY", "")
_OR_MODEL   = os.environ.get("ANIMEKA_MOOD_MODEL", "anthropic/claude-haiku-4-5")
_REPO       = os.environ.get("ANIMEKA_REPO_DID", "did:web:an1m3k4x.etzhayyim.com")

_SAMPLE_RATE = 44100


# ── TypedDict ────────────────────────────────────────────────────────────────

class AudioState(TypedDict, total=False):
    max_cuts: int
    rkeys: list[str]
    # intermediates
    cut_rows: list[dict]          # [{rkey, output_cid, title, dialogue, work_title}]
    moods: dict[str, str]         # rkey → mood string
    processed: list[dict]
    summary: dict
    error: str | None


# ── Mood palette ─────────────────────────────────────────────────────────────

_MOODS = ["action", "emotional", "calm", "dark", "bright", "mysterious"]

_MOOD_PROMPT = """\
You are a music supervisor for a Japanese anime production.
Given the work title and any available context, pick ONE mood for the background music of this scene.

Work title: {title}
Scene context: {context}

Choose exactly one from: action, emotional, calm, dark, bright, mysterious

Return ONLY the single word. No explanation."""

# ── Musical definitions per mood ──────────────────────────────────────────────

_MOOD_PARAMS: dict[str, dict] = {
    "action": dict(
        bpm=138, key_root=220.0, scale=[0,2,3,5,7,8,10],  # A natural minor
        melody_oct=1, bass_oct=-2, chord_voicing=[(0,7,12),(5,12,17),(3,10,15),(7,14,19)],
        drum_kick_beats=[0,0.5,1,1.5,2,2.5,3,3.5],
        drum_hat_every=0.25, melody_staccato=0.3,
        bgm_vol=0.28, melody_vol=0.18, bass_vol=0.12, drum_vol=0.10,
    ),
    "emotional": dict(
        bpm=72, key_root=261.63, scale=[0,2,4,5,7,9,11],  # C major
        melody_oct=1, bass_oct=-2, chord_voicing=[(0,7,12),(5,9,14),(4,7,11),(7,11,14)],
        drum_kick_beats=[], drum_hat_every=0, melody_staccato=0.9,
        bgm_vol=0.22, melody_vol=0.20, bass_vol=0.10, drum_vol=0.0,
    ),
    "calm": dict(
        bpm=90, key_root=261.63, scale=[0,2,4,7,9],  # C pentatonic major
        melody_oct=1, bass_oct=-2, chord_voicing=[(0,7,12),(4,9,16),(7,12,19),(2,9,14)],
        drum_kick_beats=[0, 2], drum_hat_every=0.5, melody_staccato=0.7,
        bgm_vol=0.18, melody_vol=0.14, bass_vol=0.08, drum_vol=0.05,
    ),
    "dark": dict(
        bpm=80, key_root=196.0, scale=[0,1,3,5,6,8,10],  # G phrygian
        melody_oct=0, bass_oct=-2, chord_voicing=[(0,6,10),(5,8,15),(3,6,13),(1,6,10)],
        drum_kick_beats=[0, 1.5, 3], drum_hat_every=0, melody_staccato=0.5,
        bgm_vol=0.20, melody_vol=0.14, bass_vol=0.14, drum_vol=0.06,
    ),
    "bright": dict(
        bpm=120, key_root=293.66, scale=[0,2,4,7,9],  # D pentatonic major
        melody_oct=1, bass_oct=-2, chord_voicing=[(0,7,12),(4,9,16),(7,12,19),(5,9,14)],
        drum_kick_beats=[0,1,2,3], drum_hat_every=0.25, melody_staccato=0.4,
        bgm_vol=0.24, melody_vol=0.18, bass_vol=0.10, drum_vol=0.08,
    ),
    "mysterious": dict(
        bpm=85, key_root=233.08, scale=[0,1,4,5,6,9,10],  # Bb diminished-like
        melody_oct=0, bass_oct=-2, chord_voicing=[(0,6,9),(3,6,12),(5,9,14),(1,6,10)],
        drum_kick_beats=[0, 2.5], drum_hat_every=0, melody_staccato=0.6,
        bgm_vol=0.20, melody_vol=0.12, bass_vol=0.10, drum_vol=0.04,
    ),
}


# ── Low-level audio synthesis ─────────────────────────────────────────────────

def _semitones_to_hz(base_hz: float, semitones: float) -> float:
    return base_hz * (2 ** (semitones / 12.0))


def _adsr(n_samples: int, attack: float, decay: float, sustain: float,
          release: float, sr: int = _SAMPLE_RATE) -> np.ndarray:
    env = np.zeros(n_samples)
    a = min(int(attack * sr), n_samples)
    d = min(int(decay * sr), n_samples - a)
    r = int(release * sr)
    s = max(0, n_samples - a - d - r)
    r = min(r, n_samples - a - d - s)
    if a: env[:a] = np.linspace(0, 1, a)
    if d: env[a:a+d] = np.linspace(1, sustain, d)
    if s: env[a+d:a+d+s] = sustain
    if r: env[a+d+s:a+d+s+r] = np.linspace(sustain, 0, r)
    return env


def _sine(freq: float, n: int, sr: int = _SAMPLE_RATE, phase: float = 0.0) -> np.ndarray:
    t = np.arange(n) / sr
    return np.sin(2 * np.pi * freq * t + phase)


def _synth_note(freq: float, dur: float, staccato: float, osc: str = "sine",
                sr: int = _SAMPLE_RATE) -> np.ndarray:
    n = int(dur * sr)
    sounding = max(0.05, staccato)
    n_snd = int(sounding * n)
    attack = min(0.04, sounding * 0.1)
    decay  = min(0.05, sounding * 0.15)
    sustain_level = 0.7
    release = min(0.08, sounding * 0.2)

    if osc == "sine":
        wave = _sine(freq, n_snd) + 0.3 * _sine(freq * 2, n_snd) + 0.1 * _sine(freq * 3, n_snd)
    elif osc == "saw":
        t = np.arange(n_snd) / sr
        wave = sum(np.sin(2 * np.pi * freq * k * t) / k for k in range(1, 8))
    else:
        wave = _sine(freq, n_snd)

    env = _adsr(n_snd, attack, decay, sustain_level, release)
    result = np.zeros(n)
    result[:n_snd] = wave * env
    return result


def _synth_chord(freqs: list[float], dur: float, sr: int = _SAMPLE_RATE) -> np.ndarray:
    n = int(dur * sr)
    attack = 0.12; decay = 0.1; sustain_lvl = 0.6; release = 0.3
    result = np.zeros(n)
    for f in freqs:
        wave = _sine(f, n) + 0.2 * _sine(f * 2, n)
        env = _adsr(n, attack, decay, sustain_lvl, release)
        result += wave * env / len(freqs)
    return result


def _synth_kick(n: int, sr: int = _SAMPLE_RATE) -> np.ndarray:
    freq_start, freq_end = 120.0, 40.0
    dur = 0.18
    n_k = int(dur * sr)
    if n_k > n: n_k = n
    t = np.arange(n_k) / sr
    freq = np.exp(np.linspace(np.log(freq_start), np.log(freq_end), n_k))
    phase = np.cumsum(2 * np.pi * freq / sr)
    wave = np.sin(phase)
    env = np.exp(-t * 28)
    result = np.zeros(n)
    result[:n_k] = wave * env
    return result * 0.8


def _synth_hihat(n: int, sr: int = _SAMPLE_RATE, closed: bool = True) -> np.ndarray:
    noise = np.random.randn(n) * 0.5
    # High-pass filter approx (difference)
    hp = np.diff(noise, prepend=noise[0])
    dur = 0.04 if closed else 0.10
    n_h = int(dur * sr)
    env = np.zeros(n)
    env[:min(n_h, n)] = np.exp(-np.arange(min(n_h, n)) / (sr * dur * 0.5))
    return hp * env * 0.3


def synthesize_bgm(mood: str, duration_sec: float, sr: int = _SAMPLE_RATE) -> np.ndarray:
    """Full BGM synthesis for the given mood and duration."""
    params = _MOOD_PARAMS.get(mood, _MOOD_PARAMS["calm"])
    bpm       = params["bpm"]
    root      = params["key_root"]
    scale     = params["scale"]
    m_oct     = params["melody_oct"]
    b_oct     = params["bass_oct"]
    voicings  = params["chord_voicing"]
    staccato  = params["melody_staccato"]
    kick_beats = params["drum_kick_beats"]
    hat_every  = params["drum_hat_every"]
    bgm_vol   = params["bgm_vol"]
    mel_vol   = params["melody_vol"]
    bass_vol  = params["bass_vol"]
    drum_vol  = params["drum_vol"]

    beat_dur   = 60.0 / bpm
    bar_dur    = beat_dur * 4
    n_total    = int(duration_sec * sr)
    mix        = np.zeros(n_total)

    # Melody pattern (random walk on scale)
    rng = random.Random(42)
    mel_degree = 4
    mel_pattern: list[tuple[int, float]] = []  # (scale_degree, beat_fraction)
    beat_subdivisions = [0.5, 0.5] if staccato < 0.5 else [1.0]
    pos = 0.0
    while pos < duration_sec:
        step = rng.choice([-2, -1, 0, 1, 2])
        mel_degree = max(0, min(len(scale) - 1, mel_degree + step))
        sub = rng.choice(beat_subdivisions)
        mel_pattern.append((mel_degree, sub * beat_dur))
        pos += sub * beat_dur

    # Write melody
    t_mel = 0.0
    for deg, note_dur in mel_pattern:
        if t_mel >= duration_sec: break
        st = scale[deg]
        freq = _semitones_to_hz(root, st + m_oct * 12)
        n_note = int(note_dur * sr)
        start_s = int(t_mel * sr)
        if start_s + n_note > n_total: n_note = n_total - start_s
        if n_note <= 0: break
        note_wave = _synth_note(freq, note_dur, staccato)
        mix[start_s:start_s + n_note] += note_wave[:n_note] * mel_vol
        t_mel += note_dur

    # Chord pads every bar
    chord_idx = 0
    t_chord = 0.0
    while t_chord < duration_sec:
        voicing = voicings[chord_idx % len(voicings)]
        chord_freqs = [_semitones_to_hz(root, s) for s in voicing]
        chord_len = min(bar_dur, duration_sec - t_chord)
        n_chord = int(chord_len * sr)
        start_s = int(t_chord * sr)
        if n_chord > 0:
            chord_wave = _synth_chord(chord_freqs, chord_len)
            mix[start_s:start_s + n_chord] += chord_wave[:n_chord] * bgm_vol
        t_chord += bar_dur
        chord_idx += 1

    # Bass line (root note each bar)
    t_bass = 0.0
    chord_idx = 0
    while t_bass < duration_sec:
        voicing = voicings[chord_idx % len(voicings)]
        bass_freq = _semitones_to_hz(root, voicing[0] + b_oct * 12)
        bass_len = min(beat_dur * 2, duration_sec - t_bass)
        n_bass = int(bass_len * sr)
        start_s = int(t_bass * sr)
        if n_bass > 0:
            bass_wave = _synth_note(bass_freq, bass_len, 0.85, osc="saw")
            mix[start_s:start_s + n_bass] += bass_wave[:n_bass] * bass_vol
        t_bass += bar_dur
        chord_idx += 1

    # Drums
    if drum_vol > 0:
        t_drum = 0.0
        while t_drum < duration_sec:
            # Kick
            for beat_offset in kick_beats:
                t_k = t_drum + beat_offset * beat_dur
                if t_k >= duration_sec: break
                start_s = int(t_k * sr)
                n_k = min(int(0.3 * sr), n_total - start_s)
                if n_k > 0:
                    mix[start_s:start_s + n_k] += _synth_kick(n_k)[:n_k] * drum_vol
            # Hi-hat
            if hat_every > 0:
                t_h = t_drum
                while t_h < t_drum + bar_dur and t_h < duration_sec:
                    start_s = int(t_h * sr)
                    n_h = min(int(0.05 * sr), n_total - start_s)
                    if n_h > 0:
                        mix[start_s:start_s + n_h] += _synth_hihat(n_h)[:n_h]
                    t_h += hat_every * beat_dur
            t_drum += bar_dur

    # Fade in/out
    fade_n = int(min(0.8, duration_sec * 0.15) * sr)
    if fade_n > 0:
        mix[:fade_n] *= np.linspace(0, 1, fade_n)
        mix[-fade_n:] *= np.linspace(1, 0, fade_n)

    # Normalise to -3 dBFS
    peak = np.abs(mix).max()
    if peak > 0:
        mix = mix / peak * 0.7

    return mix.astype(np.float32)


# ── SFX synthesis ─────────────────────────────────────────────────────────────

_SFX_PROFILES: dict[str, dict] = {
    # outdoor daytime: birds + light breeze
    "outdoor_day":  {"noise_col": 0.7, "noise_amp": 0.06, "chirp_rate": 3.0, "chirp_amp": 0.04, "rain": False},
    # outdoor night: crickets + wind
    "outdoor_night": {"noise_col": 0.5, "noise_amp": 0.05, "chirp_rate": 8.0, "chirp_amp": 0.06, "rain": False},
    # indoor: subtle room tone
    "indoor":       {"noise_col": 0.95, "noise_amp": 0.02, "chirp_rate": 0.0, "chirp_amp": 0.0, "rain": False},
    # rain: broadband rain + rumble
    "rain":         {"noise_col": 0.3, "noise_amp": 0.12, "chirp_rate": 0.0, "chirp_amp": 0.0, "rain": True},
    # crowd: low chatter (filtered noise + modulation)
    "crowd":        {"noise_col": 0.6, "noise_amp": 0.08, "chirp_rate": 1.5, "chirp_amp": 0.02, "rain": False},
}

_LOC_PROFILE: dict[str, str] = {
    "outdoor": "outdoor_day", "forest": "outdoor_day", "park": "outdoor_day",
    "school": "indoor", "classroom": "indoor", "room": "indoor", "house": "indoor",
    "office": "indoor", "corridor": "indoor", "hall": "indoor",
    "night": "outdoor_night", "street": "outdoor_day",
    "rain": "rain", "storm": "rain",
    "cafe": "crowd", "restaurant": "crowd", "market": "crowd",
}

def _classify_sfx(location: str, time_of_day: str) -> str:
    loc = (location or "").lower()
    tod = (time_of_day or "").lower()
    if "rain" in loc or "storm" in loc:
        return "rain"
    for key, profile in _LOC_PROFILE.items():
        if key in loc:
            if profile == "outdoor_day" and ("night" in tod or "evening" in tod):
                return "outdoor_night"
            return profile
    if "night" in tod or "evening" in tod:
        return "outdoor_night"
    return "outdoor_day"

def synthesize_sfx(location: str, time_of_day: str, duration_sec: float,
                   sr: int = _SAMPLE_RATE) -> np.ndarray:
    profile_key = _classify_sfx(location, time_of_day)
    p = _SFX_PROFILES[profile_key]
    n = int(duration_sec * sr)
    rng = random.Random(hash(profile_key) & 0xFFFFFF)

    # Coloured noise base (low-pass filtered white noise)
    white = np.array([rng.gauss(0, 1) for _ in range(n)], dtype=np.float32)
    col = p["noise_col"]
    # Simple IIR low-pass: y[i] = col * y[i-1] + (1-col) * x[i]
    noise = np.zeros(n, dtype=np.float32)
    prev = 0.0
    for i in range(n):
        prev = col * prev + (1.0 - col) * white[i]
        noise[i] = prev
    peak = np.abs(noise).max()
    if peak > 0:
        noise = noise / peak * float(p["noise_amp"])

    # Rain: add high-freq component
    if p["rain"]:
        high = np.array([rng.gauss(0, 1) for _ in range(n)], dtype=np.float32)
        noise += high * 0.04

    # Periodic chirps (birds / crickets)
    chirp_rate = p["chirp_rate"]
    chirp_amp = p["chirp_amp"]
    if chirp_rate > 0 and chirp_amp > 0:
        chirp_interval = int(sr / chirp_rate)
        t_chirp = np.arange(min(int(0.08 * sr), chirp_interval)) / sr
        chirp_freq = 3200.0 if "night" in profile_key else 4200.0
        chirp_wave = np.sin(2 * np.pi * chirp_freq * t_chirp) * np.exp(-t_chirp * 40) * chirp_amp
        for onset in range(0, n, chirp_interval):
            end = min(onset + len(chirp_wave), n)
            if rng.random() < 0.6:  # not every interval
                noise[onset:end] += chirp_wave[:end - onset]

    # Fade in/out
    fade = int(min(0.3, duration_sec * 0.1) * sr)
    if fade > 0:
        noise[:fade] *= np.linspace(0, 1, fade)
        noise[-fade:] *= np.linspace(1, 0, fade)

    return noise.astype(np.float32)


# ── SS0: fetch cuts ───────────────────────────────────────────────────────────

async def _ss0_fetch_cuts(state: AudioState) -> dict[str, Any]:
    max_cuts = int(state.get("max_cuts") or 5)
    rkeys_filter = state.get("rkeys") or []
    if not _RW_URL:
        return {"error": "RW_URL not configured"}
    try:
        import psycopg
        conn = await psycopg.AsyncConnection.connect(_RW_URL, autocommit=True)

        if rkeys_filter:
            placeholders = ", ".join(f"'{r}'" for r in rkeys_filter[:20])
            sql = f"""
                SELECT v.rkey, v.output_cid, v.dialogue, v.title, v.mood, v.lighting_mood, v.time_of_day,
                       w.title as work_title, v.camera_note, v.location
                FROM public.vertex_animeka v
                LEFT JOIN public.vertex_animeka w
                  ON w.collection = 'com.etzhayyim.animeka.work' AND w.rkey = v.work_id
                WHERE v.collection = 'com.etzhayyim.animeka.cut'
                  AND v.output_cid IS NOT NULL AND v.output_cid != ''
                  AND v.rkey IN ({placeholders})
            """
        else:
            sql = f"""
                SELECT v.rkey, v.output_cid, v.dialogue, v.title, v.mood, v.lighting_mood, v.time_of_day,
                       w.title as work_title, v.camera_note, v.location
                FROM public.vertex_animeka v
                LEFT JOIN public.vertex_animeka w
                  ON w.collection = 'com.etzhayyim.animeka.work' AND w.rkey = v.work_id
                WHERE v.collection = 'com.etzhayyim.animeka.cut'
                  AND v.output_cid IS NOT NULL AND v.output_cid != ''
                ORDER BY v.created_at DESC LIMIT {max_cuts}
            """

        rows = await conn.execute(sql)
        cut_rows = [
            {
                "rkey": r[0], "output_cid": r[1],
                "dialogue": r[2] or r[8] or "",
                "title": r[3] or "", "mood": r[4] or r[5] or "",
                "time_of_day": r[6] or "", "work_title": r[7] or "",
                "camera_note": r[8] or "", "location": r[9] or "",
            }
            for r in await rows.fetchall()
        ]
        await conn.close()
        _log.info("SS0 audio: fetched %d cuts", len(cut_rows))
        return {"cut_rows": cut_rows}
    except Exception as exc:
        _log.error("SS0 audio fetch: %s", exc)
        return {"error": str(exc)}


# ── SS1: infer mood per cut (LLM or heuristic) ───────────────────────────────

async def _ss1_infer_mood(state: AudioState) -> dict[str, Any]:
    cut_rows = state.get("cut_rows") or []
    if not cut_rows or state.get("error"):
        return {}

    moods: dict[str, str] = {}

    async def _infer_one(row: dict) -> tuple[str, str]:
        rkey = row["rkey"]
        # Use existing mood if present
        if row["mood"] in _MOODS:
            return rkey, row["mood"]

        # Heuristic from time_of_day field
        tod = (row["time_of_day"] or "").lower()
        if "night" in tod or "midnight" in tod:
            return rkey, "dark"
        if "dawn" in tod or "dusk" in tod:
            return rkey, "mysterious"

        # LLM inference if work title available
        if _OR_KEY and row["work_title"]:
            context = f"time: {row['time_of_day'] or 'unknown'}, dialogue: {row['dialogue'][:80] or 'none'}"
            prompt = _MOOD_PROMPT.format(title=row["work_title"], context=context)
            try:
                async with httpx.AsyncClient(timeout=15) as c:
                    r = await c.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        json={"model": _OR_MODEL, "max_tokens": 10,
                              "messages": [{"role": "user", "content": prompt}]},
                        headers={"Authorization": f"Bearer {_OR_KEY}", "content-type": "application/json"},
                    )
                    r.raise_for_status()
                    word = r.json()["choices"][0]["message"]["content"].strip().lower().split()[0]
                    if word in _MOODS:
                        return rkey, word
            except Exception as exc:
                _log.warning("mood inference %s: %s", rkey, exc)

        # Autopilot cuts: derive mood from timestamp hour + rkey hash for variety
        # rkey pattern: "auto-YYYYMMDDTHHMMSSZ"
        import re as _re
        m = _re.search(r'T(\d{2})', rkey)
        hour = int(m.group(1)) if m else (hash(rkey) % 24)
        # Time-of-day mapping
        if 0 <= hour < 5:
            tod_mood = "dark"
        elif 5 <= hour < 8:
            tod_mood = "mysterious"
        elif 8 <= hour < 12:
            tod_mood = "calm"
        elif 12 <= hour < 17:
            tod_mood = "bright"
        elif 17 <= hour < 20:
            tod_mood = "emotional"
        else:
            tod_mood = "mysterious"
        # Mix tod_mood with hash-based secondary for variety
        h = hash(rkey) % len(_MOODS)
        secondary = _MOODS[h]
        # 70% time-of-day, 30% hash-based
        chosen = tod_mood if (hash(rkey) % 10) < 7 else secondary
        return rkey, chosen

    results = await asyncio.gather(*[_infer_one(r) for r in cut_rows])
    for rkey, mood in results:
        moods[rkey] = mood
        _log.info("SS1 mood: %s → %s", rkey[-12:], mood)

    return {"moods": moods}


# ── Audio blob upload helper ─────────────────────────────────────────────────

async def _upload_audio_blob(path: Path) -> str:
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(
            f"{_PDS_BASE}/xrpc/com.atproto.repo.uploadBlob",
            content=path.read_bytes(),
            headers={"Content-Type": "audio/wav", "x-kotodama-verified": "true", "x-etzhayyim-org-id": "anon"},
        )
        r.raise_for_status()
        return r.json()["blob"]["ref"]["$link"]


# ── SS2: generate audio (BGM + TTS) per cut ──────────────────────────────────

async def _ss2_gen_audio(state: AudioState) -> dict[str, Any]:
    cut_rows = state.get("cut_rows") or []
    moods    = state.get("moods") or {}
    if not cut_rows or state.get("error"):
        return {}

    # ensure scipy available
    try:
        import scipy.io.wavfile as wav_io  # noqa: F401
    except ImportError:
        import subprocess as _sp
        _sp.check_call(["pip", "install", "-q", "scipy"])
        import scipy.io.wavfile as wav_io  # noqa: F401

    # try edge-tts for dialogue
    has_edge_tts = False
    try:
        import edge_tts  # noqa: F401
        has_edge_tts = True
    except ImportError:
        try:
            import subprocess as _sp
            _sp.check_call(["pip", "install", "-q", "edge-tts"])
            import edge_tts  # noqa: F401
            has_edge_tts = True
        except Exception:
            pass

    try:
        from imageio_ffmpeg import get_ffmpeg_exe
    except ImportError:
        import subprocess as _sp
        _sp.check_call(["pip", "install", "-q", "imageio", "imageio-ffmpeg"])
        from imageio_ffmpeg import get_ffmpeg_exe
    ffmpeg = get_ffmpeg_exe()

    async def _process_one(row: dict) -> dict:
        rkey = row["rkey"]
        output_cid = row["output_cid"]
        dialogue = row["dialogue"] or ""
        mood = moods.get(rkey, "calm")
        dur = 4.0  # default cut duration

        tmpdir = Path(tempfile.mkdtemp())
        mp4_in  = tmpdir / "input.mp4"
        bgm_wav = tmpdir / "bgm.wav"
        sfx_wav = tmpdir / "sfx.wav"
        tts_wav = tmpdir / "tts.wav"
        mix_wav = tmpdir / "mix.wav"
        mp4_out = tmpdir / "output.mp4"

        try:
            # 1. Download existing MP4
            url = f"{_PDS_BASE}/xrpc/com.atproto.sync.getBlob?did={_BLOB_DID}&cid={output_cid}"
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.get(url)
                r.raise_for_status()
                mp4_in.write_bytes(r.content)

            # Detect actual duration
            probe = subprocess.run(
                [ffmpeg, "-i", str(mp4_in)],
                capture_output=True, timeout=10,
            )
            import re
            m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", probe.stderr.decode(errors="replace"))
            if m:
                dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))

            # 2. Synthesise BGM
            import scipy.io.wavfile as wav_io
            bgm_samples = synthesize_bgm(mood, dur + 0.5)
            # stereo
            stereo = np.stack([bgm_samples, bgm_samples], axis=1)
            wav_io.write(str(bgm_wav), _SAMPLE_RATE, stereo)

            # 2b. Synthesise ambient SFX
            sfx_samples = synthesize_sfx(
                row.get("location", ""),
                row.get("time_of_day", ""),
                dur + 0.5,
            )
            sfx_stereo = np.stack([sfx_samples, sfx_samples], axis=1)
            wav_io.write(str(sfx_wav), _SAMPLE_RATE, sfx_stereo)

            # 3. TTS: character dialogue OR scene narration from camera_note
            has_tts = False
            tts_text = dialogue or row.get("camera_note", "")
            # is_narration: no explicit dialogue, using scene description as narration
            is_narration = bool(tts_text) and not (row.get("dialogue") or "").strip()
            if tts_text and has_edge_tts:
                try:
                    import edge_tts
                    # Female character voice for dialogue, soft male narrator for scene description
                    voice = "ja-JP-KeitaNeural" if is_narration else "ja-JP-NanamiNeural"
                    communicate = edge_tts.Communicate(tts_text[:200], voice)
                    await communicate.save(str(tts_wav))
                    has_tts = tts_wav.exists() and tts_wav.stat().st_size > 1000
                    _log.info("TTS %s: voice=%s narration=%s", rkey[-12:], voice, is_narration)
                except Exception as exc:
                    _log.warning("TTS %s: %s", rkey[-12:], exc)

            # 4. Mix BGM + SFX + TTS → WAV
            if has_tts:
                # narration: BGM 40% + SFX 25% + voice 85% with 0.5s lead-in
                # dialogue:  BGM 35% + SFX 25% + voice 100% with 0.8s lead-in
                bgm_vol   = "0.40" if is_narration else "0.35"
                tts_vol   = "0.85" if is_narration else "1.00"
                tts_delay = "500"  if is_narration else "800"
                subprocess.run(
                    [ffmpeg, "-y",
                     "-i", str(bgm_wav), "-i", str(sfx_wav), "-i", str(tts_wav),
                     "-filter_complex",
                     f"[0]volume={bgm_vol}[bgm];[1]volume=0.25[sfx];[2]volume={tts_vol},adelay={tts_delay}[tts];[bgm][sfx][tts]amix=inputs=3:duration=first",
                     str(mix_wav)],
                    capture_output=True, timeout=30, check=True,
                )
                audio_src = mix_wav
            else:
                # BGM 80% + SFX 25% (no TTS)
                subprocess.run(
                    [ffmpeg, "-y",
                     "-i", str(bgm_wav), "-i", str(sfx_wav),
                     "-filter_complex",
                     "[0]volume=0.80[bgm];[1]volume=0.25[sfx];[bgm][sfx]amix=inputs=2:duration=first",
                     str(mix_wav)],
                    capture_output=True, timeout=30, check=True,
                )
                audio_src = mix_wav

            # 5. Replace audio track in MP4
            subprocess.run(
                [ffmpeg, "-y",
                 "-i", str(mp4_in), "-i", str(audio_src),
                 "-map", "0:v:0", "-map", "1:a:0",
                 "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                 "-shortest", str(mp4_out)],
                capture_output=True, timeout=60, check=True,
            )

            mp4_bytes = mp4_out.read_bytes()
            _log.info("SS2 audio done %s: mood=%s tts=%s size=%d",
                      rkey[-12:], mood, has_tts, len(mp4_bytes))

            # 6. Upload
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
                new_cid: str = r.json()["blob"]["ref"]["$link"]

            # ── Register soundCue vertex records + edges ──────────────────────
            try:
                import psycopg as _psycopg
                from datetime import datetime, timezone
                import secrets as _secrets

                repo = _REPO
                cut_vid = f"at://{repo}/com.etzhayyim.animeka.cut/{rkey}"
                now = datetime.now(tz=timezone.utc).isoformat()

                # Upload audio blobs
                bgm_cid = await _upload_audio_blob(bgm_wav) if bgm_wav.exists() else None
                sfx_cid = await _upload_audio_blob(sfx_wav) if sfx_wav.exists() else None
                narr_cid = await _upload_audio_blob(tts_wav) if has_tts and tts_wav.exists() else None

                _rw = await _psycopg.AsyncConnection.connect(_RW_URL, autocommit=True)
                try:
                    tracks = []
                    if bgm_cid:
                        tracks.append(("bgm", bgm_cid, f"{rkey}-bgm"))
                    if sfx_cid:
                        tracks.append(("sfx", sfx_cid, f"{rkey}-sfx"))
                    if narr_cid:
                        tracks.append(("narration", narr_cid, f"{rkey}-narr"))

                    for track_type, asset_cid, sc_rkey in tracks:
                        sc_vid = f"at://{repo}/com.etzhayyim.animeka.soundCue/{sc_rkey}"
                        # Upsert soundCue vertex
                        await _rw.execute(
                            "DELETE FROM vertex_animeka WHERE vertex_id = %s",
                            [sc_vid],
                        )
                        await _rw.execute(
                            """INSERT INTO vertex_animeka
                               (vertex_id, repo, rkey, collection, kind, owner_did,
                                cut_id, track_type, asset_cid, status, created_at)
                               VALUES (%s,%s,%s,'com.etzhayyim.animeka.soundCue','soundCue',%s,
                                       %s,%s,%s,'generated',%s)""",
                            [sc_vid, repo, sc_rkey, repo,
                             rkey, track_type, asset_cid, now],
                        )
                        # Edge: cut → soundCue
                        edge_id = f"edge-{sc_rkey}-{_secrets.token_hex(4)}"
                        await _rw.execute(
                            """INSERT INTO edge_cut_has_keyframe
                               (edge_id, src_vid, dst_vid, repo, cut_id, kind, layer_role, owner_did, created_at)
                               VALUES (%s,%s,%s,%s,%s,'soundCue',%s,%s,%s)""",
                            [edge_id, cut_vid, sc_vid, repo, rkey, track_type, repo, now],
                        )
                    _log.info("soundCue registered: %d tracks for %s", len(tracks), rkey[-12:])
                finally:
                    await _rw.close()
            except Exception as exc:
                _log.warning("soundCue register %s: %s", rkey[-12:], exc)

            return {"rkey": rkey, "new_output_cid": new_cid, "mood": mood, "has_tts": has_tts}

        except Exception as exc:
            _log.warning("SS2 audio %s: %s", rkey[-12:], exc)
            return {"rkey": rkey, "error": str(exc)[:150]}
        finally:
            for p in [mp4_in, bgm_wav, sfx_wav, tts_wav, mix_wav, mp4_out]:
                p.unlink(missing_ok=True)
            try: tmpdir.rmdir()
            except Exception: pass

    results = await asyncio.gather(*[_process_one(r) for r in cut_rows])
    _log.info("SS2 audio: processed %d cuts", len(results))
    return {"processed": list(results)}


# ── SS3: persist new output_cid to DB ────────────────────────────────────────

async def _ss3_persist(state: AudioState) -> dict[str, Any]:
    processed = state.get("processed") or []
    if not processed or state.get("error"):
        return {}

    successful = [p for p in processed if p.get("new_output_cid") and not p.get("error")]

    if _RW_URL and successful:
        try:
            import psycopg
            conn = await psycopg.AsyncConnection.connect(_RW_URL, autocommit=True)
            for p in successful:
                await conn.execute(
                    "UPDATE public.vertex_animeka SET output_cid = %s "
                    "WHERE rkey = %s AND collection = 'com.etzhayyim.animeka.cut'",
                    [p["new_output_cid"], p["rkey"]],
                )
            await conn.close()
            _log.info("SS3 audio: persisted %d cuts", len(successful))
        except Exception as exc:
            _log.warning("SS3 audio persist: %s", exc)

    mood_counts: dict[str, int] = {}
    for p in successful:
        m = p.get("mood", "?")
        mood_counts[m] = mood_counts.get(m, 0) + 1

    summary = {
        "total_processed": len(processed),
        "successful": len(successful),
        "failed": len(processed) - len(successful),
        "mood_distribution": mood_counts,
        "tts_cuts": sum(1 for p in successful if p.get("has_tts")),
    }
    return {"summary": summary}


# ── Routing ───────────────────────────────────────────────────────────────────

def _route_after_mood(state: AudioState) -> str:
    return END if (state.get("error") or not state.get("moods")) else "gen_audio"

def _route_after_audio(state: AudioState) -> str:
    return END if (state.get("error") or not state.get("processed")) else "persist"


# ── Graph assembly ────────────────────────────────────────────────────────────

def _build_graph() -> StateGraph:
    g = StateGraph(AudioState)
    g.add_node("fetch_cuts",  _ss0_fetch_cuts)
    g.add_node("infer_mood",  _ss1_infer_mood)
    g.add_node("gen_audio",   _ss2_gen_audio)
    g.add_node("persist",     _ss3_persist)
    g.add_edge(START, "fetch_cuts")
    g.add_edge("fetch_cuts", "infer_mood")
    g.add_conditional_edges("infer_mood", _route_after_mood, ["gen_audio", END])
    g.add_conditional_edges("gen_audio", _route_after_audio, ["persist", END])
    g.add_edge("persist", END)
    return g


GRAPH = _build_graph().compile(name="generate_audio")
