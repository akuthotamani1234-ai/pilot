"""Before a Jira execution starts: can it actually test anything? (Reported 26 Nov 2026: 18 approved test cases ran
as 'complete' and every one was 'Not automated', because no AI reached the engine.)

  ai        which AI the engine will REALLY use - resolved exactly as the run resolves it (privacy.select_provider:
            the choice made here, else LLM_PROVIDER; local-only privacy turns a cloud AI into 'none') - and whether
            it is ready (a key / a running local model). Requirement test cases are turned into browser steps by
            the AI, so without one a requirement-based or hybrid run is refused instead of started.
  browser   the run's own Chromium (Playwright) opens the website once, headless: proves the browser starts and
            looks at the real page - a visible password box means the site needs a login, so a test account must be
            given or saved. Nothing is clicked or typed.
  target    an http(s) address, authorized, not a metadata / credential URL (safety.check_target).

Each problem has a message and a recovery action; 'blocking' problems stop the run before anything is created.
"""
from __future__ import annotations

import os
import threading
import time

PROBE_TIMEOUT_S = 25


def ai_status(requested: str = "", model: str = "", api_key: str = "") -> dict:
    from .config import settings
    from .privacy import PrivacyError, load_policy, select_provider
    configured = os.environ.get("LLM_PROVIDER") or settings.llm_provider or "ollama"
    mode = load_policy().mode
    out = {"requested": requested or "", "configured": configured, "privacy_mode": mode, "model": model or "",
           "provider": "", "ready": False, "reason": "", "recovery": ""}
    try:
        chosen = select_provider(requested or None, configured, settings.ollama_url)
    except PrivacyError as error:
        out.update(reason=str(error), recovery="allow_cloud" if mode == "local" else "choose_ai")
        return out
    out["provider"] = chosen
    if chosen == "none":
        if not requested and mode == "local" and configured.lower() in ("openai", "anthropic", "gemini",
                                                                        "huggingface"):
            out.update(reason=f"The configured AI ({configured}) is a cloud AI and privacy is set to local-only, so "
                              "this run would have no AI.", recovery="allow_cloud")
        else:
            out.update(reason="No AI is selected.", recovery="choose_ai")
        return out
    entry = _provider_entry(chosen)
    if entry is None:
        out.update(reason=f"{chosen} is not a supported AI provider.", recovery="choose_ai")
        return out
    if chosen == "ollama":
        ok = bool(entry.get("running") and entry.get("installed"))
        out.update(ready=ok, reason="" if ok else entry.get("readiness_reason", "Ollama is not ready"),
                   recovery="" if ok else "start_ollama")
        if ok and model and model not in entry.get("installed", []):
            out.update(ready=False, reason=f"The local model '{model}' is not installed in Ollama.",
                       recovery="choose_model")
        return out
    has_key = bool(api_key) or bool(entry.get("has_key"))
    out.update(ready=has_key, reason="" if has_key else f"{entry.get('name', chosen)} needs an API key.",
               recovery="" if has_key else "api_key")
    out["model"] = model or (entry.get("models") or [""])[0]
    return out


def _provider_entry(provider_id: str) -> dict | None:
    from . import server
    for p in server.providers()["providers"]:
        if p["id"] == provider_id:
            return p
    return None


_BROWSER_CACHE: dict = {}


def browser_probe(url: str, timeout_s: float = PROBE_TIMEOUT_S) -> dict:
    """Open the page once in the run's Chromium (headless). {ok, browser, login_form, title, final_url, error}."""
    result: dict = {"ok": False, "browser": False, "login_form": False, "title": "", "final_url": "", "error": ""}

    def work():
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch(headless=True)
                except Exception as error:  # (Playwright's Chromium is missing or cannot start)
                    result["error"] = f"the browser could not start: {str(error).splitlines()[0][:200]}"
                    return
                result["browser"] = True
                try:
                    page = browser.new_page()
                    page.goto(url, wait_until="domcontentloaded", timeout=int(timeout_s * 1000) - 5000)
                    try:
                        page.wait_for_selector("input[type=password]", state="visible", timeout=4000)
                        result["login_form"] = True
                    except Exception:
                        result["login_form"] = False
                    result.update(ok=True, title=page.title()[:120], final_url=page.url[:300])
                except Exception as error:
                    result["error"] = f"the website did not open in the browser: {str(error).splitlines()[0][:200]}"
                finally:
                    browser.close()
        except Exception as error:
            result["error"] = f"the browser could not start: {str(error).splitlines()[0][:200]}"

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        result["error"] = result["error"] or f"the browser check took longer than {int(timeout_s)} s"
    return result


def check(*, strategy: str, case_count: int, url: str, authorized: bool, app_type: str = "web",
          llm_provider: str = "", llm_model: str = "", api_key: str = "", has_account: bool = False,
          probe=None, demo_checkout: bool = False, android: dict | None = None) -> dict:
    """All prerequisites of one execution. problems: [{code, message, recovery, blocking}]."""
    from .safety import UrlError, check_target
    started = time.time()
    problems: list[dict] = []

    def problem(code, message, recovery, blocking=True):
        problems.append({"code": code, "message": message, "recovery": recovery, "blocking": blocking})

    needs_ai = strategy in ("requirements", "hybrid") and case_count > 0
    if strategy != "autonomous" and case_count == 0:
        problem("no_cases", "No approved test case is selected.", "select_cases")
    ai = ai_status(llm_provider, llm_model, api_key)
    if needs_ai and not ai["ready"]:
        problem("ai", f"An AI provider is required to automate these {case_count} test case"
                      f"{'' if case_count == 1 else 's'}: {ai['reason']} Choose and configure an AI provider "
                      "below to continue - your selection is kept.", ai["recovery"] or "choose_ai")
    if app_type == "android":
        a = android or {}
        if not a.get("device_id"):
            problem("device", "Choose the Android device or emulator to test on (its id from 'adb devices').",
                    "enter_device")
        if a.get("mode", "installed") == "installed" and not a.get("package_name"):
            problem("package", "Enter the Android app's package name (e.g. com.example.app).", "enter_package")
        if a.get("mode") == "web" and not url:
            problem("target", "Enter the website address to open in Android Chrome.", "enter_url")
    elif app_type != "web":
        problem("app_type", f"'{app_type}' targets are not run from here.", "use_studio")
    if not url:
        if app_type == "web":
            problem("target", "Target website not found. Please enter the website URL you want to test.",
                    "enter_url")
    else:  # (every address - a website or an Android Chrome start page - is checked the same way)
        try:
            check_target(url, resolve=False)
        except UrlError as error:
            problem("target", str(error), "enter_url")
    if demo_checkout and strategy != "requirements":
        problem("demo_checkout", "The demo checkout is only for requirement-based runs (the built-in website tests "
                                 "would also send forms). Choose requirement-based testing, or untick the demo "
                                 "checkout.", "choose_strategy")
    if not authorized:
        problem("authorization", "Confirm that you own the application or have permission to test it.",
                "confirm_authorization")
    browser = {"skipped": True}
    if url and not any(p["code"] == "target" for p in problems) and app_type == "web":  # (Android: Appium checks)
        browser = (probe or browser_probe)(url)
        if not browser.get("browser"):
            problem("browser", f"The test browser is not available: {browser.get('error')}", "install_browser")
        elif not browser.get("ok"):
            problem("target_unreachable", f"The website could not be opened: {browser.get('error')}", "retry_or_change")
        elif browser.get("login_form") and not has_account:
            problem("login", "This website shows a login form, and no test account is given or saved for it. Enter "
                             "the test account (user name and password) - your selection is kept.", "enter_account")
    return {"ok": not any(p["blocking"] for p in problems), "problems": problems, "ai": ai,
            "needs_ai": needs_ai, "browser": browser, "seconds": round(time.time() - started, 1)}
