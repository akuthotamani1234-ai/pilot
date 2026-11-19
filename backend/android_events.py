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
            from .finalization import folder_is_linked
            dest = self.root / f"events.android-{os.getpid()}.jsonl"
            if folder_is_linked(self.root) or dest.is_symlink():
                return
            if not self.root.exists():
                self.root.mkdir(parents=True, exist_ok=True)
            if folder_is_linked(self.root) or dest.is_symlink() or not self.root.is_dir():
                return
            self.stream = dest.open("a", encoding="utf-8")
        # Redact free text before encoding: a short numeric secret must not turn
        # JSON timestamps or elapsed values into invalid JSON.
        for key in ("text", "case_title", "expected", "observed", "selector", "url", "case_id"):
            if isinstance(record.get(key), str):
                record[key] = redact(record[key], self.secrets)
        self.stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.stream.flush()  # live readers see a complete line while the next action is still running

    @staticmethod
    def _selector(step):
        """Prefer resource_id in the evidence timeline; hide fill values."""
        action = step.get("action", "action")
        if action == "fill":
            locator = step.get("locator") or {}
            strategy = locator.get("strategy") or ""
            # Record durable strategy without the typed value.
            return {"selector": f"{strategy}: (value hidden)"} if strategy else {}
        locator = step.get("locator") or {}
        if not locator:
            return {}
        strategy = locator.get("strategy") or ""
        value = locator.get("value") or ""
        return {"selector": f"{strategy}: {value}", "locator_strategy": strategy}

    @contextmanager
    def action(self, step, index=1, flow=""):
        action = step.get("action", "action")
        text = f"{flow + ': ' if flow else ''}step {index} {action}"
        # Even non-password fill values can contain private account data.
        if action == "fill":
            text += " (value hidden)"
        if action.startswith("assert_"):
            expected = step.get("value") or "Configured assertion must hold"
        elif action == "tap":
            expected = "Control responds; follow-up oracle decides success"
        elif action == "fill":
            expected = "Input retains the supplied value"
        elif action == "select":
            expected = "Selected value is retained"
        else:
            expected = "Action completes"
        target = self._selector(step)
        self.emit("started", text, expected=str(expected)[:200], **target)
        try:
            yield
        except BaseException as error:
            self.emit("failed", text, expected=str(expected)[:200], observed=type(error).__name__, **target)
            raise
        else:
            observed = ("Assertion verified" if action.startswith("assert_")
                        else "Value retained" if action in ("fill", "select")
                        else "Action completed")
            self.emit("passed", text, expected=str(expected)[:200], observed=observed, **target)


class LiveSteps(list):
    """Preserve the existing evidence list while publishing each verified UI step."""
    def __init__(self, timeline):
        super().__init__()
        self.timeline = timeline

    def append(self, item):
        super().append(item)
        self.timeline.emit("passed" if item.get("ok") else "failed", item.get("text", "UI step"))
