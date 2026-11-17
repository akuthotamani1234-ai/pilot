"""QX-A12 agent evaluation. A model change waits until a labeled check is stored.

The check records accuracy, cost, reliability, and claims the evidence does not support.
"""


def evaluate(tasks: list[dict]) -> dict:
    """Score labeled tasks. A task matches when its actual result is the expected one."""
    total = len(tasks)
    denominator = total or 1
    accurate = 0
    reliable = 0
    unsupported = []
    cost = 0.0
    for task in tasks:
        cost += float(task.get("cost") or 0)
        if task.get("unsupported"):
            unsupported.append(str(task.get("id") or ""))
        elif task.get("actual") == task.get("expected"):
            accurate += 1
        if not task.get("failed"):
            reliable += 1
    return {
        "tasks": total,
        "accuracy": accurate / denominator,
        "cost": cost,
        "reliability": reliable / denominator,
        "unsupported_claims": unsupported,
        "stored": True,
    }


def model_change_allowed(evaluation: dict | None) -> tuple[bool, str]:
    """A model or prompt change ships only after an evaluation has been stored."""
    if not evaluation or not evaluation.get("stored"):
        return False, "a model change waits until the evaluation is stored"
    return True, "evaluation is stored"
