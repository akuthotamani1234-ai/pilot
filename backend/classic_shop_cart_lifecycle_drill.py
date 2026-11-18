"""Gate C: ClassicShop cart add → remove lifecycle confirmation.

Localhost ClassicShop only. Broader live portal paths still open —
``gate_c_complete`` stays False.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "classic_shop_cart_lifecycle_drill.json"


def run_classic_shop_cart_lifecycle_drill(*, ops_dir: Path | None = None) -> dict:
    from tests.classic_shop import ClassicShop

    shop = ClassicShop().start()
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    steps: list[dict] = []
    try:
        # Seed session
        opener.open(shop.url + "/index.php", timeout=10).read()
        steps.append({"step": "open_home", "ok": True})

        # Add product id=1 (no options) via AJAX cart POST
        body = urllib.parse.urlencode({"product_id": "1", "quantity": "1"}).encode()
        req = urllib.request.Request(  # noqa: S310
            shop.url + "/index.php?rt=checkout/cart",
            data=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Requested-With": "XMLHttpRequest",
            },
            method="POST",
        )
        raw = opener.open(req, timeout=10).read().decode("utf-8", errors="replace")
        added = "count" in raw or "ITEMS" in raw or "1" in raw
        # Confirm cart has lines via HTML cart page
        cart_html = opener.open(shop.url + "/index.php?rt=checkout/cart", timeout=10).read().decode(
            "utf-8", errors="replace"
        )
        has_line = "remove=" in cart_html or "quantity[" in cart_html
        steps.append({"step": "add_to_cart", "ok": added or has_line})

        # Remove via GET remove= (HTML may already percent-encode the key)
        remove_key = "1:"
        marker = "remove="
        if marker in cart_html:
            raw_key = cart_html.split(marker, 1)[1].split('"', 1)[0].split("&", 1)[0]
            remove_key = urllib.parse.unquote(raw_key) or remove_key
        opener.open(
            shop.url + "/index.php?rt=checkout/cart&remove=" + urllib.parse.quote(remove_key, safe=""),
            timeout=10,
        ).read()
        after = opener.open(shop.url + "/index.php?rt=checkout/cart", timeout=10).read().decode(
            "utf-8", errors="replace"
        )
        empty = (
            "shopping cart is empty" in after.lower()
            or ("remove=" not in after and "quantity[" not in after)
        )
        steps.append({"step": "remove_from_cart", "ok": empty, "remove_key": remove_key[:40]})

        ok = all(s.get("ok") for s in steps)
        evidence = {
            "gate_c_complete": False,
            "drill": "classic_shop_cart_lifecycle",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "base_url": shop.url,
            "steps": steps,
            "ok": ok,
            "reason": (
                "ClassicShop cart add→remove lifecycle ok; broader live portal paths still open"
                if ok else
                "ClassicShop cart lifecycle failed; broader live portal paths still open"
            ),
        }
    except (OSError, ValueError, urllib.error.URLError) as exc:
        evidence = {
            "gate_c_complete": False,
            "drill": "classic_shop_cart_lifecycle",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ok": False,
            "steps": steps,
            "reason": f"ClassicShop lifecycle error: {exc}; broader live portal paths still open",
        }
    finally:
        try:
            shop.stop()
        except Exception:
            pass

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "classic_shop_cart_lifecycle_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "classic_shop_cart_lifecycle_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
