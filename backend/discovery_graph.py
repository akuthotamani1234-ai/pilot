"""Gate A discovery graph with explicit provenance on every node and edge.

Built from the post-crawl app map (same inventory as registry.json). Never marks
Gate A complete — a persisted graph is evidence of structure, not full-surface proof.
"""
from __future__ import annotations

import json
from pathlib import Path

SCHEMA_VERSION = 1


def build_graph(app_map: list[dict], crawl: dict | None = None) -> dict:
    """Nodes/edges with provenance derived from discovered pages and controls."""
    from .registry import build

    reg = build(app_map or [], crawl or {})
    nodes = []
    for pid, page in (reg.get("pages") or {}).items():
        nodes.append({
            "id": pid,
            "kind": "page",
            "pattern": page.get("pattern"),
            "auth": bool(page.get("auth")),
            "page_type": page.get("type") or "",
            "provenance": {
                "source": "discovery",
                "urls": list(page.get("urls") or [])[:8],
                "slugs": list(page.get("slugs") or [])[:8],
                "http_status": page.get("status"),
                "error": page.get("error") or "",
                "needs_permission": bool(page.get("needs_permission")),
            },
        })
    for fid, feat in (reg.get("features") or {}).items():
        nodes.append({
            "id": fid,
            "kind": "feature",
            "feature_kind": feat.get("kind") or "",
            "provenance": {
                "source": "discovery",
                "pages": list(feat.get("pages") or []),
                "evidence": feat.get("evidence") or feat.get("name") or feat.get("selector") or "",
                "status": feat.get("status") or "inspected",
            },
        })
    edges = []
    for edge in reg.get("edges") or []:
        edges.append({
            "from": edge.get("from"),
            "to": edge.get("to"),
            "to_url": edge.get("to_url") or "",
            "via": edge.get("via") or "",
            "label": edge.get("label") or "",
            "provenance": {
                "source": "discovery",
                "via": edge.get("via") or "",
                "label": edge.get("label") or "",
            },
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "gate_a_complete": False,
        "nodes": nodes,
        "edges": edges,
        "counts": {
            "nodes": len(nodes),
            "edges": len(edges),
            "pages": len(reg.get("pages") or {}),
            "features": len(reg.get("features") or {}),
        },
        "note": "Persisted structure with provenance. Not proof that every template, state, iframe, or API was covered.",
    }


def write_graph(run_dir: str | Path, app_map: list[dict], crawl: dict | None = None) -> dict:
    """Write discovery_graph.json beside other run artifacts."""
    from .surface_coverage import summarize_surfaces

    path = Path(run_dir)
    graph = build_graph(app_map, crawl)
    graph["surfaces"] = summarize_surfaces(app_map, crawl)
    from .finalization import folder_is_linked, write_text_unless_linked
    if not folder_is_linked(path):
        path.mkdir(parents=True, exist_ok=True)
        write_text_unless_linked(path, "discovery_graph.json", json.dumps(graph, indent=2))
        write_text_unless_linked(path, "surface_coverage.json", json.dumps(graph["surfaces"], indent=2))
    return graph
