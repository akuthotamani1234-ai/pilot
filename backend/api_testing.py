"""REST API tests: real requests to an authorized API, real checks of what it answers.

(api_inventory.py only RECORDS the calls a website's browser made; this module EXECUTES API tests.)

  spec        an OpenAPI 3 / Swagger 2 document (URL or text, JSON or YAML) -> the operations: method, path,
              parameters, request body and documented responses with their schemas ($ref resolved)
  tests       ApiTest: one request (method, path with {params}, query, headers, JSON body, the run's auth or not),
              the expected status codes, assertions on the JSON answer ("data.items[0].id" eq / contains / exists /
              gte / lte / len_gte / type / matches), values saved for the next request ({{name}}: request chains),
              a response-time limit, and the test case it verifies (traceability)
  from spec   smoke tests: each GET that needs no unknown input -> its documented success status and schema
  from Jira   the AI maps each approved test case to ApiTests from the operations (only real operations kept)
  safety      the target is checked like a website (http(s), no metadata / private addresses unless local is
              allowed); GET / HEAD / OPTIONS always; POST / PUT / PATCH only when the run allows writes; DELETE only
              when it allows DELETE explicitly; anything else is Blocked with the reason - never sent silently
  evidence    each request and answer with secrets redacted (Authorization, cookies, api keys, password / token
              fields, card-like numbers), the status, the time and every check with what it found
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Literal
from urllib.parse import urljoin, urlparse

from pydantic import BaseModel, Field

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
WRITE_METHODS = {"POST", "PUT", "PATCH"}
MAX_SPEC_BYTES = 5_000_000
MAX_BODY_SHOWN = 4000
SECRET_KEYS = re.compile(r"pass(word)?|secret|token|api[_-]?key|authorization|cookie|session|card|cvv|cvc|iban|ssn",
                         re.I)
CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")


class Check(BaseModel):
    path: str = Field(default="", max_length=200)  # "" = the whole JSON answer; "items[0].name", "data.total"
    op: Literal["eq", "ne", "contains", "exists", "not_exists", "gte", "lte", "len_gte", "len_eq", "type",
                "matches", "all_eq"] = "exists"  # all_eq: every item of the array at path has value["field"] ==
    # value["equals"] (a filter / business rule: "findByStatus?status=sold lists only sold pets")
    value: Any = None


class ApiTest(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    method: Literal["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    path: str = Field(min_length=1, max_length=500)
    path_params: dict[str, Any] = Field(default_factory=dict)  # {"petId": 7} fills "/pet/{petId}"
    query: dict[str, Any] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any = None
    auth: bool = True  # (send the run's credential; False checks the API refuses without it)
    expect_status: list[int] = Field(default_factory=lambda: [200], min_length=1, max_length=10)
    checks: list[Check] = Field(default_factory=list, max_length=30)
    schema_check: bool = True  # (validate the answer against the documented schema of that status)
    save: dict[str, str] = Field(default_factory=dict)  # {"pet_id": "id"} -> {{pet_id}} in later tests
    max_ms: int = Field(default=10000, ge=100, le=120000)
    case: str = Field(default="", max_length=80)  # the requirement test case it verifies
    kind: str = Field(default="", max_length=30)  # schema / business_rule / negative / boundary / auth / validation


# ---------------------------------------------------------------- the specification

def load_spec(source: str, fetch=None) -> dict:
    """An OpenAPI / Swagger document from a URL (checked like a website target) or from its text."""
    text = source
    if re.match(r"https?://", source.strip(), re.I):
        from .safety import check_target
        check_target(source.strip())
        if fetch is None:
            import httpx
            r = httpx.get(source.strip(), timeout=30, follow_redirects=False)
            r.raise_for_status()
            text = r.text
        else:
            text = fetch(source.strip())
    if len(text.encode("utf-8", "replace")) > MAX_SPEC_BYTES:
        raise ValueError("the API specification is larger than 5 MB")
    try:
        spec = json.loads(text)
    except ValueError:
        import yaml
        spec = yaml.safe_load(text)
    if not isinstance(spec, dict) or not (spec.get("openapi") or spec.get("swagger")) or "paths" not in spec:
        raise ValueError("this is not an OpenAPI / Swagger document (no 'openapi' / 'swagger' and 'paths')")
    return spec


def _ref(spec: dict, node, depth: int = 0):
    """Resolve local $ref (#/components/schemas/X, #/definitions/X), bounded (recursive schemas)."""
    if depth > 12:
        return {}
    if isinstance(node, dict):
        if "$ref" in node and isinstance(node["$ref"], str) and node["$ref"].startswith("#/"):
            target = spec
            for part in node["$ref"][2:].split("/"):
                target = target.get(part, {}) if isinstance(target, dict) else {}
            return _ref(spec, target, depth + 1)
        return {k: _ref(spec, v, depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [_ref(spec, v, depth + 1) for v in node]
    return node


def base_url(spec: dict, spec_url: str = "") -> str:
    servers = spec.get("servers") or []
    url = servers[0].get("url", "") if servers and isinstance(servers[0], dict) else ""
    if not url and spec.get("host"):  # (Swagger 2)
        url = f"{(spec.get('schemes') or ['https'])[0]}://{spec['host']}{spec.get('basePath', '')}"
    if spec_url:
        url = urljoin(spec_url, url or "/")
    return url.rstrip("/")


def operations(spec: dict) -> list[dict]:
    out = []
    for path, item in (spec.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        shared = item.get("parameters") or []
        for method, op in item.items():
            if method.upper() not in SAFE_METHODS | WRITE_METHODS | {"DELETE"} or not isinstance(op, dict):
                continue
            params = [_ref(spec, p) for p in shared + (op.get("parameters") or [])]
            body = _ref(spec, ((op.get("requestBody") or {}).get("content") or {}).get("application/json", {})
                        .get("schema")) if op.get("requestBody") else None
            responses = {}
            for code, r in (op.get("responses") or {}).items():
                r = _ref(spec, r)
                schema = ((r.get("content") or {}).get("application/json") or {}).get("schema") or r.get("schema")
                responses[str(code)] = schema or {}
            out.append({"id": op.get("operationId") or f"{method.upper()} {path}", "method": method.upper(),
                        "path": path, "summary": str(op.get("summary") or op.get("description") or "")[:200],
                        "params": [{"name": p.get("name"), "in": p.get("in"), "required": bool(p.get("required")),
                                    "schema": p.get("schema") or {}, "example": p.get("example")}
                                   for p in params if isinstance(p, dict)],
                        "body": body, "responses": responses, "secured": bool(op.get("security", spec.get("security")))})
    return out


def smoke_tests(ops: list[dict]) -> list[ApiTest]:
    """Each GET that needs no unknown input: its documented success status and schema."""
    out = []
    for op in ops:
        if op["method"] != "GET":
            continue
        query, path, unknown = {}, op["path"], False
        for p in op["params"]:
            if not p["required"]:
                continue
            value = p.get("example") or (p["schema"].get("enum") or [None])[0] or p["schema"].get("default")
            if value is None:
                unknown = True
                break
            if p["in"] == "path":
                path = path.replace("{" + p["name"] + "}", str(value))
            elif p["in"] == "query":
                query[p["name"]] = value
        if unknown or "{" in path:  # (a path parameter with no known value - declared or not - is not guessed)
            continue
        ok = sorted(int(c) for c in op["responses"] if c.isdigit() and 200 <= int(c) < 300) or [200]
        out.append(ApiTest(name=f"{op['method']} {op['path']} answers as documented", method="GET", path=path,
                           query=query, expect_status=ok))
    return out


FIELD_HINT = re.compile(r"[A-Za-z_][\w-]{0,40}")


def _documented(op: dict, low: int, high: int) -> list[int]:
    return sorted(int(c) for c in op["responses"] if c.isdigit() and low <= int(c) < high)


def _item_schema(op: dict) -> dict:
    ok = next((op["responses"][c] for c in op["responses"] if c.isdigit() and 200 <= int(c) < 300), {}) or {}
    return ok.get("items") or {} if ok.get("type") == "array" else {}


def explore_tests(ops: list[dict], allow: set[str] | None = None, authed: bool = False) -> list[ApiTest]:
    """Autonomous API tests from the specification alone - each kind only where the document says what must
    happen (nothing is guessed):
      schema         each GET without unknown input -> its documented status and response schema (smoke_tests)
      business_rule  a list filtered by an enum query parameter that is also a field of its items -> every item
                     returned has that value (e.g. status=sold lists only sold items)
      negative       an invalid enum value / a malformed path id -> one of the operation's DOCUMENTED 4xx answers
      boundary       a value just outside a declared minimum / maximum -> a documented 4xx
      auth           a secured operation without the run's credential -> a documented 401 / 403 (only when the
                     run has a credential)
      validation     a write without its required body fields -> a documented 4xx (only for methods this run allows
                     to send; the API must refuse it, so nothing is created)
    A 5xx is always a failure; an invalid input answered 2xx is a 'Validation defect'."""
    allow = {m.upper() for m in (allow or set())}
    out = [t.model_copy(update={"kind": "schema"}) for t in smoke_tests(ops)]
    for op in ops:
        bad = _documented(op, 400, 500)
        path_params = [p for p in op["params"] if p["in"] == "path"]
        if op["method"] == "GET":
            item = _item_schema(op)
            for p in op["params"]:
                enum = p["schema"].get("enum") or (p["schema"].get("items") or {}).get("enum") or []
                if p["in"] != "query" or not enum or path_params:
                    continue
                ok = _documented(op, 200, 300) or [200]
                if p["name"] in (item.get("properties") or {}):
                    for v in enum[:3]:
                        out.append(ApiTest(name=f"GET {op['path']}?{p['name']}={v} lists only items with "
                                                f"{p['name']} = {v}", path=op["path"], query={p["name"]: v},
                                           expect_status=ok, kind="business_rule",
                                           checks=[Check(path="", op="all_eq", value={"field": p["name"],
                                                                                      "equals": v})]))
                if bad:
                    out.append(ApiTest(name=f"GET {op['path']} refuses an invalid {p['name']}", path=op["path"],
                                       query={p["name"]: "qa-invalid-value"}, expect_status=bad, schema_check=False,
                                       kind="negative"))
        if op["method"] in ("GET", "DELETE") and path_params and bad and (op["method"] == "GET" or "DELETE" in allow):
            for p in path_params:
                t = p["schema"].get("type")
                others = {q["name"]: q.get("example") for q in path_params if q is not p}
                if t in ("integer", "number") and all(v is not None for v in others.values()) and op["method"] == "GET":
                    out.append(ApiTest(name=f"GET {op['path']} refuses a {p['name']} that is not a number",
                                       path=op["path"], path_params={p["name"]: "not-a-number", **others},
                                       expect_status=bad, schema_check=False, kind="negative"))
                    lo, hi = p["schema"].get("minimum"), p["schema"].get("maximum")
                    for edge, why in ((lo - 1 if isinstance(lo, (int, float)) else None, f"below its minimum {lo}"),
                                      (hi + 1 if isinstance(hi, (int, float)) else None, f"above its maximum {hi}")):
                        if edge is not None:
                            out.append(ApiTest(name=f"GET {op['path']} refuses {p['name']} {why}", path=op["path"],
                                               path_params={p["name"]: edge, **others}, expect_status=bad,
                                               schema_check=False, kind="boundary"))
        for p in op["params"]:
            lo, hi = p["schema"].get("minimum"), p["schema"].get("maximum")
            if op["method"] != "GET" or p["in"] != "query" or not bad or path_params:
                continue
            for edge, why in ((lo - 1 if isinstance(lo, (int, float)) else None, f"below its minimum {lo}"),
                              (hi + 1 if isinstance(hi, (int, float)) else None, f"above its maximum {hi}")):
                if edge is not None:
                    out.append(ApiTest(name=f"GET {op['path']} refuses {p['name']} {why}", path=op["path"],
                                       query={p["name"]: edge}, expect_status=bad, schema_check=False,
                                       kind="boundary"))
        denied = [c for c in _documented(op, 400, 500) if c in (401, 403)]
        if authed and op.get("secured") and denied and op["method"] == "GET" and not path_params:
            out.append(ApiTest(name=f"GET {op['path']} refuses a request without credentials", path=op["path"],
                               auth=False, expect_status=denied, schema_check=False, kind="auth"))
        body = op.get("body") or {}
        if op["method"] in allow and op["method"] in WRITE_METHODS and body.get("required") and bad \
                and not path_params:
            out.append(ApiTest(name=f"{op['method']} {op['path']} refuses a body without its required fields "
                                    f"({', '.join(body['required'][:4])})", method=op["method"], path=op["path"],
                               body={}, expect_status=bad, schema_check=False, kind="validation"))
    return out


def match_operation(method: str, path: str, ops: list[dict]) -> dict | None:
    """The documented operation a concrete request is ('/pet/7' -> 'GET /pet/{petId}'); a literal segment beats a
    parameter ('/pet/findByStatus' is not '/pet/{petId}')."""
    path = re.sub(r"\{\{\w+\}\}", "x", path.split("?")[0])
    best, score = None, -1
    for op in ops:
        if op["method"] != method:
            continue
        rx = "^" + re.sub(r"\\\{[^/]+?\\\}", "[^/]+", re.escape(op["path"])) + "/?$"
        if re.match(rx, path):
            literal = len([p for p in op["path"].split("/") if p and not p.startswith("{")])
            if literal > score:
                best, score = op, literal
    return best


# ---------------------------------------------------------------- checks

def _get(data, path: str):
    """'items[0].name' / 'data.total' / '' (the whole answer). Raises KeyError when missing."""
    cur = data
    for part in re.findall(r"[^.\[\]]+|\[\d+\]", path or ""):
        if part.startswith("["):
            idx = int(part[1:-1])
            if not isinstance(cur, list) or idx >= len(cur):
                raise KeyError(path)
            cur = cur[idx]
        else:
            if not isinstance(cur, dict) or part not in cur:
                raise KeyError(path)
            cur = cur[part]
    return cur


TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}


def schema_problems(value, schema: dict, where: str = "$", depth: int = 0) -> list[str]:
    """A small JSON-schema check of the parts APIs document: type, required, properties, items, enum, nullable."""
    if not isinstance(schema, dict) or not schema or depth > 12:
        return []
    if value is None and (schema.get("nullable") or schema.get("type") == "null"):
        return []
    out = []
    t = schema.get("type")
    want = TYPES.get(t) if isinstance(t, str) else None
    if want and not (isinstance(value, want) and not (t in ("integer", "number") and isinstance(value, bool))):
        return [f"{where}: expected {t}, got {type(value).__name__}"]
    if schema.get("enum") and value not in schema["enum"]:
        out.append(f"{where}: {value!r} is not one of {schema['enum'][:8]}")
    if isinstance(value, dict):
        for name in schema.get("required") or []:
            if name not in value:
                out.append(f"{where}.{name}: required, missing")
        for name, sub in (schema.get("properties") or {}).items():
            if name in value:
                out += schema_problems(value[name], sub, f"{where}.{name}", depth + 1)
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for i, item in enumerate(value[:50]):
            out += schema_problems(item, schema["items"], f"{where}[{i}]", depth + 1)
    return out[:20]


def run_check(data, check: Check) -> tuple[bool, str]:
    try:
        found = _get(data, check.path)
    except KeyError:
        return (check.op == "not_exists"), f"{check.path or '(answer)'} is missing"
    v = check.value
    ok = {"exists": True, "not_exists": False, "eq": found == v, "ne": found != v,
          "contains": (str(v).casefold() in json.dumps(found).casefold()) if not isinstance(found, list)
          else any(v == x or str(v).casefold() in json.dumps(x).casefold() for x in found),
          "gte": isinstance(found, (int, float)) and isinstance(v, (int, float)) and found >= v,
          "lte": isinstance(found, (int, float)) and isinstance(v, (int, float)) and found <= v,
          "len_gte": hasattr(found, "__len__") and isinstance(v, int) and len(found) >= v,
          "len_eq": hasattr(found, "__len__") and isinstance(v, int) and len(found) == v,
          "type": isinstance(found, TYPES.get(str(v), ())) and not (str(v) in ("integer", "number")
                                                                   and isinstance(found, bool)),
          "matches": bool(re.search(str(v), str(found))),
          "all_eq": isinstance(found, list) and isinstance(v, dict) and all(
              isinstance(x, dict) and x.get(v.get("field")) == v.get("equals") for x in found)}[check.op]
    if check.op == "all_eq" and isinstance(found, list) and isinstance(v, dict) and not ok:
        wrong = [x.get(v.get("field")) if isinstance(x, dict) else x for x in found
                 if not (isinstance(x, dict) and x.get(v.get("field")) == v.get("equals"))]
        return ok, f"{len(wrong)} of {len(found)} item(s) have {v.get('field')} = {json.dumps(wrong[:5])[:120]}"
    return ok, f"{check.path or '(answer)'} = {json.dumps(found)[:160]}"


# ---------------------------------------------------------------- evidence (never a secret)

def redact(value, secrets: list[str] = ()):
    if isinstance(value, dict):
        return {k: ("[redacted]" if SECRET_KEYS.search(str(k)) else redact(v, secrets)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, secrets) for v in value[:50]]
    if isinstance(value, str):
        for s in secrets:
            if s:
                value = value.replace(s, "[redacted]")
        return CARD.sub("[card number]", value)
    return value


def _fill(text: str, saved: dict) -> str:
    return re.sub(r"\{\{(\w+)\}\}", lambda m: str(saved.get(m.group(1), m.group(0))), text)


def _fill_any(value, saved: dict):
    if isinstance(value, str):
        return _fill(value, saved)
    if isinstance(value, dict):
        return {k: _fill_any(v, saved) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill_any(v, saved) for v in value]
    return value


# ---------------------------------------------------------------- execution

def run(base: str, tests: list[ApiTest], *, auth: dict | None = None, allow: set[str] | None = None,
        ops: list[dict] | None = None, client=None, allow_local: bool = False) -> list[dict]:
    """Execute the tests in order (later ones may use values saved by earlier ones). auth: {"type": "bearer" |
    "basic" | "header", "token" / "username"+"password" / "name"+"value"}. allow: the methods beyond GET / HEAD /
    OPTIONS this run may send (e.g. {"POST", "PUT"}; DELETE only when named)."""
    import httpx

    from .safety import UrlError, check_target
    allow = {m.upper() for m in (allow or set())}
    host = urlparse(base).hostname or ""
    try:
        if not allow_local:
            check_target(base)
    except UrlError as error:
        return [{"name": t.name, "case": t.case, "status": "Blocked", "reason": f"Blocked: {error}"} for t in tests]
    secrets = [str(v) for k, v in (auth or {}).items() if k != "type" and v and len(str(v)) > 3]
    own = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=False)
    saved: dict = {}
    results = []
    try:
        for t in tests:
            res = {"name": t.name, "case": t.case, "method": t.method, "path": t.path, "checks": [],
                   **({"kind": t.kind} if t.kind else {})}
            if t.method not in SAFE_METHODS and t.method not in allow:
                res.update(status="Blocked", reason=(
                    f"Blocked: {t.method} changes data - it is sent only when this run allows {t.method} (a staging / "
                    "test API, operation-specific permission)"))
                results.append(res)
                continue
            path = _fill(t.path, saved)
            for name, value in t.path_params.items():  # (a {param} of the documented path, possibly {{saved}})
                path = path.replace("{" + name + "}", str(_fill_any(value, saved)))
            if "{" in path or "{{" in json.dumps(t.query) + json.dumps(t.body):
                res.update(status="Blocked", reason=f"Blocked: a value it needs is not known ({path}) - an earlier "
                                                    "request that saves it did not run or failed")
                results.append(res)
                continue
            url = base + (path if path.startswith("/") else "/" + path)
            if (urlparse(url).hostname or "") != host:
                res.update(status="Blocked", reason="Blocked: the request leaves the API under test")
                results.append(res)
                continue
            headers = {"Accept": "application/json", **t.headers}
            if t.auth and auth:
                if auth.get("type") == "bearer" and auth.get("token"):
                    headers["Authorization"] = f"Bearer {auth['token']}"
                elif auth.get("type") == "header" and auth.get("name"):
                    headers[auth["name"]] = str(auth.get("value") or "")
            basic = (auth["username"], auth["password"]) if t.auth and auth and auth.get("type") == "basic" else None
            body = _fill_any(t.body, saved)
            started = time.perf_counter()
            try:
                r = client.request(t.method, url, params=_fill_any(t.query, saved) or None, headers=headers,
                                   json=body if body is not None else None, auth=basic)
            except httpx.HTTPError as error:
                res.update(status="Failed", category="API unreachable", reason=f"{type(error).__name__}: "
                                                                                f"{str(error)[:200]}")
                results.append(res)
                continue
            ms = round((time.perf_counter() - started) * 1000)
            try:
                data = r.json()
            except ValueError:
                data = None
            res.update(request={"method": t.method, "url": redact(url, secrets), "query": redact(t.query, secrets),
                                "headers": redact(dict(headers.items()), secrets),
                                "body": redact(body, secrets)},
                       response={"status": r.status_code, "ms": ms,
                                 "content_type": r.headers.get("content-type", "")[:80],
                                 "body": redact(data, secrets) if data is not None else r.text[:MAX_BODY_SHOWN]})
            failed = []
            if r.status_code not in t.expect_status:
                failed.append(f"status {r.status_code}, expected {t.expect_status}")
            res["checks"].append({"check": f"status in {t.expect_status}", "ok": r.status_code in t.expect_status,
                                  "found": r.status_code})
            if ms > t.max_ms:
                failed.append(f"took {ms} ms (limit {t.max_ms} ms)")
            res["checks"].append({"check": f"time <= {t.max_ms} ms", "ok": ms <= t.max_ms, "found": ms})
            op = match_operation(t.method, path, ops or [])
            if t.schema_check and op and data is not None:
                schema = op["responses"].get(str(r.status_code))
                problems = schema_problems(data, schema) if schema else []
                res["checks"].append({"check": "answer matches the documented schema", "ok": not problems,
                                      "found": "; ".join(problems[:5]) or "as documented"})
                failed += problems[:3]
            for c in t.checks:
                ok, found = run_check(data, c) if data is not None else (False, "the answer is not JSON")
                res["checks"].append({"check": f"{c.path or '(answer)'} {c.op} {json.dumps(c.value)[:80]}",
                                      "ok": ok, "found": redact(found, secrets)})
                if not ok:
                    failed.append(f"{c.path or '(answer)'} {c.op} {c.value!r}: {found}")
            for name, p in t.save.items():
                try:
                    saved[name] = _get(data, p)
                except KeyError:
                    pass
            # a check whose path is not in the answer at all is the TEST's mistake (the answer has another shape) -
            # unless the documented schema check already found the API wrong; such a test needs review
            only_paths = failed and all("is missing" in f for f in failed if not f.startswith(("status ", "took ")))\
                and not any(f.startswith(("status ", "took ", "$")) for f in failed)
            accepted_bad = t.kind in ("negative", "boundary", "auth", "validation") and 200 <= r.status_code < 300
            res.update(status="Failed" if failed else "Passed", reason="; ".join(failed)[:600],
                       category=("Test mistake" if only_paths else
                                 "Validation defect (invalid input accepted)" if accepted_bad else
                                 "API assertion failure") if failed else "")
            results.append(res)
    finally:
        if own:
            client.close()
    return results


# ---------------------------------------------------------------- Jira test cases -> API tests (AI)

class _Plan(BaseModel):
    case: str
    tests: list[ApiTest] = Field(default_factory=list, max_length=8)
    not_possible: str = ""


def tests_for_cases(cases: list[dict], ops: list[dict], ask=None) -> tuple[list[ApiTest], dict[str, str]]:
    """The AI maps each test case to API tests built ONLY from the documented operations. Returns (tests, {case id:
    why it could not be mapped})."""
    from .llm import LLMError, ask_structured
    ask = ask or ask_structured
    def shape(schema, depth=0):  # (a compact view of a schema: required fields and their types)
        if not isinstance(schema, dict) or depth > 2:
            return None
        if schema.get("type") == "array":
            return [shape(schema.get("items"), depth + 1)]
        props = schema.get("properties") or {}
        if not props:
            return schema.get("type") or None
        return {("*" if k in (schema.get("required") or []) else "") + k: shape(v, depth + 1) or v.get("type")
                for k, v in list(props.items())[:15]}
    catalog = [{"method": o["method"], "path": o["path"], "summary": o["summary"],
                "params": [{k: p[k] for k in ("name", "in", "required")} for p in o["params"]],
                **({"body (* = required)": shape(o["body"])} if o.get("body") else {}),
                "success": [c for c in o["responses"] if c.startswith("2")],
                "answer": shape(next((v for c, v in o["responses"].items() if c.startswith("2")), None))}
               for o in ops][:150]
    out, why = [], {}
    for i in range(0, len(cases), 10):
        batch = cases[i:i + 10]
        prompt = (
            "Turn each approved test case into REST API tests for this API, using the documented OPERATIONS below.\n"
            "Most test cases are one or two requests to a documented operation plus checks of its answer: a status "
            "code (e.g. an id that does not exist -> the operation's 404; a wrong value -> 400), fields of the JSON "
            "answer, or a value read back after creating it. A request body gives every required (*) field of the "
            "operation's body. A check path starts at the answer: '[0].status' when the answer is a list, "
            "'status' or 'items[0].status' when it is an object. Write the path exactly as documented ('/things/{id}') "
            "and give its values in path_params ({\"id\": 12345}); use {{name}} for a value an earlier test saved "
            "with `save` ({\"name\": \"id\"} saves the answer's id). A test that needs data first creates it "
            "(POST) and saves its id. checks: {\"path\": \"items[0].status\" (\"\" = the whole answer), \"op\": "
            "eq | ne | contains | exists | not_exists | gte | lte | len_gte | len_eq | type | matches, \"value\": "
            "...}. For 'every item has X' use contains on the list only when the API documents it; otherwise check "
            "the first items. Only when NO documented operation is about the test case, give no tests and say why in "
            "not_possible. Never invent an operation. No comments in the JSON.\n"
            "Shape of one element: {\"case\": \"TC-X-1\", \"tests\": [{\"name\": \"...\", \"method\": "
            "\"GET\", \"path\": \"/things/{id}\", \"path_params\": {\"id\": 12345}, \"query\": {}, "
            "\"body\": null, \"expect_status\": [404], \"checks\": [], \"save\": {}}], "
            "\"not_possible\": \"\"}\nReturn a JSON ARRAY with one such element per test case (an array even for "
            "one test case).\n\nOPERATIONS:\n" + json.dumps(catalog)
            + "\n\nTEST CASES:\n" + json.dumps([{"id": c["id"], "title": c.get("title"),
                                                  "steps": c.get("steps"), "expected": c.get("expected")}
                                                 for c in batch]))
        try:
            plans = ask(prompt, list[_Plan] | _Plan, agent="api_tests", page="api")
            plans = plans if isinstance(plans, list) else [plans]  # (one test case: one object is fine too)
        except (LLMError, ValueError) as error:
            for c in batch:
                why[c["id"]] = f"Not automated: the AI could not plan API tests ({str(error)[:120]})"
            continue
        seen = set()
        for p in plans:
            if p.case not in {c["id"] for c in batch}:
                continue
            seen.add(p.case)
            real = []
            for t in p.tests:
                if match_operation(t.method, t.path, ops):  # (an invented operation is dropped)
                    real.append(t.model_copy(update={"case": p.case}))
            if real:
                out += real
            else:
                why[p.case] = "Not automated: " + (p.not_possible or "no documented operation can test it")[:300]
        for c in batch:
            if c["id"] not in seen and c["id"] not in why:
                why[c["id"]] = "Not automated: the AI gave no API test for it"
    return out, why


# ---------------------------------------------------------------- a run (Jira executions, the Studio)

def to_run_cases(results: list[dict], why: dict[str, str], case_ids: list[str]) -> list[dict]:
    """One record per requirement test case, in the run's test_cases.json format (bridge.collect reads it): Passed only
    when every API test of that case ran and passed; Failed when one failed; Blocked / Not automated with the reason."""
    out = []
    for cid in case_ids:
        mine = [r for r in results if r.get("case") == cid]
        if not mine:
            out.append({"requirement_test": cid, "tc_id": cid, "execution_status": "Not run",
                        "skip_reason": why.get(cid, "Not automated: no API test was planned for it")})
            continue
        # a step after a BLOCKED step depends on what that step would have done (the pet a blocked POST never
        # created is not found): its failure is not the API's - the case is Blocked. A failure BEFORE it stays Failed.
        first_blocked = next((i for i, r in enumerate(mine) if r["status"] == "Blocked"), len(mine))
        statuses = {r["status"] for r in mine[:first_blocked]} | ({"Blocked"} if first_blocked < len(mine) else set())
        real = [r for r in mine[:first_blocked] if r["status"] == "Failed" and r.get("category") != "Test mistake"]
        status = "Failed" if "Failed" in statuses else "Blocked" if "Blocked" in statuses else "Passed"
        reasons = [f"{r['name']}: {r.get('reason')}" for r in mine if r.get("reason")]
        out.append({"requirement_test": cid, "tc_id": cid, "execution_status": status,
                    "skip_reason": ("Blocked: " + "; ".join(reasons))[:500] if status == "Blocked" else "",
                    "actual_result": "; ".join(reasons)[:2000] or f"{len(mine)} API test(s) passed",
                    "failure_category": (real[0].get("category") if real else
                                         next((r.get("category") for r in mine if r.get("category")), "")),
                    "steps": [f"{r.get('method')} {r.get('path')}" for r in mine],
                    "check_count": sum(len(r.get("checks") or []) for r in mine),
                    "evidence": [f"api_results.json#{r['name']}" for r in mine]})
    return out


def autonomous_records(results: list[dict]) -> list[dict]:
    """The autonomous API tests (no Jira case) as run records of their own (API-AUTO-n), so an autonomous / hybrid
    execution counts what really ran: Passed / Failed (with the category) / Blocked with the reason."""
    out = []
    for n, r in enumerate([r for r in results if not r.get("case")], 1):
        status = r.get("status") or "Not run"
        out.append({"tc_id": f"API-AUTO-{n}", "title": r.get("name"), "origin": "autonomous", "kind": r.get("kind", ""),
                    "execution_status": status if status in ("Passed", "Failed") else "Not run",
                    "skip_reason": str(r.get("reason") or "")[:500] if status not in ("Passed", "Failed") else "",
                    "actual_result": str(r.get("reason") or "all checks passed")[:2000],
                    "failure_category": r.get("category") or "", "steps": [f"{r.get('method')} {r.get('path')}"],
                    "check_count": len(r.get("checks") or []), "evidence": [f"api_results.json#{r.get('name')}"]})
    return out
