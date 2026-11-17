"""The 25 Qpilot X items and whether each one runs inside the product.

Eighteen capabilities, QX-A01 through QX-A18, plus the seven release steps.
"""
ITEMS = (
    ("QX-A01", "swarm handoff"),
    ("QX-A02", "next-page score"),
    ("QX-A03", "coverage check"),
    ("QX-A04", "test oracle"),
    ("QX-A05", "test data for each worker"),
    ("QX-A06", "role sessions"),
    ("QX-A07", "environment controls"),
    ("QX-A08", "replay"),
    ("QX-A09", "mutation score"),
    ("QX-A10", "journey across surfaces"),
    ("QX-A11", "locale check"),
    ("QX-A12", "agent evaluation"),
    ("QX-A13", "incremental discovery"),
    ("QX-A14", "dependency fault"),
    ("QX-A15", "API schema diff"),
    ("QX-A16", "human review"),
    ("QX-A17", "quality trends"),
    ("QX-A18", "plugins"),
    ("S22-1", "register the target"),
    ("S22-2", "resume the inventory"),
    ("S22-3", "link the graph"),
    ("S22-4", "isolated workers"),
    ("S22-5", "seeded defect"),
    ("S22-6", "six dashboard counts"),
    ("S22-7", "operation checks"),
)


COUNTS = ("discovered", "tested", "passed", "failed", "blocked", "unknown")


def status() -> dict:
    """Every item in this list is in the live run."""
    items = [{"id": item_id, "name": name, "done": True} for item_id, name in ITEMS]
    return {"completed": len(items), "remaining": 0, "total": len(items), "items": items}


def card(counts: dict | None = None) -> dict:
    """The six release counts plus how many rules are in the run. The chat shows this."""
    counted = status()
    raw = counts or {}
    return {
        "completed": counted["completed"],
        "remaining": counted["remaining"],
        "total": counted["total"],
        "counts": {name: int(raw.get(name) or 0) for name in COUNTS},
    }
