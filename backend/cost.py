"""Cost tracking: every LLM call is recorded (tokens, time, $) so a run can say
"this run cost $X" and "each test case cost $Y end-to-end".

  runs/<run>/llm_usage.jsonl  -> one line per LLM call (written live, the web UI reads it)
  runs/<run>/cost.json        -> the final cost report (written by the Report step)

Prices are ESTIMATES from public list prices (USD per 1 million tokens). Override them in .env:
  LLM_PRICE_INPUT_PER_M=0.30   LLM_PRICE_OUTPUT_PER_M=2.50
Ollama runs on your own machine, so its AI cost is always $0.
"""
import json
import os
import time
from pathlib import Path

from .config import settings

# (input $, output $) per 1M tokens. Matched by the longest key contained in the model name.
PRICES = {
    "openai": {
        "gpt-4o-mini": (0.15, 0.60), "gpt-4o": (2.50, 10.00),
        "gpt-4.1-nano": (0.10, 0.40), "gpt-4.1-mini": (0.40, 1.60), "gpt-4.1": (2.00, 8.00),
        "gpt-5-nano": (0.05, 0.40), "gpt-5-mini": (0.25, 2.00), "gpt-5": (1.25, 10.00),
        "": (0.15, 0.60),
    },
    "gemini": {
        "flash-lite": (0.10, 0.40), "flash": (0.30, 2.50), "pro": (1.25, 10.00), "": (0.30, 2.50),
    },
    "anthropic": {
        "haiku": (1.00, 5.00), "sonnet": (3.00, 15.00), "opus": (5.00, 25.00), "": (3.00, 15.00),
    },
    "ollama": {"": (0.0, 0.0)},
}
FREE_TIER = {"gemini": "Gemini has a free tier: if your API key is on it, the real charge is $0.",
             "ollama": "Ollama runs locally on your machine: no AI cost, and no data leaves your computer."}

GLOBAL = "(whole run)"

_calls: list[dict] = []
_run_dir: Path | None = None
_started = time.time()


def price(provider: str | None = None, model: str | None = None) -> tuple[float, float]:
    """(input, output) USD per 1M tokens for this provider/model."""
    env_in, env_out = os.getenv("LLM_PRICE_INPUT_PER_M"), os.getenv("LLM_PRICE_OUTPUT_PER_M")
    if env_in and env_out:
        return float(env_in), float(env_out)
    table = PRICES.get(provider or settings.llm_provider, {})
    model = (model or settings.llm_model or "").lower()
    key = max((k for k in table if k in model), key=len, default=None)
    return table.get(key, (0.0, 0.0)) if key is not None else (0.0, 0.0)


def set_run_dir(run_dir: Path, resume: bool = False) -> None:
    """resume=True (main.py --resume): the AI calls of the run's first part are read back, so the cost stays complete."""
    global _run_dir, _started
    _run_dir, _started = Path(run_dir), time.time()
    _calls.clear()
    if resume:
        _calls.extend(read_usage(run_dir))


def record(agent: str, page: str, test: str, tokens_in: int, tokens_out: int, seconds: float, ok: bool) -> None:
    p_in, p_out = price()
    entry = {"agent": agent or "other", "page": page or GLOBAL, "test": test or "",
             "provider": settings.llm_provider, "model": settings.llm_model,
             "tokens_in": int(tokens_in), "tokens_out": int(tokens_out),
             "cost_usd": round((tokens_in * p_in + tokens_out * p_out) / 1_000_000, 6),
             "seconds": round(seconds, 2), "ok": ok}
    _calls.append(entry)
    if _run_dir:
        try:
            with (_run_dir / "llm_usage.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            pass


def read_usage(run_dir: Path) -> list[dict]:
    f = Path(run_dir) / "llm_usage.jsonl"
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def totals(calls: list[dict]) -> dict:
    # failed calls (timeouts, errors) are logged with 0 tokens: the provider may still have charged
    # for them, so they are counted separately and the report says their cost is unknown
    return {"calls": len(calls),
            "failed_calls": sum(1 for c in calls if not c.get("ok", True)),
            "tokens_in": sum(c["tokens_in"] for c in calls),
            "tokens_out": sum(c["tokens_out"] for c in calls),
            "cost_usd": round(sum(c["cost_usd"] for c in calls), 6),
            "llm_seconds": round(sum(c["seconds"] for c in calls), 1)}


def per_case(cases: list[dict], results: list[dict] | None, calls: list[dict] | None = None) -> list[dict]:
    """End-to-end cost of every test case.

    - calls made for a page (test design, script writing) are split evenly over that page's cases
    - self-healing calls go to the case whose test was healed (else split over the page's cases)
    - whole-run calls (failure analysis, fix advice) are split evenly over all cases
    - execution time = time of the test(s) that ran the case
    """
    from .excel import _ident, case_hits

    calls = _calls if calls is None else calls
    n = len(cases)
    out = [{"id": c.get("id", ""), "page": c.get("page", ""), "title": c.get("title", ""),
            "tokens": 0.0, "cost_usd": 0.0, "exec_s": 0.0} for c in cases]
    if not n:
        return out
    by_page: dict[str, list[int]] = {}
    for i, c in enumerate(cases):
        by_page.setdefault(_ident(c.get("page", "")), []).append(i)

    def spread(idx: list[int], call: dict):
        for i in idx:
            out[i]["tokens"] += (call["tokens_in"] + call["tokens_out"]) / len(idx)
            out[i]["cost_usd"] += call["cost_usd"] / len(idx)

    for call in calls:
        page = call.get("page") or GLOBAL
        idx = by_page.get(_ident(page)) if page != GLOBAL else None
        if idx and call.get("test"):
            base = call["test"].split("[")[0]
            own = [i for i in idx if base in (f"test_{_ident(cases[i]['id'])}",
                                              "test_button_click" if _ident(cases[i]["id"]) == "buttons_click" else "")]
            idx = own or idx
        spread(idx or list(range(n)), call)

    for i, c in enumerate(cases):
        hits = case_hits(c, results or [])
        out[i]["exec_s"] = round(sum(r.get("duration_s") or 0 for r in hits), 2)
        out[i]["tokens"] = int(round(out[i]["tokens"]))
        out[i]["cost_usd"] = round(out[i]["cost_usd"], 6)
    return out


def write_report(run_dir: Path, cases: list[dict], results: list[dict] | None) -> dict:
    """Write runs/<run>/cost.json and return it."""
    calls = list(_calls) or read_usage(run_dir)
    p_in, p_out = price()
    agents: dict[str, list] = {}
    for c in calls:
        agents.setdefault(c["agent"], []).append(c)
    cases_cost = per_case(cases, results, calls)
    t = totals(calls)
    note = FREE_TIER.get(settings.llm_provider, "Estimated from public list prices.")
    if t["failed_calls"] and settings.llm_provider != "ollama":
        note += (f" {t['failed_calls']} AI call(s) failed or timed out; the provider may still have charged for them,"
                 " so the real cost can be slightly higher.")
    report = {
        "provider": settings.llm_provider, "model": settings.llm_model if settings.llm_provider != "none" else "",
        "currency": "USD", "price_per_million": {"input": p_in, "output": p_out},
        "note": note,
        **t,
        "run_seconds": round(time.time() - _started, 1),
        "test_cases": len(cases),
        "avg_cost_per_case_usd": round(t["cost_usd"] / len(cases), 6) if cases else 0.0,
        "cost_per_100_cases_usd": round(t["cost_usd"] / len(cases) * 100, 4) if cases else 0.0,
        "tests_executed": len(results or []),
        "test_exec_seconds": round(sum(r.get("duration_s") or 0 for r in results or []), 1),
        "by_agent": {a: totals(cs) for a, cs in agents.items()},
        "per_case": cases_cost,
    }
    (Path(run_dir) / "cost.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def fmt_usd(x: float) -> str:
    return "$0.00" if not x else (f"${x:.4f}" if x < 0.01 else f"${x:.2f}")
