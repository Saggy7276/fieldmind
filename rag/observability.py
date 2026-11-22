"""
Local-only observability for FieldMind (the system is air-gapped, so nothing
is shipped to an external service).

  * one JSON line per request in logs/traces.jsonl: stage timings, retrieved
    chunk ids and scores, guardrail decisions, outcome
  * in-process metrics served at GET /metrics, as JSON or Prometheus text
    (?format=prom) for a local Prometheus/Grafana if the site runs one

Set FIELDMIND_LOG_TEXT=0 to keep question and answer text out of the trace log.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections import Counter, defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path(os.getenv("FIELDMIND_LOG_DIR", "logs"))
LOG_TEXT = os.getenv("FIELDMIND_LOG_TEXT", "1") != "0"
MAX_LOG_BYTES = 20 * 1024 * 1024


class Metrics:
    """Thread-safe counters and latency windows (last 1000 samples per stage)."""

    def __init__(self, window: int = 1000):
        self._lock = threading.Lock()
        self.counters: Counter[str] = Counter()
        self.latencies: dict[str, deque] = defaultdict(lambda: deque(maxlen=window))
        self.started = time.time()

    def inc(self, name: str, n: int = 1) -> None:
        with self._lock:
            self.counters[name] += n

    def observe(self, stage: str, ms: float) -> None:
        with self._lock:
            self.latencies[stage].append(ms)

    @staticmethod
    def _pct(values: list[float], p: float) -> float:
        if not values:
            return 0.0
        s = sorted(values)
        return s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))]

    def snapshot(self) -> dict:
        with self._lock:
            lat = {k: list(v) for k, v in self.latencies.items()}
            counters = dict(self.counters)
        return {
            "uptime_s": round(time.time() - self.started, 1),
            "counters": counters,
            "latency_ms": {
                k: {"n": len(v), "p50": round(self._pct(v, 50), 1), "p95": round(self._pct(v, 95), 1),
                    "max": round(max(v), 1)}
                for k, v in lat.items() if v
            },
        }

    def prometheus(self) -> str:
        snap = self.snapshot()
        lines = [f"fieldmind_uptime_seconds {snap['uptime_s']}"]
        for name, v in sorted(snap["counters"].items()):
            lines.append(f'fieldmind_events_total{{event="{name}"}} {v}')
        for stage, s in sorted(snap["latency_ms"].items()):
            for q in ("p50", "p95"):
                lines.append(f'fieldmind_latency_ms{{stage="{stage}",quantile="{q[1:]}"}} {s[q]}')
        return "\n".join(lines) + "\n"


METRICS = Metrics()
_write_lock = threading.Lock()


def _write(record: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / "traces.jsonl"
    with _write_lock:
        if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
            path.replace(path.with_suffix(".jsonl.1"))
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


class Trace:
    """One request. Use `with trace.span("retrieve"):` to time a stage."""

    def __init__(self, channel: str, question: str = ""):
        self.id = uuid.uuid4().hex[:12]
        self.t0 = time.perf_counter()
        self.record: dict = {
            "trace_id": self.id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "channel": channel,
            "spans_ms": {},
            "events": [],
        }
        if LOG_TEXT:
            self.record["question"] = question
        self._done = False
        METRICS.inc("requests")

    @contextmanager
    def span(self, name: str):
        t = time.perf_counter()
        try:
            yield
        finally:
            self.add_span(name, (time.perf_counter() - t) * 1000)

    def add_span(self, name: str, ms: float) -> None:
        self.record["spans_ms"][name] = round(ms, 1)
        METRICS.observe(name, ms)

    def since_start_ms(self) -> float:
        return (time.perf_counter() - self.t0) * 1000

    def set(self, **attrs) -> None:
        if not LOG_TEXT:
            attrs.pop("answer", None)
        self.record.update(attrs)

    def event(self, name: str, **attrs) -> None:
        self.record["events"].append({"name": name, "at_ms": round(self.since_start_ms(), 1), **attrs})
        METRICS.inc(name)

    def finish(self, outcome: str, **attrs) -> None:
        if self._done:
            return
        self._done = True
        self.set(outcome=outcome, **attrs)
        self.add_span("total", self.since_start_ms())
        METRICS.inc(f"outcome.{outcome}")
        _write(self.record)
