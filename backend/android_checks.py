"""Phone-level checks a real Android tester adds after the screens and buttons work:

  deep links     every link the app declares (myapp://product/1) opens the app, not a crash or another app
  appearance     dark mode, a large font and another language: no text cut off or pushed off the screen
  device-only    camera, QR scanner, fingerprint, AR, NFC, Bluetooth on an emulator: "not testable here", never a pass
  performance    cold start time and memory use of the app

Every phone setting changed here (dark mode, font size, the app's language) is put back afterwards, also when a
check fails. Results go to the session's findings / tries (they reach the report) and to android_checks.json.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

DEVICE_ONLY = re.compile(r"\b(camera|qr|scanner|scan|barcode|finger ?print|biometric|face ?id|augmented reality|"
                         r"\bar\b|try[- ]?on|nfc|bluetooth|usb|gps|geo ?location)\b", re.I)
ELLIPSIS = re.compile(r"(…|\.\.\.)\s*$")
SLOW_START_MS = 5000


# ---------------------------------------------------------------- pure helpers (unit-tested)

def deep_links(dumpsys: str, package: str) -> list[str]:
    """The app's own deep links from `dumpsys package <pkg>`: intent filters with VIEW + BROWSABLE and a custom
    scheme (http/https links lead to real websites: left out). 'scheme://host/path' or 'scheme://'."""
    links, block = [], {}

    def flush():
        if block.get("view") and block.get("browsable"):
            for scheme in block.get("schemes", []):
                if scheme.lower() in ("http", "https"):
                    continue
                hosts = block.get("hosts") or [""]
                paths = block.get("paths") or [""]
                for host in hosts:
                    for path in paths:
                        links.append(f"{scheme}://{host}{path if path.startswith('/') or not path else '/' + path}")

    for raw in (dumpsys or "").splitlines():
        line = raw.strip()
        if re.match(r"^[0-9a-f]+ " + re.escape(package) + r"/", line) or line.startswith("Filter:"):
            flush()
            block = {}
        elif line.startswith('Action: "android.intent.action.VIEW"'):
            block["view"] = True
        elif line.startswith('Category: "android.intent.category.BROWSABLE"'):
            block["browsable"] = True
        elif m := re.match(r'Scheme: "([^"]+)"', line):
            block.setdefault("schemes", []).append(m.group(1))
        elif m := re.match(r'Authority: "([^"]+)"', line):
            block.setdefault("hosts", []).append(m.group(1))
        elif m := re.match(r'Path(?:Prefix|Pattern)?: "?(?:PatternMatcher\{[A-Z_]+: )?([^"}]+)', line):
            block.setdefault("paths", []).append(m.group(1).replace(".*", ""))
    flush()
    return list(dict.fromkeys(links))[:10]


def _bounds(element: dict):
    m = re.match(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]", str(element.get("bounds") or ""))
    return tuple(int(x) for x in m.groups()) if m else None


def layout_problems(screen: dict, width: int, baseline: dict | None = None) -> list[str]:
    """Text a person cannot read fully: pushed past the screen's edge, or newly cut off with '…' (not cut off in
    the normal look). Compared with the same screen's normal look when given."""
    before = {e.get("resource_id") or e.get("accessibility_id") or "": e.get("text") or ""
              for e in (baseline or {}).get("elements", [])}
    out = []
    for e in screen.get("elements", []):
        text = (e.get("text") or "").strip()
        if not e.get("visible", True) or not text:
            continue
        box = _bounds(e)
        if box and width and (box[2] > width + 2 or box[0] < -2):
            out.append(f"'{text[:40]}' runs past the edge of the screen")
        elif ELLIPSIS.search(text):
            key = e.get("resource_id") or e.get("accessibility_id") or ""
            if not (key and ELLIPSIS.search(before.get(key, ""))):
                out.append(f"'{text[:40]}' is cut off")
    return list(dict.fromkeys(out))[:8]


def device_only_features(screens: list[dict]) -> list[str]:
    """Screens / controls that need real phone hardware (camera, scanner, fingerprint, AR...)."""
    found = []
    for s in screens:
        words = " ".join([s.get("screen_name", "")] + [str(e.get("text") or e.get("accessibility_id") or "")
                                                       for e in s.get("elements", []) if isinstance(e, dict)])
        for m in DEVICE_ONLY.finditer(words):
            name = m.group(0).strip().lower()
            if name not in found:
                found.append(name)
    return found[:12]


def start_time_ms(am_output: str) -> int | None:
    m = re.search(r"TotalTime:\s*(\d+)", am_output or "")
    return int(m.group(1)) if m else None


def memory_kb(meminfo: str) -> int | None:
    m = re.search(r"TOTAL PSS:\s*(\d+)", meminfo or "") or re.search(r"^\s*TOTAL\s+(\d+)", meminfo or "", re.M)
    return int(m.group(1)) if m else None


def is_emulator(device_id: str, qemu: str = "") -> bool:
    return (device_id or "").startswith("emulator-") or qemu.strip() == "1"


# ---------------------------------------------------------------- on the device

class Checks:
    def __init__(self, driver, config: dict, adb: str | None, run_dir: Path, inspect, session=None):
        self.driver, self.config, self.adb, self.run_dir, self.inspect = driver, config, adb, Path(run_dir), inspect
        self.session = session
        self.package = config.get("package_name", "")
        self.device = config.get("device_id", "")
        self.results: dict = {"deep_links": [], "appearance": [], "device_only": {}, "performance": {}}

    def shell(self, *args: str, timeout: int = 20) -> str:
        from .android import _run_cli
        if not self.adb:
            raise RuntimeError("adb is not available")
        result = _run_cli(self.adb, ["-s", self.device, "shell", *args], timeout)
        return result.stdout or ""

    def finding(self, where: str, text: str, detail: str = ""):
        if self.session is not None:
            self.session.findings.append({"screen": where, "finding": text, "detail": detail})
            self.session.tried.append({"check": text, "outcome": "finding", "reason": text, "detail": detail,
                                       "screen": where})

    def note(self, check: str, outcome: str, detail: str = ""):
        if self.session is not None:
            self.session.tried.append({"check": check, "outcome": outcome, "detail": detail})

    def relaunch(self):
        try:
            self.driver.terminate_app(self.package)
        except Exception:
            pass
        self.driver.activate_app(self.package)
        time.sleep(2.5)

    def in_front(self) -> bool:
        try:
            return self.driver.current_package == self.package
        except Exception:
            return False

    # -- deep links
    def run_deep_links(self):
        links = deep_links(self.shell("dumpsys", "package", self.package), self.package)
        if not links:
            self.note("Deep links", "none declared", "the app declares no custom links (myapp://...) to open it")
            return
        for url in links:
            try:
                self.driver.execute_script("mobile: deepLink", {"url": url, "package": self.package})
                time.sleep(2.5)
                ok = self.in_front()
            except Exception as error:
                ok, why = False, type(error).__name__
            else:
                why = "" if ok else "another app or the home screen was in front"
            self.results["deep_links"].append({"url": url, "opened": ok, "why": why})
            if ok:
                self.note(f"Deep link {url} opens the app", "passed")
            else:
                self.finding("deep link", f"The deep link {url} did not open the app", why)
        self.relaunch()

    # -- appearance
    def run_appearance(self):
        width = 0
        try:
            width = int(self.driver.get_window_size().get("width") or 0)
        except Exception:
            pass
        self.relaunch()
        normal = self.inspect()
        font_before = (self.shell("settings", "get", "system", "font_scale").strip() or "1.0")
        looks = [("dark mode", ("cmd", "uimode", "night", "yes"), ("cmd", "uimode", "night", "no")),
                 ("large font (130%)", ("settings", "put", "system", "font_scale", "1.3"),
                  ("settings", "put", "system", "font_scale", font_before if font_before != "null" else "1.0")),
                 ("German language", ("cmd", "locale", "set-app-locales", self.package, "--locales", "de-DE"),
                  ("cmd", "locale", "set-app-locales", self.package, "--locales", ""))]
        for name, on, off in looks:
            problems, opened = [], False
            try:
                self.shell(*on)
                self.relaunch()
                opened = self.in_front()
                if opened:
                    problems = layout_problems(self.inspect(), width, normal)
            except Exception as error:
                self.note(f"The app in {name}", "not testable here", type(error).__name__)
                continue
            finally:
                try:
                    self.shell(*off)  # (always put back, also after a failure)
                except Exception:
                    pass
            self.results["appearance"].append({"look": name, "opened": opened, "problems": problems})
            if not opened:
                self.finding("appearance", f"The app did not open in {name}")
            elif problems:
                self.finding(normal.get("screen_name", "the start screen"), f"In {name}: " + "; ".join(problems[:3]))
            else:
                self.note(f"The start screen in {name}: no text cut off", "passed")
        self.relaunch()

    # -- hardware the emulator does not have
    def run_device_only(self, screens: list[dict]):
        qemu = ""
        try:
            qemu = self.shell("getprop", "ro.kernel.qemu")
        except Exception:
            pass
        features = device_only_features(screens)
        emulator = is_emulator(self.device, qemu)
        self.results["device_only"] = {"emulator": emulator, "features": features}
        if emulator:
            for feature in features:
                self.note(f"'{feature}'", "not testable here",
                          "an emulator has no real camera / scanner / fingerprint sensor: its screen may open, the "
                          "feature itself needs a real phone")

    # -- performance
    def run_performance(self):
        activity = ""
        for line in reversed(self.shell("cmd", "package", "resolve-activity", "--brief", self.package).splitlines()):
            if "/" in line:
                activity = line.strip()
                break
        starts = []
        if activity:
            for _ in range(3):
                ms = start_time_ms(self.shell("am", "start", "-W", "-S", "-n", activity, timeout=40))
                if ms:
                    starts.append(ms)
                time.sleep(1)
        memory = memory_kb(self.shell("dumpsys", "meminfo", self.package))
        perf = {"cold_start_ms": sorted(starts)[len(starts) // 2] if starts else None, "cold_starts_ms": starts,
                "memory_kb": memory}
        self.results["performance"] = perf
        if perf["cold_start_ms"] and perf["cold_start_ms"] > SLOW_START_MS:
            self.finding("app start", f"The app takes {perf['cold_start_ms'] / 1000:.1f} s to start (more than "
                                      f"{SLOW_START_MS / 1000:.0f} s)", f"cold starts: {starts} ms")
        else:
            self.note("App start time and memory", "measured",
                      f"cold start {perf['cold_start_ms']} ms, memory {memory} KB")

    def run_all(self, screens: list[dict]) -> dict:
        for name, step in (("device_only", lambda: self.run_device_only(screens)), ("deep_links", self.run_deep_links),
                           ("appearance", self.run_appearance), ("performance", self.run_performance)):
            try:
                step()
            except Exception as error:  # one part failing never stops the others or the run
                self.results.setdefault("errors", {})[name] = f"{type(error).__name__}: {str(error)[:160]}"
        try:
            (self.run_dir / "android_checks.json").write_text(json.dumps(self.results, indent=2), encoding="utf-8")
        except OSError:
            pass
        return self.results
