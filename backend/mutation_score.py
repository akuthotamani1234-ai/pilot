"""QX-A09 mutation score. Planted defects show whether Qpilot caught them.

A miss is a defect in Qpilot. A report that names a defect that was not planted
is a false report. The score does not hide a miss.
"""


def score_planted(planted: list[dict], reported: list[str]) -> dict:
    """Compare planted defect ids with the ids Qpilot reported."""
    planted_ids = [str(row.get("id") or "") for row in planted if row.get("id")]
    planted_set = set(planted_ids)
    reported_ids = [str(item) for item in reported]
    caught = [item for item in planted_ids if item in reported_ids]
    missed = [item for item in planted_ids if item not in reported_ids]
    false_reports = [item for item in reported_ids if item not in planted_set]
    return {
        "caught": caught,
        "missed": missed,
        "false_reports": false_reports,
        "qpilot_defects": [f"missed planted defect {item}" for item in missed],
    }
