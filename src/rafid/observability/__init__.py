"""Structured logging with a trace id, so one turn is one query.

Deliberately tiny: a dict-per-event logger with a contextvar trace id. Every
seam in the pipeline logs through this, and the cost meter (phase 18) attaches
its records to the same trace.
"""

from __future__ import annotations

import json
import sys
import uuid
from contextvars import ContextVar

_trace: ContextVar[str] = ContextVar("trace_id", default="")
RECORDS: list[dict] = []  # in-memory sink; the notebook reads it
EMIT = False  # set True to also print each event as it happens


def new_trace_id() -> str:
    tid = f"trace_{uuid.uuid4().hex[:10]}"
    _trace.set(tid)
    return tid


def current_trace_id() -> str:
    return _trace.get()


class _Logger:
    def __init__(self, name: str) -> None:
        self.name = name

    def _emit(self, level: str, event: str, **fields) -> None:
        record = {"logger": self.name, "level": level, "event": event,
                  "trace_id": current_trace_id(), **fields}
        RECORDS.append(record)
        if EMIT:
            print(json.dumps(record, ensure_ascii=False), file=sys.stderr)

    def info(self, event: str, **fields) -> None:
        self._emit("info", event, **fields)

    def warning(self, event: str, **fields) -> None:
        self._emit("warning", event, **fields)

    def error(self, event: str, **fields) -> None:
        self._emit("error", event, **fields)


def get_logger(name: str) -> _Logger:
    return _Logger(name)


def records(event: str | None = None) -> list[dict]:
    return [r for r in RECORDS if event is None or r["event"] == event]


def clear() -> None:
    RECORDS.clear()
