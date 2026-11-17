"""QX-A08 replay. A defect package can be run again from the recorded steps.

A package needs the environment, build, browser or device, seed, starting
state, test data, actions, network evidence, screenshots, and the assertion
that failed. A short summary is not enough to replay.
"""
FIELDS = (
    "environment",
    "build",
    "browser",
    "seed",
    "starting_state",
    "test_data",
    "actions",
    "network",
    "screenshots",
    "assertion",
)


def missing_fields(package: dict) -> list[str]:
    """Names of the fields a replay still needs."""
    missing = []
    for field in FIELDS:
        value = package.get(field)
        if value is None or value == "" or value == [] or value == {}:
            missing.append(field)
    return missing


def make_package(**fields: object) -> dict:
    """Build a package. It is complete only when every required field is present."""
    package = {field: fields.get(field) for field in FIELDS}
    package["missing"] = missing_fields(package)
    package["complete"] = not package["missing"]
    return package


def replay(package: dict) -> dict:
    """Return the recorded steps, or the list of fields that still block replay."""
    missing = missing_fields(package)
    if missing:
        return {"ran": False, "missing": missing, "steps": []}
    return {"ran": True, "missing": [], "steps": list(package.get("actions") or [])}
