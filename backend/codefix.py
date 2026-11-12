"""'Code now -> change to': for each problem in "What you should fix", find the line of the website's
code that causes it and write the corrected line.

  1. Built-in rules (no AI, always the same answer) handle the common HTML problems:
       form with `novalidate`, missing `required`, wrong box type (text instead of email / url / number),
       missing `maxlength`.
  2. For the rest (JavaScript errors, broken images / links / files, XSS ...) the line is found in the
     page's code and the AI writes the corrected line, if an AI is selected.

The code comes from the page as the browser received it (runs/<run>/html/<page>.html and the element
tags saved by Discovery). Server-side code (Python, Java, database...) can't be seen, so those problems
only get advice in words.
"""
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from .excel import _ident
from .llm import LLMError, ask_llm, extract_json, llm_enabled, load_prompt


def _attr_re(name: str):
    return re.compile(rf"""\s{name}(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?(?=[\s/>])""", re.I)


def set_attr(tag: str, name: str, value: str | None = None) -> str:
    """Add or replace an attribute in an opening tag: set_attr('<input type="text">', 'type', 'email')."""
    new = f" {name}" if value is None else f' {name}="{value}"'
    rx = _attr_re(name)
    if rx.search(tag):
        return rx.sub(new, tag, count=1)
    end = tag.rfind("/>") if tag.rstrip().endswith("/>") else tag.rfind(">")
    return (tag[:end].rstrip() + new + (" " if tag[end:].startswith("/") else "") + tag[end:]) if end > 0 else tag


def del_attr(tag: str, name: str) -> str:
    return _attr_re(name).sub("", tag, count=1)


def has_attr(tag: str, name: str) -> bool:
    return bool(_attr_re(name).search(tag or ""))


def find_line(html: str, needles: list[str], width: int = 300) -> str:
    """The first line of the page's code that contains one of the needles (cut around it if very long)."""
    if not html:
        return ""
    lines = html.splitlines()
    for needle in [n for n in needles if n]:
        for line in lines:
            if needle in line:
                s = line.strip()
                if len(s) <= width:
                    return s
                k = s.find(needle)
                a = max(0, k - width // 2)
                return ("…" if a else "") + s[a:a + width] + ("…" if a + width < len(s) else "")
    return ""


def _needles_for_url(url: str) -> list[str]:
    """How a page may refer to a file / link: full URL, path, or just the file name."""
    p = urlparse(url)
    path = p.path or ""
    name = path.rsplit("/", 1)[-1]
    return [url, path + (f"?{p.query}" if p.query else ""), path, name if len(name) > 3 else ""]


class Context:
    """Pages, their saved HTML and the designed test cases, looked up by URL / test file / test name."""

    def __init__(self, state: dict):
        self.run_dir = Path(state["run_dir"])
        self.pages = state.get("app_map", [])
        self.by_url = {p["url"]: p for p in self.pages}
        self.by_file = {}
        for p in self.pages:
            for suffix in ("", "_added", "_data"):
                self.by_file[f"test_{_ident(p['slug'])}{suffix}.py"] = p
        all_cases = [x for c in state.get("test_cases", []) for x in [c] + list(c.get("checks") or [])]
        self.cases = {f"test_{_ident(c['id'])}": c for c in all_cases if c.get("id")}
        self._html = {}

    def page_of(self, f: dict) -> dict | None:
        return self.by_file.get(f.get("file") or "") or self.by_url.get(f.get("page_url") or "")

    def html(self, page: dict | None) -> str:
        if not page:
            return ""
        slug = page["slug"]
        if slug not in self._html:
            fp = self.run_dir / "html" / f"{slug}.html"
            self._html[slug] = fp.read_text(encoding="utf-8", errors="replace") if fp.exists() else ""
        return self._html[slug]

    def case(self, f: dict) -> dict | None:
        return self.cases.get((f.get("test") or "").split("[")[0])


def _code(before: list[str] | str, after: list[str] | str | None, page: dict | None, how: str = "rules") -> dict:
    join = lambda x: "\n".join(x) if isinstance(x, list) else x  # noqa: E731
    return {"before": join(before), "after": join(after) if after is not None else None,
            "page": page["url"] if page else "", "how": how if after is not None else None}


def code_for(fails: list[dict], ctx: Context) -> dict | None:
    """The code change for one fix (built from all the failures merged into it)."""
    f = fails[0]
    t, err = f.get("test") or "", f.get("error") or ""
    page = ctx.page_of(f)

    # --- form submitted empty / with a bad email -> remove novalidate, add required / type="email"
    m = re.match(r"test_form(\d+)_(required_validation|invalid_email)", t)
    if m and page:
        form = next((x for x in page.get("forms", []) if x.get("index") == int(m.group(1))), None)
        if form and form.get("open_tag"):
            fields = [fl for fl in form.get("fields", []) if fl.get("html") and fl.get("type") not in ("checkbox", "radio")]
            if m.group(2) == "invalid_email":
                fields = [fl for fl in fields if fl.get("type") == "email" or "mail" in (fl.get("name") or "").lower()]
            before = [form["open_tag"]] + [fl["html"] for fl in fields]
            after_form = del_attr(form["open_tag"], "novalidate")
            after_fields = []
            none_required = not any(fl.get("required") for fl in form.get("fields", []))
            for fl in fields:
                tag = fl["html"]
                if m.group(2) == "invalid_email":
                    tag = set_attr(tag, "type", "email")
                elif none_required and not has_attr(tag, "required"):
                    tag = set_attr(tag, "required")
                after_fields.append(tag)
            after = [after_form] + after_fields
            return _code(before, after if after != before else None, page)

    # --- test data on one input box
    if t.startswith("test_data_"):
        case = ctx.case(f) or {}
        box = case.get("box_html") or ""
        if box:
            after = box
            for x in fails:
                c, e = ctx.case(x) or {}, x.get("error") or ""
                if "invalid value was accepted" in e and c.get("suggest_type"):
                    after = set_attr(after, "type", c["suggest_type"])
                if "more than its limit" in e and str(c.get("expect", "")).startswith("max:"):
                    after = set_attr(after, "maxlength", c["expect"][4:])
            return _code(box, after if after != box else None, page)

    # --- broken internal link: the <a> on the page where it was found
    if t.startswith("test_link[int_"):
        lm = re.search(r"HTTP \d+\s+(\S+)", err) or re.search(r"opened: (\S+)", err)
        found = re.search(r"found on (\S+?)\)?$", err.replace("\n", " "))
        src_page = ctx.by_url.get(found.group(1).rstrip(")")) if found else page
        if lm:
            line = find_line(ctx.html(src_page), [f'href="{n}' for n in _needles_for_url(lm.group(1)) if n])
            if line:
                return _code(line, None, src_page)

    if f.get("source") == "crawler":
        html = ctx.html(page)
        if t == "broken_image":
            line = find_line(html, _needles_for_url(err))
            return _code(line, None, page) if line else None
        if t == "failed_request":
            mm = re.match(r"HTTP \d+\s*→\s*(\S+)", err)
            line = find_line(html, _needles_for_url(mm.group(1))) if mm else ""
            return _code(line, None, page) if line else None
        if t == "console_error":
            nm = re.search(r"(\w+) is not defined", err)
            line = find_line(html, [nm.group(1) + "(", nm.group(1)]) if nm else ""
            return _code(line, None, page) if line else None
    return None


def ai_fill(fixes: list[dict]) -> None:
    """Ask the AI for the corrected code where the rules could only find the current line."""
    todo = [x for x in fixes if x.get("code") and x["code"].get("after") is None and x["code"].get("before")][:15]
    if not todo or not llm_enabled():
        return
    brief = [{"id": x["id"], "problem": x["title"], "advice": x["fix"], "page": x["code"]["page"],
              "error": x.get("error", "")[:300], "code_now": x["code"]["before"][:1500]} for x in todo]
    try:
        answer = extract_json(ask_llm(load_prompt("fix_code").format(items=json.dumps(brief, indent=1)), agent="fix_code"))
    except (LLMError, json.JSONDecodeError, ValueError) as e:
        print(f"  [advice] AI code fixes skipped: {str(e)[:150]}")
        return
    by_id = {x["id"]: x for x in todo}
    for upd in answer if isinstance(answer, list) else []:
        try:
            x = by_id[int(upd["id"])]
        except (KeyError, ValueError, TypeError):
            continue
        after = (upd.get("change_to") or "").strip()
        if after and after != x["code"]["before"].strip() and len(after) < 3000:
            x["code"]["after"], x["code"]["how"] = after, "ai"
