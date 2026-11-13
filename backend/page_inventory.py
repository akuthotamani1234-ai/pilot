"""Read-only DOM component inventory, state observations and evidence-linked export."""

import hashlib
import html
import json
from collections import Counter
from pathlib import Path

from .safety import redact

MAX_COMPONENTS = 2000
MAX_STATES = 24

DOM_COMPONENTS_JS = r"""() => {
  const roots = [], nodes = [], MAX_NODES = 20000, MAX_ITEMS = 2000;
  let truncated = false;
  const visit = root => {
    roots.push(root);
    const iterator = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
    let element;
    while ((element = iterator.nextNode())) {
      if (nodes.length >= MAX_NODES) { truncated = true; break; }
      nodes.push(element);
      if (element.shadowRoot) visit(element.shadowRoot);
    }
  };
  visit(document);
  const q = value => String(value).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  const esc = value => CSS.escape(value);
  const clean = value => String(value || '').replace(/\s+/g, ' ').trim().slice(0, 120);
  const stable = value => value && value.length < 100 && !/[\u0000-\u001f]/.test(value) && !/[a-f0-9]{16,}|\d{7,}/i.test(value);
  const localSelector = element => {
    const root = element.getRootNode();
    for (const key of ['data-testid', 'data-test', 'data-qa', 'id']) {
      const value = element.getAttribute(key);
      if (!stable(value)) continue;
      const selector = key === 'id' ? '#' + esc(value) : '[' + key + '="' + q(value) + '"]';
      if (root.querySelectorAll(selector).length === 1) return selector;
    }
    const parts = [];
    let current = element;
    while (current && current.nodeType === 1 && parts.length < 64) {
      const tag = current.tagName.toLowerCase();
      const siblings = current.parentElement ? [...current.parentElement.children].filter(e => e.tagName === current.tagName) : [];
      parts.unshift(tag + (siblings.length > 1 ? ':nth-of-type(' + (siblings.indexOf(current) + 1) + ')' : ''));
      const selector = parts.join(' > ');
      if (root.querySelectorAll(selector).length === 1) return selector;
      current = current.parentElement;
    }
    return parts.join(' > ');
  };
  const selectors = new WeakMap();
  const selectorFor = element => {
    if (selectors.has(element)) return selectors.get(element);
    const local = localSelector(element), root = element.getRootNode();
    const full = root.host ? selectorFor(root.host) + ' >> ' + local : local;
    selectors.set(element, full);
    return full;
  };
  const visible = element => {
    const style = getComputedStyle(element), rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 && style.display !== 'none'
      && style.visibility !== 'hidden' && style.visibility !== 'collapse';
  };
  const typeOf = element => {
    const tag = element.tagName.toLowerCase(), role = (element.getAttribute('role') || '').toLowerCase();
    if (tag === 'input') return ({checkbox:'checkbox', radio:'radio', range:'slider', file:'file_upload',
      date:'date_picker', datetime:'date_picker', 'datetime-local':'date_picker', search:'search_input',
      number:'number_input', password:'password_input', submit:'button', button:'button', reset:'button'})[element.type] || 'text_input';
    if (tag === 'select') return 'dropdown';
    if (tag === 'textarea' || element.isContentEditable) return 'text_input';
    if (role === 'combobox') return 'dropdown';
    if (role) return ({menu:'menu', menubar:'menu', menuitem:'menu_item', menuitemcheckbox:'menu_item',
      menuitemradio:'menu_item', navigation:'navigation', tab:'tab', tablist:'tabs', tabpanel:'tab_panel',
      dialog:'dialog', alertdialog:'dialog', alert:'alert', status:'status', tooltip:'tooltip',
      table:'table', grid:'data_grid', treegrid:'data_grid', tree:'tree', treeitem:'tree_item',
      option:'option', listbox:'listbox', button:'button', link:'link', checkbox:'checkbox',
      radio:'radio', switch:'switch', slider:'slider', progressbar:'progress', textbox:'text_input',
      searchbox:'search_input', img:'image', region:'region', heading:'heading'})[role] || 'aria_component';
    if (tag === 'a' && element.hasAttribute('href')) return 'link';
    if (tag === 'button') return element.hasAttribute('aria-haspopup') ? 'dropdown_trigger' : 'button';
    if (tag === 'summary') return 'accordion_trigger';
    if (tag === 'details') return 'accordion';
    if (tag === 'dialog') return 'dialog';
    if (tag === 'nav') return 'navigation';
    if (tag === 'aside') return 'sidebar';
    if (tag === 'header' || tag === 'footer' || tag === 'main') return tag;
    if (tag === 'form') return 'form';
    if (tag === 'fieldset') return 'field_group';
    if (/^h[1-6]$/.test(tag)) return 'heading';
    if (tag === 'table') return 'table';
    if (tag === 'img' || tag === 'picture') return 'image';
    if (tag === 'canvas') return 'canvas';
    if (tag === 'video' || tag === 'audio') return tag;
    if (tag === 'progress' || tag === 'meter') return 'progress';
    const words = ((element.id || '') + ' ' + (typeof element.className === 'string' ? element.className : '')).split(/[\s_-]+/);
    if (words.some(w => /^(pagination|pager)$/.test(w))) return 'pagination';
    if (words.some(w => /^(breadcrumb|breadcrumbs)$/.test(w))) return 'breadcrumbs';
    if (words.some(w => /^(chart|graph)$/.test(w))) return 'chart';
    if (words.some(w => /^(card|tile)$/.test(w))) return 'card';
    if (element.hasAttribute('aria-expanded') || element.hasAttribute('aria-controls')) return 'disclosure';
    if (element.hasAttribute('onclick') || element.hasAttribute('tabindex')) return 'custom_control';
    if (tag.includes('-')) return 'web_component';
    return null;
  };
  const nameOf = (element, kind) => {
    const root = element.getRootNode();
    const labelled = (element.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean)
      .map(id => { const label = root.getElementById ? root.getElementById(id) : null; return label ? label.textContent : ''; }).join(' ');
    const label = element.labels && element.labels[0] ? element.labels[0].textContent : '';
    const explicit = element.getAttribute('aria-label') || labelled || label || element.getAttribute('title')
      || element.getAttribute('placeholder') || element.getAttribute('alt');
    if (explicit) return clean(explicit);
    if (/input|dropdown|text_input/.test(kind)) return clean(element.getAttribute('name') || kind);
    const own = [...element.childNodes].filter(n => n.nodeType === Node.TEXT_NODE).map(n => n.textContent).join(' ');
    return clean(own) || kind.replace(/_/g, ' ');
  };
  const selected = [];
  for (const element of nodes) {
    if (element.tagName === 'INPUT' && element.type === 'hidden') continue;
    const kind = typeOf(element);
    if (!kind) continue;
    if (selected.length >= MAX_ITEMS) { truncated = true; break; }
    const isVisible = visible(element), selector = selectorFor(element);
    const row = {selector, kind, name:nameOf(element, kind), tag:element.tagName.toLowerCase(),
      role:element.getAttribute('role') || '', visible:isVisible,
      disabled:!!element.disabled || element.getAttribute('aria-disabled') === 'true',
      expanded:element.getAttribute('aria-expanded'), selected:element.getAttribute('aria-selected'),
      controls:(element.getAttribute('aria-controls') || '').split(/\s+/).filter(Boolean),
      required:!!element.required || element.getAttribute('aria-required') === 'true',
      sensitive:element.type === 'password', input_values_omitted:true};
    if (element.tagName === 'SELECT') {
      row.option_count = element.options.length;
      row.options = [...element.options].slice(0, 50).map(option => clean(option.label || option.textContent));
      row.options_truncated = element.options.length > 50;
    }
    if (kind === 'table' || kind === 'data_grid') {
      row.column_names = [...element.querySelectorAll('th,[role=columnheader]')].slice(0, 30).map(e => clean(e.textContent));
      row.rendered_rows = element.querySelectorAll('tr,[role=row]').length;
    }
    if (kind === 'canvas') row.limitation = 'Canvas pixels do not expose their internal controls as DOM elements';
    if (kind === 'web_component' && !element.shadowRoot && !element.children.length)
      row.limitation = 'Opaque custom element; closed shadow content cannot be confirmed';
    selected.push({element, row});
  }
  const known = new Map(selected.map(item => [item.element, item.row.selector]));
  const controllers = new Map();
  for (const {row} of selected) for (const target of row.controls) {
    if (!controllers.has(target)) controllers.set(target, []);
    controllers.get(target).push(row.selector);
  }
  for (const {element, row} of selected) {
    let parent = element.parentElement || element.getRootNode().host;
    while (parent && !known.has(parent)) parent = parent.parentElement || parent.getRootNode().host;
    row.parent_selector = parent ? known.get(parent) : null;
    row.controller_selectors = element.id ? (controllers.get(element.id) || []) : [];
    const root = element.getRootNode();
    row.shadow = !!root.host;
  }
  return {components:selected.map(item => item.row), truncated, scanned_nodes:nodes.length,
    open_shadow_roots:roots.length - 1, viewport:{width:innerWidth,height:innerHeight},
    limits:{max_components:MAX_ITEMS,max_dom_nodes:MAX_NODES}};
}"""


def _key(row):
    return (tuple(row.get("frame_path") or []), row.get("selector"), row.get("kind"))


def merge_snapshots(entry, snapshots, phase="initial", revealed_by=None):
    """Track discovered and actually visible components separately; never infer a test pass."""
    inventory = entry.setdefault("component_inventory", {"components": [], "states": [], "limits": [], "errors": []})
    known = {_key(row): row for row in inventory["components"]}
    signature, visible_ids = [], []
    for snapshot in snapshots:
        if not snapshot:
            continue
        if snapshot.get("error") and len(inventory["errors"]) < 10:
            inventory["errors"].append(redact(snapshot["error"])[:200])
        frame = snapshot.get("frame_path", [])
        for source in snapshot.get("components", []):
            source = {**source, "frame_path": frame}
            key = _key(source)
            if not source.get("selector"):
                continue
            if key not in known:
                if len(known) >= MAX_COMPONENTS:
                    if "Component inventory limit reached" not in inventory["limits"]:
                        inventory["limits"].append("Component inventory limit reached")
                    continue
                digest = hashlib.sha256(json.dumps([entry.get("url") or entry.get("slug"), key], sort_keys=True).encode()).hexdigest()[:16]
                known[key] = {**source, "id": "component_" + digest, "seen_visible": False, "visible_states": [],
                              "revealed_by": [], "discovery_status": "identified"}
                inventory["components"].append(known[key])
            row = known[key]
            first_visible = not row["seen_visible"]
            same_viewport = not row.get("last_viewport") or row["last_viewport"] == snapshot.get("viewport", {})
            became_visible = source.get("visible", False) and (first_visible or not row.get("visible", False))
            row["last_viewport"] = snapshot.get("viewport", {})
            for field in ("option_count", "options", "options_truncated", "disabled", "expanded", "selected", "parent_selector", "controller_selectors"):
                if field in source:
                    row[field] = source[field]
            if source.get("options"):
                row["observed_options"] = list(dict.fromkeys([*row.get("observed_options", []), *source["options"]]))[:200]
            row["seen_visible"] = row["seen_visible"] or source.get("visible", False)
            row["visible"] = source.get("visible", False)
            if source.get("visible"):
                visible_ids.append(row["id"])
                if revealed_by and became_visible and (first_visible or same_viewport) and revealed_by not in row["revealed_by"]:
                    row["revealed_by"].append(revealed_by)
            row["discovery_status"] = "observed" if row["seen_visible"] else "hidden"
            signature.append((row["id"], source.get("visible"), source.get("expanded"), source.get("selected"), tuple(source.get("options", []))))
        if snapshot.get("truncated") and "DOM scan was truncated" not in inventory["limits"]:
            inventory["limits"].append("DOM scan was truncated")
    if not signature:
        return
    state_id = "state_" + hashlib.sha256(json.dumps([sorted(signature), snapshots[0].get("viewport", {})]).encode()).hexdigest()[:16]
    state = next((s for s in inventory["states"] if s["id"] == state_id), None)
    if state is None:
        if len(inventory["states"]) >= MAX_STATES:
            if "Component state limit reached" not in inventory["limits"]:
                inventory["limits"].append("Component state limit reached")
            return
        state = {"id": state_id, "phase": phase, "revealed_by": revealed_by, "visible_components": sorted(set(visible_ids)),
                 "viewport": snapshots[0].get("viewport", {})}
        inventory["states"].append(state)
    for row in inventory["components"]:
        if row["id"] in visible_ids and state_id not in row["visible_states"]:
            row["visible_states"].append(state_id)


def capture_after_action(page, entry, target):
    """Read only the current document; navigation destinations get their own page inventory."""
    try:
        snapshot = page.evaluate(DOM_COMPONENTS_JS)
        merge_snapshots(entry, [snapshot], phase="after interaction", revealed_by=target.get("selector"))
    except Exception as error:
        inventory = entry.setdefault("component_inventory", {"components": [], "states": [], "limits": [], "errors": []})
        if len(inventory["errors"]) < 10:
            inventory["errors"].append(redact(type(error).__name__ + ": " + str(error).splitlines()[0])[:200])


def save_inventory(run_dir, app_map, registry=None):
    pages = []
    controls = [f for f in (registry or {}).get("features", {}).values() if f.get("level") == "control"]
    for page in app_map:
        inventory = page.get("component_inventory", {})
        parent_names = {(tuple(row.get("frame_path") or []), row.get("selector")): row.get("name") for row in inventory.get("components", [])}
        rows = []
        for original in inventory.get("components", []):
            row = dict(original)
            row["parent_name"] = parent_names.get((tuple(row.get("frame_path") or []), row.get("parent_selector")), "")
            selector = row["selector"]
            if row.get("frame_path"):
                from .agents.discovery import in_frames
                selector = in_frames(row["frame_path"], selector)
            matched = [f for f in controls if f.get("selector") == selector and page.get("slug") in f.get("pages", [])]
            row["test_status"] = "not_tested"
            row["test_evidence"] = []
            if len(matched) == 1:
                row["test_status"] = matched[0].get("status", "not_tested")
                row["test_evidence"] = matched[0].get("decided_by", [])
            row["test_status_reason"] = "Status requires an exact existing control-registry match and its test evidence."
            rows.append(row)
        pages.append({"url": page.get("url"), "title": page.get("title"), "slug": page.get("slug"), "auth": bool(page.get("auth")),
                      "components": rows, "states": inventory.get("states", []), "limits": inventory.get("limits", []),
                      "errors": inventory.get("errors", []) + ([] if "component_inventory" in page else ["No DOM inventory was captured for this page"]), "uninspected_frames": [f for f in page.get("frames", []) if f.get("status") != "testable"]})
    counts = Counter(row["kind"] for page in pages for row in page["components"])
    result = {"pages": pages, "counts_by_kind": dict(counts), "total_components": sum(counts.values()),
              "scope": "Observed DOM components within recorded pages, states and limits; not proof of whole-application completeness."}
    directory = Path(run_dir)
    (directory / "components.json").write_text(redact(json.dumps(result, indent=2)), encoding="utf-8")
    esc = lambda value: html.escape(str(value or ""), quote=True)  # noqa: E731
    sections = []
    for page in pages:
        body = "".join("<tr><td>" + esc(row["kind"]) + "</td><td>" + esc(row["name"]) + ("<small>" + esc(row["limitation"]) + "</small>" if row.get("limitation") else "") + "</td><td>"
                       + esc(row["discovery_status"]) + "</td><td>" + esc(row.get("parent_name")) + "</td><td>" + esc(row["test_status"]) + "</td><td><code>"
                       + esc(row["selector"]) + "</code></td><td>" + esc(" / ".join(row.get("frame_path") or []))
                       + "</td></tr>" for row in page["components"])
        notes = [*page["limits"], *page["errors"], *[f.get("reason", "Frame not inspected") for f in page["uninspected_frames"]]]
        sections.append("<section><h2>" + esc(page["title"] or page["url"]) + "</h2><p>" + esc(page["url"])
                        + "</p><p>" + str(len(page["components"])) + " components; " + str(len(page["states"]))
                        + " observed component states.</p><p>" + esc("; ".join(notes)) + "</p><div class=\"scroll\"><table>"
                        + "<tr><th>Type</th><th>Name</th><th>Discovery</th><th>Parent component</th><th>Test evidence</th><th>Locator</th><th>Frame</th></tr>"
                        + body + "</table></div></section>")
    document = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Qpilot | Page components</title><style>
body{margin:0;background:#eff3fa;color:#17243d;font:15px/1.6 system-ui}main{max-width:1250px;margin:auto;padding:28px}header{background:#152442;color:white;padding:26px;border-radius:16px}section{background:white;padding:22px;margin:20px 0;border-radius:14px}.scroll{overflow:auto}table{width:100%;border-collapse:collapse}td,th{text-align:left;vertical-align:top;padding:10px;border-bottom:1px solid #ddd}code{overflow-wrap:anywhere;font-size:12px}a{color:#5145cf}</style><main><header><h1>Page components</h1><p>Identified and observed components, with functional test evidence kept separate.</p></header><p><a href="report.html">Main report</a> | <a href="components.json">Download JSON inventory</a></p>SECTIONS<footer>SCOPE</footer></main></html>"""
    document = document.replace("SECTIONS", "".join(sections)).replace("SCOPE", esc(result["scope"]))
    (directory / "components.html").write_text(redact(document), encoding="utf-8")
    return result


def ai_component_summary(page):
    inventory = page.get("component_inventory", {})
    rows = inventory.get("components", [])
    kinds = Counter(row["kind"] for row in rows)
    examples, per_kind = [], Counter()
    for row in rows:
        if not row.get("seen_visible") or per_kind[row["kind"]] >= 2:
            continue
        examples.append({"kind": row["kind"], "name": row["name"], "selector": row["selector"],
                         "revealed_by": row.get("revealed_by", [])})
        per_kind[row["kind"]] += 1
        if len(examples) >= 60:
            break
    return {"identified_by_kind": dict(kinds), "observed_examples": examples,
            "hidden_only": sum(not row.get("seen_visible") for row in rows),
            "limits": inventory.get("limits", []),
            "meaning": "DOM discovery evidence, not proof of working functionality"}
