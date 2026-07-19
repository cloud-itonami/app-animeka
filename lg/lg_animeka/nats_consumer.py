"""NATS JetStream pull consumer for lg-animeka.

Subject hierarchy mirrors NSID directly:
  com.etzhayyim.animeka.{graph_name}

Stream LG_DISPATCH is auto-created on startup if absent.

Trigger from anywhere:
  nats pub com.etzhayyim.animeka.autopilot '{}'
  nats pub com.etzhayyim.animeka.cutRunner '{"cut_id":"..."}'

MCP tool can call nats_publish() to enqueue work.
LLM can inspect state via nats_status() which queries stream/consumer info.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

_log = logging.getLogger(__name__)

_NATS_URL = os.environ.get("NATS_URL", "nats://nats.nats.svc.cluster.local:4222")
_NATS_ENABLED = os.environ.get("LG_NATS_ENABLED", "true").lower() not in ("false", "0", "no")
_STREAM_NAME = os.environ.get("LG_NATS_STREAM", "LG_DISPATCH")
_STREAM_SUBJECTS = [f"com.etzhayyim.apps.>"]
_ACK_WAIT_SEC = int(os.environ.get("LG_NATS_ACK_WAIT_SEC", "150"))
_MAX_DELIVER = int(os.environ.get("LG_NATS_MAX_DELIVER", "3"))
_FETCH_TIMEOUT_SEC = 5


def _consumer_name(assistant_id: str) -> str:
    return f"lg-animeka-{assistant_id.replace('_', '-')}"


_ASSISTANT_TO_NSID_TAIL: dict[str, str] = {
    "autopilot":       "autopilot",
    "cut_runner":      "cutRunner",
    "auto_trace_cut":  "autoTraceCut",
    "breakdown_scene": "breakdownScene",
}


def _subject(assistant_id: str) -> str:
    tail = _ASSISTANT_TO_NSID_TAIL.get(assistant_id, assistant_id)
    return f"com.etzhayyim.animeka.{tail}"


async def _ensure_stream(js: Any) -> None:
    """Create LG_DISPATCH stream if it does not exist."""
    import nats.js.api as jsapi  # type: ignore[import-not-found]
    try:
        await js.find_stream(_STREAM_SUBJECTS[0].rstrip(">").rstrip("."))
        _log.debug("stream %s already exists", _STREAM_NAME)
    except Exception:
        pass
    try:
        await js.add_stream(jsapi.StreamConfig(
            name=_STREAM_NAME,
            subjects=_STREAM_SUBJECTS,
            retention=jsapi.RetentionPolicy.WORK_QUEUE,
            storage=jsapi.StorageType.MEMORY,
            max_age=3600,            # 1 hour — unprocessed msgs expire
            max_msg_size=1_048_576,  # 1 MiB
            discard=jsapi.DiscardPolicy.OLD,
            num_replicas=1,
        ))
        _log.info("created stream %s subjects=%s", _STREAM_NAME, _STREAM_SUBJECTS)
    except Exception as exc:
        # already exists (race) is fine
        _log.debug("add_stream %s: %s (likely already exists)", _STREAM_NAME, exc)


async def _run_consumer(
    js: Any,
    assistant_id: str,
    graph: Any,
    stop_event: asyncio.Event,
) -> None:
    """Pull-consume loop for one assistant_id.

    Fetch 1 message at a time, invoke graph, ack on success / nak on failure.
    max-in-flight=1 ensures no concurrent runs of the same graph.
    """
    import nats.errors as nerrors  # type: ignore[import-not-found]
    import nats.js.api as jsapi   # type: ignore[import-not-found]

    subject = _subject(assistant_id)
    durable = _consumer_name(assistant_id)

    # Ensure durable pull consumer exists
    try:
        await js.add_consumer(_STREAM_NAME, jsapi.ConsumerConfig(
            durable_name=durable,
            filter_subject=subject,
            ack_policy=jsapi.AckPolicy.EXPLICIT,
            ack_wait=_ACK_WAIT_SEC,
            max_deliver=_MAX_DELIVER,
            deliver_policy=jsapi.DeliverPolicy.ALL,
        ))
        _log.info("consumer %s ready subject=%s", durable, subject)
    except Exception as exc:
        _log.debug("add_consumer %s: %s (likely exists)", durable, exc)

    sub = await js.pull_subscribe(subject, durable, stream=_STREAM_NAME)
    _log.info("nats consumer started assistant=%s subject=%s", assistant_id, subject)

    while not stop_event.is_set():
        try:
            msgs = await sub.fetch(1, timeout=_FETCH_TIMEOUT_SEC)
        except nerrors.TimeoutError:
            continue
        except Exception as exc:
            _log.warning("fetch error assistant=%s: %s", assistant_id, exc)
            await asyncio.sleep(2)
            continue

        for msg in msgs:
            try:
                payload = json.loads(msg.data) if msg.data else {}
            except json.JSONDecodeError:
                payload = {}

            _log.info("nats dispatch assistant=%s subject=%s payload=%s",
                      assistant_id, subject, list(payload.keys()))
            started = time.monotonic()
            try:
                result = await graph.ainvoke(payload)
                elapsed = int((time.monotonic() - started) * 1000)
                _log.info("nats dispatch ok assistant=%s latencyMs=%d ok=%s",
                          assistant_id, elapsed, result.get("ok") if isinstance(result, dict) else True)
                await msg.ack()
            except Exception as exc:
                elapsed = int((time.monotonic() - started) * 1000)
                _log.error("nats dispatch failed assistant=%s latencyMs=%d err=%s",
                           assistant_id, elapsed, exc)
                # nak with 30s delay → JetStream redelivers
                try:
                    await msg.nak(delay=30)
                except Exception:
                    pass

    try:
        await sub.unsubscribe()
    except Exception:
        pass
    _log.info("nats consumer stopped assistant=%s", assistant_id)


class NatsConsumerManager:
    """Manages NATS JetStream consumers for a set of graphs.

    Usage (in FastAPI lifespan):
        mgr = NatsConsumerManager({"autopilot": graph, ...})
        await mgr.start()
        ...
        await mgr.stop()

    Status (for MCP/LLM):
        info = await mgr.status()
    """

    def __init__(self, graphs: dict[str, Any]) -> None:
        self._graphs = graphs
        self._nc: Any = None
        self._js: Any = None
        self._tasks: list[asyncio.Task] = []
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if not _NATS_ENABLED:
            _log.info("NATS consumer disabled (LG_NATS_ENABLED=false)")
            return
        try:
            import nats as _nats  # type: ignore[import-not-found]
            self._nc = await _nats.connect(
                _NATS_URL,
                name="lg-animeka",
                connect_timeout=5,
                reconnect_time_wait=2,
                max_reconnect_attempts=10,
            )
            self._js = self._nc.jetstream()
            await _ensure_stream(self._js)
            _log.info("NATS connected url=%s", _NATS_URL)

            for assistant_id, graph in self._graphs.items():
                t = asyncio.create_task(
                    _run_consumer(self._js, assistant_id, graph, self._stop),
                    name=f"nats-consumer-{assistant_id}",
                )
                self._tasks.append(t)
            _log.info("started %d NATS consumers", len(self._tasks))
        except Exception as exc:
            _log.error("NATS startup failed (continuing without): %s", exc)

    async def stop(self) -> None:
        self._stop.set()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._nc:
            try:
                await self._nc.drain()
            except Exception:
                pass
        _log.info("NATS consumers stopped")

    async def status(self) -> dict[str, Any]:
        if not self._nc or self._nc.is_closed:
            return {"enabled": False, "connected": False}
        consumers: list[dict[str, Any]] = []
        if self._js:
            for assistant_id in self._graphs:
                try:
                    info = await self._js.consumer_info(
                        _STREAM_NAME, _consumer_name(assistant_id)
                    )
                    consumers.append({
                        "assistant_id": assistant_id,
                        "subject": _subject(assistant_id),
                        "pending": info.num_pending,
                        "waiting": info.num_waiting,
                        "redelivered": info.num_redelivered,
                        "ack_floor": info.delivered.stream_seq,
                    })
                except Exception:
                    consumers.append({"assistant_id": assistant_id, "error": "not found"})
        stream_msgs = 0
        try:
            si = await self._js.stream_info(_STREAM_NAME)
            stream_msgs = si.state.messages
        except Exception:
            pass
        return {
            "enabled": True,
            "connected": self._nc.is_connected,
            "stream": _STREAM_NAME,
            "stream_messages": stream_msgs,
            "consumers": consumers,
        }

    async def publish(self, assistant_id: str, payload: dict[str, Any] = {}) -> dict[str, Any]:
        """Enqueue a graph invocation. Used by MCP tools and /nats/publish endpoint."""
        if not self._js:
            return {"ok": False, "error": "NATS not connected"}
        subject = _subject(assistant_id)
        try:
            ack = await self._js.publish(subject, json.dumps(payload).encode())
            return {"ok": True, "subject": subject, "seq": ack.seq, "stream": ack.stream}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:300]}


# Graphs that should have a NATS consumer (subset of all GRAPHS)
# — only graphs that make sense to trigger via message queue
CONSUMER_GRAPHS = {
    "autopilot",
    "cut_runner",
    "auto_trace_cut",
    "breakdown_scene",
}
