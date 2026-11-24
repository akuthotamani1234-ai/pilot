"""Requirement analysis (Phase 3): acceptance criteria, quality issues, conflicts, scenario suggestions, coverage.

Order of work, rules before AI:
  1 extract     criteria are COPIED from the stored sources by rules: the Jira acceptance-criteria field, an
                'Acceptance criteria' part of the description, numbered / bulleted lines, Given/When/Then, and the
                requirement-like sections of linked Confluence pages (list items, 'must/shall' sentences, table
                rows, Gherkin code blocks). Each one keeps its source, version, locator and the quoted words.
  2 check       ambiguous, incomplete, duplicate, contradictory (same source), missing criteria; conflicts between
                Jira and Confluence with the quotes of both. Rules only: nothing here is decided by an AI.
  3 suggest     positive / negative / boundary / security test ideas from rule templates; with AI allowed by the
                privacy settings, AI ideas too. Every idea says whether its expected outcome is EXPLICIT (quoted)
                or INFERRED, and waits in the approval queue (backend/approvals.py, kind requirement_suggestion).
  4 coverage    per criterion: covered / uncovered / ambiguous / blocked / pending_review.

The AI never sees credentials, never changes a criterion, and its ideas are checked: unknown criteria, invented
people/records (ai_grounding) and outcomes not in the source are refused or marked inferred. Nothing is written to
Jira or Confluence. Re-analysis keeps review decisions of unchanged ideas (fingerprint) and marks a stored analysis
STALE when a source has a newer version, was removed, or a new page was linked.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from .. import audit_store
from . import store
from .models import (
    AcceptanceCriterion,
    Analysis,
    Basis,
    Citation,
    Classification,
    Conflict,
    Coverage,
    Extraction,
    IssueKind,
    QualityIssue,
    Requirement,
    ReviewStatus,
    ScenarioKind,
    ScenarioSuggestion,
    SourceKind,
    SourceRef,
    ai_use_allowed,
    normalize_text,
)

ACTION = "requirements.analyze"
REVIEW_ACTION = "requirements.review"
APPROVAL_KIND = "requirement_suggestion"

# a list marker or an acceptance-criterion label at the start of a line: '1.', '-', '[ ]', 'AC1:', 'AC-2 -', 'AC 3.',
# 'Acceptance criterion 4:', 'Criteria 5)'
_AC_NUMBER = r"(?:AC|acceptance[\s_-]*criteri(?:on|a)|criteri(?:on|a))[\s_#-]*0*\d{1,3}\s*[:.)\-–]"
MARKER = re.compile(r"^\s*(?:\d{1,3}[.)]|[-*•]|\[[ xX]?\]|" + _AC_NUMBER + r")\s+", re.I)
AC_LABEL = re.compile(r"^\s*(?:[-*•]\s+|\d{1,3}[.)]\s+)?" + _AC_NUMBER + r"\s*\S", re.I)  # a criterion without heading
GHERKIN = re.compile(r"^\s*(?:scenario(?: outline)?:|(?:given|when|then|and|but)\b)", re.I)
_AC_TITLE = (r"(?:acceptance[\s_-]*criteri(?:a|on)s?|acs?|acceptance tests?|definition of done|dod|"
             r"conditions? of (?:satisfaction|acceptance)|success criteria|business rules|rules|criteria)")
# a heading / label line that opens the acceptance criteria: '## Acceptance Criteria', 'AcceptanceCriteria:',
# 'Acceptance Criteria (AC)', 'ACs', 'Definition of Done', 'Conditions of satisfaction' (an emoji after it is fine)
AC_HEADING = re.compile(r"^\s*(?:#+\s*)?" + _AC_TITLE + r"\s*(?:\([^)]{0,30}\))?\s*[:\-–]?\s*[^\w\s]{0,3}\s*$", re.I)
AC_INLINE = re.compile(r"^\s*(?:acceptance[\s_-]*criteri(?:a|on)s?|acs?)\s*:\s*(?P<rest>\S.*)$", re.I)
# a label or heading that starts OTHER text: it ends the acceptance criteria (notes are never criteria)
_OTHER = (r"(?:notes?|references?|links?|attachments?|out[ -]of[ -]scope|not in scope|non[- ]goals?|dependencies|"
          r"assumptions?|open questions?|questions?|comments?|designs?|mock-?ups?|wireframes?|figma|"
          r"technical (?:notes?|details?)|implementation(?: notes?| details?)?|background|context|description|"
          r"user story|resources|see also|related(?: issues?| stories| links)?|sub-?tasks?|story points?|estimates?|"
          r"test data|environment|screenshots?|additional (?:information|info|notes?|context)|faqs?|risks?)")
STOP_LABEL = re.compile(r"^\s*(?:#+\s*)?" + _OTHER + r"\b(?:\s*\([^)]{0,30}\))?\s*(?::|[-–]\s|\s*$)", re.I)
HEADING = re.compile(r"^\s*(?:#+\s*)?(acceptance criteria|acceptance|criteria|definition of done|"
                        r"business rules|rules)\s*:?\s*$", re.I)
HEADING = re.compile(r"^\s*#+\s+\S")
ONE_LINE_GWT = re.compile(r"^\s*given\s+(?P<given>.+?),?\s+when\s+(?P<when>.+?),?\s+then\s+(?P<then>.+?)\s*$",
                          re.I | re.S)
SHALL = re.compile(r"\b(must|shall|must not|shall not|is required|are required|should not|cannot|can not|"
                   r"is not allowed|are not allowed|only)\b", re.I)
AMBIGUOUS = re.compile(r"\b(fast|quick(?:ly)?|slow|user[- ]friendly|intuitive|easy|easily|appropriate(?:ly)?|"
                       r"adequate(?:ly)?|reasonable|reasonably|several|some|many|few|etc\.?|and so on|as needed|"
                       r"as required|if possible|where possible|normally|usually|properly|correctly|nice|good|"
                       r"better|best|efficient(?:ly)?|robust|seamless(?:ly)?|flexible|optimal|minimal|"
                       r"as soon as possible|asap|large|small)\b", re.I)
INCOMPLETE = re.compile(r"\b(tbd|tbc|todo|to be (?:defined|decided|confirmed|done)|fixme|xxx)\b|\?\?|\.\.\.\s*$",
                        re.I)
NEGATION = re.compile(r"\b(must not|shall not|cannot|can not|never|is not allowed|are not allowed|may not|"
                      r"should not|no longer|not)\b", re.I)
SECURITY = re.compile(r"\b(passwords?|passcodes?|pin|log ?in|sign ?in|sign ?up|log ?out|auth\w*|token|session|"
                      r"permission|role|admin|payment|card|credit|personal data|account|otp|2fa|captcha)\b", re.I)
NUMBER = re.compile(r"(?P<lim>at least|minimum(?: of)?|min\.?|no (?:fewer|less) than|more than|over|"
                    r"at most|maximum(?: of)?|max\.?|up to|no more than|fewer than|less than|within|after)?\s*"
                    r"(?P<n>\d{1,9}(?:\.\d+)?)\s*(?P<unit>%|[a-z]+(?:\s+[a-z]+){0,2})?", re.I)
UNITS = {"char": "characters", "chars": "characters", "character": "characters", "characters": "characters",
         "digit": "digits", "digits": "digits", "try": "attempts", "tries": "attempts", "attempt": "attempts",
         "attempts": "attempts", "time": "attempts", "times": "attempts", "second": "seconds", "seconds": "seconds",
         "sec": "seconds", "secs": "seconds", "s": "seconds", "minute": "minutes", "minutes": "minutes",
         "min": "minutes", "mins": "minutes", "hour": "hours", "hours": "hours", "h": "hours", "day": "days",
         "days": "days", "item": "items", "items": "items", "product": "items", "products": "items",
         "%": "percent", "percent": "percent", "mb": "mb", "kb": "kb", "gb": "gb", "years": "years",
         "year": "years", "letters": "characters", "letter": "characters"}
LOWER = re.compile(r"at least|minimum|min\.?|no (?:fewer|less) than|more than|over", re.I)
UPPER = re.compile(r"at most|maximum|max\.?|up to|no more than|fewer than|less than|within", re.I)
STOP = set("""a an the and or of to in on at for with by is are be been it its this that these those as from into
than then when given if user users system page should must shall can will may not no only be has have had a
which who whom there their they them able after before each every any all""".split())
MANUAL = re.compile(r"\b(manual(?:ly)?|visual(?:ly)? (?:check|inspect)|legal review|by hand|physically|"
                    r"print(?:ed)? (?:copy|out))\b", re.I)


# ---------------------------------------------------------------- 1 extract

def _strip(line: str) -> str:
    """A line without its list marker and criterion label ('- AC1: x' -> 'x')."""
    for _ in range(2):
        line = MARKER.sub("", line)
    return line.strip()


def _until_other(lines: list[str]) -> list[str]:
    """The lines before the first label / heading that starts other text (Notes:, References:, ...)."""
    out = []
    for ln in lines:
        if STOP_LABEL.match(ln) and not AC_LABEL.match(ln):
            break
        out.append(ln)
    return out


def _labelled(lines: list[str]) -> list[str]:
    """No acceptance-criteria heading: only the labelled criteria ('AC1: ...', 'AC-2 - ...') and their Given /
    When / Then or indented continuation lines. Plain numbered lists without a heading are NOT taken: they are
    as often steps to reproduce as criteria."""
    out, open_item = [], False
    for ln in lines:
        if AC_LABEL.match(ln):
            out.append(ln)
            open_item = True
        elif open_item and ln.strip() and not HEADING.match(ln) and not STOP_LABEL.match(ln) and (
                GHERKIN.match(_strip(ln)) or ln.startswith("   ")):
            out.append(ln)
        else:
            if open_item:
                out.append("")
            open_item = False
    return out


def _criterion_items(text: str, whole: bool) -> list[tuple[str, str]]:
    """(criterion text, quote) pairs from plain text. whole=True: the text IS acceptance criteria (the Jira field);
    otherwise the part under an 'Acceptance criteria' heading / label is read, and without such a heading only the
    labelled criteria (AC1:, AC-2, ...). A 'Notes:' / 'References:' / other heading ends the criteria."""
    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    if whole:
        lines = _until_other(lines)
    else:
        region, inside, found = [], False, False
        for ln in lines:
            if AC_HEADING.match(ln):
                inside = found = True
                continue
            inline = AC_INLINE.match(ln)
            if inline and not AC_LABEL.match(ln):
                inside = found = True
                region.append(inline.group("rest"))
                continue
            if inside and (HEADING.match(ln) or (STOP_LABEL.match(ln) and not AC_LABEL.match(ln))):
                inside = False
                region.append("")
                continue
            if inside:
                region.append(ln)
        lines = region if found else _labelled(lines)
    items: list[list[str]] = []
    gherkin: list[str] | None = None
    for ln in lines:
        if not ln.strip():
            gherkin = None
            continue
        body = _strip(ln)
        if GHERKIN.match(body):
            starts_new = gherkin is None or re.match(r"^\s*(scenario|given)\b", body, re.I) and any(
                re.match(r"^\s*then\b", _strip(x), re.I) for x in gherkin)
            if MARKER.match(ln) or starts_new:
                gherkin = [ln]
                items.append(gherkin)
            else:
                gherkin.append(ln)
            continue
        gherkin = None
        if MARKER.match(ln) or not ln.startswith("   "):
            items.append([ln])
        elif items:
            items[-1].append(ln)  # (an indented continuation line)
    out = []
    for group in items:
        quote = "\n".join(group).strip()
        words = " ".join(_strip(g) for g in group)
        words = re.sub(r"^\s*scenario(?: outline)?:\s*", "", words, flags=re.I).strip()
        if len(words) >= 3 and not HEADING.match(group[0]):
            out.append((words, quote))
    return out


def _gherkin_parts(text: str) -> dict:
    m = ONE_LINE_GWT.match(text)
    if m:
        return {k: v.strip().rstrip(".,") for k, v in m.groupdict().items()}
    parts, current = {"given": [], "when": [], "then": []}, None
    for chunk in re.split(r"\s*\b(?=(?:given|when|then|and|but)\b)", text, flags=re.I):
        m = re.match(r"(given|when|then|and|but)\s+(.*)", chunk.strip(), re.I | re.S)
        if not m:
            continue
        word, rest = m.group(1).lower(), m.group(2).strip().rstrip(".,")
        if word in ("given", "when", "then"):
            current = word
            parts[current].append(rest)
        elif current:
            parts[current].append(rest)
    if not parts["then"] and not parts["given"] and not parts["when"]:
        return {}
    joiner = {"given": " and ", "when": " and ", "then": " and "}
    return {k: joiner[k].join(v) for k, v in parts.items() if v}


def _make(requirement_id: str, n: int, text: str, citation: Citation, platforms: list[str]) -> AcceptanceCriterion:
    parts = _gherkin_parts(text) if re.search(r"\b(given|when|then)\b", text, re.I) else {}
    automatable, reason = True, ""
    from ..android_checks import DEVICE_ONLY  # (the same list the Android tester uses for 'not testable here')
    if MANUAL.search(text):
        automatable, reason = False, "the source asks for a manual / visual / legal check"
    elif DEVICE_ONLY.search(text):
        automatable, reason = False, (f"needs device hardware ('{DEVICE_ONLY.search(text).group(0)}'): "
                                      "test on a real phone")
    try:
        return AcceptanceCriterion(id=f"{requirement_id}#AC-{n}", requirement_id=requirement_id, text=text,
                                   given=parts.get("given", ""), when=parts.get("when", ""),
                                   then=parts.get("then", ""), expected_outcome=parts.get("then", ""),
                                   citations=[citation], extraction=Extraction.rules, automatable=automatable,
                                   not_automatable_reason=reason, platforms=platforms)
    except ValueError:
        # (a Gherkin part that is not word for word in the quote: keep the criterion, drop the parts)
        return AcceptanceCriterion(id=f"{requirement_id}#AC-{n}", requirement_id=requirement_id, text=text,
                                   citations=[citation], extraction=Extraction.rules, automatable=automatable,
                                   not_automatable_reason=reason, platforms=platforms)


def _from_story(source: SourceRef, content: dict) -> list[tuple[str, Citation]]:
    found = []
    field = content.get("acceptance_field") or "acceptance criteria"
    for words, quote in _criterion_items(content.get("acceptance_criteria", ""), whole=True):
        found.append((words, Citation(source=source, locator=field, quote=quote[:2000])))
    if not found:  # (no AC field: an 'Acceptance criteria' part of the description)
        for words, quote in _criterion_items(content.get("description", ""), whole=False):
            found.append((words, Citation(source=source, locator="description: acceptance criteria",
                                          quote=quote[:2000])))
    return found


def _from_page(source: SourceRef, content: dict) -> list[tuple[str, Citation]]:
    found = []
    for section in content.get("sections", []):
        heading_says = AC_HEADING.match(section.get("heading", "")) or section.get("requirement_like")
        if not heading_says:
            continue
        locator = ("section: " + " > ".join(section.get("path") or [])) or "page"
        header_row = ""
        for i, block in enumerate(section.get("blocks", [])):
            text, kind = block["text"], block["type"]
            if kind == "table_row":
                prev = section["blocks"][i - 1]["type"] if i else ""
                if prev != "table_row":
                    header_row = text  # (the first row of a table names the columns)
                    continue
                found.append((text, Citation(source=source, locator=locator + " (table)",
                                             quote=f"{header_row}\n{text}"[:2000])))
            elif kind == "code" and GHERKIN.search(text):
                for words, quote in _criterion_items(text, whole=True):
                    found.append((words, Citation(source=source, locator=locator + " (Gherkin)", quote=quote[:2000])))
            elif kind in ("list_item", "task") or (kind == "paragraph" and (SHALL.search(text)
                                                                           or GHERKIN.match(text))):
                words = _strip(text)
                if len(words) >= 3:
                    found.append((words, Citation(source=source, locator=locator, quote=text[:2000])))
    return found


def build_requirement(db, tenant_id: str, root_key: str) -> Requirement:
    """The requirement of a stored story (with the pages that specify it) or of a stored page on its own."""
    root = store.get_source(db, tenant_id, root_key)
    if not root:
        raise LookupError(f"{root_key} is not stored for this tenant")
    src: SourceRef = root["source"]
    sources = [(src, root["content"], root["present"])]
    if src.kind == SourceKind.jira_issue:
        jira_type = str(root["content"].get("type", "")).strip().lower()
        kind = jira_type if jira_type in ("bug", "task", "epic") else "story"  # (Story, User Story, custom types)
        req_id, title = src.source_id, src.title
        seen = {root_key}
        frontier = [link["to_key"] for link in store.links_from(db, tenant_id, root_key)
                    if link["relation"] == "specified_by"]
        frontier += [link["from_key"] for link in store.links_to(db, tenant_id, root_key)
                     if link["relation"] == "mentions"]
        for key in frontier:
            if key in seen:
                continue
            seen.add(key)
            page = store.get_source(db, tenant_id, key)
            if page:
                sources.append((page["source"], page["content"], page["present"]))
    else:
        req_id, kind, title = f"conf-{src.source_id}", "spec", src.title
    criteria, n = [], 0
    for source, content, _present in sources:
        pieces = _from_story(source, content) if source.kind == SourceKind.jira_issue else _from_page(source, content)
        platforms = ["web"]
        for words, citation in pieces:
            n += 1
            if n > 999:
                break
            criteria.append(_make(req_id, n, words, citation, platforms))
    return Requirement(id=req_id, tenant_id=tenant_id, kind=kind, title=title[:500] or req_id,
                       sources=[s for s, _c, _p in sources], criteria=criteria,
                       classification=_classification(db, tenant_id, [s for s, _c, _p in sources]),
                       labels=list(root["content"].get("labels") or []) if src.kind == SourceKind.jira_issue else [],
                       status=str(root["content"].get("status", "")) if src.kind == SourceKind.jira_issue else "")


def _classification(db, tenant_id: str, sources: list[SourceRef]) -> Classification:
    order = [Classification.public, Classification.internal, Classification.confidential]
    worst = Classification.public
    for s in sources:
        conn = store.get_connection(db, tenant_id, s.connection_id)
        level = conn.classification if conn else Classification.internal  # (unknown: not public)
        if order.index(level) > order.index(worst):
            worst = level
    return worst


# ---------------------------------------------------------------- 2 check

def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9']+", normalize_text(text)) if w not in STOP and len(w) > 1}


def _similar(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def _limits(text: str) -> list[tuple[str, float, str]]:
    """(unit, number, 'min' | 'max' | '') for each number with a known unit."""
    out = []
    for m in NUMBER.finditer(text):
        # (the unit may follow a word or two: '3 wrong tries', '8 or more characters')
        unit = next((UNITS[w] for w in (m.group("unit") or "").lower().replace(".", "").split() if w in UNITS), None)
        if not unit:
            continue
        lim = m.group("lim") or ""
        kind = "min" if LOWER.fullmatch(lim.strip()) else "max" if UPPER.fullmatch(lim.strip()) else ""
        out.append((unit, float(m.group("n")), kind))
    return out


def _disagree(a: AcceptanceCriterion, b: AcceptanceCriterion) -> str:
    """Why two criteria about the same thing contradict each other ('' = they do not)."""
    shared = _tokens(a.text) & _tokens(b.text)
    if len(shared) < 2 or _similar(a.text, b.text) < 0.3:
        return ""
    for unit, n1, k1 in _limits(a.text):
        for unit2, n2, k2 in _limits(b.text):
            if unit == unit2 and n1 != n2 and (k1 == k2 or not k1 or not k2):
                return f"different {unit}: {n1:g} vs {n2:g}"
    neg_a, neg_b = bool(NEGATION.search(a.text)), bool(NEGATION.search(b.text))
    if neg_a != neg_b and _similar(NEGATION.sub("", a.text), NEGATION.sub("", b.text)) >= 0.6:
        return "one says it is allowed / happens, the other says it is not"
    return ""


def check(requirement: Requirement) -> tuple[list[QualityIssue], list[Conflict]]:
    issues: list[QualityIssue] = []
    conflicts: list[Conflict] = []
    rid = requirement.id

    def issue(kind: IssueKind, criteria: list[AcceptanceCriterion], detail: str, citations=None):
        issues.append(QualityIssue(id=f"{rid}#Q-{len(issues) + 1}", requirement_id=rid, kind=kind,
                                   criterion_ids=[c.id for c in criteria], detail=detail,
                                   citations=citations or [c.citations[0] for c in criteria]))

    if not requirement.criteria:
        first = requirement.sources[0]
        issue(IssueKind.missing_criteria, [], "no acceptance criteria were found in the story or its linked pages; "
              "none were invented - ask the owner to add them",
              [Citation(source=first, locator="summary", quote=first.title or requirement.title)])
    for c in requirement.criteria:
        if m := INCOMPLETE.search(c.text):
            issue(IssueKind.incomplete, [c], f"not finished: '{m.group(0)}'")
        elif (c.given or c.when) and not c.then and re.search(r"\b(given|when)\b", c.text, re.I):
            issue(IssueKind.incomplete, [c], "Given/When without a Then: the expected result is missing")
        if m := AMBIGUOUS.search(c.text):
            if not re.search(r"\d", c.text) or m.group(0).lower() in ("etc", "etc.", "and so on", "as needed"):
                issue(IssueKind.ambiguous, [c], f"vague word '{m.group(0)}': say exactly what is expected")
    crits = requirement.criteria
    for i, a in enumerate(crits):
        for b in crits[i + 1:]:
            same_source = a.citations[0].source.key == b.citations[0].source.key
            why = _disagree(a, b)  # (first: '8 characters' vs '12 characters' share every word but disagree)
            if not why:
                if normalize_text(a.text) == normalize_text(b.text) or _similar(a.text, b.text) >= 0.85:
                    issue(IssueKind.duplicate, [a, b], "the same criterion appears twice"
                          + ("" if same_source else " (in the story and in a linked page)"))
                continue
            if same_source:
                issue(IssueKind.contradictory, [a, b], f"these criteria contradict each other: {why}")
            else:
                conflicts.append(Conflict(id=f"{rid}#X-{len(conflicts) + 1}", tenant_id=requirement.tenant_id,
                                          requirement_ids=[rid], summary=f"{a.id} and {b.id} disagree: {why}",
                                          citations=[a.citations[0], b.citations[0]], detected_by="rules"))
    return issues, conflicts


# ---------------------------------------------------------------- 3 suggest

def _fingerprint(criterion: AcceptanceCriterion, kind: str, title: str) -> str:
    raw = f"{normalize_text(criterion.text)}|{kind}|{normalize_text(title)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def rule_suggestions(requirement: Requirement, blocked: set[str]) -> list[dict]:
    """Test ideas from fixed templates. Only the positive check of a criterion can be EXPLICIT (its own words);
    negative, boundary and security ideas are INFERRED and say so."""
    out = []
    for c in requirement.criteria:
        if c.id in blocked or not c.usable:
            continue
        quote = c.citations[0].quote
        steps = [s for s in (f"Given {c.given}" if c.given else "", f"When {c.when}" if c.when else "") if s]
        expected = c.then or c.text
        out.append({"criterion": c, "kind": ScenarioKind.positive, "title": f"Check: {c.text}"[:300], "steps": steps,
                        "expected_outcome": expected, "basis": Basis.explicit, "support_quote": quote,
                        "note": "expected outcome quoted from the source"})
        if SHALL.search(c.text) or re.search(r"\b(required|only|at least|at most|maximum|minimum)\b",
                                             c.text, re.I):
            out.append({"criterion": c, "kind": ScenarioKind.negative, "title": f"Break the rule: {c.text}"[:300],
                            "steps": ["Do what the criterion forbids or leave out what it requires"],
                            "expected_outcome": "", "basis": Basis.inferred, "support_quote": "",
                            "note": "inferred: the source does not say how a violation is reported"})
        for unit, n, kind in _limits(c.text):
            if kind == "min" or (not kind and unit in ("characters", "digits", "items")):
                values = [n - 1, n]
            elif kind == "max":
                values = [n, n + 1]
            else:
                values = [n - 1, n]
            out.append({"criterion": c, "kind": ScenarioKind.boundary,
                            "title": f"Boundary {unit}: try {values[0]:g} and {values[1]:g} ({c.text})"[:300],
                            "steps": [f"Use {v:g} {unit}" for v in values], "expected_outcome": "", "basis": Basis.inferred,
                            "support_quote": "", "note": f"inferred from the number {n:g} {unit} in the source"})
            break
        if SECURITY.search(c.text):
            out.append({"criterion": c, "kind": ScenarioKind.security,
                            "title": f"Security around: {c.text}"[:300],
                            "steps": ["Check secrets are never shown or sent in clear text",
                                   "Check error messages do not reveal which part was wrong",
                                   "Check repeated attempts are limited"],
                            "expected_outcome": "", "basis": Basis.inferred, "support_quote": "",
                            "note": "inferred: common security checks, not stated in the source"})
    return out


class _AIIdea(BaseModel):
    criterion_ids: list[str] = Field(min_length=1, max_length=5)
    kind: ScenarioKind
    title: str = Field(min_length=3, max_length=300)
    steps: list[str] = Field(default_factory=list, max_length=12)
    expected_outcome: str = Field(default="", max_length=600)


AI_SYSTEM = ("You suggest software test scenarios for acceptance criteria. Use ONLY the criteria given. Do not add "
             "requirements, people, records, prices or messages that are not in them. Return JSON only.")


def ai_suggestions(requirement: Requirement, blocked: set[str], ask=None) -> list[dict]:
    """AI test ideas, checked before use: unknown criterion ids, invented people / records and outcomes not in the
    cited criteria are refused or marked inferred. The criteria themselves are never changed by the AI."""
    from ..ai_grounding import invented_record_problem
    from ..objective import destructive
    usable = [c for c in requirement.criteria if c.usable and c.id not in blocked]
    if not usable:
        return []
    listing = "\n".join(f"{c.id}: {c.text}" for c in usable)
    prompt = ("Acceptance criteria:\n" + listing + "\n\nFor these criteria suggest test scenarios of the kinds "
              "positive, negative, boundary and security (only where relevant). Answer a JSON list of objects "
              '{"criterion_ids": [...], "kind": "...", "title": "...", "steps": ["..."], "expected_outcome": "..."}. '
              "Leave expected_outcome empty when the criteria do not state the result.")
    if ask is None:
        from ..llm import ask_structured
        ask = ask_structured
    ideas = ask(prompt, list[_AIIdea], system=AI_SYSTEM, agent="requirements")
    by_id = {c.id: c for c in usable}
    source_text = "\n".join(c.text + "\n" + c.citations[0].quote for c in usable)
    out = []
    for idea in ideas[:60]:
        cited = [by_id[i] for i in idea.criterion_ids if i in by_id]
        if not cited or len(cited) != len(idea.criterion_ids):
            continue  # (refers to a criterion that does not exist: refused)
        words = " ".join([idea.title, *idea.steps, idea.expected_outcome])
        if invented_record_problem(words, [], requirements=source_text):
            continue  # (invented people or records: refused)
        quote = "\n".join(c.citations[0].quote + "\n" + c.text for c in cited)
        explicit = bool(idea.expected_outcome) and normalize_text(idea.expected_outcome) in normalize_text(quote)
        out.append({"criterion": cited[0], "criteria": cited, "kind": idea.kind, "title": idea.title, "steps": idea.steps,
                        "expected_outcome": idea.expected_outcome, "basis": Basis.explicit if explicit else Basis.inferred,
                        "support_quote": quote[:2000] if explicit else "",
                        "note": "AI suggestion: expected outcome quoted from the source" if explicit else
                        "AI suggestion: inferred, not a confirmed requirement", "destructive": destructive(words).lower(),
                        "origin": "ai"})
    return out


# ---------------------------------------------------------------- 4 coverage

def _held(requirement: Requirement, issues: list[QualityIssue], conflicts: list[Conflict]) -> tuple[set, set]:
    """(criteria in an open conflict, ambiguous / incomplete criteria): both are clarified before any test idea."""
    places = {(cit.source.key, cit.locator, cit.quote) for x in conflicts if x.status == "open" for cit in x.citations}
    disputed = {c.id for c in requirement.criteria
                if (c.citations[0].source.key, c.citations[0].locator, c.citations[0].quote) in places}
    vague = {cid for q in issues if q.kind in (IssueKind.ambiguous, IssueKind.incomplete) for cid in q.criterion_ids}
    return disputed, vague


def coverage(requirement: Requirement, issues: list[QualityIssue], conflicts: list[Conflict],
             suggestions: list[ScenarioSuggestion], missing_sources: set[str]) -> tuple[dict, dict]:
    status, why = {}, {}
    disputed, vague = _held(requirement, issues, conflicts)
    for c in requirement.criteria:
        mine = [s for s in suggestions if c.id in s.criterion_ids]
        if not c.automatable:
            status[c.id], why[c.id] = Coverage.blocked, c.not_automatable_reason
        elif c.citations[0].source.key in missing_sources:
            status[c.id], why[c.id] = Coverage.blocked, "its source page or story is no longer visible"
        elif c.id in disputed:
            status[c.id], why[c.id] = Coverage.blocked, "an open conflict with another source"
        elif c.review == ReviewStatus.rejected:
            status[c.id], why[c.id] = Coverage.blocked, "a reviewer rejected this criterion"
        elif c.id in vague:
            status[c.id], why[c.id] = Coverage.ambiguous, "ambiguous or incomplete: clarify it first"
        elif any(s.review == ReviewStatus.accepted for s in mine):
            status[c.id], why[c.id] = Coverage.covered, "an approved test scenario exists (not yet executed)"
        elif not c.usable or any(s.review == ReviewStatus.needs_review for s in mine):
            status[c.id], why[c.id] = Coverage.pending_review, "test scenarios wait for review"
        else:
            status[c.id], why[c.id] = Coverage.uncovered, "no approved test scenario"
    return status, why


# ---------------------------------------------------------------- the whole analysis

def _audit(actor, allowed, tenant_id, action, detail, audit_db):
    try:
        audit_store.record_audit(actor=actor or "system", action=action, allowed=allowed, tenant_id=tenant_id,
                                 detail=json.dumps(detail, sort_keys=True, default=str)[:2000], db_path=audit_db)
    except (OSError, ValueError):
        pass


def _ai_permission(requirement: Requirement, db, tenant_id: str) -> tuple[bool, str]:
    from ..config import settings
    from ..privacy import PrivacyError, load_policy, require_loopback_ai, runtime_mode
    provider = settings.llm_provider
    if provider in ("none", ""):
        return False, "no AI provider is configured"
    local = False
    if provider == "ollama":
        try:
            require_loopback_ai(settings.ollama_url)
            local = True
        except PrivacyError:
            return False, "the Ollama address is not on this computer"
    policy = load_policy()
    for source in requirement.sources:
        conn = store.get_connection(db, tenant_id, source.connection_id)
        ok, why = ai_use_allowed(requirement.classification, privacy_mode=runtime_mode(),
                                 cloud_consent=policy.cloud_consent, provider_is_local=local, connection=conn)
        if not ok:
            return False, why
    return True, "allowed by the privacy settings"


def analyze(db, tenant_id: str, root_key: str, *, ai: str = "off", actor: str = "system", approvals_db=None,
            audit_db=None, ask=None, now: datetime | None = None) -> Analysis:
    """Analyse one stored story (with its linked pages) or one stored page. ai: 'off' (rules only) or 'auto' (AI
    ideas too, only when the privacy settings allow it). Suggestions go to the approval queue."""
    from .. import approvals
    if ai not in ("off", "auto"):
        raise ValueError("ai must be 'off' or 'auto'")
    requirement = build_requirement(db, tenant_id, root_key)
    previous = store.get_analysis(db, tenant_id, requirement.id)
    kept = {s.fingerprint: s for s in (previous.suggestions if previous else []) if s.fingerprint}
    issues, conflicts = check(requirement)
    if previous:  # (a person's resolution of an unchanged conflict stays)
        resolved = {(x.summary, tuple(c.quote for c in x.citations)): x for x in previous.conflicts if x.status != "open"}
        conflicts = [resolved.get((x.summary, tuple(c.quote for c in x.citations)), x) for x in conflicts]
    disputed, vague = _held(requirement, issues, conflicts)
    blocked = {c.id for c in requirement.criteria if not c.automatable} | disputed | vague
    ideas = rule_suggestions(requirement, blocked)
    ai_state, ai_note = "off", "rules only"
    if ai == "auto":
        allowed, why = _ai_permission(requirement, db, tenant_id)
        if not allowed:
            ai_state, ai_note = "not_allowed", why
        else:
            try:
                ideas += ai_suggestions(requirement, blocked, ask=ask)
                ai_state, ai_note = "used", "AI suggestions added (each one reviewed before use)"
            except Exception as error:  # (no AI answer: the rules result stands)
                ai_state, ai_note = "failed", f"AI unavailable: {type(error).__name__}"
    suggestions: list[ScenarioSuggestion] = []
    seen_titles = set()
    for idea in ideas:
        crit = idea["criterion"]
        title_key = normalize_text(idea["title"])
        if title_key in seen_titles:  # (the same idea for a repeated criterion: one suggestion covers both)
            for i, existing in enumerate(suggestions):
                if normalize_text(existing.title) == title_key and crit.id not in existing.criterion_ids:
                    suggestions[i] = existing.model_copy(update={"criterion_ids": [*existing.criterion_ids, crit.id]})
            continue
        seen_titles.add(title_key)
        fp = _fingerprint(crit, idea["kind"].value, idea["title"])
        old = kept.get(fp)
        suggestion = ScenarioSuggestion(
            id=f"{requirement.id}#S-{len(suggestions) + 1}", requirement_id=requirement.id,
            criterion_ids=[c.id for c in idea.get("criteria", [crit])], kind=idea["kind"], title=idea["title"],
            steps=idea["steps"], expected_outcome=idea["expected_outcome"], basis=idea["basis"],
            support_quote=idea["support_quote"], note=idea["note"], origin=idea.get("origin", "rules"),
            destructive=idea.get("destructive", ""), fingerprint=fp,
            review=old.review if old else ReviewStatus.needs_review, reviewer=old.reviewer if old else "",
            approval_id=old.approval_id if old else "")
        if not suggestion.approval_id:
            detail = json.dumps({"requirement": requirement.id, "suggestion": suggestion.id, "basis":
                                 suggestion.basis.value, "criteria": suggestion.criterion_ids})
            row = approvals.create(APPROVAL_KIND, suggestion.title[:200], detail=detail, tenant_id=tenant_id,
                                   path=approvals_db)
            suggestion = suggestion.model_copy(update={"approval_id": row["id"]})
        suggestions.append(suggestion)
    versions = {s.key: s.version for s in requirement.sources}
    missing = {s.key for s in requirement.sources
               if not (store.get_source(db, tenant_id, s.key) or {}).get("present", True)}
    status, why = coverage(requirement, issues, conflicts, suggestions, missing)
    analysis = Analysis(tenant_id=tenant_id, requirement=requirement, source_versions=versions,
                        missing_sources=sorted(missing),
                        analyzed_at=now or datetime.now(UTC), actor=actor, ai=ai_state, ai_note=ai_note,
                        issues=issues, conflicts=conflicts, suggestions=suggestions, coverage=status,
                        coverage_reason=why)
    store.save_analysis(db, analysis, event=f"analyzed (ai: {ai_state})")
    _audit(actor, True, tenant_id, ACTION, {"requirement": requirement.id, "criteria": len(requirement.criteria),
                                            "issues": len(issues), "conflicts": len(conflicts),
                                            "suggestions": len(suggestions), "ai": ai_state}, audit_db)
    return analysis


def stale(db, tenant_id: str, analysis: Analysis) -> list[str]:
    """Why a stored analysis no longer matches its sources ([] = still current)."""
    reasons = []
    for key, version in analysis.source_versions.items():
        now = store.get_source(db, tenant_id, key)
        if not now:
            reasons.append(f"{key} is no longer stored")
        elif not now["present"] and key not in analysis.missing_sources:
            reasons.append(f"{key} is no longer visible in Atlassian")
        elif now["source"].version != version:
            reasons.append(f"{key} changed: version {version} -> {now['source'].version}")
    root = next(iter(analysis.source_versions), "")
    if root and ":jira_issue:" in root:
        linked = {link["to_key"] for link in store.links_from(db, tenant_id, root) if link["relation"] == "specified_by"}
        linked |= {link["from_key"] for link in store.links_to(db, tenant_id, root) if link["relation"] == "mentions"}
        for key in sorted(linked - set(analysis.source_versions)):
            if store.get_source(db, tenant_id, key):
                reasons.append(f"{key} was linked after the analysis")
    return reasons


def review(db, tenant_id: str, requirement_id: str, suggestion_id: str, answer: str, reviewer: str, *,
           approvals_db=None, audit_db=None) -> ScenarioSuggestion:
    """A person accepts or rejects one suggestion, through the existing approval queue. The criteria never change."""
    from .. import approvals
    if not (reviewer or "").strip():
        raise ValueError("a review needs the reviewer's name")
    analysis = store.get_analysis(db, tenant_id, requirement_id)
    if analysis is None:
        raise LookupError(f"{requirement_id} has no analysis for this tenant")
    target = next((s for s in analysis.suggestions if s.id == suggestion_id), None)
    if target is None:
        raise LookupError(f"{suggestion_id} is not a suggestion of {requirement_id}")
    try:
        queued = approvals.get_approval(target.approval_id, tenant_id=tenant_id, path=approvals_db)
        if not _approval_matches(queued, requirement_id, suggestion_id):
            raise PermissionError("the approval record does not belong to this suggestion")
        row = approvals.decide_approval(target.approval_id, answer, tenant_id=tenant_id, path=approvals_db,
                                        decided_by=reviewer.strip())
    except PermissionError as error:
        _audit(reviewer, False, tenant_id, REVIEW_ACTION, {"suggestion": suggestion_id, "why": str(error)[:120]},
               audit_db)
        raise
    decision = ReviewStatus.accepted if row["status"] == "accepted" else ReviewStatus.rejected
    updated = target.model_copy(update={"review": decision, "reviewer": reviewer.strip()})
    suggestions = [updated if s.id == suggestion_id else s for s in analysis.suggestions]
    missing = {k for k in analysis.source_versions
               if not (store.get_source(db, tenant_id, k) or {}).get("present", True)}
    status, why = coverage(analysis.requirement, analysis.issues, analysis.conflicts, suggestions, missing)
    analysis = analysis.model_copy(update={"suggestions": suggestions, "coverage": status, "coverage_reason": why})
    store.save_analysis(db, analysis, event=f"{suggestion_id} {decision.value} by {reviewer.strip()}"[:200])
    _audit(reviewer, True, tenant_id, REVIEW_ACTION, {"suggestion": suggestion_id, "decision": decision.value},
           audit_db)
    return updated


def summary(analysis: Analysis) -> dict:
    """A compact, readable view (for people and the Studio later)."""
    return {
        "requirement": analysis.requirement.id, "title": analysis.requirement.title,
        "sources": [f"{s.kind.value} {s.source_id} v{s.version}" for s in analysis.requirement.sources],
        "ai": f"{analysis.ai} ({analysis.ai_note})",
        "criteria": [{"id": c.id, "text": c.text, "from": f"{c.citations[0].source.source_id} "
                      f"v{c.citations[0].source.version} · {c.citations[0].locator}",
                      "then": c.then, "coverage": analysis.coverage.get(c.id, "").value
                      if analysis.coverage.get(c.id) else "", "why": analysis.coverage_reason.get(c.id, "")}
                     for c in analysis.requirement.criteria],
        "issues": [f"{q.kind.value}: {', '.join(q.criterion_ids) or analysis.requirement.id} - {q.detail}"
                   for q in analysis.issues],
        "conflicts": [{"summary": x.summary, "evidence": [f"{c.source.source_id} v{c.source.version} "
                                                          f"({c.locator}): {c.quote}" for c in x.citations]}
                      for x in analysis.conflicts],
        "suggestions": [f"{s.id} [{s.kind.value}, {s.basis.value}, {s.origin}, {s.review.value}] {s.title}"
                        for s in analysis.suggestions],
    }


def _approval_matches(row: dict, requirement_id: str, suggestion_id: str) -> bool:
    """The queue row was created by analyze() for exactly this suggestion (not made up through another route)."""
    if row.get("kind") != APPROVAL_KIND:
        return False
    try:
        detail = json.loads(row.get("detail") or "{}")
    except ValueError:
        return False
    return detail.get("requirement") == requirement_id and detail.get("suggestion") == suggestion_id


def review_approval(db, approval_id: str, answer: str, reviewer: str, *, tenant_id: str | None = None,
                    approvals_db=None, audit_db=None) -> ScenarioSuggestion:
    """Decide a requirement suggestion by its approval-queue id (what the approvals API receives): the queue AND
    the stored analysis change together. tenant_id=None (Studio login off) uses the row's own tenant."""
    from .. import approvals
    row = approvals.get_approval(approval_id, tenant_id=tenant_id, path=approvals_db)
    if row.get("kind") != APPROVAL_KIND:
        raise ValueError("not a requirement suggestion")
    try:
        detail = json.loads(row.get("detail") or "{}")
    except ValueError:
        raise PermissionError("the approval record has no requirement reference") from None
    requirement_id, suggestion_id = str(detail.get("requirement", "")), str(detail.get("suggestion", ""))
    if not (requirement_id and suggestion_id):
        raise PermissionError("the approval record has no requirement reference")
    tenant = str(row.get("tenant_id") or "")
    analysis = store.get_analysis(db, tenant, requirement_id) if tenant else None
    target = next((s for s in (analysis.suggestions if analysis else []) if s.id == suggestion_id), None)
    if target is None or target.approval_id != approval_id:
        # (a row that analyze() did not create, or one replaced by a newer analysis)
        _audit(reviewer or "unknown", False, tenant, REVIEW_ACTION,
               {"approval": approval_id, "why": "no matching suggestion"}, audit_db)
        raise PermissionError("this approval is not linked to a current requirement suggestion")
    return review(db, tenant, requirement_id, suggestion_id, answer, reviewer, approvals_db=approvals_db,
                  audit_db=audit_db)
