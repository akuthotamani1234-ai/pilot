"""QX-A18 plugins. A versioned plugin may add an action, an assertion, or a note.

It cannot turn off authorization, secret redaction, or the payment, delete,
and logout blocks.
"""
LOCKS = ("authorization", "redact", "pay", "delete", "logout")


def review_plugin(plugin: dict) -> dict:
    """Accept a plugin, or refuse it when it tries to turn a lock off."""
    version = str(plugin.get("version") or "").strip()
    if not version:
        return {"accepted": False, "reason": "a plugin needs a version", "locks": list(LOCKS)}
    disable = {str(item).strip().lower() for item in plugin.get("disable") or [] if str(item).strip()}
    blocked = [name for name in LOCKS if name in disable]
    if blocked:
        return {
            "accepted": False,
            "reason": "a plugin cannot turn off " + ", ".join(blocked),
            "locks": list(LOCKS),
        }
    return {
        "accepted": True,
        "reason": "",
        "version": version,
        "actions": [str(item) for item in plugin.get("actions") or []],
        "assertions": [str(item) for item in plugin.get("assertions") or []],
        "notes": [str(item) for item in plugin.get("notes") or []],
        "locks": list(LOCKS),
    }
