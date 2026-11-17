"""The Qpilot X rules recorded for one run.

The listing sample is left as the crawl already chose it. These records are the
other decisions: the next-page score, coverage, sessions, and the gates that
stay closed on production.
"""
from .agent_eval import model_change_allowed
from .dependency_fault import inject_fault
from .env_controls import CONTROLS, action_still_blocked, enable_control
from .explore_score import rank_candidates
from .locale_check import keep_sample
from .plugins import LOCKS
from .replay_pack import FIELDS


def run_record(*, run_id: str, environment: str, sample: int, candidates: list[dict],
               roles: list[str], catalog_size: int = 0) -> dict:
    """A bounded record of the rules that apply to this run. Secrets are not included."""
    ranked = rank_candidates(candidates)[:50]
    controls = {name: enable_control(environment, name)[0] for name in sorted(CONTROLS)}
    allowed, reason = model_change_allowed(None)
    pay_blocked, pay_reason = action_still_blocked("pay")
    production_fault = inject_fault("production", "external-api", permitted=True)
    return {
        "sample_unchanged": True,
        "sample": int(sample),
        "explore": {"ranked": [{"url": row.get("url"), "score": row.get("score")} for row in ranked]},
        "sessions": {"run_id": run_id, "roles": list(roles), "secrets": False},
        "environment": {"controls": controls, "payment_blocked": pay_blocked, "payment_reason": pay_reason},
        "replay": {"required": list(FIELDS)},
        "locale": {"sample": keep_sample(sample, catalog_size or sample)},
        "evaluation": {"model_change_allowed": allowed, "reason": reason},
        "dependency": {"production_injected": production_fault["injected"], "reason": production_fault["reason"]},
        "plugins": {"locks": list(LOCKS)},
        "trends": {"rewrites_verdict": False},
    }
