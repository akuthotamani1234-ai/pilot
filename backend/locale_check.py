"""QX-A11 locale check. Language, currency, date, tax, and regional offer are compared.

A new locale keeps the small product sample. It does not open the rest of the catalog.
"""
import json
import re
from pathlib import Path

FIELDS = ("language", "currency", "date_format", "tax", "offered")
# A visible ISO code is recorded as written. A symbol is recorded only when no code is shown,
# and it is not turned into a code (¥ is not assumed to be JPY).
_ISO_CURRENCY = re.compile(r"\b(AED|AUD|CAD|CHF|CNY|EUR|GBP|INR|JPY|SAR|SGD|USD)\b")
_CURRENCY_SYMBOL = re.compile("[₹€£¥$]")


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


def _present(value: object) -> object | None:
    """A value the page actually carried. Blank text is treated as not found."""
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, bool | int | float):
        return value
    return None


def _currency_in_text(text: str) -> str | None:
    """An ISO code written on the page, or else the currency symbol that was visible."""
    iso = _ISO_CURRENCY.search(text or "")
    if iso:
        return iso.group(1)
    symbol = _CURRENCY_SYMBOL.search(text or "")
    return symbol.group(0) if symbol else None


def _visible_text(page: dict) -> str:
    parts: list[str] = []
    for key in ("text", "main_text"):
        if isinstance(page.get(key), str):
            parts.append(page[key])
    totals = page.get("totals")
    if isinstance(totals, list):
        parts.extend(str(item) for item in totals if item)
    return " ".join(parts)


def observe_page(page: dict) -> dict:
    """Locale facts a recorded page already shows. Missing facts are left out."""
    if not isinstance(page, dict):
        return {}
    blob = page.get("locale") if isinstance(page.get("locale"), dict) else {}
    found: dict = {}
    for field in FIELDS:
        value = _present(page.get(field))
        if value is None and field == "language":
            value = _present(page.get("lang"))
        if value is None:
            value = _present(blob.get(field))
        if value is not None:
            found[field] = value
    if "currency" not in found:
        currency = _currency_in_text(_visible_text(page))
        if currency is not None:
            found["currency"] = currency
    return found


def remember_locale(observed: dict, page: dict) -> dict:
    """Keep the first fact each page shows. A later page does not replace it."""
    for key, value in observe_page(page).items():
        if key not in observed:
            observed[key] = value
    return observed


def locale_payload(observed: dict) -> dict:
    """The run file shape: only facts that were found, and no invented expected values."""
    kept = {field: observed[field] for field in FIELDS
            if field in observed and observed[field] not in (None, "")}
    return {"observed": kept, "expected": {}}


def write_locale(run_dir: Path, observed: dict) -> dict:
    """Write runs/<run>/locale.json. Expected stays empty until a person supplies it."""
    payload = locale_payload(observed)
    folder = Path(run_dir)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "locale.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
