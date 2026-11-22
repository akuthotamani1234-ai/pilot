"""Your testing objective: the plain-English instructions of a run, what they target and what became of them.

runs/<run>/objective.json is written when the run starts and updated by each stage:
  discovery   which pages matched your instructions (they are explored first; with QA_OBJECTIVE_FOCUS=1 only them
              and the pages they lead to)
  test design the plan for each instruction (navigation, preconditions, actions, test data, assertions, unknowns),
              or why it was not automated (no AI, not possible on this website, needs clarification, destructive)
  report      the outcome of each instruction's test, with its evidence
Nothing here invents a result: an instruction without an executed test stays 'not automated' with its reason.
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from pathlib import Path

FILE = "objective.json"
_lock = threading.Lock()

# words that say nothing about WHERE to test
STOP = set("""a an and are as at be by can check click do does each enter entered error errors every for from go
have i if in into is it its log login logged make my navigate of on open or page pages please report results
screenshot screenshots search see should test tests the their then there these this to try user using verify was
when whether which with works admin as also all any field fields name names id ids value values that them new
""".split())
# a request that would change or destroy data: never done from an instruction (staging + explicit permission only)
DESTRUCTIVE = re.compile(r"\b(delete|deleting|remove|removing|erase|purge|wipe|drop|terminate|deactivate|"
                         r"pay|payment|purchase|buy|transfer|place (an )?order|checkout|reset (the )?password)\b", re.I)


def keywords(text: str) -> list[str]:
    words = re.findall(r"[a-z][a-z0-9]{2,}", (text or "").lower())
    out = []
    for w in words:
        if w not in STOP and w not in out:
            out.append(w)
    return out[:20]


def destructive(text: str) -> str:
    """The destructive words of an instruction ('' = none)."""
    m = DESTRUCTIVE.search(text or "")
    return m.group(0) if m else ""


class Objective:
    """The instructions of one run and the words that point to where they are tested."""

    def __init__(self, instructions: list[dict], requirements: str = ""):
        self.instructions = [dict(i) for i in instructions if (i.get("text") or "").strip()]
        self.requirements = (requirements or "").strip()
        words: list[str] = []
        for i in self.instructions:
            i.setdefault("keywords", keywords(i["text"]))
            words += [w for w in i["keywords"] if w not in words]
        for w in keywords(self.requirements):
            if w not in words:
                words.append(w)
        self.words = words

    def __bool__(self) -> bool:
        return bool(self.words)

    def score(self, url: str = "", text: str = "") -> int:
        """How strongly this link / page matches the objective: each word the visible text names counts 2, a word only
        in the address path counts 1 (every page of /pim/ names 'pim'; 'Employee List' says what the page IS).
        0 = no match."""
        if not self.words:
            return 0
        from urllib.parse import urlparse
        path = urlparse(url or "").path.lower()
        parts = set(re.findall(r"[a-z][a-z0-9]{2,}", path))
        label = set(re.findall(r"[a-z][a-z0-9]{2,}", (text or "").lower()))

        def names(w: str, words: set[str]) -> bool:
            return w in words or any(p.startswith(w) or w.startswith(p) for p in words if len(p) >= 4)
        hits = 0
        for w in self.words:
            hits += 2 if names(w, label) else 1 if names(w, parts) else 0
        return hits

    def matches(self, url: str = "", text: str = "") -> bool:
        return self.score(url, text) > 0


def _path(run_dir) -> Path:
    return Path(run_dir) / FILE


def read(run_dir) -> dict:
    try:
        data = json.loads(_path(run_dir).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(run_dir, data: dict) -> None:
    from .finalization import folder_is_linked
    path = _path(run_dir)
    if folder_is_linked(path.parent) or path.is_symlink():
        return
    tmp = path.with_name(f".objective.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def update(run_dir, **fields) -> dict:
    with _lock:
        data = read(run_dir)
        data.update(fields)
        _write(run_dir, data)
        return data


def update_instruction(run_dir, instruction_id: str, **fields) -> None:
    with _lock:
        data = read(run_dir)
        for item in data.get("instructions", []):
            if item.get("id") == instruction_id:
                item.update(fields)
        _write(run_dir, data)


def start(run_dir, site_key: str, requirements: str = "", ai: bool = False) -> Objective:
    """Write objective.json for a new run (or keep a resumed one) and return the Objective."""
    from .my_tests import load
    saved = load(site_key) if site_key else []
    instructions = [{"id": t["id"], "text": t["text"]} for t in saved]
    obj = Objective(instructions, requirements)
    data = read(run_dir)
    if not data:
        data = {"instructions": [{"id": i["id"], "text": i["text"], "keywords": i["keywords"],
                                  "destructive": destructive(i["text"]),
                                  "status": "waiting for discovery", "targets": []} for i in obj.instructions],
                "requirements": obj.requirements, "keywords": obj.words, "ai": bool(ai),
                "focus": os.environ.get("QA_OBJECTIVE_FOCUS") == "1"}
        if obj or obj.requirements:
            with _lock:
                _write(run_dir, data)
    return obj


def record_targets(run_dir, obj: Objective, pages: list[dict]) -> None:
    """After discovery: which explored pages match each instruction (by address or title)."""
    data = read(run_dir)
    if not data:
        return
    for item in data.get("instructions", []):
        single = Objective([{"id": item["id"], "text": item["text"]}])
        hits = [p["url"] for p in pages if single.score(p.get("url", ""), p.get("title", "")) > 0]
        item["targets"] = hits[:20]
        if item.get("status") == "waiting for discovery":
            item["status"] = "targets found" if hits else "no matching page found"
    data["pages_matching"] = sum(1 for p in pages if obj.matches(p.get("url", ""), p.get("title", "")))
    with _lock:
        _write(run_dir, data)


def outcomes(run_dir, cases: list[dict], results: list[dict]) -> list[dict]:
    """Each instruction's result from what really ran: the test written for it, its outcome and evidence.
    An instruction whose test did not run keeps its reason; nothing is reported as passed without an executed test."""
    data = read(run_dir)
    by_test = {}
    for r in results or []:
        by_test.setdefault(r.get("test"), r)
    items = []
    for item in data.get("instructions", []):
        case = next((c for c in cases or [] if c.get("my_test") == item["id"]), None)
        tests = (case or {}).get("tests") or []
        ran = [by_test[t] for t in tests if t in by_test]
        if case is None:
            status, outcome = item.get("status") or "not designed", "not run"
        elif case.get("skip_reason"):
            status, outcome = case["skip_reason"], "not run"
        elif not ran:
            status, outcome = "automated, but its test did not run", "not run"
        else:
            outs = [r.get("outcome") for r in ran]
            outcome = ("failed" if "failed" in outs or "error" in outs else
                       "passed" if outs and all(o == "passed" for o in outs) else outs[0] or "unknown")
            status = "executed"
        evidence = []
        for r in ran:
            for key in ("screenshot", "trace"):
                if r.get(key):
                    evidence.append(str(r[key]))
        row = {"id": item["id"], "instruction": item["text"], "status": status, "outcome": outcome,
               "targets": item.get("targets", []), "plan": item.get("plan") or {}, "tests": tests,
               "assertions_checked": sum(int(r.get("checks") or 0) for r in ran),
               "error": next((str(r.get("error") or "")[:400] for r in ran if r.get("error")), ""),
               "evidence": evidence[:6]}
        items.append(row)
    if items:
        update(run_dir, results=[{k: v for k, v in i.items() if k not in ("plan",)} for i in items])
    return items
