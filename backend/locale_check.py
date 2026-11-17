"""QX-A11 locale check. Language, currency, date, tax, and regional offer are compared.

A new locale keeps the small product sample. It does not open the rest of the catalog.
"""
FIELDS = ("language", "currency", "date_format", "tax", "offered")


def check_locale(observed: dict, expected: dict) -> dict:
    """Compare one locale's observed values with the approved expected values."""
    checks = []
    for field in FIELDS:
        checks.append({
            "field": field,
            "ok": observed.get(field) == expected.get(field),
            "expected": expected.get(field),
            "observed": observed.get(field),
        })
    return {"ok": all(row["ok"] for row in checks), "checks": checks}


def keep_sample(sample_size: int, catalog_size: int) -> int:
    """The number of products a locale run opens. The catalog size does not raise it."""
    sample = max(0, int(sample_size))
    catalog = max(0, int(catalog_size))
    if sample == 0:
        return 0
    return min(sample, catalog)
