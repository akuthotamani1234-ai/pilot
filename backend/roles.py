"""Several user roles (Step 15): what each role may open, tested again - and a lower role must stay locked out.

From roles.json (written by discovery: every OTHER role of TEST_ACCOUNTS signed in once and opened the pages behind
the login):
  ok                        -> "Role 'editor' can open /reports"        (it opens: status < 400, not refused)
  denied / login / redirected -> "Role 'viewer' can't open /admin"      (401 / 403, 'access denied', the login page,
                                                                          or sent somewhere else - never the page)
The tests start in that role's own saved login (conftest.py: as_role) - its password is never in a test.
The report shows a role x page table.
"""
from pprint import pformat
from urllib.parse import urlparse

MAX_ROLE_CASES = 40


def role_cases(state: dict) -> list[dict]:
    roles = (state.get("roles") or {}).get("roles") or {}
    out = []
    for role, r in roles.items():
        if r.get("login") != "success":
            continue
        for url, seen in (r.get("pages") or {}).items():
            access = seen.get("access")
            if access not in ("ok", "denied", "login", "redirected") or len(out) >= MAX_ROLE_CASES:
                continue
            path = urlparse(url).path or "/"
            opens = access == "ok"
            n = len(out) + 1
            out.append({"id": f"role_{n}", "kind": "role", "type": "positive" if opens else "negative",
                        "priority": "medium" if opens else "high",
                        "title": f"Role '{role}' {'can' if opens else 'can not'} open {path}",
                        "steps": [f"Sign in as the '{role}' role (its own test account)", f"Open {url}"],
                        "expected": ("The page opens (status < 400, not refused)" if opens else
                                     "It is refused: 401 / 403, an 'access denied' message, the login page, or another "
                                     "page - never this one (a lower role must not open it)"),
                        "page": "site", "url": url, "pages": [], "guest": False, "test_data": f"role {role}",
                        "oracle": "observed" if opens else "rule",
                        "files": ["test_roles.py"], "tests": [f"test_role_{n}"],
                        "spec": {"role": role, "url": url, "expect": "open" if opens else "refused"}})
    return out


ROLE_HELPERS = r'''
DENIED = re.compile(r"access denied|not authori[sz]ed|forbidden|no permission|not allowed|insufficient (rights|"
                    r"permissions?)|\b403\b", re.I)


def _check_role(as_role, R):
    p = as_role(R['role'])
    resp = p.goto(R['url'])
    _settle(p)
    status = resp.status if resp else None
    text = p.locator('body').inner_text()
    moved = _key(p.url) != _key(R['url'])
    refused = status in (401, 403) or bool(DENIED.search(text)) or moved \
        or p.locator('input[type=password]').count() > 0
    if R['expect'] == 'open':
        assert not refused, (f"Role '{R['role']}' can no longer open {R['url']} (status {status}, now on {p.url})")
        assert status is None or status < 400, f"Role '{R['role']}': {R['url']} answered HTTP {status}"
        _step_ok(f"role '{R['role']}' opens {R['url']}")
    else:
        assert refused, (f"Role '{R['role']}' could open {R['url']} (status {status}) - it was refused while exploring: "
                         "a lower role must not see it")
        _step_ok(f"role '{R['role']}' is refused at {R['url']} (status {status}, now on {p.url})")
'''


def roles_script(cases: list[dict], header: list[str]) -> str:
    out = ['"""Several user roles: each role opens what it may, and is refused what it may not (a lower role must',
           'never open an admin page). Each test starts in that role\'s own saved login."""', *header, ROLE_HELPERS, ""]
    for c in cases:
        out += [f"def test_{c['id']}(page, as_role):",
                f'    """{c["title"].replace(chr(34), chr(39))}"""',
                f"    R = {pformat(c['spec'], width=100, sort_dicts=False)}",
                "    _check_role(as_role, R)", "", ""]
    return "\n".join(out).rstrip() + "\n"
