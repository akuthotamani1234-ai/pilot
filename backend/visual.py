"""Visual regression (optional, VISUAL_CHECK): every page's picture and layout - at desktop width (1366 px, the whole
page) and at phone width (390 x 844) - compared with the APPROVED look of this website (baseline/<site>/visual/).

What is found, for a person to judge (a page can change on purpose, so a change is never a website bug by itself):
  missing   an element of the approved page is gone (a heading, button, link, box, picture)
  added     elements the approved page did not have
  moved     elements moved or changed size; a block that moved together is ONE change ("from 'Products' on, the
            content moved 120 px down") - not every element below it
  overlap   two elements now cover each other that did not before (text or a picture pushed over another)
  picture   more of the picture changed than VISUAL_PIXEL_PERCENT (the diff picture marks the changed pixels red)
  height    the page got much longer or shorter
Carousels, ads, live regions, frames and cookie banners change by themselves: they are left out. Numbers count as one
value ('Rs. 500' = 'Rs. 600'): this check is about the layout, not the prices.

The first run of a website saves its look as the baseline. A page seen for the first time is added (there is nothing
to compare it with) - when the run FINISHES (save_baseline: an unfinished run never changes the baseline). A CHANGED
page keeps its old approved look until a person approves the new one - the 'Approve the new look' button in the app,
or `main.py --approve-visual <run>` - so a change is never accepted silently (VISUAL_AUTO_APPROVE=true accepts every
new look of a finished run, e.g. in CI right after an intended redesign).
"""
import base64
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

from .agents.change_detection import baseline_path, page_key
from .config import settings
from .state import QAState

# every visible element a person would notice, with a stable name and its box on the page (document coordinates)
VISUAL_JS = r"""() => {
  const SKIP = '.carousel, .slider, .swiper, .slick-slider, .owl-carousel, [class*="carousel"], ' +
               '[aria-roledescription="carousel"], marquee, [aria-live], iframe, ins.adsbygoogle, [id^="google_ads"], ' +
               '[id*="cookie" i], [class*="cookie" i], [id*="consent" i], [class*="consent" i]';
  const KINDS = 'h1, h2, h3, h4, button, a, input, select, textarea, img, label, nav, header, footer, form, table, [role=button]';
  const BOXY = new Set(['NAV', 'HEADER', 'FOOTER', 'FORM', 'TABLE']);
  const words = (s) => (s || '').replace(/\s+/g, ' ').trim().replace(/\d+([.,]\d+)*/g, '#').slice(0, 40);
  const name = (e) => {
    if (e.tagName === 'IMG') return words(e.getAttribute('alt')) || (e.getAttribute('src') || '').split('?')[0].split('/').pop().slice(0, 40);
    if (['INPUT', 'SELECT', 'TEXTAREA'].includes(e.tagName))
      return words(e.getAttribute('aria-label') || e.getAttribute('placeholder') || e.name || e.id || e.type);
    if (BOXY.has(e.tagName)) return words(e.id || e.getAttribute('aria-label') || '');
    return words(e.innerText || e.getAttribute('aria-label') || e.title || e.value);
  };
  const seen = {}, out = [], sx = window.scrollX, sy = window.scrollY;
  for (const e of document.querySelectorAll(KINDS)) {
    if (out.length >= 400) break;
    if (e.closest(SKIP)) continue;
    const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    if (r.width < 2 || r.height < 2 || s.visibility === 'hidden' || s.display === 'none' || +s.opacity === 0) continue;
    const n = name(e);
    if (!n && !BOXY.has(e.tagName)) continue;
    let key = e.tagName.toLowerCase() + ':' + n;
    seen[key] = (seen[key] || 0) + 1;
    if (seen[key] > 1) key += ' #' + seen[key];
    out.push({k: key, b: [Math.round(r.left + sx), Math.round(r.top + sy), Math.round(r.width), Math.round(r.height)], e});
  }
  // two elements that cover each other - not one inside the other (a link around its picture)
  const small = out.filter((o) => !BOXY.has(o.e.tagName)), overlaps = [];
  for (let i = 0; i < small.length && overlaps.length < 40; i++) for (let j = i + 1; j < small.length; j++) {
    const a = small[i].b, b = small[j].b;
    const w = Math.min(a[0] + a[2], b[0] + b[2]) - Math.max(a[0], b[0]), h = Math.min(a[1] + a[3], b[1] + b[3]) - Math.max(a[1], b[1]);
    if (w <= 0 || h <= 0 || w * h < 0.3 * Math.min(a[2] * a[3], b[2] * b[3])) continue;
    if (small[i].e.contains(small[j].e) || small[j].e.contains(small[i].e)) continue;
    overlaps.push(small[i].k + ' | ' + small[j].k);
  }
  const d = document.documentElement;
  return {size: [d.scrollWidth, d.scrollHeight], boxes: out.map((o) => ({k: o.k, b: o.b})), overlaps};
}"""

# two pictures -> the share of pixels that changed, where, and a diff picture (changes red over the faded new picture)
DIFF_JS = r"""async ([a, b, tol, maxH]) => {
  const load = (src) => new Promise((ok, bad) => { const i = new Image(); i.onload = () => ok(i);
                                                    i.onerror = () => bad(new Error('not a picture')); i.src = src; });
  const [A, B] = await Promise.all([load(a), load(b)]);
  const w = Math.min(A.width, B.width), h = Math.min(A.height, B.height, maxH);
  const pixels = (img) => { const c = document.createElement('canvas'); c.width = w; c.height = h;
                            const x = c.getContext('2d'); x.drawImage(img, 0, 0); return x.getImageData(0, 0, w, h).data; };
  const pa = pixels(A), pb = pixels(B), out = new ImageData(w, h), o = out.data;
  let changed = 0, box = null;
  for (let p = 0; p < pa.length; p += 4) {
    if (Math.abs(pa[p] - pb[p]) + Math.abs(pa[p + 1] - pb[p + 1]) + Math.abs(pa[p + 2] - pb[p + 2]) > tol) {
      changed++; o[p] = 230; o[p + 1] = 30; o[p + 2] = 30; o[p + 3] = 255;
      const i = p / 4, x = i % w, y = (i - x) / w;
      if (!box) box = [x, y, x, y];
      else { box[0] = Math.min(box[0], x); box[1] = Math.min(box[1], y); box[2] = Math.max(box[2], x); box[3] = Math.max(box[3], y); }
    } else {
      for (let k = 0; k < 3; k++) o[p + k] = 255 - (255 - pb[p + k]) * 0.3;
      o[p + 3] = 255;
    }
  }
  let diff = '';
  if (changed) { const c = document.createElement('canvas'); c.width = w; c.height = h;
                 c.getContext('2d').putImageData(out, 0, 0); diff = c.toDataURL('image/png'); }
  return {percent: 100 * changed / Math.max(1, w * h), box, diff, old_size: [A.width, A.height], new_size: [B.width, B.height]};
}"""

PIXEL_TOLERANCE = 60   # summed RGB difference of one pixel that still counts as the same (smoothed text edges)
MAX_HEIGHT = 8000      # px of a whole-page picture compared (very long pages: the top part)
WIDTHS = ("desktop", "phone")
INDEX = "index.json"


def enabled() -> bool:
    return settings.visual_check


def capture_file(run_dir: Path, slug: str) -> Path:
    return run_dir / "visual" / f"{slug}.json"


def save_capture(run_dir: Path, slug: str, url: str, desktop: dict | None, phone: dict | None) -> str:
    """The crawler's layout of one page (its screenshots are named in it) -> runs/<run>/visual/<slug>.json."""
    f = capture_file(run_dir, slug)
    f.parent.mkdir(exist_ok=True)
    f.write_text(json.dumps({"url": url, "desktop": desktop, "phone": phone}), encoding="utf-8")
    return f.relative_to(run_dir).as_posix()


def _label(key: str) -> str:
    """'button:Add to cart #2' -> "button 'Add to cart'"."""
    tag, _, text = key.partition(":")
    text = text.rsplit(" #", 1)[0] if " #" in text else text
    return f"{tag} '{text}'" if text else tag


def compare_layout(old: dict, new: dict, move_px: int) -> list[dict]:
    """What changed between the approved layout and this one (see the top of this file)."""
    ob, nb = {x["k"]: x["b"] for x in old.get("boxes", [])}, {x["k"]: x["b"] for x in new.get("boxes", [])}
    out = []
    missing = [k for k in ob if k not in nb]
    if missing:
        out.append({"kind": "missing", "detail": f"{len(missing)} element(s) of the approved page are gone: "
                    + ", ".join(_label(k) for k in missing[:8]), "items": missing[:40]})
    added = [k for k in nb if k not in ob]
    if added:
        out.append({"kind": "added", "detail": f"{len(added)} new element(s): " + ", ".join(_label(k) for k in added[:8]),
                    "items": added[:40]})
    moves = []
    for k in ob:
        if k not in nb:
            continue
        (x0, y0, w0, h0), (x1, y1, w1, h1) = ob[k], nb[k]
        resized = abs(w1 - w0) > max(move_px, 0.25 * w0) or abs(h1 - h0) > max(move_px, 0.25 * h0)
        if resized or abs(x1 - x0) > move_px or abs(y1 - y0) > move_px:
            moves.append({"k": k, "d": (x1 - x0, y1 - y0), "resized": resized, "old": ob[k], "new": nb[k]})
    step = lambda m: (round(m["d"][0] / move_px), round(m["d"][1] / move_px))  # noqa: E731
    groups: dict[tuple, list] = {}
    for m in moves:
        if not m["resized"]:
            groups.setdefault(step(m), []).append(m)
    together = {g for g, ms in groups.items() if len(ms) >= 3}  # a block moved: content above it grew / shrank
    for g in sorted(together, key=lambda g: -len(groups[g])):
        ms = sorted(groups[g], key=lambda m: (m["old"][1], m["old"][0]))
        dx, dy = ms[0]["d"]
        out.append({"kind": "moved", "detail": f"from {_label(ms[0]['k'])} on, {len(ms)} elements moved together "
                    f"({dx:+d} px across, {dy:+d} px down)", "items": [m["k"] for m in ms[:40]]})
    alone = sorted((m for m in moves if m["resized"] or step(m) not in together), key=lambda m: (m["old"][1], m["old"][0]))
    for m in alone[:10]:
        (x0, y0, w0, h0), (x1, y1, w1, h1) = m["old"], m["new"]
        out.append({"kind": "moved", "detail": f"{_label(m['k'])}: " + (
            f"size {w0}x{h0} -> {w1}x{h1} px" if m["resized"] else f"moved {x1 - x0:+d} px across, {y1 - y0:+d} px down"),
            "items": [m["k"]]})
    if len(alone) > 10:
        out.append({"kind": "moved", "detail": f"... and {len(alone) - 10} more element(s) moved", "items": []})
    new_overlaps = [o for o in new.get("overlaps", []) if o not in set(old.get("overlaps", []))]
    if new_overlaps:
        out.append({"kind": "overlap", "detail": f"{len(new_overlaps)} new overlap(s): " + "; ".join(
            " covers ".join(_label(k) for k in o.split(" | ")) for o in new_overlaps[:5]), "items": new_overlaps[:20]})
    h0, h1 = (old.get("size") or [0, 0])[1], (new.get("size") or [0, 0])[1]
    if h0 and abs(h1 - h0) > max(100, 0.15 * h0):
        out.append({"kind": "height", "detail": f"the page is {h1 - h0:+d} px {'longer' if h1 > h0 else 'shorter'} "
                    f"({h0} -> {h1} px)", "items": []})
    return out


def compare_pictures(page, old_png: Path, new_png: Path, diff_png: Path) -> dict:
    """The share of the picture that changed (%), and the diff picture written to diff_png when anything changed."""
    def url(p: Path) -> str:
        return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()
    r = page.evaluate(DIFF_JS, [url(old_png), url(new_png), PIXEL_TOLERANCE, MAX_HEIGHT])
    diff = r.pop("diff")
    if diff:
        diff_png.parent.mkdir(parents=True, exist_ok=True)
        diff_png.write_bytes(base64.b64decode(diff.split(",", 1)[1]))
    r["percent"] = round(r["percent"], 2)
    return r


def _bkey(key: str) -> str:
    return hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest()[:12]


def _vkey(p: dict) -> str:
    """The page, as a visitor or logged in (the same address can look different)."""
    return page_key(p["url"]) + (" (logged in)" if p.get("auth") else "")


def load_index(site_key: str) -> dict:
    try:
        return json.loads((baseline_path(site_key) / "visual" / INDEX).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"pages": {}}


def _store(site_key: str, index: dict, key: str, cap: dict, run_dir: Path, title: str, run_id: str) -> None:
    """This run's look of one page becomes its approved look (pictures copied into the baseline)."""
    vdir = baseline_path(site_key) / "visual"
    vdir.mkdir(parents=True, exist_ok=True)
    widths = {}
    for w in WIDTHS:
        c = cap.get(w)
        if not c or not c.get("shot") or not (run_dir / c["shot"]).exists():
            continue
        name = f"{_bkey(key)}_{w}.png"
        shutil.copyfile(run_dir / c["shot"], vdir / name)
        widths[w] = dict(c, shot=name)
    if widths:
        index["pages"][key] = {"url": cap.get("url"), "title": title, "widths": widths, "run_id": run_id,
                               "approved": datetime.now().strftime("%Y-%m-%d %H:%M")}


def _save_index(site_key: str, index: dict) -> None:
    vdir = baseline_path(site_key) / "visual"
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / INDEX).write_text(json.dumps(index, indent=1), encoding="utf-8")


def visual_check_agent(state: QAState) -> QAState:
    """Compare every page's look with its approved look (see the top of this file). Only reads the baseline: new looks
    are kept by keep_new_looks() when the run finishes."""
    log = state.get("log", [])
    if not enabled():
        return {"log": log + ["Visual check: off (VISUAL_CHECK=false)."]}
    run_dir, site = Path(state["run_dir"]), state["site_key"]
    pages = [p for p in state.get("app_map", []) if p.get("visual") and not p.get("error")]
    left_out = max(0, len(pages) - settings.visual_max_pages)
    pages = pages[:settings.visual_max_pages]
    index = load_index(site)
    first = not index["pages"]
    report = {"first_run": first, "pages": [], "left_out": left_out, "pixel_percent": settings.visual_pixel_percent,
              "move_px": settings.visual_move_px}
    if pages:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                tab = browser.new_page()
                for p in pages:
                    report["pages"].append(_check_page(tab, p, run_dir, site, index))
            finally:
                browser.close()
    if settings.visual_auto_approve:  # (e.g. CI right after an intended redesign: this run's look is the new look)
        for r in report["pages"]:
            if r["status"] == "changed":
                r["status"], r["auto"] = "approved", True
    counts = {s: sum(1 for r in report["pages"] if r["status"] == s) for s in ("same", "changed", "new", "approved")}
    report["counts"] = dict(counts, compared=counts["same"] + counts["changed"] + counts["approved"])
    (run_dir / "visual.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    if first:
        msg = (f"Visual check: no approved look yet - the look of {counts['new']} page(s) becomes it when this run "
               "finishes (compared from the next run).")
    else:
        msg = (f"Visual check: {report['counts']['compared']} page(s) compared with the approved look - "
               f"{counts['changed']} changed (to review), {counts['same']} the same, {counts['new']} new.")
    print(f"  [visual] {msg[len('Visual check: '):]}", flush=True)
    return {"visual": report["counts"], "log": log + [msg]}


def _capture(run_dir: Path, r: dict) -> dict:
    return json.loads((run_dir / r["capture"]).read_text(encoding="utf-8"))


def _check_page(tab, p: dict, run_dir: Path, site: str, index: dict) -> dict:
    key, cap = _vkey(p), json.loads((run_dir / p["visual"]).read_text(encoding="utf-8"))
    r = {"url": p["url"], "key": key, "title": p.get("title") or "", "slug": p["slug"], "capture": p["visual"],
         "widths": {}}
    old = index["pages"].get(key)
    if not old:  # nothing to compare with: this look becomes its baseline when the run finishes
        r["status"] = "new"
        return r
    vdir = baseline_path(site) / "visual"
    for w in WIDTHS:
        now, then = cap.get(w), old["widths"].get(w)
        if not now or not then:
            continue
        changes = compare_layout(then, now, settings.visual_move_px)
        res = {"changes": changes, "shot": now.get("shot")}
        if now.get("shot") and (run_dir / now["shot"]).exists() and (vdir / then["shot"]).exists():
            approved = run_dir / "visual" / f"{p['slug']}_{w}_approved.png"  # (the report shows it next to the new one)
            shutil.copyfile(vdir / then["shot"], approved)
            res["approved_shot"] = approved.relative_to(run_dir).as_posix()
            diff = run_dir / "visual" / f"{p['slug']}_{w}_diff.png"
            try:
                pic = compare_pictures(tab, vdir / then["shot"], run_dir / now["shot"], diff)
                res["percent"] = pic["percent"]
                if diff.exists():
                    res["diff_shot"] = diff.relative_to(run_dir).as_posix()
                if pic["percent"] > settings.visual_pixel_percent:
                    changes.append({"kind": "picture", "detail": f"{pic['percent']:.1f}% of the picture changed "
                                    f"(more than {settings.visual_pixel_percent:g}%)", "items": []})
            except Exception as e:  # (a picture that can't be read: the layout comparison still counts)
                res["picture_error"] = str(e).splitlines()[0][:150]
        r["widths"][w] = res
    r["status"] = "changed" if any(res["changes"] for res in r["widths"].values()) else "same"
    return r


def keep_new_looks(run_dir: Path, site_key: str) -> int:
    """The run finished (save_baseline): the look of its NEW pages joins the approved look - and with
    VISUAL_AUTO_APPROVE the new look of its changed pages. Returns how many pages were kept."""
    try:
        report = json.loads((Path(run_dir) / "visual.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    index, n = load_index(site_key), 0
    for r in report["pages"]:
        if r["status"] == "new" or (r["status"] == "approved" and r.get("auto")):
            _store(site_key, index, r["key"], _capture(Path(run_dir), r), Path(run_dir), r["title"], Path(run_dir).name)
            n += 1
    if n:
        _save_index(site_key, index)
    return n


def approve(run_dir: Path, keys: list[str] | None = None) -> int:
    """A person approved the new look of these pages of this run (None = every changed page): it becomes the baseline
    the next runs compare with. Returns how many pages were approved."""
    run_dir = Path(run_dir)
    report = json.loads((run_dir / "visual.json").read_text(encoding="utf-8"))
    site = json.loads((run_dir / "run_args.json").read_text(encoding="utf-8"))["site_key"]
    index, n = load_index(site), 0
    for r in report["pages"]:
        if r["status"] == "changed" and (keys is None or r["key"] in keys):
            _store(site, index, r["key"], _capture(run_dir, r), run_dir, r["title"], run_dir.name)
            r["status"], n = "approved", n + 1
    if n:
        _save_index(site, index)
        report["counts"]["changed"] -= n
        report["counts"]["approved"] = report["counts"].get("approved", 0) + n
        (run_dir / "visual.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return n
