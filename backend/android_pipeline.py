"""Android adapters for shared QA agents, bounded discovery and serial pytest execution."""

import json
import os
import re
import signal
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

import requests
from defusedxml import ElementTree

from .android import (
    AndroidEnvironmentError,
    _local_appium_url,
    android_environment,
    capture_screenshot,
    close_session,
    create_session,
    find_unique,
    inspect_driver,
    require_device,
    safe_navigation_elements,
    validate_mobile_config,
)
from .android_design import normalize_screens, validate_mobile_script
from .safety import clean_env, redact, redact_json
from .state import QAState

AndroidState = QAState

ROOT = Path(__file__).resolve().parent.parent


def _run_dir(state):
    return Path(state["run_dir"])


def _save_json(path, data):
    # Keep package_name / app package ids valid; substring username redaction must not break them.
    path.write_text(redact_json(data), encoding="utf-8")


def setup_agent(state):
    config = validate_mobile_config(state["config"])
    if config.get("apk_path"):
        try:
            Path(config["apk_path"]).resolve().relative_to((_run_dir(state) / ".private").resolve())
        except ValueError as e:
            raise AndroidEnvironmentError("The APK must be inside this run's private folder.") from e
    environment = android_environment(config["appium_url"])
    _save_json(_run_dir(state) / "android_environment.json", environment)
    if not environment["ok"]:
        raise AndroidEnvironmentError("; ".join(environment["errors"]))
    require_device(config["device_id"], environment["devices"])
    from . import llm
    warnings = list(state.get("ai_warnings", []))
    ai_unavailable = False
    if llm.llm_enabled():
        try:
            llm.ask_llm("Reply with OK. This is an Android testing provider readiness check; no app content is included.",
                        agent="setup", page="android", timeout_s=20, max_attempts=1)
        except llm.LLMError as error:
            if not config.get("allow_rules_fallback", True):
                raise AndroidEnvironmentError("AI readiness check failed before app discovery: " + redact(str(error))[:250]) from error
            ai_unavailable = True
            warning = "AI readiness failed; rules and templates will be used for this run: " + redact(str(error))[:250]
            warnings.append(warning)
            print("::warning::" + warning, flush=True)
    return {
        "config": config,
        "environment": environment,
        "target_type": "mobile",
        "ai_unavailable": ai_unavailable,
        "ai_warnings": warnings,
        "log": state.get("log", []) + warnings + ["Android environment verified."],
    }


def discovery_agent(state):
    config = state["config"].copy()
    run_dir = _run_dir(state)
    driver = create_session(config)
    screens, actions, issues, unvisited = [], [], [], []
    from .android import EXHAUSTIVE_WALL_CLOCK_S
    discovery_timeout = int(config.get("discovery_timeout_s") or 0)
    # 0 = until exhausted; still apply an emergency wall-clock so a stuck driver cannot run forever.
    deadline = time.monotonic() + (discovery_timeout or EXHAUSTIVE_WALL_CLOCK_S)
    seen = set()
    budget = {"used": 0, "recovery": 0}
    observed_destinations, skipped = {}, []
    pending = deque()
    authentication_flows = {}
    active_authentication_flow = None
    authentication_root_id = None
    user_session = None
    from .android_runtime import screen_key, settled_screen

    web_test_mode = config.get("app_mode") == "web" and bool(config.get("interaction_testing"))
    bot_gate = None
    if config.get("app_mode") == "web":
        # A bot check (Cloudflare "Just a moment...") is waited for, then handed to a person on the device; its page
        # is never read as the website and never becomes a test.
        from .android_web import BotCheckGate
        bot_gate = BotCheckGate(config, stop_path=run_dir / "STOP")
        driver._blowai_bot_gate = bot_gate

    def settled(expected=None, timeout=10):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise DiscoveryLimitReached("Discovery time limit reached")
        return settled_screen(lambda: inspect_driver(driver, config), expected, timeout=min(timeout, remaining))

    class DiscoveryLimitReached(AndroidEnvironmentError):
        pass

    def navigation_action(action, recovery=False, cheap=False):
        if (run_dir / "STOP").exists():
            raise DiscoveryLimitReached("Stop requested")
        if time.monotonic() >= deadline:
            raise DiscoveryLimitReached("Discovery time limit reached")
        if cheap:
            # One tap or Back to return (cheap_return): counted on its own, not as a relaunch-and-replay recovery
            budget["cheap"] = budget.get("cheap", 0) + 1
        elif recovery:
            action_cap = int(config.get("max_actions") or 0)
            recovery_cap = max(10, (action_cap or 200) * 3)
            if not budget.get("interaction_phase") and budget["recovery"] >= recovery_cap:
                raise DiscoveryLimitReached("Recovery action limit reached")
            budget["recovery"] += 1
        else:
            key = "authenticated_used" if budget.get("interaction_phase") else "used"
            action_cap = int(config.get("max_actions") or 0)
            if action_cap and budget.get(key, 0) >= action_cap:
                raise DiscoveryLimitReached("Exploration action limit reached")
            budget[key] = budget.get(key, 0) + 1
        action()
        time.sleep(0.2)

    def wait_for_app(seconds=15):
        """activate_app can return while the other app is still in front. Never read that app's screen."""
        from .android import bring_app_back

        limit = min(deadline, time.monotonic() + seconds)
        while driver.current_package != config["package_name"]:
            if (run_dir / "STOP").exists():
                raise DiscoveryLimitReached("Stop requested")
            # The keyboard is hidden and (in test mode) a permission prompt declined while waiting, not just slept on
            other = bring_app_back(driver, config)
            if not other:
                break
            if time.monotonic() >= limit:
                raise AndroidEnvironmentError(f"The selected app did not return to the foreground ({other} is in front).")
            time.sleep(.3)

    def cheap_return(target):
        """Back to the screen a control was tried on, the cheap way first: close a dialog with its own Continue /
        Close / OK / Cancel / Done button, or press Back once. Only when that fails does restore() relaunch the app.
        (Run android_20261109_170355_a7b3dd spent 50 recovery actions on full relaunches and 18 on exploring.)"""
        from .android_runtime import same_screen

        if config.get("app_mode") == "web":
            return False
        try:
            current = inspect_driver(driver, config)
        except AndroidEnvironmentError:
            return False
        if same_screen(current, target):
            return True
        # 1. The control that opens the target is on this screen too (the menu button on every screen): tap it
        elements = {e["id"]: e for s in screens for e in s["elements"]}
        opener = elements.get((target.get("path") or [None])[-1])
        owner = next((s for s in screens if opener is not None and opener in s["elements"]), None)
        if opener is not None and owner is not None and opener in safe_navigation_elements(owner) and any(
                e.get("visible") and e.get("locators")[:1] == opener["locators"][:1] for e in current["elements"]
                if e.get("locators")):
            try:
                navigation_action(find_unique(driver, opener["locators"][0]).click, cheap=True)
                current = inspect_driver(driver, config)
                if same_screen(current, target):
                    return True
            except DiscoveryLimitReached:
                raise
            except Exception:
                return False
        if screens and same_screen(current, screens[0]):
            return False  # Back on the launch screen would leave the app: restore() replays the path instead
        closers = [e for e in current["elements"] if e.get("visible") and e.get("clickable") and e.get("enabled", True)
                   and e.get("locators") and e.get("locator_unique", True)
                   and re.fullmatch(r"\s*(continue|close|ok|okay|cancel|done|got it|dismiss|x|×|✕)\s*",
                                    e.get("text") or e.get("accessibility_id") or "", re.I)]
        try:
            if len(closers) == 1 and current.get("activity") == target.get("activity"):
                navigation_action(find_unique(driver, closers[0]["locators"][0]).click, cheap=True)
            else:
                navigation_action(driver.back, cheap=True)
            current = inspect_driver(driver, config)
        except DiscoveryLimitReached:
            raise
        except Exception:
            return False
        return same_screen(current, target)

    def relaunch_app():
        """Start the app again from its launch screen (or reopen the start URL in Chrome)."""
        if config.get("app_mode") == "web":
            navigation_action(lambda: driver.get(config["start_url"]), recovery=True)
        else:
            package = config["package_name"]
            try:
                navigation_action(lambda: driver.terminate_app(package), recovery=True)
            except DiscoveryLimitReached:
                raise
            except Exception:
                pass
            try:
                navigation_action(lambda: driver.activate_app(package), recovery=True)
                wait_for_app(20)
            except DiscoveryLimitReached:
                raise
            except Exception as activate_error:
                adb = state.get("environment", {}).get("adb")
                if not adb:
                    raise AndroidEnvironmentError("The selected app did not return to the foreground.") from activate_error
                print("[android] Recovering by launching the selected app from the emulator launcher.", flush=True)
                from .android import _run_cli

                result = _run_cli(adb, ["-s", config["device_id"], "shell", "monkey", "-p", package,
                                        "-c", "android.intent.category.LAUNCHER", "1"], 15)
                if result.returncode:
                    raise AndroidEnvironmentError("The Android launcher could not reopen the selected app.") from activate_error
                wait_for_app(30)
        settled(screens[0], timeout=30)

    def restore(target):
        from .android_runtime import same_screen

        authentication_flow_id = target.get("authentication_flow_id")
        if authentication_flow_id:
            auth_root = next((s for s in screens if s.get("id") == target.get("authentication_root_id")), None)
            flow = authentication_flows.get(authentication_flow_id)
            if auth_root is None or flow is None or user_session is None:
                raise AndroidEnvironmentError("The authenticated screen has no replayable approved login setup.")
            current = inspect_driver(driver, config)
            if same_screen(current, target):
                settled(target)
                return
            if not same_screen(current, auth_root):
                # Start clean before replaying the approved login, then explore only
                # controls reachable from that authenticated root.
                from .android import reset_app_data
                from .qa_contracts import parse_contract
                from .qa_runtime import AndroidContractAdapter, ContractRuntime

                reset_app_data(driver, config["package_name"])
                wait_for_app(30)
                settled(screens[0], timeout=30)
                contract = parse_contract({**user_session.base, "flows": [flow]})
                adapter = AndroidContractAdapter(driver, config, contract, stop_path=run_dir / "STOP")
                runtime = ContractRuntime(adapter, contract.model_dump(mode="json"),
                                          {"secrets": user_session.secrets, "databases": {}})
                runtime.execute(authentication_flow_id)
                settled(auth_root, timeout=30)
            elements = {e["id"]: (owner, e) for owner in screens for e in owner["elements"]}
            path = target.get("path", [])
            for index, element_id in enumerate(path):
                owner, element = elements[element_id]
                live = inspect_driver(driver, config)
                if not same_screen(live, owner) or element not in safe_navigation_elements(owner):
                    raise AndroidEnvironmentError("The authenticated recovery path no longer matches observed safe navigation.")
                selected = find_unique(driver, element["locators"][0])
                navigation_action(selected.click, recovery=True)
                destination = elements[path[index + 1]][0] if index + 1 < len(path) else target
                settled(destination, timeout=15)
            settled(target)
            return

        def inspect_target(wait=False):
            # Back may leave a native app instead of restoring its drawer.
            # Bring back only the approved target, without reading external UI.
            if config.get("app_mode") == "web":
                from .android_web import guard_url
                try:
                    guard_url(driver.current_url, config)
                except (AndroidEnvironmentError, ValueError):
                    navigation_action(lambda: driver.get(config["start_url"]), recovery=True)
                    wait = True
            elif driver.current_package != config["package_name"]:
                navigation_action(lambda: driver.activate_app(config["package_name"]), recovery=True)
                wait_for_app()
                wait = True
            current = inspect_driver(driver, config)
            settle_deadline = min(deadline, time.monotonic() + 8)
            while wait and not same_screen(current, target) and not same_screen(current, screens[0]):
                if time.monotonic() >= settle_deadline:
                    break
                time.sleep(.3)
                current = inspect_driver(driver, config)
            return current

        current = inspect_target()
        if same_screen(current, target):
            return
        if config.get("app_mode") == "web":
            navigation_action(lambda: driver.get(config["start_url"]), recovery=True)
            current = inspect_target(wait=True)
        if not same_screen(current, screens[0]):
            navigation_action(driver.back, recovery=True)
            current = inspect_target(wait=True)
        if same_screen(current, target):
            return
        # Some native apps implement Back as Home rather than maintaining a screen stack.
        if not same_screen(current, screens[0]):
            relaunch_app()
        elements = {e["id"]: (visited, e) for visited in screens for e in visited["elements"]}
        path = target.get("path", [])
        for index, element_id in enumerate(path):
            owner, element = elements[element_id]
            live = inspect_driver(driver, config)
            if not same_screen(live, owner) or element not in safe_navigation_elements(owner):
                raise AndroidEnvironmentError(
                    "Recovery path no longer identifies safe navigation on the expected screen."
                )
            try:
                selected = find_unique(driver, element["locators"][0])
            except Exception as error:
                from selenium.common.exceptions import NoSuchElementException

                if not isinstance(error, NoSuchElementException) or not element.get('scroll_hint'):
                    raise
                from .android_scroll import seek_observed

                selected, _, _ = seek_observed(driver, owner, element, config, run_dir / 'STOP')
            navigation_action(selected.click, recovery=True)
            destination = elements[path[index + 1]][0] if index + 1 < len(path) else target
            settled(destination, timeout=15)
        settled(target)

    def record_screen(screen, path, depth):
        screen["path"] = path
        if active_authentication_flow:
            screen["authentication_flow_id"] = active_authentication_flow
            screen["authentication_root_id"] = authentication_root_id
            screen["authentication_setup_steps"] = authentication_flows[active_authentication_flow]["steps"]
        if screen.get("inventory_truncated"):
            issues.append({"error": "DOM inventory exceeded 1500 rendered nodes; remaining nodes were not inspected."})
        normalize_screens([screen])
        seen.add(screen_key(screen))
        screen["screenshot"] = capture_screenshot(driver, run_dir, screen["id"], config.get("package_name"))
        screens.append(screen)
        live_page = {
            "url": screen.get("web_url") or f"android://{screen['package_name']}/{screen['id']}",
            "slug": screen["id"], "title": screen["screen_name"], "status": 200,
            "platform": "android", "activity": screen.get("activity"),
            "screenshot": screen["screenshot"], "elements": len(screen["elements"]),
        }
        print("::page::" + json.dumps(live_page), flush=True)
        print("[android] Inspecting additional content on a discovered screen.", flush=True)
        from .android_runtime import device_unavailable
        from .android_scroll import discover_viewports

        try:
            gaps = discover_viewports(driver, screen, config, budget, deadline, run_dir)
            unvisited.extend({'screen_id': screen['id'], **gap} for gap in gaps)
        except Exception as error:
            if device_unavailable(error):
                raise
            issues.append({'action': 'offscreen discovery', 'error': redact(str(error))[:300]})
        normalize_screens([screen])
        print(f"[android] Screen inspection finished; {len(unvisited)} discovered item(s) remain to visit.", flush=True)
        pending.append((screen, path, depth))

    def visit(screen, path, depth):
        restored = False
        candidates = safe_navigation_elements(screen)
        expectations = config.get("expected_destinations", {})
        test_build = config.get("interaction_testing") and config.get("app_mode") != "web"

        def rank(e):
            # Menu items and tabs first, then labelled buttons, then per-card controls (a product picture)
            if e.get("navigation_role") in ("menu_item", "tab"):
                return 0
            words = e.get("text") or e.get("accessibility_id") or ""
            repeated = sum((o.get("text") or o.get("accessibility_id") or "") == words for o in candidates) > 1
            return 2 if repeated or not words else 1
        candidates.sort(
            key=lambda e: ((e.get("text") or e.get("accessibility_id") or "").strip().casefold() not in expectations,
                           # Test-build mode tests forms: reach the login screen early, before the time runs out.
                           not (test_build and re.search(r"\b(log ?in|sign ?in)\b",
                                                         (e.get("text") or e.get("accessibility_id") or ""), re.I)),
                           rank(e) if config.get("app_mode") != "web" else 0)
        )
        cap = int(config.get("max_candidates_per_screen") or 0)
        if config.get("app_mode") != "web" and cap and len(candidates) > cap:
            for rest in candidates[cap:]:
                unvisited.append({"screen_id": screen["id"], "element_id": rest["id"],
                                  "label": (rest.get("text") or rest.get("accessibility_id") or "navigation")[:100],
                                  "reason": f"candidate cap reached: at most {cap} controls are explored per screen"})
            candidates = candidates[:cap]
        from .android import repeat_family
        from .android_runtime import device_unavailable

        families = set()
        for position, element in enumerate(candidates):
            label = (
                element.get("text") or element.get("accessibility_id") or element.get("resource_id") or "navigation"
            )[:100]
            family = repeat_family(element)
            if family in families:
                skipped.append({"screen_id": screen["id"], "element_id": element["id"], "label": label,
                                "reason": "Same kind of unlabelled control as one already tried on this screen"})
                continue
            if family:
                families.add(family)
            label_key = label.strip().casefold()
            # A toolbar control the launch screen shows too (View menu, View cart) leads to the same place from
            # every screen: explored once, like a tab (run android_20261109_170355_a7b3dd re-explored it everywhere).
            toolbar = (config.get("app_mode") != "web" and label_key and any(
                element["locators"][0] in e.get("locators", [])[:1] and (e.get("text") or e.get("accessibility_id") or "")
                .strip().casefold() == label_key for e in screens[0]["elements"]))
            locator_key = json.dumps([element["locators"][0], label_key,
                                      "global_tab" if element.get("navigation_role") == "tab" or toolbar
                                      else "home" if config.get("app_mode") != "web" and label_key == "home"
                                      else screen["fingerprint"]], sort_keys=True)
            # Reuse only an actually observed destination for the same control.
            # A matching label alone is not proof of where a button goes.
            if label_key not in expectations and observed_destinations.get(locator_key) in seen:
                skipped.append({"screen_id": screen["id"], "element_id": element["id"], "label": label,
                                "reason": "This navigation control already led to an explored screen"})
                continue
            action_count = (budget.get("authenticated_used", 0) if budget.get("interaction_phase")
                            else budget["used"])
            max_depth = int(config.get("max_depth") or 0)
            max_screens = int(config.get("max_screens") or 0)
            max_actions = int(config.get("max_actions") or 0)
            if (
                (max_depth and depth >= max_depth)
                or (max_screens and len(screens) >= max_screens)
                or (max_actions and action_count >= max_actions)
                or time.monotonic() >= deadline
                or (run_dir / "STOP").exists()
            ):
                unvisited.append(
                    {
                        "screen_id": screen["id"],
                        "element_id": element["id"],
                        "label": label,
                        "reason": ("Stop requested" if (run_dir / "STOP").exists() else
                                   "Discovery time limit reached" if time.monotonic() >= deadline else
                                   "Exploration action limit reached" if max_actions and action_count >= max_actions else
                                   "Screen limit reached" if max_screens and len(screens) >= max_screens else
                                   "Exploration depth limit reached"),
                    }
                )
                continue
            record = {
                "label": label,
                "locator": element["locators"][0],
                "element_id": element["id"],
                "before_fingerprint": screen["fingerprint"],
                "depth": depth,
            }
            actions.append(record)
            print("[android] Exploring a safe navigation control.", flush=True)
            try:
                if not restored:
                    restore(screen)
                    restored = True
                selected = None
                for locator in element["locators"]:
                    try:
                        selected = find_unique(driver, locator)
                        record["locator"] = locator
                        break
                    except Exception as e:
                        from selenium.common.exceptions import NoSuchElementException

                        if not isinstance(e, NoSuchElementException):
                            raise
                if selected is None or not selected.is_enabled():
                    if selected is None and element.get('scroll_hint'):
                        from .android_scroll import seek_observed

                        selected, used_locator, _ = seek_observed(driver, screen, element, config, run_dir / 'STOP')
                        record['locator'] = used_locator
                    if selected is None or not selected.is_enabled():
                        raise AndroidEnvironmentError("Navigation locator is ambiguous, absent or disabled.")
                navigation_action(selected.click)
                after = settled(timeout=20)
                record.update(
                    expected_fingerprint=after["fingerprint"], screen_name=after["screen_name"],
                    destination_observed=True, outcome="observed"
                )
                observed_destinations[locator_key] = screen_key(after)
                if screen_key(after) not in seen:
                    record_screen(after, path + [element["id"]], depth + 1)
            except DiscoveryLimitReached:
                raise
            except Exception as e:
                if device_unavailable(e):
                    raise
                if "left the selected application" in str(e) or "left the approved website" in str(e):
                    # Opening another app (browser, image viewer, store) is not an app failure. It is
                    # recorded, never followed: external content is not inspected.
                    record.update(outcome="left_app", error="Opened content outside the selected app; not followed.")
                    issues.append({"action": label, "error": f"'{label}' opens content outside the app; it was not followed."})
                else:
                    record.update(outcome="inconclusive", error=redact(f"{type(e).__name__}: {e}")[:300])
                    issues.append({"action": label, "error": record["error"]})
            # Always restore before considering another control, including after a failed/external navigation.
            try:
                if not cheap_return(screen):
                    restore(screen)
            except DiscoveryLimitReached:
                raise
            except Exception as e:
                if device_unavailable(e):
                    raise
                try:
                    # One clean relaunch, then replay the recorded path to this screen.
                    relaunch_app()
                    restore(screen)
                except DiscoveryLimitReached:
                    raise
                except Exception as again:
                    if device_unavailable(again):
                        raise
                    reason = f"Could not return to '{screen['screen_name']}' after '{label}'"
                    issues.append({"action": label, "error": reason + ": " + redact(str(again))[:250]})
                    for rest in candidates[position + 1:]:
                        unvisited.append({"screen_id": screen["id"], "element_id": rest["id"],
                                          "label": (rest.get("text") or rest.get("accessibility_id") or "navigation")[:100],
                                          "reason": reason})
                    # Only this screen's remaining controls are skipped; other screens are still explored.
                    return
            print(f"[android] Navigation result: {record.get('outcome', 'inconclusive')}.", flush=True)

    def finish_session(session, stopped):
        replayed = sum(item["meta"].get("discovery_replay") == "passed" for item in session.flows)
        findings = sum(str(item["meta"].get("discovery_replay", "")).startswith("failed twice:") for item in session.flows)
        print(f"[android] Test mode kept {len(session.flows)} flow(s): {replayed} replay-verified, "
              f"{findings} repeatable assertion failure(s), from {session.used} interaction tries.", flush=True)
        print("::stage::test_build::done", flush=True)
        saved = session.saved_secrets()
        if saved:
            # The account test mode registered itself: the final run logs in with it again. Private file only.
            (run_dir / ".private").mkdir(exist_ok=True)
            (run_dir / ".private" / "auto_secrets.json").write_text(json.dumps(saved), encoding="utf-8")
        return {"enabled": True, "flows": session.flows, "tried": session.tried, "findings": session.findings,
                "coverage": session.coverage, "tries_used": session.used, "stopped": stopped,
                "mode": "website" if config.get("app_mode") == "web" else "app",
                "contract": session.contract() if session.flows else None}

    def website_testing():
        """Test mode on a website in Android Chrome (android_site.py): every menu, every page, every feature."""
        nonlocal user_session
        from . import llm
        from .android_site import SiteDevice, SiteSession

        tries = int(config.get("max_interactions") or 0) or 10**9
        device = SiteDevice(driver, config, screens, run_dir / "STOP", deadline, tries,
                            record=lambda screen: record_screen(screen, [], 1))
        session = SiteSession(device, environment=os.environ)
        user_session = session
        ask = None
        if llm.llm_enabled() and not state.get("ai_unavailable"):
            def ask(prompt, shape):
                return llm.ask_structured(prompt, shape, agent="interaction_design", page="android", timeout_s=90)
        print("::stage::test_build::start", flush=True)
        print("[android] Test mode on a website: explore until exhausted "
              "(checkout and payment are never pressed).", flush=True)
        stopped = ""
        try:
            stopped = session.run(ask, config.get("requirements", ""))
        except Exception as error:  # the checks already kept stand even when one part breaks
            from .android_runtime import device_unavailable
            if device_unavailable(error):
                raise
            stopped = "Stopped by an error: " + redact(str(error))[:200]
            issues.append({"error": "Test mode stopped: " + redact(str(error))[:250]})
        finally:
            try:
                from .android_web import reset_site_data
                reset_site_data(driver, config)  # leave the browser as a first-time visitor for the final run
            except Exception:
                pass
        return finish_session(session, stopped)

    def user_like_testing():
        """Act like a manual tester on a test build (android_interact.py), with its own tries and time budget."""
        nonlocal user_session
        nonlocal deadline
        from types import SimpleNamespace

        from . import llm
        from .android import interaction_blocker, reset_app_data
        from .android_interact import Budget

        blocker = interaction_blocker(config)
        if blocker:
            return {"enabled": False, "reason": blocker} if config.get("interaction_testing") else None
        from .android import EXHAUSTIVE_WALL_CLOCK_S
        interaction_timeout = int(config.get("interaction_timeout_s") or 0)
        deadline = time.monotonic() + (interaction_timeout or EXHAUSTIVE_WALL_CLOCK_S)
        # What exploration itself used; the replays of user-like testing restore screens too, which is not exploring
        budget.setdefault("discovery_recovery", budget["recovery"])
        budget["interaction_phase"] = True  # the session counts its own tries; replays are not "recovery"
        package = screens[0]["package_name"]
        if config.get("app_mode") == "web":
            return website_testing()

        def limited(action):
            try:
                return action()
            except DiscoveryLimitReached as e:
                raise Budget(str(e)) from e

        def fresh_start():
            def run():
                reset_app_data(driver, package)
                wait_for_app(30)
                return settled(screens[0], timeout=30)
            return limited(run)

        def go_to(screen):
            fresh_start()
            return limited(lambda: (restore(screen), settled(screen, timeout=15))[1])

        def hide_keyboard():
            """The soft keyboard can cover a form's boxes after a submission: hide it (True when it was shown)."""
            try:
                if driver.is_keyboard_shown():
                    driver.hide_keyboard()
                    return True
            except Exception:
                return False
            return False

        from .android_app import AppSession

        tries = int(config.get("max_interactions") or 0) or 10**9
        device = SimpleNamespace(driver=driver, config=config, screens=screens, stop_path=run_dir / "STOP",
                                 deadline=deadline, max_tries=tries, fresh_start=fresh_start,
                                 go_to=go_to, observe=lambda: limited(lambda: settled(timeout=10)),
                                 hide_keyboard=hide_keyboard)
        # A screen test mode reaches first (Login from the menu) joins the run's screens with its path
        device.record = lambda screen, path: record_screen(screen, path, len(path))
        session = AppSession(device, environment=os.environ)
        user_session = session

        def explore_after_login(flow):
            nonlocal active_authentication_flow, authentication_root_id
            authentication_flows[flow["id"]] = flow
            current = settled(timeout=20)
            if any(e.get("visible") and e.get("input_capable") and e.get("password")
                   for e in current["elements"]):
                return
            normalize_screens([current])
            from .android_runtime import screen_key
            key = screen_key(current)
            if key in seen:
                existing = next(s for s in screens if screen_key(s) == key)
                existing["authentication_flow_id"] = flow["id"]
                existing["authentication_root_id"] = existing["id"]
                existing["authentication_setup_steps"] = flow["steps"]
                existing["path"] = []
                authentication_root_id = existing["id"]
                root = existing
            else:
                authentication_root_id = current["id"]
                active_authentication_flow = flow["id"]
                record_screen(current, [], 0)
                root = current
            active_authentication_flow = flow["id"]
            if not root.get("authentication_setup_steps"):
                root["authentication_flow_id"] = flow["id"]
                root["authentication_root_id"] = root["id"]
                root["authentication_setup_steps"] = flow["steps"]
            pending.append((root, [], 0))
            try:
                while pending:
                    screen, path, depth = pending.popleft()
                    visit(screen, path, depth)
            finally:
                active_authentication_flow = None

        device.on_authenticated = explore_after_login
        ask = None
        if llm.llm_enabled() and not state.get("ai_unavailable"):
            def ask(prompt, shape):
                return llm.ask_structured(prompt, shape, agent="interaction_design", page="android", timeout_s=90)
        print("::stage::test_build::start", flush=True)
        print("[android] Test-build mode: exercising discovered controls, forms and phone behavior.", flush=True)
        stopped = ""
        try:
            stopped = session.run(ask, config.get("requirements", ""))
        except Exception as error:  # the checks already kept stand even when one part breaks
            from .android_runtime import device_unavailable
            if device_unavailable(error):
                raise
            stopped = "Stopped by an error: " + redact(str(error))[:200]
            issues.append({"error": "Test-build mode stopped: " + redact(str(error))[:250]})
        finally:
            try:
                reset_app_data(driver, package)  # restore the disposable test app to a clean launch state
            except Exception:
                pass
        return finish_session(session, stopped)

    interaction, lost = None, False
    try:
        try:
            from .android import interaction_blocker, reset_app_data

            if config.get("app_mode") == "installed" and not interaction_blocker(config):
                # Test-build mode starts every user-like test from cleared data: explore that same fresh app.
                reset_app_data(driver, config["package_name"])
                wait_for_app(30)
            initial = inspect_driver(driver, config)
            launch_deadline = time.monotonic() + 30
            while (not any(e.get("visible") and e.get("locators") and
                           (e.get("text") or e.get("accessibility_id") or e.get("clickable") or e.get("input_capable"))
                           for e in initial["elements"])
                   or (not any(e.get("clickable") or e.get("input_capable") for e in initial["elements"])
                       and re.search(r"splash|loading|please wait", initial.get("activity", "") + " " + initial.get("screen_name", ""), re.I))):
                if time.monotonic() >= launch_deadline:
                    raise AndroidEnvironmentError("App discovery stopped at an unfinished launch screen")
                time.sleep(.3)
                initial = inspect_driver(driver, config)
            config["package_name"] = initial["package_name"]
            stored = run_dir / ".private" / "android_config.json"
            if stored.is_file():
                # Keep package_name and the exported LAUNCHER activity (after splash retry) on disk for pytest.
                try:
                    saved = json.loads(stored.read_text(encoding="utf-8"))
                    changed = False
                    if config.get("app_mode") == "apk" and not saved.get("package_name"):
                        saved["package_name"] = config["package_name"]
                        changed = True
                    if config.get("package_name") and saved.get("package_name") != config["package_name"]:
                        saved["package_name"] = config["package_name"]
                        changed = True
                    if config.get("app_activity") and saved.get("app_activity") != config["app_activity"]:
                        saved["app_activity"] = config["app_activity"]
                        changed = True
                    if changed:
                        stored.write_text(json.dumps(saved, indent=2), encoding="utf-8")
                except (OSError, ValueError):
                    pass
            bound_package = config.get('qa_contract', {}).get('android_package')
            if bound_package and bound_package != config['package_name']:
                raise AndroidEnvironmentError('The uploaded app does not match the package required by these test flows')
            adb = state.get("environment", {}).get("adb")
            if adb:
                try:
                    from .android import _run_cli

                    metadata = _run_cli(
                        adb, ["-s", config["device_id"], "shell", "dumpsys", "package", initial["package_name"]], 10
                    )
                    match = re.search(r"versionName=([^\s]+)", metadata.stdout)
                    if match:
                        config["app_version"] = match.group(1)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            initial = settled(timeout=30)
            record_screen(initial, [], 0)
            if web_test_mode and not interaction_blocker(config):
                pending.clear()  # the website explorer opens every menu and page itself (menus first in its budget)
            while pending:
                screen, path, depth = pending.popleft()
                visit(screen, path, depth)
            restore(screens[0])
        except DiscoveryLimitReached as e:
            reason = str(e)
            issues.append({"error": reason})
            accounted = {a.get("element_id") for a in actions} | {a.get("element_id") for a in unvisited + skipped}
            for screen in screens:
                for element in safe_navigation_elements(screen):
                    if element["id"] not in accounted:
                        unvisited.append({"screen_id": screen["id"], "element_id": element["id"],
                                          "label": element.get("text") or element.get("accessibility_id") or "navigation",
                                          "reason": reason})
        except Exception as e:
            from .android_runtime import device_unavailable

            issues.append({"error": redact(str(e))[:300]})
            lost = device_unavailable(e)
        if screens and not lost and not (run_dir / "STOP").exists():
            try:
                interaction = user_like_testing()
            except Exception as e:  # the safe exploration's evidence stands even if user-like testing breaks
                issues.append({"error": "Test-build mode stopped: " + redact(str(e))[:250]})
                interaction = {"enabled": True, "flows": [], "tried": [], "findings": [], "tries_used": 0,
                               "stopped": "Stopped by an error: " + redact(str(e))[:200], "contract": None}
    finally:
        exploring_recovery = budget.get("discovery_recovery", budget["recovery"])
        if exploring_recovery > 2 * max(1, budget["used"]) and unvisited:
            issues.append({"error": f"Discovery spent most of its time recovering ({exploring_recovery} recovery and "
                                    f"{budget['used']} exploring actions); {len(unvisited)} controls were not reached.",
                           "recovery_heavy": True})
        if getattr(driver, "_blowai_platform_recoveries", []):
            issues.append({"error": "Android System UI recovery was required during discovery.",
                           "platform_recoveries": driver._blowai_platform_recoveries})
        cleanup = close_session(driver)
        if cleanup:
            issues.append({"error": cleanup})
        # Preserve all valid evidence even when the device disappears or quit() fails.
        _save_json(run_dir / "screens.json", screens)
        _save_json(
            run_dir / "android_discovery.json",
            {"actions": actions, "issues": issues, "unvisited": unvisited, "skipped_navigation": skipped,
             "bot_check": bot_check_result(bot_gate),
             "navigation_action_count": budget["used"] + budget.get("authenticated_used", 0),
             "recovery_action_count": budget["recovery"],
             "discovery_recovery_action_count": budget.get("discovery_recovery", budget["recovery"]),
             "cheap_return_action_count": budget.get("cheap", 0),
             'scroll_action_count': budget.get('scroll', 0), 'scroll_recovery_count': budget.get('scroll_recovery', 0)},
        )
    app_map = [
        {
            "url": s.get("web_url") or f"android://{s['package_name']}/{s['id']}",
            "slug": s["id"],
            "title": s["screen_name"],
            "status": 200,
            "platform": "android",
            "activity": s.get("activity"),
            "screenshot": s.get("screenshot"),
            "elements": len(s["elements"]),
            "fingerprint": s["fingerprint"],
        }
        for s in screens
    ]
    _save_json(run_dir / "app_map.json", app_map)
    log = [f"Discovered {len(screens)} screens with {len(actions)} bounded actions."]
    auto_flows = []
    if interaction is not None:
        contract = interaction.pop("contract", None)
        auto_flows = interaction.pop("flows", []) if contract else []
        if contract:
            # Private copy for the trusted runtime; a public copy the person can reuse as approved flows.
            # Do not redact the private contract: assert_text / accessibility_id values often contain the
            # test username (e.g. "Welcome demo user"); redacting them makes execution look for [REDACTED].
            (run_dir / ".private").mkdir(exist_ok=True)
            (run_dir / ".private" / "auto_contract.json").write_text(
                json.dumps(contract, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            _save_json(run_dir / "auto_flows.json", contract)
        _save_json(run_dir / "android_interaction.json", {**interaction, "kept": len(auto_flows)})
        log.append(f"Test-build mode: kept {len(auto_flows)} replay-verified user-like tests from "
                   f"{interaction.get('tries_used', 0)} tries." if interaction.get("enabled")
                   else "Test-build mode not used: " + interaction.get("reason", ""))
    result = {
        "config": config,
        "screens": screens,
        "app_map": app_map,
        "actions": actions,
        "discovery_issues": issues,
        "unvisited": unvisited,
        "auto_flows": auto_flows,
        "interaction": interaction or {},
        "bot_check": bot_check_result(bot_gate),
        "log": state.get("log", []) + log,
    }
    if not screens:
        result["setup_error"] = issues[0]["error"] if issues else "No Android screen was discovered."
    return result


def bot_check_result(gate) -> dict:
    """What the website's bot check did in this run (nothing, finished by itself, completed by a person, blocked)."""
    if gate is None:
        return {}
    return {"blocked": bool(gate.blocked), "message": gate.blocked, "events": list(gate.events)}


def test_design_agent(state):
    from .agents.test_design import test_design_agent as shared

    result = shared({**state, "target_type": "mobile"})
    _save_json(_run_dir(state) / "test_cases.json", result["test_cases"])
    return result


def script_generator_agent(state):
    from .agents.script_generator import script_generator_agent as shared

    return shared({**state, "target_type": "mobile"})


def _parse_junit(path: Path, cases: list[dict]) -> list[dict]:
    if not path.exists():
        return []
    root = ElementTree.parse(path).getroot()
    by_name = {case["id"]: case for case in cases}
    out = []
    for test in root.iter("testcase"):
        test_name = test.attrib.get("name", "")
        case_id = test_name.rsplit("[", 1)[-1].rstrip("]") if "[" in test_name else test_name.removeprefix("test_")
        case = by_name.get(case_id, {})
        failure = test.find("failure")
        error = test.find("error")
        skipped = test.find("skipped")
        issue = failure if failure is not None else error
        detail = ""
        if issue is not None:
            detail = (issue.attrib.get("message", "") + "\n" + (issue.text or "")).strip()[:2000]
        elif skipped is not None:
            detail = (skipped.attrib.get("message", "") + "\n" + (skipped.text or "")).strip()[:1000]
        outcome = (
            "failed"
            if failure is not None
            else "error"
            if error is not None
            else "inconclusive"
            if skipped is not None
            else "passed"
        )
        out.append(
            {
                "id": case_id,
                "title": case.get("title", test.attrib.get("name", "")),
                "file": "test_android_generated.py",
                "test": test_name,
                "exception_type": issue.attrib.get("type", "") if issue is not None else "",
                "outcome": outcome,
                "error": detail,
                "duration_s": float(test.attrib.get("time", 0) or 0),
            }
        )
    return out


def _run_mobile_process(command, env, timeout):
    """Reuse the Windows execution Job Object; timeouts/interrupts close the entire worker tree."""
    job, process, assigned = None, None, False

    def terminate():
        if job is not None and assigned:
            job.kill()
        elif process is not None and process.poll() is None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                os.killpg(process.pid, signal.SIGKILL)

    try:
        if os.name == "nt":
            from .agents.executor import _Job

            job = _Job(memory_mb=1024, max_processes=8)
        kwargs = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        )
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **kwargs,
        )
        if job is not None:
            job.add(process)
            assigned = True
        try:
            output, error = process.communicate(timeout=timeout)
            return subprocess.CompletedProcess(command, process.returncode, output, error), False
        except subprocess.TimeoutExpired:
            terminate()
            output, error = process.communicate(timeout=10)
            return subprocess.CompletedProcess(command, process.returncode, output, error), True
    finally:
        if process is not None and process.poll() is None:
            terminate()
            process.wait(timeout=10)
        if job is not None:
            job.close()


def _cleanup_worker_session(run_dir, config):
    """Close only this run's recorded session, including after forced worker termination."""
    session_file = run_dir / ".private" / "active_appium_session.json"
    if not session_file.exists():
        return ""
    try:
        session_id = json.loads(session_file.read_text(encoding="utf-8"))["session_id"]
        if not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,128}", session_id):
            raise ValueError("Invalid session identifier in worker evidence")
        url = _local_appium_url(config["appium_url"])
        with requests.Session() as client:
            client.trust_env = False
            response = client.delete(url.rstrip("/") + "/session/" + session_id, timeout=(3, 10))
        if response.status_code not in (200, 204, 404):
            raise AndroidEnvironmentError(f"Appium session cleanup returned HTTP {response.status_code}")
        session_file.unlink(missing_ok=True)
        return ""
    except Exception as error:
        return "Could not close this run's Appium session: " + str(error)


def _execute_mobile(state):
    run_dir = _run_dir(state)
    cases = [c for c in state.get("test_cases", []) if not c.get("blocked")]
    script = run_dir / "generated_tests" / "test_android_generated.py"
    if not cases or not script.is_file():
        raise AndroidEnvironmentError("No validated Android scripts are available for execution.")
    error = validate_mobile_script(script.read_text(encoding="utf-8"), cases)
    if error:
        raise AndroidEnvironmentError("Mobile script validation failed before execution: " + error)
    # A resumed execution replaces its incomplete attempt rather than duplicating results.
    events = run_dir / "android_results.jsonl"
    events.unlink(missing_ok=True)
    unavailable_path = run_dir / "android_execution_unavailable.json"
    unavailable_path.unlink(missing_ok=True)
    (run_dir / "android_cleanup.jsonl").unlink(missing_ok=True)
    (run_dir / "android_healing.jsonl").unlink(missing_ok=True)
    from .qa_contracts import contract_case_budget, parse_contract
    from .qa_oracles import resolve_private_inputs

    contract = parse_contract(state["config"].get("qa_contract"))
    inputs_path = run_dir / ".private" / "contract_inputs.json"
    resolved_inputs = resolve_private_inputs(contract)
    if any(c.get("auto_flow_id") for c in cases):
        from .android_interact import flow_secrets
        # Test-mode flows: fresh throwaway values (a wrong password), the account test mode registered during
        # exploration (private file), plus the private test account, if given.
        saved_path = run_dir / ".private" / "auto_secrets.json"
        try:
            saved = json.loads(saved_path.read_text(encoding="utf-8")) if saved_path.is_file() else {}
        except ValueError:
            saved = {}
        resolved_inputs = {**resolved_inputs,
                           "secrets": {**flow_secrets(os.environ, saved), **resolved_inputs["secrets"]}}
    env = clean_env(os.environ.copy())
    env["ANDROID_CONTRACT_INPUTS"] = json.dumps(resolved_inputs)
    env.update(
        PYTHONPATH=str(ROOT),
        PYTHONUTF8="1",
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        ANDROID_MOBILE_CONFIG=str(run_dir / ".private" / "android_config.json"),
        ANDROID_MOBILE_CASES=str(run_dir / "generated_tests" / "android_test_cases.json"),
    )
    junit = run_dir / "android_junit.xml"
    junit.unlink(missing_ok=True)
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--junitxml=" + str(junit), str(script)]
    started = time.monotonic()
    output, returncode, cleanup_error = "", None, ""
    try:
        case_budgets = sum(contract_case_budget(contract, c['contract_id']) if c.get('contract_id')
                           else 150 if c.get('auto_flow_id') else 120 for c in cases)
        timeout = min(3600, case_budgets + state['config'].get('session_timeout_s', 300) + 60)
        completed, timed_out = _run_mobile_process(command, env, timeout)
        output = completed.stdout + completed.stderr
        returncode = None if timed_out else completed.returncode
        if timed_out:
            output += "\nAppium test execution exceeded its bounded time limit; the worker tree was terminated."
    except subprocess.TimeoutExpired:
        output = "Appium test execution exceeded its bounded time limit."
    except OSError as e:
        output = "Could not start the Appium test runner: " + str(e)
    finally:
        cleanup_error = _cleanup_worker_session(run_dir, state["config"])
        inputs_path.unlink(missing_ok=True)
    results = read_jsonl(events) or _parse_junit(junit, cases)
    unavailable = json.loads(unavailable_path.read_text(encoding="utf-8")) if unavailable_path.exists() else None
    from . import runctl
    stop_kind = runctl.kind()
    user_stopped = stop_kind in {"user_stop", "ctrl_c"} or ((run_dir / "STOP").exists() and not unavailable)
    if user_stopped:
        for result in results:
            if result.get("outcome") == "error" and "stopped by the user" in result.get("error", "").casefold():
                result.update(
                    outcome="blocked",
                    exception_type="UserStoppedRun",
                    error="Not executed because the user stopped the Android run.",
                )
    if cleanup_error and not unavailable:
        results.append(
            {
                "id": "android_forced_cleanup",
                "title": "Appium session cleanup",
                "outcome": "error",
                "exception_type": "AndroidEnvironmentError",
                "error": cleanup_error,
                "file": script.name,
                "test": "session_cleanup",
            }
        )
    by_id = {c["id"]: c for c in cases}
    for result in results:
        result["title"] = by_id.get(result["id"], {}).get("title", result["id"])
    actual = {r["id"] for r in results}
    for case in cases:
        if case["id"] not in actual:
            results.append(
                {
                    "id": case["id"],
                    "title": case["title"],
                    "outcome": "blocked" if unavailable else "error",
                    "error": ("Not executed after Android/session became unavailable: " + unavailable["error"])
                    if unavailable else output[-2000:] or "No execution evidence was produced.",
                    "exception_type": "AndroidEnvironmentError",
                    "file": script.name,
                    "test": "test_" + case["id"],
                }
            )
    if actual == set(by_id) and (
        returncode not in (0, 1)
        or returncode == 1
        and not any(result["outcome"] in ("failed", "error") for result in results)
    ):
        results.append(
            {
                "id": "android_execution",
                "title": "Runner infrastructure",
                "outcome": "error",
                "error": output[-2000:] or "Pytest failed outside the recorded test calls.",
                "exception_type": "AndroidEnvironmentError",
                "file": script.name,
                "test": "runner",
            }
        )
    for case in state.get("test_cases", []):
        if case.get("blocked"):
            results.append(
                {
                    "id": case["id"],
                    "title": case["title"],
                    "outcome": "blocked",
                    "error": case.get("automation_note", ""),
                    "file": script.name,
                    "test": "blocked",
                }
            )
    duration = round(time.monotonic() - started, 2)
    _save_json(run_dir / "results.json", results)
    _save_json(
        run_dir / "execution.json",
        {
            "runner": "pytest + Appium Python Client",
            "duration_s": duration,
            "returncode": returncode,
            "return_output": output[-6000:],
        },
    )
    result = {"results": results, "execution_duration_s": duration}
    if user_stopped:
        result.update(incomplete=True, incomplete_reason="The mobile run was stopped by the user.",
                      stop_kind=stop_kind or "user_stop")
    if unavailable:
        result.update(incomplete=True, incomplete_reason="Android execution stopped after device/session loss: " + unavailable["error"])
        _save_json(run_dir / "android_cleanup.json", {"error": cleanup_error, "events": read_jsonl(run_dir / "android_cleanup.jsonl")})
    return result


def read_jsonl(path):
    rows = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def failure_analysis_agent(state):
    from .agents.failure_analysis import failure_analysis_agent as shared

    return shared({**state, "target_type": "mobile"})


def execution_agent(state):
    from .agents.executor import execution_agent as shared

    return shared({**state, "target_type": "mobile"})


def self_healing_agent(state):
    from .agents.self_healing import self_healing_agent as shared

    return shared({**state, "target_type": "mobile"})


def reporter_agent(state):
    from .agents.reporter import reporter_agent as shared

    return shared({**state, "target_type": "mobile"})
