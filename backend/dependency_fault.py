"""QX-A14 dependency faults. A permitted service can be made unavailable on staging.

The report records that the fault was injected. Production is refused, including
a third party's production service.
"""
from .data_lifecycle import production_environment


def inject_fault(environment: str, service: str, *, permitted: bool) -> dict:
    """Decide whether a dependency fault may be injected, and the report line."""
    name = str(service or "").strip()
    if not name:
        return {"injected": False, "reason": "a dependency fault needs a service name"}
    if production_environment(environment):
        return {"injected": False, "reason": "a dependency fault is not used on production"}
    if (environment or "").strip().lower() not in {"test", "staging"}:
        return {"injected": False, "reason": "a dependency fault runs only on an approved test or staging target"}
    if not permitted:
        return {"injected": False, "reason": f"{name} is not a permitted service"}
    return {
        "injected": True,
        "service": name,
        "reason": f"{name} was made unavailable on {environment.strip().lower()}",
    }
