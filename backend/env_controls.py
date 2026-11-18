"""QX-A07 environment controls. Stubs, a fixed clock, and a network fault stay off production.

Turning a control on does not allow payment, delete, or logout.
"""
from .data_lifecycle import production_environment

CONTROLS = frozenset({"stub_api", "fixed_clock", "network_fault"})
PROTECTED = frozenset({"pay", "delete", "logout"})


def enable_control(environment: str, control: str) -> tuple[bool, str]:
    """Whether this run may use one staging control."""
    if control not in CONTROLS:
        return False, "unknown environment control"
    if production_environment(environment):
        return False, "environment controls are off on production"
    if (environment or "").strip().lower() not in {"test", "staging"}:
        return False, "environment controls run only on an approved test or staging target"
    return True, control


def action_still_blocked(kind: str) -> tuple[bool, str]:
    """Payment, delete, and logout stay blocked even when a control is on."""
    if kind in PROTECTED:
        return True, "payment, delete, and logout stay blocked"
    return False, ""
