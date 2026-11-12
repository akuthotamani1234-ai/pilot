"""Evidence-backed mobile design and strictly constrained AI Python generation."""

import ast
import hashlib
import json
import time
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from . import llm
from .safety import redact

METHODS = {"open_screen", "assert_visible", "assert_enabled", "assert_text", "tap", "assert_screen", "assert_destination",
           "assert_contract", "assert_flow"}


class MobileProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=180)
    screen_id: str
    element_ids: list[str] = Field(min_length=1, max_length=10)
    category: str = "ui_validation"
    priority: str = "medium"
    description: str = Field(default="", max_length=500)


def screen_id(screen: dict) -> str:
    evidence = str((screen.get("package_name"), screen.get("activity"), screen.get("fingerprint")))
    return "screen_" + hashlib.sha256(evidence.encode()).hexdigest()[:12]


def normalize_screens(screens: list[dict]) -> list[dict]:
    for screen in screens:
        sid = screen.setdefault("id", screen_id(screen))
        screen.setdefault("path", [])
        for index, element in enumerate(screen.get("elements", [])):
            element.setdefault("id", f"{sid}:e{index:04d}")
    return screens


def normalize_case(case: dict) -> dict:
    """The mobile adapter fills the same fields used by status, Excel and web reporting."""
    case = dict(case)
    cid = case["id"]
    sid = case.get("screen_id", "launch")
    plan = case.get("plan", [])
    case.update(
        target_type="mobile",
        platform="android",
        page=sid,
        pages=[sid],
        tc_id=case.get("tc_id") or "TC-" + hashlib.sha256(cid.encode()).hexdigest()[:8].upper(),
        url=case.get("url", "android://app/" + sid),
        feature=case.get("category", "smoke"),
        element=", ".join(case.get("element_ids", [])),
        scenario="workflow" if case.get("kind") in ("navigation", "interaction") else "happy",
        risk=case.get("risk", "medium"),
        priority=case.get("priority", "medium"),
        preconditions=["Authorized Android app and available device", "App opens on its observed start screen"]
        + (["Test mode: the test starts fresh (app data, or this website's cookies and storage, cleared)"]
           if case.get("reset_app_data") else []),
        test_data="",
        test_data_ref="none",
        actual_result="",
        evidence=[],
        requirement=case.get("requirement", "Discovered UI evidence"),
        skip_reason=case.get("skip_reason", ""),
        steps=[method + " " + ", ".join(map(str, args)) for method, args in plan] or ["Review this blocked scenario"],
        automation_status="Not automated" if case.get("blocked") else "Pending",
        execution_status="Not run",
        files=[] if case.get("blocked") else ["test_android_generated.py"],
        tests=[] if case.get("blocked") else ["test_" + cid],
        generation_source=case.get("generation_source", "rule"),
        functionality_status=case.get("functionality_status", "confirmed"),
    )
    return case


def design_cases(state: dict) -> dict:
    screens = normalize_screens(state.get("screens", []))
    from .qa_contracts import contract_cases, parse_contract

    def normalize(case):
        if state["config"].get("app_mode") == "web":
            owner = next((s for s in screens if s["id"] == case.get("screen_id")), {})
            case = {**case, "url": owner.get("web_url") or state["config"]["start_url"]}
        return normalize_case(case)

    cases = contract_cases(parse_contract(state["config"].get("qa_contract")))
    if state["config"].get("contract_only"):
        limit = state["config"].get("max_test_cases", 100)
        return {"screens": screens, "test_cases": [normalize(c) for c in cases[:limit]],
                "cases_left_out": max(0, len(cases) - limit),
                "log": state.get("log", []) + [f"Designed {min(limit, len(cases))} explicit QA contract cases."]}
    if screens:
        first = screens[0]
        visible = [e for e in first["elements"] if e.get("visible") and e.get("locators")]
        visible = [
            e
            for e in visible
            if e.get("accessibility_id") or e.get("resource_id") or e.get("text") or e.get("input_capable")
        ]
        visible.sort(
            key=lambda e: (not bool(e.get("accessibility_id") or e.get("resource_id")), e.get("type") != "text")
        )
        if visible:
            cases.append(
                {
                    "id": "android_launch_screen",
                    "title": "The app launches with visible UI",
                    "kind": "screen",
                    "type": "screen",
                    "screen_id": first["id"],
                    "priority": "high",
                    "element_ids": [visible[0]["id"]],
                    "expected": "The discovered start control is visible.",
                    "plan": [["open_screen", [first["id"]]], ["assert_visible", [visible[0]["id"]]]],
                }
            )
    destinations = state["config"].get("expected_destinations", {})
    by_fingerprint = {s["fingerprint"]: s for s in screens}
    for index, action in enumerate(state.get("actions", []), 1):
        if action.get("outcome") != "observed":
            continue
        screen = by_fingerprint.get(action["before_fingerprint"])
        if not screen:
            continue
        element = next((e for e in screen["elements"] if action["locator"] in e.get("locators", [])), None)
        if element is None:
            continue
        label = " ".join(action["label"].split())
        destination = destinations.get(label.strip().casefold())
        reached = by_fingerprint.get(action.get("expected_fingerprint"), {}).get("screen_name") or "its screen"
        plan = [["open_screen", [screen["id"]]], ["tap", [element["id"]]]]
        # Unknown destinations are observed regression evidence, not confirmed functionality.
        if destination:
            plan.append(["assert_screen", [destination]])
        elif state["config"].get('verify_observed_navigation') and action.get('destination_observed') and action.get('expected_fingerprint') in by_fingerprint:
            observed = by_fingerprint[action['expected_fingerprint']]
            plan.append(['assert_destination', [observed['id']]])
        else:
            plan = [["open_screen", [screen["id"]]], ["assert_visible", [element["id"]]]]
        cases.append(
            {
                "id": f"android_navigation_{index:03d}",
                # Titles say the user action and the expected result, not the control's internal name
                "title": f"Open {label}" if destination else f"Tap '{label}' on {screen['screen_name']}: '{reached}' opens"
                if len(plan) == 3 else f"'{label}' is shown on {screen['screen_name']}",
                "kind": "navigation" if len(plan) == 3 else "ui",
                "type": "mobile_navigation",
                "screen_id": screen["id"],
                "category": "navigation",
                "element_ids": [element["id"]],
                "locator": action["locator"],
                "expected_screen_name": destination,
                "before_fingerprint": action["before_fingerprint"],
                "expected_fingerprint": action.get("expected_fingerprint"),
                "plan": plan,
                "expected": f"The app opens {destination}."
                if destination
                else "Safe navigation reaches the destination recorded during discovery; business correctness needs requirements."
                if len(plan) == 3 else "The observed navigation control is visible; destination needs requirements.",
                "functionality_status": "confirmed" if destination else "inferred",
                "requirement": "User-supplied navigation expectation"
                if destination
                else "Observed navigation regression evidence" if len(plan) == 3 else "Discovered UI only; destination not verified",
            }
        )
    from .android import safe_navigation_elements

    blocked = []
    sampled_out = 0
    for screen in screens:
        safe = safe_navigation_elements(screen)
        for element in screen["elements"]:
            if element.get("visible") and (
                element.get("input_capable") or element.get("clickable") and element not in safe
            ):
                blocked.append(element["id"])
        # Whole-app mode checks each unique discovered control in one screen-level
        # case. This keeps broad coverage practical while never submitting forms.
        ui_families = set()
        assertions = []
        checked_elements = []
        for element in screen["elements"]:
            if (
                (element.get("visible") or element.get("requires_scroll"))
                and element.get("locators")
                and element.get("locator_unique", True)
                and not element.get("outside_active_drawer")
                and not element.get("within_webview")
                and (element.get("input_capable") or element.get("accessibility_id") or element.get("resource_id")
                     or any(c.isalnum() for c in element.get("text", "")))
                and (element.get("input_capable") or element.get("clickable") or element.get("type") == "text")
            ):
                family = (element.get('class_name'), element.get('accessibility_id')
                          or element.get('resource_id') or element.get('text'))
                if family in ui_families:
                    sampled_out += 1
                    continue
                ui_families.add(family)
                checked_elements.append(element["id"])
                # Check all top-viewport controls first; observed offscreen controls
                # run afterward so scrolling cannot hide later top-viewport checks.
                element_assertions = [["assert_visible", [element["id"]]]]
                if element.get("clickable") or element.get("input_capable"):
                    element_assertions.append(["assert_enabled", [element["id"], "true" if element.get("enabled") else "false"]])
                expected_value = state["config"].get("expected_values", {}).get(
                    (element.get("accessibility_id") or "").casefold()
                )
                if element.get("input_capable"):
                    expected_value = None  # Never embed input values/credentials in code or AI prompts.
                if expected_value is not None or element.get("text") and element.get("text_comparable", True):
                    element_assertions.append(
                        [
                            "assert_text",
                            [element["id"], expected_value if expected_value is not None else element["text"]],
                        ]
                    )
                assertions.append((bool(element.get("requires_scroll")), element["id"], element_assertions,
                                   expected_value is not None))
        if checked_elements:
            ordered = sorted(assertions, key=lambda item: item[0])
            # Small batches keep checks isolated: a stale control should not
            # prevent the rest of the screen from being inspected.
            batch_size = 12
            for batch_index, start in enumerate(range(0, len(ordered), batch_size)):
                batch = ordered[start:start + batch_size]
                screen_plan = [["open_screen", [screen["id"]]]]
                for _, _, element_assertions, _ in batch:
                    screen_plan.extend(element_assertions)
                batch_elements = [element_id for _, element_id, _, _ in batch]
                supplied = [user_value for _, _, _, user_value in batch]
                requirement = ("User-supplied expected displayed value" if all(supplied)
                               else "User-supplied expected displayed values and observed UI regression evidence"
                               if any(supplied) else "Observed UI regression evidence")
                cases.append(
                    {
                        "id": "android_ui_" + hashlib.sha256(f"{screen['id']}:{batch_index}".encode()).hexdigest()[:12],
                        "title": f"Verify discovered controls {start + 1}-{start + len(batch)} on " + (screen.get("screen_name") or "Android screen")[:80],
                        "kind": "ui",
                        "type": "ui_validation",
                        "screen_id": screen["id"],
                        "category": "ui_validation",
                        "element_ids": batch_elements,
                        "expected": f"All {len(batch_elements)} unique discovered controls in this check match their observed visibility, enabled state, and labels.",
                        "requirement": requirement,
                        "plan": screen_plan,
                    }
                )
    notes = []
    if llm.llm_enabled() and not state.get("ai_unavailable") and screens:
        screen_aliases = {f"S{index}": screen for index, screen in enumerate(screens[:8], 1)}
        element_aliases = {}
        evidence = []
        for alias, screen in screen_aliases.items():
            compact = []
            for element in screen["elements"]:
                if (
                    not element.get("visible")
                    or element.get("outside_active_drawer")
                    or element.get("within_webview")
                    or not (element.get("input_capable") or element.get("accessibility_id") or element.get("resource_id")
                            or any(c.isalnum() for c in element.get("text", "")))
                    or not element.get("locators")
                    or not element.get("locator_unique", True)
                    or element.get("type") not in ("text", "button", "input")
                ):
                    continue
                eid = f"E{len(element_aliases) + 1}"
                element_aliases[eid] = element["id"]
                compact.append(
                    {
                        "id": eid,
                        "type": element["type"],
                        "label": element.get("accessibility_id") or element.get("text"),
                    }
                )
                if len(compact) >= 12:
                    break
            evidence.append({"screen_id": alias, "name": screen["screen_name"], "elements": compact})
        prompt = (
            "Return ONLY a JSON array of at most 3 Android UI test proposals. Each test checks ONE or TWO visible controls. "
            "Use the exact short S/E references in this inventory; never invent a reference. No actions or credentials. "
            'Example shape: [{"title":"Heading is visible","screen_id":"S1","element_ids":["E1"],'
            '"category":"ui_validation","priority":"medium","description":"Read-only visibility check"}].\n'
        )
        prompt += json.dumps(
            {
                "screens": evidence,
                "requirements": state["config"].get("requirements", ""),
                "expected_destinations": destinations,
            }
        )
        try:
            if not element_aliases:
                raise ValueError("No eligible observed UI controls for AI design.")
            bound_proposal = create_model(
                "ObservedMobileProposal",
                __base__=MobileProposal,
                screen_id=(Literal[tuple(screen_aliases)], ...),
                element_ids=(list[Literal[tuple(element_aliases)]], Field(min_length=1, max_length=2)),
            )
            shape = Annotated[list[bound_proposal], Field(max_length=3)]
            proposals = llm.ask_structured(prompt, shape, agent="test_design", page="android", timeout_s=90)
            for index, proposal in enumerate(proposals[:3], 1):
                screen = screen_aliases.get(proposal.screen_id) or next(
                    (s for s in screens if s["id"] == proposal.screen_id), None
                )
                proposal.element_ids = [element_aliases.get(eid, eid) for eid in proposal.element_ids]
                if screen is None:
                    notes.append("Rejected an AI proposal with an undiscovered screen.")
                    continue
                elements = {e["id"]: e for e in screen["elements"] if e.get("visible") and e.get("locators")}
                if any(eid not in elements for eid in proposal.element_ids):
                    notes.append("Rejected an AI proposal with undiscovered elements.")
                    continue
                plan = [["open_screen", [screen["id"]]]] + [["assert_visible", [eid]] for eid in proposal.element_ids]
                cases.append(
                    {
                        "id": f"android_ai_{index:03d}",
                        "title": "UI: " + proposal.title,
                        "description": proposal.description,
                        "screen_id": screen["id"],
                        "element_ids": proposal.element_ids,
                        "kind": "ui",
                        "type": "ui_validation",
                        "category": proposal.category,
                        "priority": proposal.priority if proposal.priority in ("high", "medium", "low") else "medium",
                        "expected": "The referenced discovered controls are visible.",
                        "plan": plan,
                        "generation_source": "llm",
                    }
                )
        except (llm.LLMError, ValueError) as e:
            if not state["config"].get("allow_rules_fallback", True):
                raise llm.LLMError("Selected Android AI failed; rules fallback was not approved: " + redact(str(e))[:250]) from e
            notes.append("AI design fell back to rules: " + redact(str(e))[:250])
    # Test-build mode: replay-verified user-like flows (forms, undoable actions, phone checks, AI journeys).
    from .android_interact import auto_cases

    interaction_cases = auto_cases(state.get("auto_flows", []))
    cases.extend(interaction_cases)
    authenticated_ids = {screen["id"] for screen in screens if screen.get("authentication_flow_id")}
    for case in cases:
        if case.get("screen_id") in authenticated_ids and case.get("kind") != "interaction":
            # Each authenticated UI/navigation check starts from clean app data;
            # MobileRuntime then replays the private login flow before opening it.
            case["reset_app_data"] = True
    exercised = {eid for case in interaction_cases for eid in case.get("element_ids", [])}
    blocked = [eid for eid in blocked if eid not in exercised]
    # Navigation, configured behavior and user-like flows are kept first when the case limit applies.
    if cases:
        cases.sort(
            key=lambda case: 0
            if case.get("kind") == "contract"
            else 0
            if case["id"] == "android_launch_screen"
            else 1
            if case.get("kind") in ("navigation", "interaction")
            else 2
            if case.get("generation_source") == "llm"
            else 3
        )
    limit = state["config"].get("max_test_cases", 100)
    omitted = max(0, len(cases) - limit)
    cases = cases[:limit]
    # User-like flows change app data (a cart, a switch): run them after the read-only checks. Each one starts
    # from cleared data itself, so a change made by one never leaks into another.
    cases = [c for c in cases if c.get("kind") != "interaction"] + [c for c in cases if c.get("kind") == "interaction"]
    if blocked:
        cases.append(
            {
                "id": "android_blocked_controls",
                "title": "Controls not exercised during safe discovery",
                "kind": "blocked",
                "type": "blocked",
                "blocked": True,
                "blocked_count": len(blocked),
                "element_ids": blocked,
                "functionality_status": "blocked",
                "automation_note": f"{len(blocked)} controls were not exercised by discovery; consult explicit approved-flow results for functional coverage.",
                "expected": "Only explicitly approved test flows may interact with these controls.",
            }
        )
    return {
        "screens": screens,
        "ai_warnings": state.get("ai_warnings", []) + [note for note in notes if "fell back to rules" in note],
        "test_cases": [normalize(c) for c in cases],
        "cases_left_out": omitted,
        "android_design_scope": {'sampled_ui_checks_left_out': sampled_out,
                                 'observed_navigation_checks': sum(c.get('kind') == 'navigation' and not c.get('expected_screen_name') for c in cases)},
        "log": state.get("log", []) + notes + [f"Designed {len(cases)} Android cases; {omitted} omitted by the limit; {sampled_out} repetitive UI checks sampled out."],
    }


def validate_mobile_script(code: str, cases: list[dict]) -> str | None:
    """Only literal calls to the frozen, evidence-backed plan are executable. No arbitrary Python."""
    try:
        if len(code) > 200000:
            return "Mobile code exceeds the bounded size limit."
        tree = ast.parse(code)
        expected = {"test_" + c["id"]: c for c in cases if not c.get("blocked")}
        seen = set()
        for node in tree.body:
            if isinstance(node, ast.Import) and all(a.name == "pytest" and not a.asname for a in node.names):
                continue
            if (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and node.module == "appium.webdriver.common.appiumby"
                and all(a.name == "AppiumBy" and not a.asname for a in node.names)
            ):
                continue
            if (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                continue
            if not isinstance(node, ast.FunctionDef) or node.name not in expected or node.name in seen:
                return "Only the expected test functions are allowed."
            if (
                node.decorator_list
                or node.returns
                or node.args.defaults
                or node.args.kw_defaults
                or node.args.posonlyargs
                or node.args.kwonlyargs
                or node.args.vararg
                or node.args.kwarg
                or [a.arg for a in node.args.args] != ["mobile"]
                or node.args.args[0].annotation
            ):
                return "Every test must take only the mobile fixture, without annotations or decorators."
            calls = []
            for statement in node.body:
                if (
                    isinstance(statement, ast.Expr)
                    and isinstance(statement.value, ast.Constant)
                    and isinstance(statement.value.value, str)
                ):
                    continue
                if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
                    return "Only calls to approved mobile actions are allowed."
                call = statement.value
                if (
                    not isinstance(call.func, ast.Attribute)
                    or not isinstance(call.func.value, ast.Name)
                    or call.func.value.id != "mobile"
                    or call.func.attr not in METHODS
                    or call.keywords
                    or any(not isinstance(arg, ast.Constant) or not isinstance(arg.value, str) for arg in call.args)
                ):
                    return "Invalid mobile action or nonliteral argument."
                calls.append([call.func.attr, [arg.value for arg in call.args]])
            if calls != expected[node.name]["plan"] or not any(method.startswith("assert_") for method, _ in calls):
                return "The script must preserve every approved step and assertion, in order."
            seen.add(node.name)
        if seen != set(expected):
            return "Some expected tests are missing."
    except (SyntaxError, ValueError, TypeError, KeyError, AttributeError) as e:
        return "Invalid mobile script: " + str(e)[:200]
    return None


def generate_scripts(state: dict) -> dict:
    run_dir = Path(state["run_dir"])
    test_dir = run_dir / "generated_tests"
    test_dir.mkdir(exist_ok=True)
    cases = [c for c in state.get("test_cases", []) if not c.get("blocked")]
    if not cases:
        return {"scripts": [], "script_errors": ["No executable cases were designed."]}
    screens = {screen["id"]: screen for screen in state.get("screens", [])}
    elements = {e["id"] for screen in screens.values() for e in screen["elements"]}
    for case in cases:
        if screens:
            for method, args in case["plan"]:
                if (
                    method in {"open_screen", "assert_destination"}
                    and args[0] not in screens
                    or method in ("tap", "assert_visible", "assert_enabled", "assert_text")
                    and args[0] not in elements
                ):
                    raise ValueError("The mobile plan references undiscovered evidence.")
    code = (
        "\n\n".join(
            "def test_"
            + c["id"]
            + "(mobile):\n"
            + "\n".join(
                "    mobile." + method + "(" + ", ".join(repr(arg) for arg in args) + ")" for method, args in c["plan"]
            )
            for c in cases
        )
        + "\n"
    )
    source, errors = "template", []
    if llm.llm_enabled() and not state.get("ai_unavailable"):
        try:
            signatures = "\n".join("def test_" + c["id"] + "(mobile):" for c in cases)
            prompt = (
                "Return ONLY Python code with exactly these function signatures, no classes or extra functions:\n"
                + signatures
                + "\nTranslate each plan below to calls on mobile, in order. Preserve EVERY literal reference and assertion. "
                'Example plan [["open_screen",["S1"]],["assert_visible",["E1"]]] becomes '
                "mobile.open_screen('S1') then mobile.assert_visible('E1') in the function body. "
                "Only allowed statements are those exact calls. The assert_* methods already assert internally and return None: call them directly, never wrap them in assert. Do not add imports, decorators, variables or driver access.\n"
                + json.dumps([{k: c[k] for k in ("id", "plan")} for c in cases])
            )
            deadline = time.monotonic() + 90
            for attempt in range(2):
                proposed = llm.extract_code(llm.ask_llm(prompt, agent="script_generator", page="android",
                                                       timeout_s=max(0, deadline - time.monotonic())))
                error = validate_mobile_script(proposed, cases)
                if not error:
                    code, source = proposed, "llm"
                    break
                private = run_dir / ".private"
                private.mkdir(exist_ok=True)
                (private / f"rejected_mobile_code_{attempt + 1}.txt").write_text(redact(proposed), encoding="utf-8")
                if attempt:
                    raise llm.LLMError(error)
                prompt += (
                    "\nYour previous answer was rejected: "
                    + error
                    + "\nReturn exactly the requested functions and frozen calls."
                )
        except (llm.LLMError, ValueError) as e:
            if not state["config"].get("allow_rules_fallback", True):
                raise llm.LLMError("Selected Android AI script generation failed; template fallback was not approved: " + redact(str(e))[:250]) from e
            errors.append("AI script rejected; validated template fallback: " + redact(str(e))[:250])
    error = validate_mobile_script(code, cases)
    if error:
        raise ValueError(error)
    destination = test_dir / "test_android_generated.py"
    destination.write_text("# generated by: " + source + "\n" + code, encoding="utf-8")
    template = Path(__file__).parent / "templates" / "android_conftest.py"
    (test_dir / "conftest.py").write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    (test_dir / "pytest.ini").write_text("[pytest]\npython_files = test_*.py\n", encoding="utf-8")
    (test_dir / "android_test_cases.json").write_text(json.dumps(cases, indent=2), encoding="utf-8")
    for case in state.get("test_cases", []):
        if not case.get("blocked"):
            case["script_source"] = source
            case["automation_status"] = "Automated"
    from .excel import write_workbook

    write_workbook(run_dir, state["test_cases"])
    return {
        "scripts": [str(destination)],
        "ai_warnings": state.get("ai_warnings", []) + errors,
        "script_sources": {destination.name: source},
        "script_errors": errors,
        "test_cases": state["test_cases"],
        "log": state.get("log", []) + errors + ["Validated Appium scripts: " + source],
    }
