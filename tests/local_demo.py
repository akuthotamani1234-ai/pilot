"""Run the real Qpilot web graph against the controlled quote fixture."""
import argparse
import json
from datetime import datetime
from pathlib import Path

from tests.accuracy_benchmark import run_agent
from tests.qa_contract_fixture import ContractFixture


def quote_contract():
    def locator(selector):
        return {"strategy": "css", "value": selector}

    return {"version": 1, "test_environment": True, "rules": [{
        "id": "quote_total", "title": "Displayed total equals quantity times unit price",
        "actual": locator("#total"), "expression": "quantity * price",
        "variables": {"quantity": {"locator": locator("#quantity")}, "price": {"locator": locator("#price")}},
    }]}


def run_scenario(work, mode, model):
    work.mkdir(parents=True)
    with ContractFixture(work / "fixture.sqlite", broken=mode == "seeded", demo_links=True) as fixture:
        options = {
            "QA_CONTRACT_JSON": json.dumps(quote_contract()), "QA_CONTRACT_ONLY": "1" if mode == "targeted" else "0",
            "QPILOT_CONCURRENT_CONTRACT": "1", "REVIEW": "off", "TEST_WORKERS": "2", "SWARM_SAMPLE": "2",
            "VISION": "off", "HARD_PAGE_CAP": "5", "SLACK_WEBHOOK_URL": "", "JIRA_URL": "",
            "LLM_PROVIDER": "ollama" if model else "none", "LLM_MODEL": model, "USE_SAVED_ACCOUNT": "false",
            "BLOWAI_PRIVACY_MODE": "local",
        }
        run, _ = run_agent(fixture, work, options, account=())
    results = json.loads((run / "results.json").read_text(encoding="utf-8"))
    rows = [row for row in results if row.get("contract_id") == "quote_total"]
    expected = "failed" if mode == "seeded" else "passed"
    correct = len(rows) == 1 and rows[0]["outcome"] == expected
    overlap_file = run / "contract_overlap.json"
    overlap = json.loads(overlap_file.read_text(encoding="utf-8")) if overlap_file.exists() else {}
    report = run / "report.html"
    ai = json.loads((run / "cost.json").read_text(encoding="utf-8"))
    return {"mode": mode, "report": str(report), "quote_outcomes": [row["outcome"] for row in rows],
            "overlap": overlap, "ai_calls": ai.get("calls"), "failed_ai_calls": ai.get("failed_calls"),
            "provider": ai.get("provider"),
            "passed": bool(correct and report.is_file()
                           and (len(results) == 1 if mode == "targeted"
                                else "contract_quote_total" in overlap.get("overlapped_cases", []))
                           and (not model or (ai.get("calls", 0) > ai.get("failed_calls", 0)
                                              and ai.get("tokens_out", 0) > 0 and ai.get("provider") == "ollama")))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["clean", "seeded", "targeted", "all"], default="all")
    parser.add_argument("--ollama-model", default="", help="Use the specified installed local model.")
    args = parser.parse_args()
    root = Path("runs/local-demo").resolve() / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    root.mkdir(parents=True)
    results = []
    for mode in (["clean", "seeded", "targeted"] if args.mode == "all" else [args.mode]):
        try:
            results.append(run_scenario(root / mode, mode, args.ollama_model))
        except (RuntimeError, ValueError, OSError) as exc:
            results.append({"mode": mode, "passed": False, "error": str(exc)})
        (root / "evidence.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"{mode}: {results[-1]['passed']} ({root / 'evidence.json'})", flush=True)
    return int(any(not row["passed"] for row in results))


if __name__ == "__main__":
    raise SystemExit(main())
