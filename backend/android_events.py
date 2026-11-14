"""Durable Android action events; input values and exception messages stay private."""
import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .safety import redact, secret_values


class Timeline:
    def __init__(self, root, case=None, phase="execution", secrets=()):
        self.root = Path(root) if root else None
        self.case = case or {}
        self.phase = phase
        self.secrets = list(set(secret_values()) | {value for value in secrets if value})
        self.started = time.monotonic()
        self.stream = None

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None

    def __del__(self):
        self.close()

    def emit(self, status, text, **details):
        if self.root is None:
            return
        record = {"id": uuid.uuid4().hex, "timestamp": time.time(), "worker": f"android-{os.getpid()}",
                  "elapsed": round(time.monotonic() - self.started, 2), "status": status, "text": text,
                  "phase": self.phase, "case_id": self.case.get("id", ""),
                  "case_title": self.case.get("title", ""), **details}
        if self.stream is None:
            self.root.mkdir(parents=True, exist_ok=True)
            self.stream = (self.root / f"events.android-{os.getpid()}.jsonl").open("a", encoding="utf-8")
        # Redact free text before encoding: a short numeric secret must not turn
        # JSON timestamps or elapsed values into invalid JSON.
        for key in ("text", "case_title", "expected", "observed", "selector", "url", "case_id"):
            if isinstance(record.get(key), str):
                record[key] = redact(record[key], self.secrets)
        self.stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.stream.flush()  # live readers see a complete line while the next action is still running

    @contextmanager
    def action(self, step, index=1, flow=""):
        action = step.get("action", "action")
        text = f"{flow + ': ' if flow else ''}step {index} {action}"
        # Even non-password fill values can contain private account data.
        if action == "fill":
            text += " (value hidden)"
        expected = "Configured assertion must hold" if action.startswith("assert_") else "Action completes"
        locator = step.get("locator") or {}
        target = {} if action == "fill" else {"selector": f"{locator.get('strategy', '')}: {locator.get('value', '')}"} if locator else {}
        self.emit("started", text, expected=expected, **target)
        try:
            yield
        except BaseException as error:
            self.emit("failed", text, expected=expected, observed=type(error).__name__, **target)
            raise
        else:
            self.emit("passed", text, expected=expected,
                      observed="Assertion verified" if action.startswith("assert_") else "Action completed", **target)


class LiveSteps(list):
    """Preserve the existing evidence list while publishing each verified UI step."""
    def __init__(self, timeline):
        super().__init__()
        self.timeline = timeline

    def append(self, item):
        super().append(item)
        self.timeline.emit("passed" if item.get("ok") else "failed", item.get("text", "UI step"))
