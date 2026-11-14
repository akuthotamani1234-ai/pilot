"""Reviewable AI scenarios bound to controls observed in this application's run."""
import json
from typing import Literal

from pydantic import Field

from .android_interact import usable
from .finalization import read_json
from .qa_contracts import Model, parse_contract
from .safety import redact


class DraftStep(Model):
    action: Literal["tap", "fill", "assert_text", "assert_visible", "assert_not_visible", "assert_enabled", "hide_keyboard"]
    target: str | None = Field(default=None, max_length=20)
    value: str | None = Field(default=None, max_length=300)
    secret_ref: str | None = Field(default=None, pattern=r"^BLOWAI_SECRET_[A-Z0-9_]+$")


class Draft(Model):
    title: str = Field(min_length=1, max_length=180)
    expected_basis: str = Field(min_length=1, max_length=1000)
    steps: list[DraftStep] = Field(min_length=1, max_length=40)


def inventory(root):
    screens = read_json(root / "screens.json", [])
    screens += read_json(root / "android_interaction.json", {}).get("state_inventory", [])
    aliases = {}
    for screen in screens:
        for element in screen.get("elements", []):
            if not usable(element):
                continue
            alias = f"E{len(aliases) + 1}"
            label = element.get("accessibility_id") or element.get("resource_id") or element.get("hint")
            if not label and not element.get("input_capable"):
                label = element.get("text", "")
            aliases[alias] = {"locator": element["locators"][0], "screen": screen.get("screen_name", "Screen"),
                              "label": label or "input", "input": bool(element.get("input_capable")),
                              "password": bool(element.get("password"))}
            if len(aliases) >= 300:
                return aliases, screens
    return aliases, screens


def draft(root, instructions: str, ask=None):
    if not instructions.strip() or len(instructions) > 6000:
        raise ValueError("Describe the workflow and expected outcome in 1–6000 characters.")
    aliases, screens = inventory(root)
    if not aliases:
        raise ValueError("Run discovery first so the draft can use observed controls.")
    if ask is None:
        from .llm import ask_structured
        ask = ask_structured
    prompt = ("Draft ONE Android QA workflow from the request. Return title, expected_basis, steps. "
              "Use ONLY target aliases below, never invent a locator, credentials, account, or a successful outcome. "
              "Include explicit result assertions based on the user's requirements. All fill steps must use "
              "BLOWAI_SECRET_* references supplied in the request; omit flows requiring unknown credentials. "
              "No payment, purchase, destructive actions or permissions. This is an unexecuted draft for human review. "
              "Screen paths may require extra navigation: include it only when established by these controls.\nRequest:\n"
              + redact(instructions) + "\nObserved controls (first 300 maximum; not exhaustive):\n"
              + redact(json.dumps(aliases, ensure_ascii=False)))
    proposal = ask(prompt, Draft, agent="android_scenario_draft", timeout_s=45)
    steps = []
    for item in proposal.steps:
        step = {"action": item.action}
        if item.action != "hide_keyboard":
            if item.target not in aliases:
                raise ValueError("The draft referenced a control that was not observed.")
            step["locator"] = aliases[item.target]["locator"]
        if item.action == "fill":
            if not item.secret_ref or not aliases[item.target]["input"]:
                raise ValueError("Draft form inputs require private test-data references and an observed input.")
            step["secret_ref"] = item.secret_ref
        elif item.value is not None:
            step["value"] = item.value
        if item.action == "tap":
            step["purpose"] = "test_form"
        steps.append(step)
    packages = {screen.get("package_name") for screen in screens if screen.get("package_name")}
    raw = {"version": 1, "test_environment": False, "flows": [{"id": "draft_scenario", "title": proposal.title,
            "approved": False, "steps": steps}]}
    if len(packages) == 1:
        raw["android_package"] = next(iter(packages))
    contract = parse_contract(raw)
    return {"contract": contract.model_dump(mode="json", exclude_defaults=True, exclude_none=True),
            "expected_basis": redact(proposal.expected_basis), "observed_controls": len(aliases),
            "note": "AI draft only. Review navigation, expected behavior and private data references, then approve the flow and test environment. Nothing has executed."}
