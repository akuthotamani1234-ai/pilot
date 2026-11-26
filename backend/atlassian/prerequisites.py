"""Prerequisites between requirement test cases: which test case needs which other one first (a persistent graph).

A test case may need an application state another requirement establishes ("Given products are in the cart" needs the
case that adds a product; "the order appears in the order history" needs the case that places it). The graph is built
from, in order of trust:

  link      a Jira issue link of the requirement: "is blocked by", "depends on", "requires" (explicit, by a person)
  declared  the case's own preconditions / "Given ..." matched to a POSITIVE case of another requirement whose title and
            expected result say they establish it (word overlap - nothing about any website or domain is assumed)
  ai        optional: the AI reads the cases (id, title, preconditions, expected - small batches) and names the ones a
            case needs; only real case ids are kept, each with its reason
  manual    added or removed by a person (kept over every inferred one)

Login is not an edge: the engine logs in with the test account before every test that needs it.

At execution (bridge.plan): every prerequisite of a selected case is added to the run even when its requirement was
not selected (marked as an added prerequisite, never as a selected requirement), and the dependent test first does the
prerequisite's steps itself (each test keeps its own browser state: tests stay isolated and may run in parallel). After
the run (bridge.collect): a dependent test that did not pass while one of its prerequisites failed is Blocked, naming
that prerequisite - not a failure of the feature it tests. Cycles are reported and never followed.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS req_dependencies (
    tenant_id TEXT NOT NULL, case_id TEXT NOT NULL, requires_id TEXT NOT NULL, source TEXT NOT NULL,
    reason TEXT NOT NULL, at TEXT NOT NULL, removed INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, case_id, requires_id));
"""
# Jira link wording (the inward / outward text of the link type) that says "this one needs that one first"
NEEDS_LINK = re.compile(r"^(is blocked by|depends on|requires|is dependent on|has to be done after|needs)$", re.I)
LOGIN = re.compile(r"\b(log(?:ged)? ?in|sign(?:ed)? ?in|authenticat\w*|a test account|credentials?)\b", re.I)
STOP = set("""a an the and or of to in on at for with by from is are be been being it its this that these those as
user users shopper customer person he she they we you i can should must will shall may has have had having when then
given there their any all each every some page screen app application website site open shows show shown displayed
see visible available able valid one two""".split())
MAX_AI_BATCH = 30


def connect_schema(db) -> None:
    db.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _words(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z][a-z0-9]+", (text or "").lower()):
        if w in STOP or len(w) < 3:
            continue
        for suffix in ("ies", "es", "s", "ed", "ing"):  # (a light stem: products/product, added/add)
            if w.endswith(suffix) and len(w) - len(suffix) >= 3:
                w = w[: -len(suffix)] + ("y" if suffix == "ies" else "")
                break
        out.add(w)
    return out


def _preconditions(case: dict) -> list[str]:
    pre = [str(p) for p in case.get("preconditions") or [] if str(p).strip()]
    pre += [str(s)[6:] for s in case.get("steps") or [] if str(s).lower().startswith("given ")]
    return [p for p in pre if not (LOGIN.search(p) and len(_words(LOGIN.sub(" ", p))) < 2)]  # (login: the engine)


def _provides(case: dict) -> set[str]:
    return _words(" ".join([str(case.get("title") or ""), str(case.get("expected") or "")]))


def infer(cases: list[dict], sources: dict[str, dict]) -> list[dict]:
    """Edges {case_id, requires_id, source, reason} from Jira links and declared preconditions (no AI)."""
    by_req: dict[str, list[dict]] = {}
    for c in cases:
        by_req.setdefault(c["requirement_id"], []).append(c)
    positive = lambda cs: [c for c in cs if c.get("kind") == "positive"] or cs  # noqa: E731
    edges: list[dict] = []
    for c in cases:  # (1) the requirement's Jira links: every case of it needs the linked requirement's positive cases
        content = (sources.get(c["requirement_id"]) or {}).get("content") or {}
        for link in content.get("links") or []:
            if NEEDS_LINK.match(str(link.get("type") or "").strip()) and link.get("key") in by_req \
                    and link["key"] != c["requirement_id"]:
                for p in positive(by_req[link["key"]]):
                    edges.append({"case_id": c["id"], "requires_id": p["id"], "source": "link",
                                  "reason": f"{c['requirement_id']} {link['type']} {link['key']} (Jira link)"})
    for c in cases:  # (2) a declared precondition another requirement's positive case establishes
        for pre in _preconditions(c):
            want = _words(pre)
            if len(want) < 2:
                continue
            best, score = None, 0.0
            for other in cases:
                if other["requirement_id"] == c["requirement_id"] or other.get("kind") != "positive":
                    continue
                got = want & _provides(other)
                s = len(got) / len(want)
                if len(got) >= 2 and s >= 0.6 and s > score:
                    best, score = other, s
            if best:
                edges.append({"case_id": c["id"], "requires_id": best["id"], "source": "declared",
                              "reason": f"precondition '{pre[:120]}' is what {best['id']} establishes "
                                        f"({round(100 * score)}% of its words)"})
    return _unique(edges)


def ai_edges(cases: list[dict]) -> tuple[list[dict], str]:
    """Edges the AI names (small batches; unknown ids dropped). Returns (edges, note)."""
    from pydantic import BaseModel, Field

    from ..llm import LLMError, ask_structured, llm_enabled

    class Need(BaseModel):
        case: str = Field(max_length=60)
        requires: str = Field(max_length=60)
        reason: str = Field(min_length=3, max_length=200)

    if not llm_enabled():
        return [], "no AI is configured: only Jira links and declared preconditions were used"
    ids = {c["id"] for c in cases}
    out, notes = [], []
    rows = [{"id": c["id"], "requirement": c["requirement_id"], "title": c.get("title"),
             "preconditions": c.get("preconditions") or [], "steps": (c.get("steps") or [])[:6],
             "expected": str(c.get("expected") or "")[:300]} for c in cases]
    for i in range(0, len(rows), MAX_AI_BATCH):
        batch = rows[i:i + MAX_AI_BATCH]
        prompt = ("These are approved test cases of one application. For each case, name the OTHER cases that must "
                  "be done first because they create the application state it starts from (e.g. something must "
                  "exist, be selected, submitted or created first). Logging in is NOT a prerequisite (it is handled "
                  "separately). Only name a prerequisite when the case clearly cannot start without it. Use only the "
                  "ids given. Return a JSON array of {\"case\": id, \"requires\": id, \"reason\": why}.\n\n"
                  + json.dumps(batch, indent=1))
        try:
            needs = ask_structured(prompt, list[Need], agent="requirements", page="prerequisites")
        except (LLMError, ValueError) as error:
            notes.append(f"the AI could not plan batch {i // MAX_AI_BATCH + 1}: {str(error)[:120]}")
            continue
        for n in needs:
            if n.case in ids and n.requires in ids and n.case != n.requires:
                out.append({"case_id": n.case, "requires_id": n.requires, "source": "ai", "reason": n.reason})
    return _unique(out), "; ".join(notes)


def _unique(edges: list[dict]) -> list[dict]:
    seen, out = set(), []
    for e in edges:
        k = (e["case_id"], e["requires_id"])
        if k not in seen and e["case_id"] != e["requires_id"]:
            seen.add(k)
            out.append(e)
    return out


def save(db, tenant: str, edges: list[dict], replace: tuple[str, ...] = ("link", "declared")) -> None:
    """Replace the inferred edges of the given sources (an AI plan also replaces 'ai'); a person's manual edges and
    removals are always kept."""
    with db:
        for source in replace:
            db.execute("DELETE FROM req_dependencies WHERE tenant_id = ? AND source = ?", (tenant, source))
        kept = {(r["case_id"], r["requires_id"]) for r in db.execute(
            "SELECT case_id, requires_id FROM req_dependencies WHERE tenant_id = ?", (tenant,))}
        for e in edges:
            if (e["case_id"], e["requires_id"]) in kept:
                continue
            db.execute("INSERT OR REPLACE INTO req_dependencies (tenant_id, case_id, requires_id, source, reason, at,"
                       " removed) VALUES (?, ?, ?, ?, ?, ?, 0)",
                       (tenant, e["case_id"], e["requires_id"], e["source"], e["reason"][:300], _now()))


def set_manual(db, tenant: str, case_id: str, requires_id: str, present: bool, reason: str = "") -> None:
    """A person adds (present) or removes an edge; a removal also hides an inferred edge from later plans."""
    if case_id == requires_id:
        raise ValueError("a test case cannot be its own prerequisite")
    with db:
        db.execute("INSERT OR REPLACE INTO req_dependencies (tenant_id, case_id, requires_id, source, reason, at, "
                   "removed) VALUES (?, ?, ?, 'manual', ?, ?, ?)",
                   (tenant, case_id, requires_id, (reason or ("added" if present else "removed") + " by a person")[:300],
                    _now(), 0 if present else 1))


def edges(db, tenant: str) -> list[dict]:
    rows = db.execute("SELECT case_id, requires_id, source, reason, at FROM req_dependencies WHERE tenant_id = ? "
                      "AND removed = 0 ORDER BY case_id, requires_id", (tenant,))
    return [dict(r) for r in rows]


def cycles(all_edges: list[dict]) -> list[list[str]]:
    """Every dependency cycle (as a list of case ids), found by depth-first search."""
    graph: dict[str, list[str]] = {}
    for e in all_edges:
        graph.setdefault(e["case_id"], []).append(e["requires_id"])
    found, state, stack = [], {}, []

    def visit(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for nxt in graph.get(node, []):
            if state.get(nxt) == 1:
                cyc = stack[stack.index(nxt):] + [nxt]
                if sorted(cyc[:-1]) not in [sorted(c[:-1]) for c in found]:
                    found.append(cyc)
            elif not state.get(nxt):
                visit(nxt)
        stack.pop()
        state[node] = 2

    for n in list(graph):
        if not state.get(n):
            visit(n)
    return found


def closure(selected: list[str], all_edges: list[dict], runnable: set[str]) -> dict:
    """What a run of `selected` needs: {order, added, requires: {case: [its prerequisites]}, skipped, cycles}.
    Edges inside a cycle are not followed; a prerequisite that cannot run (not approved / blocked / stale) is listed
    in `skipped` with its dependent (the dependent then runs without it and says so)."""
    in_cycle = {n for c in cycles(all_edges) for n in c}
    graph: dict[str, list[dict]] = {}
    for e in all_edges:
        if not (e["case_id"] in in_cycle and e["requires_id"] in in_cycle):
            graph.setdefault(e["case_id"], []).append(e)
    order, requires, skipped, seen = [], {}, [], set()

    def walk(node: str) -> None:
        if node in seen:
            return
        seen.add(node)
        for e in graph.get(node, []):
            if e["requires_id"] not in runnable:
                skipped.append({"case": node, "requires": e["requires_id"], "reason": e["reason"]})
                continue
            requires.setdefault(node, []).append(e["requires_id"])
            walk(e["requires_id"])
        order.append(node)

    for s in selected:
        walk(s)
    return {"order": order, "added": [n for n in order if n not in selected], "requires": requires,
            "skipped": skipped, "cycles": list(cycles(all_edges))}


def all_requirements_of(case_id: str, requires: dict[str, list[str]]) -> list[str]:
    """Every prerequisite of a case, transitively, in the order they must be done (deepest first)."""
    out: list[str] = []

    def walk(n: str) -> None:
        for r in requires.get(n, []):
            if r not in out:
                walk(r)
                out.append(r)
    walk(case_id)
    return out
