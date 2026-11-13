"""Agent 1 — Website Discovery Agent.

Walks through the whole website (same domain only), and for every page:
  * takes a full-page screenshot
  * records HTTP status, load time, title
  * records console errors, JavaScript errors, failed/broken requests
  * collects links, buttons, inputs and forms (with stable selectors)
The result is the "application map" that the other agents use.
"""
import hashlib
import json
import re
import time
from collections import Counter, deque
from contextlib import contextmanager
from html import unescape
from pathlib import Path
from urllib.parse import parse_qsl, urldefrag, urljoin, urlparse, urlunparse

from playwright.sync_api import TimeoutError as PageTimeout, sync_playwright

from .. import runctl, visual
from ..actions import action_risk
from ..auth import CAPTCHA, NOTES, log_in, login_form, looks_logged_out, wait_for_person
from ..config import settings
from ..observe import DIALOG_INIT_JS, Explorer, autoscroll, close_consent
from ..page_inventory import DOM_COMPONENTS_JS, merge_snapshots, save_inventory
from ..page_status import page_testable
from ..safety import Scope, blocked_tracker_said, guard_context
from ..secret_store import load_account, save_account
from ..state import QAState

PRIVATE = ".private"  # runs/<run>/.private/ holds the saved login (session cookies): never served, deleted after the run

SKIP_EXTENSIONS = re.compile(
    r"\.(pdf|zip|rar|gz|exe|dmg|jpg|jpeg|png|gif|svg|webp|mp4|mp3|avi|docx?|xlsx?|pptx?|css|js|xml|json)$",
    re.I,
)

# The page's LIST OF ITEMS (products, search results, articles, orders ...): the biggest group of repeated cards that
# each hold a link to their own page. A card is found by its siblings (the same tag + class, 3 or more of them), so it
# works whatever the website calls its classes - and a list in a menu, breadcrumb, tab bar, page links, header, footer
# or sidebar is never it (a <body class="product-category"> is no card either). A card holds more than its link (a
# price, a picture, a text): a list of bare links is a menu. mark = true: each card's main link gets data-qa-item="<n>",
# so a test can click the card it read. Used while exploring (EXTRACT_JS) and by the tests (ITEMS_JS) - the same rule.
# -> {selector, links: [{href, text}], names, cards, hrefs}  ({} = no list on this page)
# The website's own frame around the content: menus, header, footer, breadcrumb, tab bar, page links, sidebar - by
# the tag, the role, or a word of its class / id ('topnav', 'main_menu_top', 'headerstrip', 'nav-tabs'), so it works
# whatever the markup. (The item list never comes from there; a search result's page is read without it.)
CHROME_FN = r"""const qaChrome = e => {
  const word = w => /^(nav|navbar|navigation|breadcrumbs?|pagination|pager|tabs|dropdown|footer|header|topbar|toolbar|sidebar|filters?|facets?)$/i.test(w)
    || /^(nav|menu|header|footer)/i.test(w) || /(nav|menu)$/i.test(w);
  return /^(NAV|HEADER|FOOTER|ASIDE)$/.test(e.tagName)
    || /^(navigation|menu|menubar|tablist|banner|contentinfo|toolbar|complementary)$/.test(e.getAttribute('role') || '')
    || `${typeof e.className === 'string' ? e.className : ''} ${e.id || ''}`.split(/[\s_-]+/).some(w => w && word(w));
};"""
# the text of the page's own content - also its hidden tabs (description, tags) - without the website's frame
MAIN_TEXT_JS = "() => {" + CHROME_FN + r"""
  const b = document.body.cloneNode(true);
  b.querySelectorAll('script, style, noscript, template').forEach(e => e.remove());
  [...b.querySelectorAll('*')].filter(qaChrome).forEach(e => e.remove());
  return (b.textContent || '').replace(/\s+/g, ' ');
}"""
ITEM_LIST_FN = CHROME_FN + r"""
const qaItemList = (mark, hints) => {
  const vis = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
                     return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const esc = v => (window.CSS && CSS.escape) ? CSS.escape(v) : v;
  const STATEC = /^(active|current|selected|open|show|hover|focus|disabled|hidden|first|last|odd|even|is-.*|js-.*|ng-.*|has-.*)$/i;
  const cls = e => [...(e.classList || [])].filter(c => /^[A-Za-z][\w-]*$/.test(c) && !STATEC.test(c));
  const sig = e => e.tagName + '|' + (cls(e)[0] || '');
  const inChrome = e => { for (let a = e; a && a !== document.body && a !== document.documentElement; a = a.parentElement)
                            if (qaChrome(a)) return true; return false; };
  const real = a => { const h = (a.getAttribute('href') || '').trim();
                      return h && !h.startsWith('#') && !/^(javascript|mailto|tel):/i.test(h); };
  const MONEY = /[₹$€£¥]\s?\d|\d[\d.,]*\s?(€|eur\b|usd\b|inr\b|rs\.?)|\b(rs|inr)\.?\s?\d/i;
  // a link that only says what to do ('View Product' on every card of automationexercise.com) is no item's name -
  // nor is a heading that is the price ('<h2>Rs. 500</h2><p>Blue Top</p>'): the card's own name is
  const CTA = /^\s*(view|see|show|open|read|shop|buy|add|more|details|learn|quick)\b/i;
  const named = s => s && s.trim().length >= 3 && !MONEY.test(s) && !CTA.test(s);
  const text = e => (e.innerText || '').trim();
  const nameOf = (c, a) => {
    const t = text(a) || a.getAttribute('title') || '';
    if (named(t)) return t.trim().split('\n')[0].slice(0, 80);
    const h = [...c.querySelectorAll('h1, h2, h3, h4, h5, h6, [class*=name i], [class*=title i]')].find(e => named(text(e)));
    if (h) return text(h).split('\n')[0].slice(0, 80);
    return (text(c).split('\n').find(l => named(l)) || t).trim().slice(0, 80);
  };
  const done = (cards, mains, selector) => {
    if (mark) {
      document.querySelectorAll('[data-qa-item]').forEach(x => x.removeAttribute('data-qa-item'));
      mains.forEach((a, n) => a.setAttribute('data-qa-item', String(n)));
    }
    const names = cards.map((c, n) => nameOf(c, mains[n])), links = [];
    cards.forEach((c, n) => { if (!links.some(l => l.href === mains[n].href)) links.push({ href: mains[n].href, text: names[n] }); });
    // what a card's links and controls do (a cart icon that opens the item - 'choose an option first' - instead of
    // adding it): an item whose card works differently is worth a sample of its own
    const shapeOf = (c, m) => [...c.querySelectorAll('a, button, input, select')].map(e => e.tagName[0] + (e.tagName !== 'A'
      ? '' : e.href === m.href ? '=' : /^(#|javascript)/i.test(e.getAttribute('href') || '') ? '#' : '~')).join('');
    return { selector, links: links.slice(0, 30), names: names.slice(0, 60),
             cards: cards.map(c => text(c).slice(0, 300)).slice(0, 60), hrefs: mains.map(a => a.href).slice(0, 60),
             shapes: cards.map((c, n) => shapeOf(c, mains[n])).slice(0, 60) };
  };
  // The cards of a list this website showed elsewhere (its address from the explorer - e.g. the shop's grid), here
  // perhaps with only 1 or 2 of them (a search's results): each card is the biggest element around its own link.
  for (const h of hints || []) {
    let found = [];
    try { found = [...document.querySelectorAll(h)].filter(a => a.tagName === 'A' && vis(a) && real(a) && !inChrome(a)); }
    catch (e) { continue; }
    if (!found.length) continue;
    const cardOf = a => { let c = a;
      for (let n = 0; n < 6 && c.parentElement && c.parentElement !== document.body
           && ![...c.parentElement.querySelectorAll(h)].some(x => x.href !== a.href); n++) c = c.parentElement;
      return c; };
    const cards = [], mains = [];
    for (const a of found) { const c = cardOf(a); if (!cards.includes(c)) { cards.push(c); mains.push(a); } }
    return done(cards, mains, h);
  }
  const groups = new Map();
  for (const a of document.querySelectorAll('a[href]')) {
    if (!real(a) || !vis(a)) continue;
    let card = null;
    for (let e = a, n = 0; e && n < 7; e = e.parentElement, n++) {
      const par = e.parentElement;
      if (!par || /^(BODY|HTML|MAIN|FORM)$/.test(e.tagName) || par.tagName === 'HTML') break;
      const s = sig(e);
      if ([...par.children].filter(c => sig(c) === s).length >= 3) { card = e; break; }
    }
    if (!card || inChrome(card.parentElement)) continue;
    const box = card.parentElement;
    if (!groups.has(box)) groups.set(box, { sig: sig(card), cards: new Map() });
    const g = groups.get(box);
    if (!g.cards.has(card)) g.cards.set(card, []);
    g.cards.get(card).push(a);
  }
  const pic = c => c.querySelector('img, picture, svg, [style*="background-image"]');
  const mainOf = (g, c) => g.cards.get(c).find(a => text(a).length >= 3 && !MONEY.test(text(a))) || g.cards.get(c)[0];
  let best = null;
  for (const [box, g] of groups) {
    const cards = [...g.cards.keys()];
    if (cards.length < 3) continue;
    const rich = cards.filter(c => MONEY.test(text(c)) || pic(c) || text(c).length > text(mainOf(g, c)).length + 8);
    if (rich.length * 2 < cards.length) continue;
    // an item is found, sorted and opened by its name: a row of pictures without one (brand logos) is no item list
    if (cards.filter(c => nameOf(c, mainOf(g, c))).length * 2 < cards.length) continue;
    const priced = cards.filter(c => MONEY.test(text(c))).length, pictured = cards.filter(pic).length;
    const score = cards.length * (1 + (priced * 2 >= cards.length ? 2 : 0) + (pictured * 2 >= cards.length ? 1 : 0));
    if (!best || score > best.score) best = { box, g, cards, score };
  }
  if (!best) {
    // Client-side cards can open details through buttons or href="#" without exposing a real URL.
    // Read the repeated cards without inventing links; Explorer observes the actual click destinations.
    const candidates = new Map();
    for (const control of document.querySelectorAll('button,[role=button],a[href="#"]')) {
      if (!vis(control) || inChrome(control)) continue;
      for (let card = control, depth = 0; card && depth < 7; card = card.parentElement, depth++) {
        const box = card.parentElement;
        if (!box || /^(BODY|HTML|MAIN)$/.test(card.tagName)) break;
        const same = [...box.children].filter(c => sig(c) === sig(card) && vis(c));
        if (same.length < 3 || !MONEY.test(text(card)) || !pic(card)) continue;
        if (!candidates.has(box)) candidates.set(box, same);
        break;
      }
    }
    let chosen = null;
    for (const [box, cards] of candidates) {
      if (!chosen || cards.length > chosen.cards.length) chosen = {box, cards};
    }
    if (!chosen) return {};
    const ownSelector = e => e.id ? '#' + esc(e.id) : e.tagName.toLowerCase() +
      cls(e).slice(0,2).map(c => '.' + esc(c)).join('');
    const selector = ownSelector(chosen.box) + ' > ' + ownSelector(chosen.cards[0]);
    const names = chosen.cards.map(c => nameOf(c,c));
    if (names.some(n => !n)) return {};
    if (mark) {
      document.querySelectorAll('[data-qa-item]').forEach(e => e.removeAttribute('data-qa-item'));
      chosen.cards.forEach((c,n) => c.setAttribute('data-qa-item',String(n)));
    }
    return {selector, links:[], count:chosen.cards.length, names, cards:chosen.cards.map(c=>text(c).slice(0,300)),
            hrefs:[], shapes:[], client_navigation:true};
  }
  // each card's main link: its first link with a text (not a price) - the card's name is its text (done())
  const main = c => mainOf(best.g, c);
  // the address of the cards' main links: the list, the card, and - when all of them share a class - that link
  const own = e => (e.id && document.querySelectorAll('#' + esc(e.id)).length === 1) ? '#' + esc(e.id)
    : cls(e).length ? e.tagName.toLowerCase() + cls(e).slice(0, 2).map(c => '.' + esc(c)).join('') : '';
  const boxSel = e => {  // (a list without an id or class of its own: inside the nearest element that has one)
    if (own(e)) return own(e);
    for (let a = e.parentElement; a && a !== document.body; a = a.parentElement) if (own(a)) return own(a) + ' ' + e.tagName.toLowerCase();
    return e.tagName.toLowerCase();
  };
  const [tag, c1] = best.g.sig.split('|');
  const cardSel = tag.toLowerCase() + (c1 ? '.' + esc(c1) : '');
  const mains = best.cards.map(main);
  const shared = cls(mains[0]).find(c => mains.every(a => a.classList.contains(c)));
  const linkSel = shared ? 'a.' + esc(shared) : 'a[href]:not([href^="#"]):not([href^="javascript" i])';
  // (a card that IS its link - <a class="card"> - has no link inside: its address is the card's own, not 'a.card a.card')
  const whole = best.cards.every((c, n) => c === mains[n]);
  let selector = whole ? `${boxSel(best.box)} > ${cardSel}` : `${boxSel(best.box)} > ${cardSel} ${linkSel}`;
  try { if (!document.querySelectorAll(selector).length) selector = whole ? cardSel : `${cardSel} ${linkSel}`; } catch (e) { selector = ''; }
  return done(best.cards, mains, selector);
};"""
# what the tests use: the item list of the page they are on (e.g. the search results), its cards marked; `hints` =
# the addresses of the website's item lists that exploring found (so 1 or 2 results are read too)
ITEMS_JS = ("(arg) => {" + ITEM_LIST_FN
            + " const o = (arg && typeof arg === 'object') ? arg : { mark: arg }; return qaItemList(o.mark, o.hints); }")

# Runs inside the browser and returns everything interesting on the page.
EXTRACT_JS = r"""
() => {
""" + ITEM_LIST_FN + r"""
  const visible = el => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const cssEsc = v => (window.CSS && CSS.escape) ? CSS.escape(v) : v;
  // every element - also inside OPEN shadow roots (web components). A closed shadow root can't be read from outside:
  // its host is reported as unsupported below. (Playwright's CSS selectors look into open shadow roots as well.)
  const roots = [];
  const walkRoots = r => { roots.push(r); r.querySelectorAll('*').forEach(e => { if (e.shadowRoot) walkRoots(e.shadowRoot); }); };
  walkRoots(document);
  const deepAll = s => roots.flatMap(r => { try { return [...r.querySelectorAll(s)]; } catch (e) { return []; } });
  // the shadow hosts around an element, outermost first ('practice-form > nested-box'); [] = not in a shadow root
  const hostsOf = el => { const out = []; let r = el.getRootNode();
    while (r && r !== document && r.host) { out.unshift(r.host.tagName.toLowerCase() + (r.host.id ? '#' + r.host.id : ''));
                                            r = r.host.getRootNode(); }
    return out; };
  // a generated database id (ULID / UUID / long number) changes when the site's data is rebuilt: never address by it
  const idish = v => /[0-9A-Z]{20,}|[0-9a-f]{8}-[0-9a-f]{4}-|\d{6,}/.test(v || '');
  const q = v => String(v).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  // A count or an amount in a text changes with the visitor's cart ('2 ITEMS - $59.00' - a fresh browser shows
  // '0 ITEMS - $0.00'): an address made of it breaks. stable() keeps its longest part without numbers ('ITEMS').
  const steady = t => (t || '').split(/(?:[₹$€£¥]\s?)?\d[\d.,:]*(?:\s?[₹$€£¥%])?/)
    .map(s => s.replace(/^[\s\-–—:()|·,.]+|[\s\-–—:()|·,.]+$/g, '')).filter(s => /[A-Za-z]{2}/.test(s))
    .sort((a, b) => b.length - a.length)[0] || '';
  const stable = t => /\d/.test(t || '') ? steady(t) : (t || '');
  const selectorFor = el => {
    if (el.id && !idish(el.id)) return '#' + cssEsc(el.id);
    const tid = el.getAttribute('data-testid') || el.getAttribute('data-test');
    if (tid && !idish(tid)) return `[data-testid="${tid}"],[data-test="${tid}"]`;
    const name = el.getAttribute('name');
    if (name && !idish(name)) return `${el.tagName.toLowerCase()}[name="${name}"]`;
    const fcn = el.getAttribute('formcontrolname');  // Angular forms often have no id / name, only this
    if (fcn) return `${el.tagName.toLowerCase()}[formcontrolname="${fcn}"]`;
    const aria = el.getAttribute('aria-label');
    if (aria && !/\d/.test(aria)) return `${el.tagName.toLowerCase()}[aria-label="${aria}"]`;
    if (aria && steady(aria)) return `${el.tagName.toLowerCase()}[aria-label*="${q(steady(aria))}"]`;  // 'Cart, 2 items'
    return null;
  };
  // No id / name / test id (very common): find it by placeholder, title, class or visible text instead,
  // so every button and box can still be tested. Repeated ones (30 x "ADD TO CART") use the first.
  const STATE_CLASS = /^(active|disabled|selected|show|open|hover|focus|focused|hidden|visible|ng-.*|is-.*)$/i;
  const fallbackFor = el => {
    const tag = el.tagName.toLowerCase();
    for (const a of ['placeholder', 'title', 'alt']) {
      const v = el.getAttribute(a);
      if (v) return `${tag}[${a}="${q(v)}"]`;
    }
    const cls = [...el.classList].filter(c => /^[A-Za-z][\w-]*$/.test(c) && !STATE_CLASS.test(c)).slice(0, 2);
    if (cls.length) return tag + cls.map(c => '.' + cssEsc(c)).join('');
    // ':has-text' only finds visible text (and the value of input buttons) - a checkbox's value "on" is not text
    const box = /^(input|select|textarea)$/.test(tag) && !/^(button|submit|reset)$/i.test(el.type || '');
    const t = box ? '' : stable((el.innerText || el.value || '').trim().split('\n')[0].slice(0, 40));
    if (t) return `${tag}:has-text("${q(t)}")`;
    if (tag === 'input' && el.type) return `input[type="${el.type}"]`;
    if (box) return tag;  // a <select> / <textarea> with nothing else: made exact below by its position
    if (tag.includes('-')) return tag;  // a web component (a shadow host) without anything else: its tag name
    return null;
  };
  // inside a shadow root: the host's address, then the element's address inside that root ('host >> inner'), so a
  // test finds THIS element even when the same markup is repeated in other components
  const shadowSel = (el, c) => {
    const r = el.getRootNode();
    if (!r || r === document || !r.host) return null;
    let inner;
    try { inner = [...r.querySelectorAll(c)]; } catch (e) { return null; }
    const host = sel(r.host);
    if (!host || !inner.includes(el)) return null;
    return `${host} >> ${inner.length <= 1 ? c : `${c} >> nth=${inner.indexOf(el)}`}`;
  };
  // The address a test uses to find the control must point to THAT control. An address shared by different
  // controls (3 buttons with the same classes: "Site visit" / "Brochure" / "Question") gets made exact with the
  // control's text (or value), else its position; ">> visible=true" skips hidden copies (e.g. a phone-only menu).
  // The SAME control repeated (30 x "ADD TO CART", one per product) keeps one address (the tests use the first).
  const firstLine = x => (x.innerText || x.value || x.getAttribute('aria-label') || '').trim().split('\n')[0].slice(0, 40);
  const sel = el => {
    const c = selectorFor(el) || fallbackFor(el);
    if (!c || c.includes(':has-text')) return c;
    let all;
    try { all = deepAll(c); } catch (e) { return c; }
    if (all.length <= 1) return c;
    const inShadow = shadowSel(el, c);
    if (inShadow) return inShadow;
    const t = firstLine(el);
    if (all.every(x => firstLine(x) === t)) return all.filter(visible).length > 1 ? c : `${c} >> visible=true`;
    if (/^(input|select|textarea)$/i.test(el.tagName)) {  // radios / checkboxes sharing a name: use their value
      // (not a box you type in: what is written in it changes - a date box holds today's date - so its position)
      const v = /^(radio|checkbox|submit|button|reset)$/i.test(el.type || '') ? el.getAttribute('value') : '';
      if (v && !idish(v) && all.filter(x => x.getAttribute('value') === v).length === 1) return `${c}[value="${q(v)}"]`;
    } else if (t && stable(t)
               && all.filter(x => firstLine(x).toLowerCase().includes(stable(t).toLowerCase())).length === 1) {
      return `${c}:has-text("${q(stable(t))}")`;  // (':has-text' finds a part of the text, any case)
    }
    const shown = all.filter(visible);
    return shown.includes(el) ? `${c} >> visible=true >> nth=${shown.indexOf(el)}` : `${c} >> nth=${all.indexOf(el)}`;
  };
  const text = el => (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 80);
  // a name a person would use for a control without text, e.g. <a class="cart-icon"> -> "cart icon"
  // a button without words: its icon says what it does (OrangeHRM's delete button is <button><i class="bi-trash">)
  const iconOf = el => { const i = el.querySelector('i, svg, img, [class*=icon]'); if (!i) return '';
    const use = i.querySelector ? i.querySelector('use') : null;
    return [i.getAttribute('aria-label'), i.getAttribute('title'), i.getAttribute('alt'), i.getAttribute('data-icon'),
            i.getAttribute('class'), use ? use.getAttribute('href') || use.getAttribute('xlink:href') : '']
      .filter(Boolean).join(' '); };
  const nameOf = el => text(el) || el.getAttribute('title') ||
    `${iconOf(el)} ${[...el.classList].filter(c => !STATE_CLASS.test(c)).join(' ')}`.replace(/[-_#]+/g, ' ')
      .replace(/\s+/g, ' ').trim().slice(0, 60);
  const group = list => {  // identical controls (same text + selector) -> one entry with a count
    const m = new Map();
    for (const x of list) {
      const k = x.text + '|' + x.selector;
      if (m.has(k)) m.get(k).count++; else m.set(k, { ...x, count: 1 });
    }
    return [...m.values()];
  };
  // the element's own HTML tag (used to show "code now -> change to" in the report)
  const tag = el => { const h = el.outerHTML; const end = h.indexOf('>'); return (end > 0 ? h.slice(0, end + 1) : h).slice(0, 400); };
  // the short text next to a box, e.g. "From" above a station box that has no <label>
  const nearText = el => {
    let n = el;
    for (let k = 0; k < 3 && n.parentElement; k++) {
      n = n.parentElement;
      const t = (n.innerText || '').split('\n').map(s => s.trim())
        .find(s => /[A-Za-z0-9]{2}/.test(s) && s.length < 30 && s !== String(el.value || '').trim());  // not "*"
      if (t) return t;
    }
    return '';
  };
  // the text written right before the box ("Sort By: <select> Per page: <select>": each box its own words - the first
  // line of their parent would name both 'Sort By')
  const prevText = el => {
    let n = el.previousSibling;
    for (let k = 0; n && k < 3; k++, n = n.previousSibling) {
      if (n.nodeType === 1 && /^(INPUT|SELECT|TEXTAREA|BUTTON)$/.test(n.tagName)) return '';  // (another box's text)
      const t = ((n.nodeType === 3 ? n.textContent : n.innerText) || '').replace(/\s+/g, ' ').trim();
      if (t) return t.length < 40 && /[A-Za-z]{2}/.test(t) ? t : '';
    }
    return '';
  };
  const labelFor = el => {
    const root = el.getRootNode().querySelector ? el.getRootNode() : document;  // (a label inside the same shadow root)
    if (el.id) {
      const labels = [...root.querySelectorAll('label[for="' + cssEsc(el.id) + '"]')];
      // Broken pages can point several labels at one ID. Prefer the adjacent or
      // nearest preceding label instead of assigning the first field's name twice.
      const adjacent = el.previousElementSibling;
      const preceding = labels.filter(l => l.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING);
      const l = labels.includes(adjacent) ? adjacent : preceding[preceding.length - 1] || labels[0];
      if (l && l.innerText.trim()) return l.innerText.trim();
    }
    const p = el.closest('label'); if (p) return p.innerText.trim();
    return el.getAttribute('placeholder') || el.getAttribute('aria-label') || el.getAttribute('title') || prevText(el)
      || nearText(el);
  };
  // the name a screen reader announces ("+" with aria-label "Increase quantity" -> "Increase quantity") and the role
  const accName = el => ((el.getAttribute('aria-label') || '').trim()
    || (el.getAttribute('aria-labelledby') || '').split(/\s+/).map(id => (document.getElementById(id) || {}).innerText || '').join(' ').trim()
    || (['INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName) ? labelFor(el) : (el.labels && el.labels[0] ? el.labels[0].innerText.trim() : ''))
    || (el.innerText || '').trim() || (['button', 'submit'].includes(el.type) ? el.value : '') || el.getAttribute('title')
    || el.getAttribute('placeholder') || el.getAttribute('alt') || '').split('\n')[0].trim().slice(0, 80);
  const INPUT_ROLE = {checkbox: 'checkbox', radio: 'radio', submit: 'button', button: 'button', range: 'slider',
                      search: 'searchbox', number: 'spinbutton'};
  const roleOf = el => el.getAttribute('role') || ({A: 'link', BUTTON: 'button', SELECT: 'combobox', TEXTAREA: 'textbox',
                                                    SUMMARY: 'button'})[el.tagName]
    || (el.tagName === 'INPUT' ? INPUT_ROLE[el.type] || 'textbox' : '');
  // a box or control that OPENS something when used: a calendar, a list of choices, suggestions while typing
  const OPENER = /date|picker|calendar|drop|select|combo|autosuggest|autocomplete|typeahead|suggest|pax|passenger|menu|toggle/i;
  // a read-only box is a picker (a date / guests box that opens on a click) when it is empty or holds a date or a
  // count - not one that just shows a fixed text ('You cannot change me')
  const PICKED = /\d{1,4}[\/.\-]\d{1,2}[\/.\-]\d{1,4}|\b(mon|tue|wed|thu|fri|sat|sun|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b|\b\d+\s*(adult|guest|traveller|passenger|room|night|person|people)s?\b/i;
  const isOpener = el => !!(el.getAttribute('aria-haspopup') || el.getAttribute('aria-expanded') !== null
    || el.getAttribute('aria-autocomplete') || el.getAttribute('list')
    || el.readOnly && el.tagName === 'INPUT' && (!el.value || PICKED.test(el.value))
    || OPENER.test(`${el.id} ${el.className} ${el.getAttribute('placeholder') || ''}`));
  // a button whose name says it opens something to look at: "Open gallery", "View photos", "Zoom", "Play video"
  const OPENS_BY_NAME = /\b(gallery|lightbox|zoom|enlarge|preview|full ?screen|play( video)?|watch( video)?|view (photos?|images?|video))\b/i;
  const suggests = el => !el.readOnly && !!(el.getAttribute('aria-autocomplete') || el.getAttribute('list')
    || /autosuggest|autocomplete|typeahead|suggest/i.test(`${el.id} ${el.className}`)
    || /type to|start typing/i.test(el.getAttribute('placeholder') || ''));

  // links; a link to a part of a page (#projects) also says which section, and - on this page - whether it exists
  const TAB_LIST = '[role=tablist], .nav-tabs, .nav-pills';
  const sectionOf = a => {
    const h = a.hash ? decodeURIComponent(a.hash.slice(1)) : '';
    return (h && !h.startsWith('/') && !h.startsWith('!')) ? h : '';  // (#/route = a page of a single-page app)
  };
  // in the website's own frame (header / menu / footer / sidebar - the same on every page), not in this page's content
  const inFrame = a => { for (let e = a; e && e !== document.body && e !== document.documentElement; e = e.parentElement)
                           if (qaChrome(e)) return true; return false; };
  const links = deepAll('a[href]').map(a => {
    const section = sectionOf(a), raw = a.getAttribute('href') || '';
    // a tab / collapse link ('#review' with data-toggle="tab", or in a tab list): its script shows a part of THIS
    // page (with a <base href> to the home page, a.href points there - but the link never goes there): a control
    const tog = !!(a.getAttribute('data-toggle') || a.getAttribute('data-bs-toggle') || a.getAttribute('role') === 'tab'
                   || (raw.startsWith('#') && (a.getAttribute('aria-controls') || a.closest(TAB_LIST))));
    const same = tog || (a.origin === location.origin && a.pathname === location.pathname);
    return { href: a.href, text: text(a), visible: visible(a), section, same, toggle: tog,
             nav: !!a.closest('nav, header, [role=navigation]'), chrome: inFrame(a), download: a.hasAttribute('download'),
             exists: section && same ? !!(document.getElementById(section) || document.getElementsByName(section).length) : null };
  });

  // buttons + links that act as buttons (<a href="#">, javascript:, onclick, an <a> with NO address that the page's
  // script handles: <a class="btn addItem">Add to Basket</a>) such as + / - / cart icon, tabs, accordions
  // (<summary>, data-toggle), and things that open popups
  const CONTROLS = 'button, input[type=submit], input[type=button], [role=button], [role=tab], summary, ' +
                   'a[href="#"], a[href^="javascript:"], a[onclick], a[data-toggle], a[data-bs-toggle], a:not([href]), ' +
                   '[aria-controls], ' + TAB_LIST.split(', ').map(t => `${t} a[href^="#"]`).join(', ');
  // (an <a> without an address and without text is a bookmark - <a name="top"> - not a control)
  const bookmark = el => el.tagName === 'A' && !el.hasAttribute('href') && !(el.innerText || '').trim()
                         && !el.querySelector('img, svg') && !el.getAttribute('aria-label')
                         && !el.getAttribute('aria-labelledby')
                         && !/^(button|link|tab)$/.test(el.getAttribute('role') || '');
  // + custom controls that are not real buttons: a <div>/<span>/<li>/<th> a person can click (pointer cursor),
  // e.g. a "1 Adult" passengers box that opens a panel. Only the outermost one, and not wrappers of real controls.
  const INTERACTIVE = 'a, button, input, select, textarea, label, summary';
  const pointer = el => getComputedStyle(el).cursor === 'pointer';
  const custom = deepAll('div, span, li, img, i, th').filter(el =>
    visible(el) && pointer(el) && !(el.parentElement && pointer(el.parentElement))
    && !el.closest(INTERACTIVE) && !el.querySelector(INTERACTIVE) && nameOf(el)).slice(0, 40);
  // what kind of control it is -> which test it gets
  const SLIDER = '[class*=carousel i], [class*=slider i], [class*=slick i], [class*=swiper i], [class*=splide i], ' +
                 '[class*=glide i], [class*=owl- i], [class*=flickity i], [aria-roledescription=carousel]';
  const toggle = el => el.getAttribute('data-toggle') || el.getAttribute('data-bs-toggle') || '';
  const kindOf = el => {
    const t = toggle(el), on = el.getAttribute('onclick') || '', txt = nameOf(el);
    if (el.getAttribute('role') === 'tab' || t === 'tab' || t === 'pill' || el.closest(TAB_LIST))
      return 'tab';
    if (t === 'modal' || el.getAttribute('aria-haspopup') === 'dialog') return 'modal';
    if (t === 'collapse' || el.tagName === 'SUMMARY' || (el.getAttribute('aria-controls') && el.getAttribute('aria-expanded') !== null))
      return 'collapse';
    // a button that only opens the browser's alert / confirm box ('JS Confirm') - not 'Confirm Order' (an action)
    if (/\b(alert|confirm|prompt)\s*\(/.test(on) || /^(js |click for js )?(alert|confirm|prompt)( box)?$/i.test(txt)) return 'dialog';
    if (el.closest('th, thead')) {
      // a table that marks its sortable columns: a header without the mark ('Actions') is not one of them
      const th = el.closest('th'), table = el.closest('table');
      if (th && table && sortHeads.some(h => h.closest('table') === table) && !sortHeads.includes(th)) return '';
      return 'sort';
    }
    // an image slider's arrows / dots (they show another slide, not another page of results) - not the other
    // buttons a slider can hold (e.g. 'Add to cart' on a product slide)
    const slider = el.closest(SLIDER), cls = typeof el.className === 'string' ? el.className : '';
    const inSlider = slider && slider !== document.body && slider !== document.documentElement
                     && slider.querySelectorAll('a, button').length < 60;
    if (['data-slide', 'data-bs-slide', 'data-slide-to', 'data-bs-slide-to'].some(a => el.hasAttribute(a))
        || (inSlider && (!txt || /^(prev(ious)?|next|[‹›«»<>←→]|\d+|(go to )?slide \d+.*)$/i.test(txt)
                         || /prev|next|arrow|dot|bullet|indicator|control|paginat/i.test(cls))))
      return 'slide';
    if (el.getAttribute('rel') === 'next' || /^(next|next page|»|›|>)$/i.test(txt) || el.closest('.pagination, .pager, [class*=paginat]'))
      return 'next';
    return '';
  };
  // sortable table columns: headers marked as sortable (tablesorter, aria-sort, data-sort, "sort" classes)
  const sortHeads = [...document.querySelectorAll('thead th, tr:first-child > th')].filter(th => visible(th)
    && !custom.includes(th) && !th.querySelector(INTERACTIVE)
    && (th.getAttribute('aria-sort') || th.getAttribute('data-sort') || th.getAttribute('onclick')
        || /sort|header/i.test(th.className) || /sort/i.test(th.closest('table').className))
    && nameOf(th)).slice(0, 10);
  const shadowOf = el => { const h = hostsOf(el); return h.length ? { shadow_path: h } : {}; };
  const buttons = group([...deepAll(CONTROLS), ...custom, ...sortHeads]
    .filter(b => visible(b) && !bookmark(b)).slice(0, 300).map(b => ({ ...shadowOf(b),
      text: nameOf(b), accname: accName(b), role: roleOf(b), selector: sel(b), type: b.getAttribute('type') || '',
      tag: b.tagName.toLowerCase(), href: b.getAttribute('href') || '',
      // a real name (a word a person reads or hears), not one made of its CSS classes ('btn btn orange')
      named: /[\p{L}\p{N}]/u.test(`${accName(b)} ${b.getAttribute('title') || ''}`) || !!b.querySelector('img[alt]:not([alt=""])'),
      in_form: !!b.closest('form'), disabled: !!b.disabled || b.classList.contains('disabled'),
      // can't be clicked now: a pager's '«' on page 1 (li.page-item.disabled gives it pointer-events: none) - not
      // 'disabled': a login button may be greyed out like this only until its boxes are filled in
      inert: b.getAttribute('aria-disabled') === 'true' || getComputedStyle(b).pointerEvents === 'none',
      // a form with neither method nor action is sent by the page's own script (Vue / React: OrangeHRM's 'Punch In'
      // posts to its API) - not a GET form that only reads
      form_method: b.closest('form') ? (b.closest('form').getAttribute('method')
        || (b.closest('form').getAttribute('action') ? 'get' : 'script')).toLowerCase() : '',
      opener: isOpener(b) || OPENS_BY_NAME.test(nameOf(b)), custom: custom.includes(b), kind: kindOf(b), html: tag(b)
    }))).slice(0, 150);

  // drag and drop: things that can be dragged, and places to drop them
  const draggables = [...document.querySelectorAll('[draggable=true]')].filter(visible).slice(0, 10)
    .map(e => ({ text: nameOf(e), selector: sel(e) }));
  const droppables = [...document.querySelectorAll('[ondrop], [id*=drop i], [class*=drop i]')]
    .filter(e => visible(e) && !e.matches('select, [class*=dropdown i], [id*=dropdown i]')).slice(0, 5)
    .map(e => ({ text: nameOf(e), selector: sel(e) }));
  // hover menus: a menu item whose sub-menu is hidden until you point at it
  const hovers = [...document.querySelectorAll('nav li, [class*=menu i] > li, .navbar li, [class*=dropdown i], [class*=hover i], .figure')]
    .filter(e => visible(e) && !e.closest('video, audio, .video-js, [role=region][aria-label*="video" i]')
      && [...e.querySelectorAll('ul, div, .dropdown-menu, .figcaption')].some(c => !visible(c) && c.querySelector('a, button, h5, p')))
    .slice(0, 6).map(e => ({ text: nameOf(e), name: stable(nameOf(e).split('\n')[0]) || nameOf(e), selector: sel(e) }));
  const iframes = [...document.querySelectorAll('iframe')].filter(visible)
    .map(f => f.getAttribute('src') || f.getAttribute('title') || 'embedded frame').slice(0, 10);

  // names of the things listed on the page (products, articles...), e.g. for a search test
  const itemNames = [...new Set([...document.querySelectorAll(
      '[class*="product-name"], [class*="item-name"], [class*="title"] , h3, h4, h5')]
    .filter(visible).map(e => e.innerText.trim().split('\n')[0]).filter(t => t.length > 2 && t.length < 60))].slice(0, 20);

  // required: the attribute, aria-required, or what a person sees - a label ending in '*', or a label styled as
  // required (OrangeHRM: <label class="oxd-input-field-required"> draws its '*' with CSS)
  const reqOf = i => { if (i.required || i.getAttribute('aria-required') === 'true') return true;
    let n = i;
    for (let k = 0; k < 3 && n.parentElement; k++) {
      n = n.parentElement;
      const lab = n.querySelector('label');
      if (lab && !lab.contains(i)) return /\*\s*$/.test(lab.innerText || '') || /required/i.test(lab.className || '');
    }
    return false; };
  const inputs = deepAll('input, textarea, select')
    .filter(i => !['hidden', 'submit', 'button'].includes(i.type)).filter(visible).slice(0, 60).map(i => ({ ...shadowOf(i),
      tag: i.tagName.toLowerCase(), type: i.type || '', name: i.name || '', id: i.id || '',
      selector: sel(i), label: labelFor(i).slice(0, 80), accname: accName(i), role: roleOf(i),
      required: reqOf(i), placeholder: i.placeholder || '', autocomplete: i.getAttribute('autocomplete') || '',
      min: i.getAttribute('min'), max: i.getAttribute('max'),
      minlength: i.minLength > 0 ? i.minLength : null, maxlength: i.maxLength > 0 ? i.maxLength : null,
      pattern: i.getAttribute('pattern') || null, html: tag(i),
      readonly: !!i.readOnly, disabled: !!i.disabled, opener: isOpener(i), suggests: suggests(i),
      checked: !!i.checked,
      options: i.tagName === 'SELECT' ? [...i.options].filter(o => !o.disabled && o.value !== '')
        .map(o => ({ value: o.value, text: o.text.trim().slice(0, 40) })).slice(0, 15) : null
    }));

  // Framework dialogs often use labelled inputs and a footer button without a <form>.
  const fieldNodes = root => [...(root.elements || root.querySelectorAll('input, textarea, select'))]
    .filter(i => /^(INPUT|TEXTAREA|SELECT)$/.test(i.tagName)
      && !['hidden', 'submit', 'button', 'reset'].includes(i.type) && visible(i));
  const nativeForms = deepAll('form, [role=form]').filter(f => visible(f) || fieldNodes(f).length);
  const dialogForms = deepAll('dialog, [role=dialog], .modal').filter(d => visible(d)
    && fieldNodes(d).some(i => !i.closest('form, [role=form]')));
  const forms = [...new Set([...nativeForms, ...dialogForms])].slice(0, 20).map((f, idx) => {
    const native = f.tagName === 'FORM';
    const fields = fieldNodes(f).filter(i => native || f.matches('[role=form]')
      ? i.form === f || i.closest('form, [role=form]') === f : !i.closest('form, [role=form]'));
    let scope = f;
    const dialog = f.closest('dialog, [role=dialog], .modal');
    if (native && dialog && dialog.querySelectorAll('form').length === 1) scope = dialog;
    const candidates = [...scope.querySelectorAll('button, input[type=submit], input[type=button], [role=button]')]
      .filter(b => visible(b) && !b.disabled && !b.hasAttribute('data-dismiss') && !b.hasAttribute('data-bs-dismiss')
        && b.type !== 'reset' && !/^(close|cancel|dismiss|back|previous|x|\u00d7)$/i.test(accName(b)));
    const submit = candidates.find(b => (b.form === f || f.contains(b))
      && (b.type === 'submit' || b.getAttribute('type') === null))
      || candidates.find(b => /^(send|submit|save|create|register|sign ?up|log ?in|sign ?in|continue|next|search|apply|confirm)\b/i.test(accName(b)));
    return {
      index: idx, selector: !f.id && dialog && dialog !== f
        ? sel(dialog) + ' ' + (native ? 'form' : '[role=form]') + ' >> nth='
          + [...dialog.querySelectorAll(native ? 'form' : '[role=form]')].indexOf(f)
        : sel(f), open_tag: tag(f), synthetic: !native,
      action: f.getAttribute('action') || '',
      method: (f.getAttribute('method') || (f.getAttribute('action') ? 'get' : 'script')).toLowerCase(),
      hidden: [...f.querySelectorAll('input[type=hidden]')].filter(i => i.name && !/csrf|token|nonce|key|secret|auth|session/i.test(i.name))
        .map(i => [i.name, String(i.value).slice(0, 100)]).slice(0, 10),
      fields: fields.map(i => ({name: i.name || '', id: i.id || '', type: i.type || '', tag: i.tagName.toLowerCase(),
        selector: sel(i), required: reqOf(i), label: labelFor(i).slice(0, 80),
        local_selector: i.id && f.querySelectorAll('[id="'+q(i.id)+'"]').length === 1 ? '[id="'+q(i.id)+'"]' :
          (i.name && f.querySelectorAll('[name="'+q(i.name)+'"]').length === 1 ? '[name="'+q(i.name)+'"]' :
          i.tagName.toLowerCase() + (i.getAttribute('type') ? '[type="'+q(i.getAttribute('type'))+'"]' : '')),
        global: !!i.closest('nav,aside,[role=navigation],[role=search]'),
        min: i.getAttribute('min'), max: i.getAttribute('max'), step: i.getAttribute('step'),
        readonly: i.readOnly, disabled: i.disabled,
        placeholder: i.placeholder || '', autocomplete: i.getAttribute('autocomplete') || '', html: tag(i)})),
      submit: submit ? {text: accName(submit), selector: sel(submit)} : null
    };
  }).filter(f => f.selector);
  for (const f of forms.filter(f => f.fields.length && f.submit)) {
    const button = buttons.find(b => b.selector === f.submit.selector);
    if (button) { button.in_form = true; button.form_method = f.method; button.type = 'submit'; }
  }

  // data tables: their columns and rows, and the search box / rows-per-page choice that belong to THEM (in the same
  // container, never the site's header search)
  const numericOptions = s => [...s.options].map(o => (o.value || o.text || '').trim()).filter(v => /^\d+$/.test(v));
  const tables = [...document.querySelectorAll('table')]
    .filter(t => visible(t) && t.querySelectorAll('tbody tr').length >= 2).slice(0, 5).map(t => {
      let box = t.parentElement;
      for (let k = 0; k < 4 && box && box.parentElement && box !== document.body
           && !box.querySelector('input[type=search], input[placeholder], select'); k++) box = box.parentElement;
      box = box || document.body;
      const search = [...box.querySelectorAll('input')].find(i => visible(i) && !inFrame(i) && (i.type === 'search'
        || /search|filter|find/i.test(`${i.placeholder} ${i.id} ${i.name} ${i.getAttribute('aria-label') || ''}`)));
      const size = [...box.querySelectorAll('select')].find(s => visible(s) && !inFrame(s) && numericOptions(s).length >= 2);
      return { selector: sel(t) || 'table',
               columns: [...t.querySelectorAll('thead th, tr:first-child > th')].map(th => (th.innerText || '').trim()).slice(0, 12),
               rows: t.querySelectorAll('tbody tr').length, search: search ? sel(search) : null,
               page_size: size ? sel(size) : null, sizes: size ? numericOptions(size).slice(0, 6) : [] };
    });

  // the page's DESIGN: the tag tree of its main content (3 levels, without the website's frame). Pages of one kind
  // (every product page) share it, even when their addresses have no number in them (/products/red-leather-bag)
  const skeleton = (() => {
    const main = document.querySelector('main, [role=main], #main, #content') || document.body;
    const skip = /^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE|SVG|PATH|BR|HR)$/;
    const walk = (e, d) => e.tagName + (d >= 3 ? '' : '(' + [...e.children].filter(c => !skip.test(c.tagName) && !qaChrome(c))
      .slice(0, 12).map(c => walk(c, d + 1)).join(',') + ')');
    return walk(main, 1);
  })();

  // a total / estimate the page shows ("Estimated total: $120") - a count box next to it must change it
  const totals = [...document.querySelectorAll('p, span, div, td, li, strong, b, label, output')]
    .filter(e => visible(e) && e.children.length <= 3 && !inFrame(e) && (e.innerText || '').length < 120
            && /\b(total|estimated|grand total|subtotal)\b/i.test(e.innerText || '') && /[$€£₹]\s?\d/.test(e.innerText || ''))
    .map(e => e.innerText.trim()).slice(0, 5);

  const images = [...document.querySelectorAll('img')];
  const brokenImages = images.filter(i => i.complete && i.naturalWidth === 0 && i.src)
                             .map(i => i.src).slice(0, 20);

  const headings = [...document.querySelectorAll('h1, h2')].map(h => h.innerText.trim()).filter(Boolean).slice(0, 10);

  // the list of items (products, search results, orders...): the repeated cards - see ITEM_LIST_FN
  const listed = qaItemList(false);
  // (with each card's text: what a filter's word must be found in - 'Non-stop' / '1 stop' on a flight card)
  const shapes = listed.shapes || [], count = {};
  shapes.forEach(s => { count[s] = (count[s] || 0) + 1; });
  const common = Object.keys(count).sort((a, b) => count[b] - count[a])[0];
  const itemLinks = listed.selector ? { selector: listed.selector, links: listed.links,
                                         count: listed.count || listed.links.length,
                                         client_navigation: !!listed.client_navigation,
                                        cards: (listed.cards || []).slice(0, 30).map(c => c.slice(0, 200)),
                                        // (the items whose card works differently from most: see shapeOf)
                                        odd: [...new Set((listed.hrefs || []).filter((h, n) => shapes[n] !== common))].slice(0, 3) } : {};

  // the names on the item cards come first (a search test types one): section titles like "Sort" or "Filters" are no items
  const cardNames = listed.names || (itemLinks.links || []).map(l => (l.text || '').trim()).filter(t => t.length > 2 && t.length < 60);
  // elements that say they ARE an item's name (a product list without links) - unlike headings ('Welcome', 'Home')
  const productNames = [...new Set([...document.querySelectorAll('[class*="product-name" i], [class*="product_name" i], ' +
      '[class*="item-name" i], [itemprop=name]')].filter(e => visible(e) && !e.closest('nav, header, footer'))
    .map(e => e.innerText.trim().split('\n')[0]).filter(t => t.length > 2 && t.length < 60))].slice(0, 20);
  // web components whose content can't be read: no open shadow root, no children, but drawn on the page -> most
  // likely a CLOSED shadow root (its controls can't be found or tested from outside - reported, never guessed)
  const unsupported = roots.flatMap(r => [...r.querySelectorAll('*')])
    .filter(e => e.tagName.includes('-') && !e.shadowRoot && !e.children.length && visible(e)).slice(0, 10)
    .map(e => ({ tag: e.tagName.toLowerCase(), selector: sel(e), ...shadowOf(e),
                 reason: 'unsupported: possibly a closed shadow root (its content cannot be read or tested from outside)' }));
  let component_snapshot;
  try { component_snapshot = (
""" + DOM_COMPONENTS_JS + r"""
  )(); } catch (error) { component_snapshot = {components:[], error:"DOM component collection failed: " + error.name}; }
  return { component_snapshot, links, buttons, inputs, forms, headings, itemNames: [...new Set([...cardNames, ...itemNames])].slice(0, 20), draggables, droppables, hovers, iframes, itemLinks,
           productNames, imageCount: images.length, brokenImages, unsupported, shadowRoots: roots.length - 1, tables,
           totals, skeleton };
}
"""


from ..safety import unwrap_link  # noqa: E402,F401 - kept importable from here (main.py, server.py)


def _route(fragment: str) -> str:
    """The page part of a single-page-app address (#/offers -> /offers); '' for a normal #section anchor."""
    if fragment.startswith("!/"):
        fragment = fragment[1:]
    return fragment.rstrip("/") if fragment.startswith("/") else ""


TRACKING = re.compile(r"^(utm_\w+|gclid|fbclid|msclkid|dclid|mc_cid|mc_eid|_ga|_gl|igshid)$", re.I)
# a display setting: the same page in another currency / language (?currency=EUR on every page of a shop) - read
# once, not once per currency (the switch itself is a control the explorer tries)
SETTING = re.compile(r"^(currency|language|lang|locale)$", re.I)


def _normalize(url: str) -> str:
    url, fragment = urldefrag(url)
    url = re.sub(r";jsessionid=[^?#/]*", "", url, flags=re.I)  # same page, different session id
    p = urlparse(url)
    if p.query:  # ?utm_source=newsletter etc. only track the visitor, ?currency=EUR only shows it in euros: same page
        parts = [x for x in p.query.split("&") if x]
        # (the other parts are kept exactly as written: re-encoded, rt=product/category would become
        # rt=product%2Fcategory - another address for the same page)
        kept = [x for x in parts if not TRACKING.match(x.partition("=")[0]) and not SETTING.match(x.partition("=")[0])]
        if len(kept) != len(parts):
            url = urlunparse(p._replace(query="&".join(kept)))
    url = url.rstrip("/") or url
    route = _route(fragment)  # #/offers is its own page in a single-page app; #top is not
    return f"{url}#{route}" if route else url


INDEX_FILE = re.compile(r"/(index|default)\.(html?|php|aspx?|jsp)$", re.I)


def _no_index(url: str) -> str:
    """A folder's index file is the folder's page: https://x.com/shop/index.html -> https://x.com/shop."""
    p = urlparse(url)
    return urlunparse(p._replace(path=INDEX_FILE.sub("", p.path))).rstrip("/") if INDEX_FILE.search(p.path) else url


def _slug(url: str) -> str:
    p = urlparse(url)
    s = (p.path.strip("/") or "home") + (("_" + p.query) if p.query else "") + _route(p.fragment)
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_")[:60]
    return s or "home"


def _folder(path: str) -> str:
    """/app/index.html -> /app (a file's folder); /shop -> /shop."""
    return path.rsplit("/", 1)[0] if re.search(r"/[^/]+\.\w{2,5}$", path) else path


def _mode(url: str) -> tuple[str, str]:
    """What to test, decided from the link itself -> (mode, folder):

      site     entire website   site.com, site.com/index.html
      section  limited pages    site.com/shop, site.com/seleniumPractise/  (the app under that folder)
      page     specific page    site.com/blog/my-post, site.com/item?id=5, site.com/page.html, site.com/app#/cart

    CRAWL_SCOPE=site / section / page in .env forces one mode; auto (default) decides as above.
    """
    p = urlparse(url)
    path = p.path.rstrip("/")
    folder = _folder(path)
    if settings.section_path:  # --section /electronics: only that part of the website (a very large site, in parts)
        return "section", "/" + settings.section_path.strip("/")
    forced = settings.crawl_scope
    if forced in ("site", "section", "page"):
        return forced, ("" if forced == "site" else folder)
    if _auth_link(url):  # a login / register page is the door to the whole app behind it
        root = _app_root(url)
        return ("section", root) if root else ("site", "")
    is_file = bool(re.search(r"/[^/]+\.\w{2,5}$", path)) and not re.search(r"/(index|default|home)\.\w+$", path, re.I)
    if p.query or _route(p.fragment) or is_file or path.count("/") >= 2:
        return "page", folder
    if not folder:
        return "site", ""
    return "section", folder


# a word in the address that means "log in / sign up" - in the path (/login) or in an app route (#/auth/register)
AUTH_WORD = re.compile(r"^(log-?in|sign-?in|sign-?up|register|registration|auth|account|users?|password-?\w*)$", re.I)


def _auth_link(url: str) -> bool:
    """site.com/login, site.com/auth/register, site.com/client/#/auth/register, index.php?rt=account/login ...
    (log in / sign up pages)."""
    p = urlparse(url)
    route = "/".join(r.partition("=")[2] for r in _query_route(p.query))
    parts = [s for s in (p.path + "/" + _route(p.fragment) + "/" + route).split("/") if s]
    return bool(parts) and AUTH_WORD.match(parts[-1]) is not None \
        and any(re.match(r"^(log-?in|sign-?in|sign-?up|register|registration|auth)$", s, re.I) for s in parts)


def _app_root(url: str) -> str:
    """The folder of the app a login / register page belongs to:
    site.com/login -> '' (whole site) · site.com/app/auth/register -> /app · site.com/client/#/auth/register -> /client"""
    p = urlparse(url)
    if _route(p.fragment):  # single-page app: the app lives at the address before the #
        return _folder(p.path.rstrip("/"))
    parts = [s for s in p.path.split("/") if s]
    while parts and AUTH_WORD.match(parts[-1]):
        parts.pop()
    return ("/" + "/".join(parts)) if parts else ""


def _settle(tab, ms: int = 5000) -> None:
    try:
        tab.wait_for_load_state("networkidle", timeout=ms)
    except Exception:
        pass  # some sites never go fully idle


# ------------------------------------------------------------------ test account: given, saved, or created
# The pages behind a login need an account. Given in the chat / .env -> used. Otherwise - ONLY when you allowed it
# for this run (AUTO_REGISTER / the tick in the web UI) - the tester signs up ONCE on the website's own sign-up page
# with clearly fake test data (an @example.com address, which never reaches a real person), saves it ENCRYPTED in
# accounts/<site>.json and reuses it on the next runs. Sites with a CAPTCHA are left alone (it is there to stop robots).

SIGNUP_TEXT = re.compile(r"\b(register|sign ?up|create (an |your |new )?account|join( us| now)?|new (user|customer)|"
                         r"get started)\b", re.I)
SIGNUP_PATH = re.compile(r"(register|sign-?up|create-?account|join)(/|$|\?)", re.I)


LOGIN_TEXT = re.compile(r"\b(log ?in|sign ?in)\b", re.I)


def _signup_url(entry: dict, start_url: str) -> str | None:
    """The website's sign-up page: the address you gave (if it is one), else a 'Register' / 'Sign up' link - a pure
    one before a 'Login or register' link (that one usually opens the LOGIN page)."""
    def is_signup(href: str, text: str = "") -> bool:  # (the address: its path, or its '#/register' route)
        p = urlparse(href or "")
        return bool(SIGNUP_TEXT.search(text or "") or SIGNUP_PATH.search(p.path) or SIGNUP_PATH.search(p.fragment))
    if is_signup(start_url):
        return start_url
    found = [l for l in entry.get("links", []) if l.get("href", "").startswith("http")
             and urlparse(l["href"]).hostname == urlparse(start_url).hostname and is_signup(l["href"], l.get("text", ""))]
    pure = [l for l in found if not LOGIN_TEXT.search(l.get("text") or "")]
    return (pure or found)[0]["href"] if found else None


# on a LOGIN page: the way to the sign-up form ("Create an account", or "Continue" in the "new customer" box)
TO_SIGNUP_JS = r"""() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const SIGNUP = /\b(register|sign ?up|create (an |your |new )?account|new (user|customer)|join)\b/i;
  const LOGIN = /\b(log ?in|sign ?in)\b/i;
  const name = e => (e.innerText || e.value || e.getAttribute('aria-label') || '').trim();
  const ctl = [...document.querySelectorAll('a[href], button, input[type=submit], input[type=button]')].filter(vis);
  let go = ctl.find(e => SIGNUP.test(name(e)) && !LOGIN.test(name(e)));
  if (!go) go = ctl.find(e => /^(continue|next)\b/i.test(name(e)) && (() => {
    for (let a = e.parentElement, n = 0; a && n < 5; a = a.parentElement, n++) {
      const t = (a.innerText || '').slice(0, 500);
      if (SIGNUP.test(t)) return !a.querySelector('input[type=password]');  // (not the login box itself)
    }
    return false; })());
  if (!go) return '';
  go.click();
  return name(go) || 'continue';
}"""
# a sign-up did NOT work when the website says so (also when the page says "Welcome" everywhere)
SIGNUP_ERROR = re.compile(r"error|invalid|incorrect|required|must|already|taken|exists|do(es)? not match|failed|"
                          r"wrong|please (enter|fill|select|check)|maximum|minimum|at least|too (long|short)", re.I)


# what the sign-up page says is wrong, as a person sees it: boxes marked invalid + error / alert / toast texts
SIGNUP_PROBLEMS_JS = r"""() => {
  const shown = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
                       return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const name = i => ((i.labels && i.labels[0] ? i.labels[0].innerText : '') || i.getAttribute('placeholder')
                     || i.getAttribute('formcontrolname') || i.name || i.id || 'a box').trim();
  const out = [];
  for (const i of document.querySelectorAll('input, select, textarea')) {
    if (i.type === 'hidden' || !shown(i)) continue;
    if ((i.matches(':invalid') && i.validationMessage) || i.getAttribute('aria-invalid') === 'true'
        || (i.classList.contains('ng-invalid') && (i.classList.contains('ng-touched') || i.classList.contains('ng-dirty'))))
      out.push(`${name(i)}: ${i.validationMessage || 'marked invalid'}`);
  }
  for (const e of document.querySelectorAll('[class*=error i], [class*=invalid i], [role=alert], [class*=toast i], [class*=alert i]')) {
    const t = (e.innerText || '').trim();
    if (shown(e) && t && t.length < 160) out.push(t);
  }
  return [...new Set(out)].slice(0, 8);
}"""
SIGNUP_OK = re.compile(r"success|created|registered|welcome|thank you|verify your|check your (e-?mail|inbox)|"
                       r"confirmation (e-?mail|link)", re.I)


def _signup_values() -> dict:
    """Clearly fake test data for one sign-up (an @example.com address never reaches a real person)."""
    import random
    from datetime import datetime
    stamp = datetime.now().strftime("%m%d%H%M%S") + str(random.randint(10, 99))
    # (a user name of 12 characters: advantageonlineshopping.com allows at most 15 - 'agenticqa' + 12 digits was
    # refused, Nov 3, 2026)
    return {"stamp": stamp, "email": f"agentic.qa.{stamp}@example.com", "username": f"qa{stamp[-10:]}",
            "password": f"Qa@{stamp[-6:]}x9Z"}  # upper + lower + digit + symbol, 12 characters


def _create_account(browser, signup_url: str) -> tuple[dict | None, str]:
    """Sign up once with fake test data and PROVE it worked. Returns (account, '') or (None, why not -
    including what the website itself said, e.g. 'Phone Number must be 10 digit')."""
    vals = _signup_values()
    context = browser.new_context(viewport={"width": 1366, "height": 900}, ignore_https_errors=True)
    tab = context.new_page()
    try:
        tab.goto(signup_url, wait_until="domcontentloaded", timeout=settings.page_timeout_ms)
        _settle(tab)
        tab.wait_for_timeout(1000)
        close_consent(tab)

        def a_login_page() -> bool:  # a form with a password box, but none of them is a sign-up form
            forms = [f for f in tab.evaluate(EXTRACT_JS).get("forms", [])
                     if any(x.get("type") == "password" for x in f.get("fields", []))]
            signup = [f for f in forms if SIGNUP_TEXT.search((f.get("submit") or {}).get("text") or "")
                      or sum(1 for x in f["fields"] if x.get("type") == "password") >= 2 or len(f["fields"]) >= 4]
            return bool(forms) and not signup
        if a_login_page():  # the sign-up link opened the LOGIN page: on to its sign-up form
            went = tab.evaluate(TO_SIGNUP_JS)
            if went:
                _settle(tab, 8000)
                tab.wait_for_timeout(1000)
            if not went or a_login_page():  # (never 'sign up' in the login form: that only tests a wrong password)
                return None, ("the sign-up form could not be reached: the sign-up link opens the login page"
                              + (f", and '{went}' there did not open a sign-up form" if went
                                 else ", and no way to a sign-up form was found there"))
        if CAPTCHA.search(tab.content()):
            return None, "the sign-up page has a CAPTCHA (made to stop robots)"
        form, data, used_username, why = _fill_signup(tab, vals)
        if why:
            return None, why
        # the button that sends the sign-up form
        submit = (form or {}).get("submit") or {}
        button = tab.locator(submit["selector"]).first if submit.get("selector") else None
        if button is None or not button.count():
            b = next((b for b in data.get("buttons", []) if b.get("selector") and SIGNUP_TEXT.search(b.get("text") or "")), None)
            button = tab.locator(b["selector"]).first if b else None
        if button is None:
            return None, "the sign-up button was not found"
        if not button.is_enabled():  # the website itself refuses the values (advantageonlineshopping.com: 'Use
            said = "; ".join(p for p in tab.evaluate(SIGNUP_PROBLEMS_JS) if SIGNUP_ERROR.search(p))  # maximum 15')
            return None, f"the website did not accept the sign-up values (its button stays disabled): {said[:300]}"
        # the sign-up form's OWN password boxes, as shown now (a hidden login popup's box is always 'gone': the
        # sign-up looked successful although the website had refused it - advantageonlineshopping.com, Nov 3, 2026)
        shown_pws = [s for s in dict.fromkeys(i.get("selector") for i in (form or {}).get("fields") or
                                              data.get("inputs", []) if i.get("type") == "password" and i.get("selector"))
                     if tab.locator(s).first.is_visible()]
        before_url, before = tab.url, set(tab.locator("body").inner_text(timeout=5000).splitlines())
        button.click(timeout=5000)
        tab.wait_for_timeout(3000)
        _settle(tab, 8000)
        # did it work? NEW evidence only (a "Welcome" on every page proves nothing): a success message that was not
        # there before, the page moved on, or the password boxes are gone - and the website does not say it failed
        text = tab.locator("body").inner_text(timeout=5000)
        new = "\n".join(l for l in text.splitlines() if l.strip() and l not in before)
        moved = _normalize(tab.url) != _normalize(before_url)
        pw_gone = bool(shown_pws) and not any(tab.locator(s).first.is_visible() for s in shown_pws)
        problems = tab.evaluate(SIGNUP_PROBLEMS_JS)
        refused = [p for p in problems if SIGNUP_ERROR.search(p)]
        if refused or not (moved or SIGNUP_OK.search(new) or pw_gone):
            said = "; ".join(refused or problems) or "no success message, and the sign-up form is still shown"
            return None, f"the website did not accept the sign-up: {said[:300]}"
        return {"username": vals["email"], "email": vals["email"],
                "user_name": vals["username"] if used_username else "", "password": vals["password"],
                "signup_page": signup_url}, ""
    except Exception as e:
        return None, f"signing up failed ({str(e).splitlines()[0][:120]})"
    finally:
        context.close()


def _tick(box) -> bool:
    """Tick a checkbox / radio and make sure it really is ticked. Many sites draw their own box ON TOP of the real
    one, so a normal (or forced) click lands on the drawing: then the real box itself, or its label, is clicked."""
    try:
        if not box.count():
            return False  # (not on the page: don't wait for it)
    except Exception:
        return False
    for attempt in (lambda: box.check(timeout=3000), lambda: box.check(timeout=3000, force=True),
                    lambda: box.evaluate("e => e.click()"),
                    lambda: box.evaluate("e => e.labels && e.labels[0] && e.labels[0].click()")):
        try:
            if box.is_checked(timeout=2000):
                return True
            attempt()
        except Exception:
            pass
    try:
        return box.is_checked(timeout=2000)
    except Exception:
        return False


def _fill_signup(tab, vals: dict) -> tuple[dict | None, dict, bool, str]:
    """Fill the sign-up form like a person (the form is NOT sent here).
    Returns (the form, the page data, a user name box was filled?, why not)."""
    email, username, password, stamp = vals["email"], vals["username"], vals["password"], vals["stamp"]
    data = tab.evaluate(EXTRACT_JS)
    # the sign-up form: the one with a password box (if several, the one whose button says 'Register'...)
    forms = [f for f in data.get("forms", []) if any(x.get("type") == "password" for x in f.get("fields", []))]
    form = next((f for f in forms if SIGNUP_TEXT.search((f.get("submit") or {}).get("text") or "")), None) \
        or max(forms, key=lambda f: len(f.get("fields", [])), default=None)
    inputs = data.get("inputs", [])
    if form:  # only the boxes of that form
        keys = {(x.get("id"), x.get("name")) for x in form.get("fields", [])}
        inputs = [i for i in inputs if (i.get("id"), i.get("name")) in keys] or inputs
    if not any((i.get("type") or "") == "password" for i in inputs):
        return form, data, False, "no sign-up form with a password box was found"
    used_username, groups = False, set()
    for i in inputs:
        s, t = i.get("selector"), (i.get("type") or "").lower()
        hint = f"{i.get('label')} {i.get('name')} {i.get('placeholder')} {i.get('id')}".lower()
        if not s or i.get("readonly") or i.get("disabled") or t in ("search", "file", "hidden", "submit", "button") \
                or "search" in hint:
            continue
        box = tab.locator(s).first
        try:
            if i.get("tag") == "select" or t.startswith("select"):
                # keep the website's own choice (e.g. the country - its regions are loaded for it); else the first
                if i.get("options") and not box.input_value(timeout=3000):
                    box.select_option(i["options"][0]["value"], timeout=5000)
                    tab.wait_for_timeout(500)  # (a country can load its regions)
            elif t == "radio":  # one choice per group (radios without a name: same address apart from the value)
                group = i.get("name") or re.sub(r"\[value=.*$", "", s)
                if group not in groups:
                    groups.add(group)
                    _tick(box)
            elif t == "checkbox":
                _tick(box)  # terms / "I am 18 or older" (usually required)
            elif t == "password":
                box.fill(password, timeout=5000)
            elif t == "email" or re.search(r"e-?mail", hint):
                box.fill(email, timeout=5000)
            elif t == "tel" or re.search(r"phone|mobile|contact|number", hint):
                box.fill("9" + stamp[-9:], timeout=5000)
            elif re.search(r"zip|post ?code|postal|pin ?code", hint):
                box.fill("10001", timeout=5000)
            elif re.search(r"city|town", hint):
                box.fill("Springfield", timeout=5000)
            elif re.search(r"address|street", hint):
                box.fill("1 Test Street", timeout=5000)
            elif re.search(r"company", hint):
                box.fill("Agentic QA", timeout=5000)
            elif re.search(r"user ?name|login|user ?id", hint):
                box.fill(username, timeout=5000)
                used_username = True
            elif re.search(r"first", hint):
                box.fill("Agentic", timeout=5000)
            elif re.search(r"last|surname", hint):
                box.fill("Tester", timeout=5000)
            elif re.search(r"name", hint):
                box.fill("Agentic Tester", timeout=5000)
            elif t == "number":
                box.fill("30", timeout=5000)
            elif t == "date":
                box.fill("1995-06-15", timeout=5000)
            elif t in ("text", "", "textarea"):
                box.fill("QA test", timeout=5000)  # (short: 'State' allowed 10 characters on advantageonlineshopping)
        except Exception:
            pass  # a box that can't be filled: the site tells us when we send the form
    return form, data, used_username, ""


def _login_name(entry: dict, form: dict, account: dict) -> str:
    """What to type into the login form: the email, or the user name if that is what the login box asks for."""
    box = next((i for i in entry.get("inputs", []) if i.get("selector") == form["user"]), {})
    hint = f"{box.get('label')} {box.get('placeholder')} {box.get('name')} {box.get('id')}".lower()
    if account.get("user_name") and box.get("type") != "email" and "mail" not in hint:
        return account["user_name"]
    return account.get("email") or account["username"]


def _use_account(account: dict) -> None:
    """The tests use this account too (qa_login fixture, login journey) - kept in memory, never printed."""
    import os
    settings.test_username, settings.test_password = account["username"], account["password"]
    os.environ["TEST_USERNAME"], os.environ["TEST_PASSWORD"] = account["username"], account["password"]


class _NotTheApp(Exception):
    """The page opened fine but belongs to a different site on the same domain."""


class _Duplicate(Exception):
    """The address only redirects to a page that was already crawled."""


class _Fragment(Exception):
    """The address answers with a bare piece of HTML (no <head>, no title): a part a page's script loads ('/infinite_
    scroll/16' - the next part of an endless list), not a page a person opens."""


# (with an empty title) a bare piece of text: no <head>, no heading, no control - at most one link ('next page')
FRAGMENT_JS = ("() => (!document.head || document.head.childElementCount === 0) && !document.querySelector("
               "'h1, h2, button, input, select, textarea, form, frame, iframe') "
               "&& document.querySelectorAll('a[href]').length <= 1")


def _in_scope(url: str, scope: str) -> bool:
    path = urlparse(url).path.rstrip("/")
    return not scope or path == scope or path.startswith(scope + "/")


# ------------------------------------------------------------------ embedded frames (iframes)
# A test reaches an element inside a frame through the chain of its frames: Playwright's
# page.frame_locator(a).frame_locator(b).locator(sel) is the same as page.locator("a >> ENTER >> b >> ENTER >> sel"),
# so every generated test and the explorer use such an address like any other.
ENTER = " >> internal:control=enter-frame >> "
FRAME_DEPTH = 5
FRAME_ATTRS_JS = """f => ({tag: f.tagName.toLowerCase(), id: f.id || '', name: f.getAttribute('name') || '',
  title: f.getAttribute('title') || '', src: f.getAttribute('src') || '',
  index: [...f.ownerDocument.querySelectorAll('iframe, frame')].indexOf(f)})"""


def frame_selector(a: dict) -> str:
    """The address of one <iframe> inside its parent: id -> name -> title -> src -> its position."""
    q = lambda v: v.replace("\\", "\\\\").replace('"', '\\"')  # noqa: E731
    tag = a.get("tag") or "iframe"
    for attr in ("id", "name", "title", "src"):
        if a.get(attr) and not (attr == "src" and a[attr].startswith(("data:", "javascript:"))):
            return f'{tag}[{attr}="{q(a[attr])}"]'
    return f"{tag} >> nth={a.get('index', 0)}"


def in_frames(path: list[str], selector: str) -> str:
    """The address of an element inside the frames `path` (outermost first)."""
    return ENTER.join(list(path) + [selector]) if path else selector


def _frame_inventory(page, base_host: str) -> tuple[list[dict], dict]:
    """Every frame of the page (nested up to FRAME_DEPTH levels): its chain of iframe addresses, and whether it can be
    tested - testable (this website, or written by the page itself: about:srcdoc), external (another website: listed,
    not tested) or unreachable (with the reason). A testable frame's own buttons, boxes, links and forms are added to
    the page with `frame_path`, addressed through the frame."""
    frames, found = [], {"buttons": [], "inputs": [], "links": [], "forms": [], "component_snapshots": []}

    def walk(frame, chain: list[str], depth: int):
        for child in frame.child_frames[:20]:
            entry = {"url": (child.url or "")[:300], "depth": depth, "path": chain}
            try:
                attrs = child.frame_element().evaluate(FRAME_ATTRS_JS)
            except Exception as e:
                frames.append(dict(entry, status="unreachable",
                                   reason=f"its frame element could not be read ({str(e).splitlines()[0][:80]})"))
                continue
            path = chain + [frame_selector(attrs)]
            entry.update(path=path, name=attrs.get("title") or attrs.get("name") or attrs.get("id") or attrs.get("src")
                         or f"frame {attrs.get('index', 0) + 1}")
            host = urlparse(child.url or "").hostname
            if child.is_detached():
                frames.append(dict(entry, status="unreachable", reason="the frame closed while the page was read"))
                continue
            if depth > FRAME_DEPTH:
                frames.append(dict(entry, status="unreachable", reason=f"nested deeper than {FRAME_DEPTH} frames"))
                continue
            if host and host != base_host:
                frames.append(dict(entry, status="external", reason=f"another website ({host}): listed, not tested"))
                continue
            if (child.url or "").startswith("chrome-error:"):
                frames.append(dict(entry, status="unreachable", reason="the frame did not load (blocked or failed)"))
                continue
            try:
                data = child.evaluate(EXTRACT_JS)
            except Exception as e:
                frames.append(dict(entry, status="unreachable",
                                   reason=f"its content could not be read ({str(e).splitlines()[0][:80]})"))
                continue
            where = {"frame_path": path, "frame": " > ".join(path)}
            if data.get("component_snapshot"):
                found["component_snapshots"].append({**data["component_snapshot"], "frame_path": path})
            for group in ("buttons", "inputs"):
                for x in data.get(group, []):
                    if x.get("selector"):
                        found[group].append(dict(x, selector=in_frames(path, x["selector"]), **where))
            for l in data.get("links", []):
                found["links"].append(dict(l, **where))
            for f in data.get("forms", []):
                f = dict(f, selector=in_frames(path, f["selector"]), **where)
                f["fields"] = [dict(x, selector=in_frames(path, x["selector"])) for x in f.get("fields", [])
                               if x.get("selector")]
                if f.get("submit") and f["submit"].get("selector"):
                    f["submit"] = dict(f["submit"], selector=in_frames(path, f["submit"]["selector"]))
                found["forms"].append(f)
            frames.append(dict(entry, status="testable", reason="", buttons=len(data.get("buttons", [])),
                               inputs=len(data.get("inputs", [])), links=len(data.get("links", [])),
                               unsupported=data.get("unsupported", [])))
            walk(child, path, depth + 1)

    try:
        walk(page.main_frame, [], 1)
    except Exception as e:  # (reading the frames must never stop the crawl)
        print(f"  [discovery] could not read the page's frames: {str(e).splitlines()[0][:120]}")
    return frames, found


def _login_page(entry: dict, url: str, start_auth: bool) -> bool:
    """Is this page the login itself (not a page with a login form among other things)? The link was a login link,
    the page opened one (site.com/app -> /login), or the login form is the page's only real content (a few boxes)."""
    boxes = [i for i in entry.get("inputs", []) if i.get("type") not in ("checkbox", "radio")]
    return start_auth or _auth_link(entry.get("final_url") or url) or len(boxes) <= 4


MENU_OUTSIDE = "site-wide menu link, outside the section"


def _leaves_section(nxt: str, section: str, widen: bool, from_folder: bool, chrome: bool) -> str:
    """Why a same-site link that leaves the section you gave is NOT followed ('' = it is followed).

    Pages under the folder are always followed. A page outside it is opened only when the CONTENT of a page inside the
    folder links to it - one step out, never further - and never because of the site-wide menu (header / nav / footer /
    sidebar, the same on every page: following it would crawl the whole website). widen: the whole app may be crawled
    (the entire website was asked for, or the link you gave is its login / sign-up page)."""
    if widen or _in_scope(nxt, section):
        return ""
    if chrome:
        return MENU_OUTSIDE
    if not from_folder:
        return "outside the section, linked only from a page outside it too (one step out at most)"
    return ""


# ------------------------------------------------------------------ is it the same app?
# A link that leaves the address you gave (site.com/shop -> site.com/blog) may still be part of your
# app (e.g. /login -> /dashboard) or a different site on the same domain. The page is opened once
# and compared with the start page: same name in the title, or mostly the same menu links = same app.

TITLE_SPLIT = re.compile(r"\s+[|\-–—:·•]\s+")


def _title_parts(title: str | None) -> set[str]:
    """'Cart – MyShop' -> {'cart', 'myshop'}: the page name and the site/app name."""
    return {p.strip().lower() for p in TITLE_SPLIT.split(title or "") if len(p.strip()) > 2}


def _menu(entry: dict, host: str) -> set[str]:
    """The same-site link paths on a page (header / menu / footer)."""
    out = set()
    for l in entry.get("links", []):
        p = urlparse(urljoin(entry["url"], l.get("href", "")))
        if p.hostname == host:
            out.add(p.path.rstrip("/") or "/")
    return out


def _same_app(entry: dict, start: dict, host: str) -> bool:
    if _title_parts(entry.get("title")) & _title_parts(start.get("title")):
        return True
    a, b = _menu(entry, host), _menu(start, host)
    return len(a | b) >= 3 and len(a & b) / len(a | b) >= 0.5


def _is_crawlable(url: str, base_host: str) -> bool:
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        return False
    if re.search(r"(javascript|mailto|tel):", url, re.I):   # e.g. href="javascript:openWin(...)"
        return False
    if p.hostname != base_host:
        return False
    return not _skip_reason(url)


def _skip_reason(url: str) -> str:
    """Why a link of the website itself is not opened by the crawler ('' = it is opened)."""
    p = urlparse(url)
    if SKIP_EXTENSIONS.search(p.path):
        return "a file (download, picture, document), not a page"
    low = url.lower()
    word = next((w for w in settings.unsafe_link_words if w in low), None)
    if word:
        return f"could change data or end the session ('{word}' in the address)"
    excluded = next((x for x in settings.exclude_paths if (p.path or "/").startswith(x)), None)
    if excluded:
        return f"left out on purpose (EXCLUDE_PATHS: {excluded})"
    return ""


def _same_site(a: str | None, b: str | None) -> bool:
    """example.com and www.example.com (or shop.example.com) are the same website."""
    a, b = (a or "").lower().removeprefix("www."), (b or "").lower().removeprefix("www.")
    return bool(a and b) and (a == b or a.endswith("." + b) or b.endswith("." + a))


class _Blocked(Exception):
    """The page sent the browser outside the approved scope (a redirect) - its content is not used."""


class _SessionLost(Exception):
    """Crawling logged in, but the page shows the login form again."""


class _Frontier:
    """The pages still to visit: pages behind the login ALWAYS come first (they are the app the test account was given
    for), then the public pages - and in each, the SECTIONS of the site's own menu first (append_menu: so a time limit
    can only cut deep pages, never a whole section - OrangeHRM's Recruitment, Time, Maintenance were never reached),
    then a page that probably shows something NEW before more pages of a kind already known (append_later). Used like
    a deque by the crawl loop."""
    ORDER = ((True, "menu"), (True, False), (True, True), (False, "menu"), (False, False), (False, True))

    def __init__(self, first: tuple):
        self.lanes = {k: deque() for k in self.ORDER}
        self.menu: set = set()  # (the menu's sections - to list the ones never reached)
        self.append(first)

    def append(self, item: tuple) -> None:
        self.lanes[(bool(item[3]), False)].append(item)

    def menu_left(self) -> list[str]:
        """The menu sections never reached (the crawl stopped first)."""
        return [x[0] for k in self.ORDER if k[1] == "menu" for x in self.lanes[k] if x in self.menu]

    def append_menu(self, item: tuple) -> None:
        self.menu.add(item)
        self.lanes[(bool(item[3]), "menu")].append(item)

    def append_later(self, item: tuple) -> None:
        self.lanes[(bool(item[3]), True)].append(item)

    def appendleft(self, item: tuple) -> None:  # (the login link, a page to read again: before even the menu)
        self.lanes[(bool(item[3]), "menu")].appendleft(item)

    def popleft(self) -> tuple:
        return next(self.lanes[k] for k in self.ORDER if self.lanes[k]).popleft()

    def remove(self, item: tuple) -> None:
        for k in self.ORDER:
            if item in self.lanes[k]:
                self.lanes[k].remove(item)
                return
        raise ValueError(item)

    def __iter__(self):
        return iter([x for k in self.ORDER for x in self.lanes[k]])

    def __len__(self) -> int:
        return sum(len(v) for v in self.lanes.values())


# At phone width: does the page scroll sideways, and which controls are cut off (outside the screen) or covered?
LAYOUT_JS = r"""() => {
  const vis = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
                     return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const W = window.innerWidth, out = [];
  const wide = document.documentElement.scrollWidth;
  if (wide > W + 2) out.push({kind: 'horizontal scroll', detail: `the page is ${wide}px wide on a ${W}px screen`});
  const name = e => (e.innerText || e.value || e.getAttribute('aria-label') || e.getAttribute('placeholder') || e.tagName)
    .trim().split('\n')[0].slice(0, 40);
  // in a box made to slide sideways (a row of filter buttons you swipe, a picture slider): out of view by design
  const slides = e => { for (let n = e.parentElement; n && n !== document.body && n !== document.documentElement; n = n.parentElement) {
    const x = getComputedStyle(n).overflowX;
    if (x !== 'visible' && n.scrollWidth > n.clientWidth + 2) return true; } return false; };
  for (const e of [...document.querySelectorAll('a[href], button, input, select, textarea')].filter(vis).slice(0, 80)) {
    const r = e.getBoundingClientRect();
    if (r.right > W + 2 || r.left < -2) {
      if (!slides(e)) out.push({kind: 'off screen', detail: `'${name(e)}' is outside the screen`});
      continue;
    }
    if (r.top < 0 || r.top > window.innerHeight) continue;  // (below the fold: not judged)
    const x = r.left + r.width / 2, y = r.top + r.height / 2, top = document.elementFromPoint(x, y);
    const ownLabel = e.labels && [...e.labels].some(l => l === top || l.contains(top));  // (a styled radio / checkbox)
    if (top && top !== e && !e.contains(top) && !top.contains(e) && !ownLabel
        && !(top.closest && top.closest('label') && top.closest('label').contains(e)))
      out.push({kind: 'covered', detail: `'${name(e)}' is covered by <${top.tagName.toLowerCase()}>`});
  }
  return out.slice(0, 15);
}"""


SHOWS_JS = "() => !!document.body && document.body.innerText.trim().length > 0"


def _shows(page) -> bool:
    """Does the page show something (text) yet? One stuck file keeps a page 'loading' that a person can already use."""
    try:
        return bool(page.evaluate(SHOWS_JS))
    except Exception:
        return False  # (still on its way to the page)


class _Pace:
    """Polite speed: at most MAX_REQUESTS_PER_SEC page loads per second on a PUBLIC website (a site on this PC / the
    local network is the user's own: as fast as it can); after HTTP 429 / 503 it waits, slows down, and says so."""

    def __init__(self, rate: float, active: bool):
        self.gap = (1 / rate) if rate and rate > 0 and active else 0.0
        self.slow, self.last, self.events = 1.0, 0.0, []

    def wait(self) -> None:
        if not self.gap:
            return
        delay = self.last + self.gap * self.slow - time.time()
        if delay > 0:
            time.sleep(min(delay, 30))
        self.last = time.time()

    def back_off(self, status: int) -> bool:
        """Wait (longer each time) and slow down; True = load the page again."""
        if len(self.events) >= 20:
            return False
        self.slow = min(self.slow * 2, 16)
        wait = min(5 * self.slow, 60)
        self.events.append({"status": status, "waited_s": wait})
        print(f"  [discovery] the website answered HTTP {status} (too many requests): waiting {wait:.0f} s and "
              "slowing down", flush=True)
        time.sleep(wait)
        self.last = time.time()
        return True


def _parent_path(url: str) -> str:
    """/products/red-leather-bag -> /products ('' for a page at the top level)."""
    path = urlparse(url).path.rstrip("/")
    return path.rsplit("/", 1)[0] if path.count("/") >= 2 else ""


# single-page apps change the address with the history API (no link, no page load): written down for the crawler
HISTORY_INIT_JS = r"""(() => { if (window.__qaRoutes) return; window.__qaRoutes = [];
  for (const k of ['pushState', 'replaceState']) { const real = history[k];
    history[k] = function (s, t, url) { try { if (url) window.__qaRoutes.push(new URL(url, location.href).href); } catch (e) {}
                                        return real.apply(this, arguments); }; }
  window.addEventListener('hashchange', () => window.__qaRoutes.push(location.href)); })();"""
SITEMAP_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)


def _sitemap_urls(context, start_url: str, limit: int = 50000) -> list[str]:
    """The addresses the website itself lists: robots.txt 'Sitemap:' lines and /sitemap.xml (a sitemap index is
    followed, at most 10 sitemaps). Only read - never anything else of robots.txt. (50,000 = what one sitemap file
    may hold: they are counted, and only a sample of each page type is visited.)"""
    base = f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}"
    todo, done, out = [f"{base}/sitemap.xml"], set(), []
    try:
        r = context.request.get(f"{base}/robots.txt", timeout=10000)
        if r.ok:
            todo = [l.split(":", 1)[1].strip() for l in r.text().splitlines()
                    if l.lower().startswith("sitemap:")] + todo
    except Exception:
        pass
    while todo and len(done) < 10 and len(out) < limit:
        sm = todo.pop(0)
        if sm in done or urlparse(sm).hostname != urlparse(start_url).hostname:
            continue
        done.add(sm)
        try:
            r = context.request.get(sm, timeout=15000)
            if not r.ok:
                continue
            body = r.text()
        except Exception:
            continue
        for encoded_loc in SITEMAP_LOC.findall(body):
            loc = unescape(encoded_loc)
            (todo if loc.lower().endswith((".xml", ".xml.gz")) and "<sitemapindex" in body.lower() else out).append(loc)
    return list(dict.fromkeys(out))[:limit]


# an address part that is an id: 123, a1b2c3d4e5, 3f2a-..., iphone-15-pro  -> /product/{id}
ID_SEGMENT = re.compile(r"^(\d+|[0-9a-f]{8,}|[0-9a-f-]{32,36}|[\w-]*\d[\w-]*)$", re.I)
SIGNIN_TEXT = re.compile(r"\b(sign ?in|log ?in|my account|your account)\b", re.I)
VISITOR_401 = re.compile(r"Failed to load resource.*status of 401|\bunauthori[sz]ed\b", re.I)  # (also the app's own log)


def _foreign_load_error(m, scope) -> bool:
    """'Failed to load resource' for ANOTHER website's file (a tracker, an ad - optimizely.com on every page): its
    failed request is reported as a third-party one; it is no JavaScript error of this website."""
    if not m.text.startswith("Failed to load resource"):
        return False
    try:
        url = (m.location or {}).get("url") or ""
    except Exception:
        return False
    return bool(url) and not scope.in_scope(url)


# The query value that PICKS the page on a website with one script for every page: index.php?rt=checkout/cart,
# ?route=account/login, ?option=com_content&view=article. A word or a path - never an id, a page number or a search
# text (those are one page shown for another item / in another state).
ROUTE_KEY = re.compile(r"^(rt|route|r|controller|ctrl|action|act|module|mod|view|option|task|cmd|do|section|page|p|"
                       r"pagename|page_name)$", re.I)
STATE_KEY = re.compile(r"^(q|query|s|search|keywords?|term|text|sort|order|dir|limit|per_?page|offset|start|"
                       r"filter_\w+|currency|language|lang|locale|"
                       # where to go AFTER this page (/signin?next=/dashboard is the sign-in page)
                       r"next|return\w*|redirect\w*|continue|url|back\w*|ref|referr?er|from|to|goto|target|callback\w*|"
                       r"dest\w*|success\w*)$", re.I)


def _query_route(query: str) -> list[str]:
    """The 'key=value' parts of a query that pick the page (sorted): ['rt=checkout/cart']."""
    out = []
    for k, v in parse_qsl(query, keep_blank_values=True):
        if v and "://" not in v and not ID_SEGMENT.match(v) and not STATE_KEY.match(k) \
                and ("/" in v or ROUTE_KEY.match(k)):
            out.append(f"{k}={v}")
    return sorted(set(out))


def _pattern(url: str, auth: bool) -> tuple | None:
    """/product/123 and /product/456 share the pattern /product/{id}; /list?page=1 and ?page=2 share /list?page.
    On a website that picks its pages with the query, the route is the page: index.php?rt=checkout/cart and
    ?rt=account/login are two pages; ?rt=product/product&product_id=5 and &product_id=7 (also with &path=68) are one
    pattern '/index.php?rt=product/product&{id}' (an item's own id: {id}). None = an ordinary page."""
    p = urlparse(url)
    templ = "/".join("{id}" if s and ID_SEGMENT.match(s) else s for s in p.path.split("/"))
    pairs = parse_qsl(p.query, keep_blank_values=True)
    route = _query_route(p.query)
    if route:  # (the other parts only say which item, or how it is shown)
        item = any(k.lower().endswith("id") and v not in ("", "0") and ID_SEGMENT.match(v)
                   for k, v in pairs if f"{k}={v}" not in route)
        return auth, templ + "?" + "&".join(route) + ("&{id}" if item else ""), ()
    keys = tuple(sorted(k for k, _ in pairs))
    return None if templ == p.path and not keys else (auth, templ, keys)


SEARCH_BOX = re.compile(r"search|keyword|\bq\b|query", re.I)


def _search_url(entry: dict, url: str, word: str) -> str | None:
    """The results page of the page's own search box - what a person reaches by searching: the address its GET form
    sends for `word` (?rt=product/search&keyword=Velvet). None = no such form (a POST form is never sent; a form
    without an action is sent by a script - where it goes is not known, the explorer clicks its button instead)."""
    from urllib.parse import quote
    for f in entry.get("forms", []):
        if (f.get("method") or "get") != "get" or not f.get("action"):
            continue
        box = next((x for x in f.get("fields", []) if x.get("name") and ((x.get("type") or "") == "search" or SEARCH_BOX.search(
            f"{x.get('name')} {x.get('id')} {x.get('placeholder')} {x.get('label')}"))), None)
        if box:  # (written like the website's own links: rt=product/search, not rt=product%2Fsearch)
            action = urljoin(url, f.get("action") or url).split("#")[0].split("?")[0]
            parts = [tuple(h) for h in f.get("hidden") or []] + [(box["name"], word)]
            return action + "?" + "&".join(f"{quote(k, safe='')}={quote(v, safe='/')}" for k, v in parts)
    return None


def _probe_word(names: list[str]) -> str:
    """The word to search for: one that is in 2 or more of the listed items (a shop may open the page of a single
    match instead of its results page), else the first word of an item."""
    words = [w for n in dict.fromkeys(x.casefold() for x in names) for w in dict.fromkeys(re.findall(r"[^\W\d_]{4,}", n))]
    many = Counter(words)
    return next((w for w in words if many[w] >= 2), words[0] if words else "a")


def _sections(raw_links: list[dict], url: str, base_host: str | None) -> list[dict]:
    """Links to a part of a page (#projects, /#contact): menu items of one-page websites. Each one must lead to a
    section that exists ("exists" is known for this page's own sections; others are checked by tests). Not a tab or
    a collapse link ('#review' with data-toggle="tab"): its script shows its part of THIS page - it is tested as a
    tab, and with a <base href> its address only looks like another page's."""
    sections, seen = [], set()
    for l in raw_links:
        s = l.get("section") or ""
        if not s or s.lower() == "top" or l.get("toggle") or urlparse(l.get("href", "")).hostname != base_host:
            continue
        k = (l["href"].split("#")[0].rstrip("/"), s, (l.get("text") or "").strip())
        if k in seen:
            continue
        seen.add(k)
        sections.append({"href": l["href"], "section": s, "text": (l.get("text") or "").split("\n")[0].strip()[:60],
                         "visible": l.get("visible", True), "nav": l.get("nav", False), "exists": l.get("exists")})
    return sections[:60]


def _event(kind: str, data: dict) -> None:
    """A live event for the web UI (::page::{...}) - only when the UI started this run."""
    import os
    if os.environ.get("QA_EVENTS") == "1":
        print(f"::{kind}::" + json.dumps(data, ensure_ascii=False), flush=True)


GONE = re.compile(r"Target page, context or browser has been closed|Browser has been closed|browser has disconnected|"
                  r"Target closed", re.I)
MAX_REOPEN = 3  # a browser that keeps going away (Chrome keeps stopping): exploring ends with the pages found
# the browser itself cancelled a page load (the website was still moving to another page): tried once more
CANCELLED = re.compile(r"net::ERR_ABORTED|NS_BINDING_ABORTED|interrupted by another navigation|"
                       r"navigation .{0,40}(aborted|cancell?ed)", re.I)


def _gone(e: Exception) -> bool:
    """Did OUR browser go away (its window was closed by hand, or Chrome stopped)? Never the website's error."""
    return bool(GONE.search(str(e)))


PAGE_W, PAGE_H = 1366, 900  # the page size every browser of a run uses (crawler and tests)
BROWSER_BARS = 150  # Chrome's own bars above the page (tabs, address, 'controlled by automated software'), at scale 1


def fit_window_args() -> list[str]:
    """Visible Chrome on Windows: start in the usable desktop area.

    The real final sizing is done by _to_front() after Chrome creates its native window. Launch args are only the
    first hint; relying on device-scale-factor made the window look half-size on some displays.
    """
    import os
    if settings.headless or os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32")
        work = wintypes.RECT()
        user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work), 0)  # the screen without the taskbar
    except Exception:
        return []
    return [
        "--start-maximized",
        f"--window-size={work.right - work.left},{work.bottom - work.top}",
        f"--window-position={work.left},{work.top}",
    ]


def watched_slow_mo_ms() -> int:
    """Visible crawl/test windows should move at a pace a person can follow."""
    if settings.headless:
        return 0
    return max(500, min(settings.slow_mo_ms or 800, 1400))


def _window(page, how: str) -> None:
    """Visible Chrome: 'normal' shows the tab's window, 'minimized' puts it in the taskbar. Exploring shows ONE window -
    the visitor's or the logged-in one, whichever visits the page now (Nov 3, 2026: two windows side by side were hard
    to follow). The minimized one keeps its session; only how it looks changes."""
    if settings.headless:
        return
    try:
        cdp = page.context.new_cdp_session(page)
        win = cdp.send("Browser.getWindowForTarget")["windowId"]
        cdp.send("Browser.setWindowBounds", {"windowId": win, "bounds": {"windowState": how}})
        cdp.detach()
    except Exception:
        pass  # (only how it looks: never a reason to stop exploring)


RAISE_FLAGS = 0x0001 | 0x0002 | 0x0010  # SetWindowPos: keep its size and place, never take the keyboard
FIT_FLAGS = 0x0010 | 0x0040  # SetWindowPos: resize/move, show, never take the keyboard


def _to_front(page) -> None:
    """Visible Chrome on Windows: a window opened by a program running in the background opens BEHIND the open windows
    (Nov 3, 2026: "nothing was showing" - it was behind VS Code, later minimized). Raised above them once, without
    taking the keyboard from what you type in. Found by a unique title the page gets for a moment.
    (The same as _to_front in templates/conftest.py.)"""
    import os
    if settings.headless or os.name != "nt":
        return
    import ctypes
    import uuid
    from ctypes import wintypes
    mark = f"agentic-qa-{uuid.uuid4().hex[:10]}"
    try:
        old = page.evaluate("t => { const o = document.title; document.title = t; return o; }", mark)
    except Exception:
        return
    try:
        user32, found = ctypes.WinDLL("user32"), []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def each(hwnd, _):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if mark in buf.value:
                    found.append(hwnd)
            return True
        for _ in range(15):  # (the window's title follows the page's within a moment)
            user32.EnumWindows(each, 0)
            if found:
                break
            time.sleep(0.1)
        if found:
            if user32.IsIconic(found[0]):
                user32.ShowWindow(found[0], 4)  # minimized -> shown again, without taking the keyboard
            work = wintypes.RECT()
            user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work), 0)  # usable desktop, excluding taskbar
            w, h = work.right - work.left, work.bottom - work.top
            user32.SetWindowPos(found[0], -1, work.left, work.top, w, h, FIT_FLAGS)
            user32.SetWindowPos(found[0], -2, work.left, work.top, w, h, FIT_FLAGS)
    except Exception:
        pass  # (only how it looks)
    finally:
        try:
            page.evaluate("t => { document.title = t; }", old)
        except Exception:
            pass


@contextmanager
def _browser_session(app_map: list):
    """The crawl's Playwright session. A stop (Ctrl+C reaches the browser driver too, which then closes) must not
    lose the pages found so far: while the run is stopping - or when our browser went away somewhere the crawl could
    not open a new one - a browser error ends the crawl instead of the agent (the tests still run on what was found)."""
    try:
        with sync_playwright() as pw:
            yield pw
    except Exception as e:
        if not runctl.stopping() and not _gone(e):
            raise
        print(f"  [discovery] the browser closed {'while stopping' if runctl.stopping() else 'during exploring'} "
              f"({str(e).splitlines()[0][:100]}) - keeping the {len(app_map)} page(s) found so far", flush=True)


def discovery_agent(state: QAState) -> QAState:
    start_url = _normalize(state["url"])
    run_dir = Path(state["run_dir"])
    shots = run_dir / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    base_host = urlparse(start_url).hostname
    start_scheme = urlparse(start_url).scheme + ":"
    scope = Scope(start_url, settings.allowed_hosts)  # approved hosts; private / metadata addresses are blocked
    mode, section = _mode(start_url)
    start_auth = _auth_link(start_url)  # the link you gave is a login / sign-up page: the whole app behind it
    max_pages = settings.max_pages or settings.hard_page_cap
    limit = min(max_pages, settings.hard_page_cap)
    # the chat shows this line to the user (frontend/chat.js looks for "[discovery] scope:")
    print("  [discovery] scope: " + {
        "site": f"Entire website – I'll test every page of {base_host} (up to {limit} pages).",
        "section": (f"Limited pages – I'll test the app behind this login page under {section or '/'} on {base_host} "
                    f"(up to {limit} pages)." if _auth_link(start_url) else
                    f"Limited pages – I'll test the pages under {section}/ on {base_host}, plus the pages its own "
                    f"content links to (not the site-wide menu) - up to {limit} pages."),
        "page": "Specific page – I'll test only this page, and check that every link on it works.",
    }[mode], flush=True)

    # (url, depth, inside the address you gave?, logged in?) - pages behind a login are visited in a 2nd,
    # logged-in browser session, so the public pages (login, register) are still seen as a visitor sees them
    queue = _Frontier((start_url, 0, True, False))  # (logged-in pages always first)
    seen = {(start_url, False)}
    crawl_started, time_limited, stopped = time.time(), False, ""
    from ..scheduling import discovery_minutes
    crawl_budget_min = discovery_minutes(settings)
    # a test account is known: logging in is the first job (the "Sign in" link is opened before anything else)
    has_account = False if settings.discovery_only or not settings.login_enabled else (
        bool(settings.test_username and settings.test_password) or bool(
            load_account(state.get("site_key") or "") if settings.use_saved_account else None) or settings.auto_register)
    if settings.login_url:  # the login page you named (LOGIN_URL): visited right after the start page
        named = _normalize(settings.login_url)
        if scope.in_scope(named) and (named, False) not in seen:
            seen.add((named, False))
            queue.append((named, 1, True, False))
    app_map, issues = [], []
    used_slugs = set()
    not_app = 0  # pages outside the address that turned out to be a different site
    MAX_NOT_APP = 10  # after this many, stop checking outside links (keeps the crawl quick)
    # learns what each control does (observe -> act -> verify -> expand); shared controls are learned once
    def created(what: str, tag: str, where: str) -> None:  # (a form exploring SENT - staging: for the cleanup)
        with (run_dir / "created.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"what": what, "tag": tag, "where": where, "status": "created", "time": time.time(),
                                 "by": "exploring"}) + "\n")
    explorer = Explorer(EXTRACT_JS, _settle, crawl_started + crawl_budget_min * 60,
                        tag_base=re.sub(r"\D", "", run_dir.name)[-6:] or "run", on_created=created)
    # the AI looks at each page's screenshot while the crawl goes on (2 at a time): what it saw is tried too
    from concurrent.futures import ThreadPoolExecutor

    from .. import vision
    look_pool, looks = ThreadPoolExecutor(max_workers=2), {}
    reread: set = set()  # (url, logged in?) pages read again because an action changed them (the cart got an item)
    login = {"found": False, "logged_in": False, "page": "", "note": "", "outcome": "not_required",
             "evidence": [], "required": False}
    landed: set = set()  # (address the browser ended up on, logged in?) - to spot addresses that only redirect
    # route coverage: what was NOT visited and why (shown in the report - nothing is skipped silently)
    blocked: list = []  # requests stopped by the safety rules
    skipped: dict = {}  # url -> reason
    routes = {"redirected_out": [], "session_expired": [], "external": set(), "needs_permission": [], "sampled": 0,
              "needs_login": []}  # (needs_login: a visitor was sent to the login page - not tested without an account)
    patterns: dict = {}  # address pattern -> how many pages of it are queued
    searched: set = set()  # search forms whose results page is queued (one search each)
    session = {"form": None, "user": "", "password": "", "landing": "", "relogins": 0}  # in memory only
    found_by: dict = {}  # address -> how it was found: link / sitemap / network / history / search / button
    pace = _Pace(settings.max_requests_per_sec, active=not scope.local)
    explorer.before_goto = pace.wait
    # page DESIGNS: (folder, design) -> pages of it visited; a folder whose pages share one design is ONE page type -
    # more of its pages are smoke-checked, not fully tested again (/products/red-leather-bag, /products/blue-scarf ...)
    designs: dict = {}
    typed: dict = {}  # folder -> its design (once PATTERN_SAMPLES pages showed it)
    counted: set = set()  # the addresses counted as one more page of a known design (once: as a visitor or logged in)

    with _browser_session(app_map) as pw:
        browser = pw.chromium.launch(headless=settings.headless, slow_mo=watched_slow_mo_ms(),
                                     args=fit_window_args())  # (visible: the whole window on the screen)

        def new_context(state=None):
            c = browser.new_context(viewport={"width": 1366, "height": 900}, ignore_https_errors=True,
                                    accept_downloads=False, storage_state=state)  # no uncontrolled downloads
            guard_context(c, scope, blocked)
            c.add_init_script(DIALOG_INIT_JS)  # what the website says in the browser's alert boxes is written down
            c.add_init_script(HISTORY_INIT_JS)  # (addresses a single-page app moves to without a link)
            return c

        contexts = {False: new_context()}
        # more ways to find pages: the website's own sitemap (robots.txt / sitemap.xml) - queued from the start page
        extra_found = []
        if mode != "page":
            extra_found = [(u, "sitemap") for u in _sitemap_urls(contexts[False], start_url)]
            if extra_found:
                print(f"  [discovery] the sitemap lists {len(extra_found)} address(es)", flush=True)

        # ONE tab per session for the whole crawl: it moves from page to page instead of opening/closing tabs.
        # `current` holds the error lists of the page being visited right now.
        current = {"console": [], "failed": [], "docs": []}

        def watch(tab):  # (requests the safety rules blocked are ours, not the website's errors - and a download the
            # browser itself cancelled (a video player switching quality, leaving the page: ERR_ABORTED) is no error)
            tab.on("console", lambda m: current["console"].append(m.text[:300])
                   if m.type == "error" and "ERR_BLOCKED_BY_CLIENT" not in m.text and not _foreign_load_error(m, scope)
                   and not blocked_tracker_said(m.text) else None)  # (a tracker WE stopped: not the website's error)
            tab.on("pageerror", lambda e: None if blocked_tracker_said(str(e))
                   else current["console"].append(f"JS exception: {str(e)[:300]}"))
            tab.on("requestfailed", lambda r: current["failed"].append(
                {"url": r.url[:200], "error": (r.failure or "failed")[:100]})
                if not re.search(r"ERR_BLOCKED_BY_CLIENT|ERR_ABORTED|NS_BINDING_ABORTED", r.failure or "") else None)
            tab.on("response", lambda r: current["failed"].append(
                {"url": r.url[:200], "error": f"HTTP {r.status}"}) if r.status >= 400 else None)
            # HTML pages the page itself loads (a script that opens a page, a redirect chain): more pages to visit -
            # not an iframe's own document (its controls belong to the page that shows it)
            def on_doc(r):
                try:
                    if r.resource_type == "document" and r.frame.parent_frame is None and len(current["docs"]) < 50:
                        current["docs"].append(r.url)
                except Exception:
                    pass  # (a service worker's request has no frame)
            tab.on("request", on_doc)
            return tab

        tabs = {False: watch(contexts[False].new_page())}
        # how much of the website's own JavaScript the run uses (Chromium; staging / a site on this PC by default)
        from .. import jscov
        cov_on = jscov.enabled(scope.local)
        cov = {False: jscov.start(tabs[False]) if cov_on else None}
        saved_login = {"state": None}  # the login (cookies + storage) right after signing in: a new browser keeps it
        reopened = {"n": 0}
        cancelled: set = set()  # (address, logged in) whose load the browser cancelled once (tried again)
        late = {"login": None, "signup": ""}  # the login page waiting for a sign-up page found later; that page
        # the session whose window you see (visible Chrome: the other one is minimized). (Not 'shown': the crawl
        # uses that name further down - cms.demo.katalon.com, Nov 3, 2026: it overwrote this and the run crashed.)
        in_front = {"auth": None}

        def show(auth) -> None:  # (also while hidden - the tests run this; only the window calls do nothing then)
            if in_front["auth"] == auth:
                return
            _window(tabs[auth], "normal")
            for k, t in tabs.items():
                if k != auth and not t.is_closed():
                    _window(t, "minimized")
            _to_front(tabs[auth])  # (in front of the other programs' windows too)
            in_front["auth"] = auth

        def reopen() -> bool:
            """Our browser went away - its window was closed by hand, or Chrome stopped (demowebshop.tricentis.com,
            Nov 3: the whole run was lost on page 91). A new one, with the saved login, and the crawl goes on: at most
            MAX_REOPEN times. False = it keeps going away (exploring then ends with the pages found)."""
            nonlocal browser
            if reopened["n"] >= MAX_REOPEN:
                return False
            reopened["n"] += 1
            try:
                browser.close()
            except Exception:
                pass
            browser = pw.chromium.launch(headless=settings.headless, slow_mo=watched_slow_mo_ms(),
                                         args=fit_window_args())
            for k in list(contexts):
                contexts[k] = new_context(saved_login["state"] if k else None)
                tabs[k] = watch(contexts[k].new_page())
                cov[k] = jscov.start(tabs[k]) if cov_on else None
            in_front["auth"] = None  # (new windows: the next page shows its own and minimizes the other)
            print("  [discovery] the browser was closed (its window, or Chrome stopped) - opened a new one"
                  + (" with the saved login" if saved_login["state"] else "") + " and going on", flush=True)
            return True

        while queue and len(app_map) < limit:
            if time.time() - crawl_started > crawl_budget_min * 60:
                time_limited = True
                print(f"  [discovery] stopped at the reserved crawl budget ({crawl_budget_min:g} min) - "
                      f"{len(queue)} pages not visited", flush=True)
                break
            if runctl.stopping():  # (the pages found so far are kept: the report is written with them)
                stopped = runctl.reason()
                print(f"  [discovery] stopped ({stopped}) - {len(queue)} pages not visited", flush=True)
                break
            url, depth, inside, auth = queue.popleft()
            if not inside and not_app >= MAX_NOT_APP:
                continue
            folder = _parent_path(url)
            if settings.pattern_samples > 0 and folder in typed and depth > 0 \
                    and (url, auth) not in reread and not _pattern(url, auth):
                # queued before its folder's design was known (the sitemap lists every product at once): a sample
                kind = f"{folder}/* (one design)"
                kinds = routes.setdefault("item_types", {}).setdefault(kind, {"found": settings.pattern_samples,
                                                                               "sampled": settings.pattern_samples,
                                                                               "smoke": []})
                if url not in counted:
                    counted.add(url)
                    kinds["found"] += 1
                    routes["sampled"] += 1
                    if len(kinds["smoke"]) < 10:
                        kinds["smoke"].append(url)
                skipped.setdefault(url, f"the same page design as {settings.pattern_samples} tested pages of "
                                        f"{folder}/ - a sample was tested")
                continue
            again = next((n for n, p in enumerate(app_map) if p["url"] == url and p["auth"] == auth), None) \
                if (url, auth) in reread else None
            if again is not None:  # read again after an action changed it: the new reading replaces the old one
                old = app_map.pop(again)
                landed.discard((url, auth))
                landed.discard((_normalize(old.get("final_url") or url), auth))
                landed.discard((_no_index(_normalize(old.get("final_url") or url)), auth))
                used_slugs.discard(old["slug"])
            if not browser.is_connected() and not reopen():  # (its window was closed, or Chrome stopped)
                queue.appendleft((url, depth, inside, auth))
                stopped = "the browser kept closing (its window was closed, or Chrome stopped)"
                break
            page, context = tabs[auth], contexts[auth]
            if page.is_closed():  # the site closed our tab (rare), or its window was closed -> open a new one
                try:
                    page = tabs[auth] = watch(context.new_page())
                except Exception as e:  # (the whole browser / session went with it)
                    if not _gone(e) or not reopen():
                        queue.appendleft((url, depth, inside, auth))
                        stopped = "the browser kept closing (its window was closed, or Chrome stopped)"
                        break
                    page, context = tabs[auth], contexts[auth]
            show(auth)
            console_errors, failed_requests = [], []
            current["console"], current["failed"], current["docs"] = console_errors, failed_requests, []

            slug = _slug(url)
            while slug in used_slugs:
                slug += "_x"
            used_slugs.add(slug)
            shot_path = shots / f"{len(app_map) + 1:02d}_{slug}.png"

            entry = {"url": url, "depth": depth, "slug": slug, "auth": auth,
                     "screenshot": shot_path.relative_to(run_dir).as_posix(),
                     "found_by": found_by.get(url, "start" if depth == 0 else "link")}
            t0 = time.time()
            try:
                pace.wait()  # (polite speed: MAX_REQUESTS_PER_SEC, slower after HTTP 429 / 503)
                try:
                    resp = page.goto(url, wait_until="domcontentloaded", timeout=settings.page_timeout_ms)
                except PageTimeout:  # a slow answer once (a busy demo server): one more try, with twice the time
                    print(f"      ↳ slow to open - trying once more with {2 * settings.page_timeout_ms // 1000} s",
                          flush=True)
                    resp = page.goto(url, wait_until="commit", timeout=2 * settings.page_timeout_ms)
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=2 * settings.page_timeout_ms)
                    except PageTimeout:
                        # the page shows, but a file the busy server never sends keeps it 'loading' (automationexercise
                        # .com: the whole run ended on its start page): a person uses it as it is - only a page with
                        # nothing on it did not open
                        if not _shows(page):
                            raise
                        entry["still_loading"] = True
                        print("      ↳ the page shows but never finished loading - testing it as it shows", flush=True)
                if resp is not None and resp.status in (429, 503) and pace.back_off(resp.status):
                    resp = page.goto(url, wait_until="domcontentloaded", timeout=settings.page_timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass  # some sites never go fully idle; that's fine
                if resp is None and "#" in url:  # single-page app: only the #/route changed, no new request
                    page.wait_for_timeout(1000)  # give the app a moment to show the new page
                closed = close_consent(page)  # a cookie banner over the page: closed with the least consent
                if closed and not routes.get("consent_closed"):
                    routes["consent_closed"] = closed
                    print(f"  [discovery] closed a cookie banner with '{closed}' (the least consent it offered)")
                entry["status"] = resp.status if resp else (200 if "#" in url else None)
                entry["load_time_ms"] = int((time.time() - t0) * 1000)
                entry["final_url"] = page.url
                # a redirect that left the approved scope: what the browser got there is not used
                why = scope.navigation_blocked(page.url)
                if why and not app_map and _same_site(urlparse(page.url).hostname, base_host):
                    # the website moved (example.com -> www.example.com): test it at its real address
                    base_host = urlparse(page.url).hostname
                    start_scheme = urlparse(page.url).scheme + ":"
                    scope.extra.append(base_host)
                    print(f"  [discovery] the website moved to {base_host} - testing it there", flush=True)
                    why = None
                if why:
                    raise _Blocked(why)
                if auth and session["form"] and looks_logged_out(page, session["form"]):
                    raise _SessionLost()
                final = _normalize(page.url)
                # e.g. /client opened the login page -> #/auth/login is the same page; /index.html is the same as /
                if (final, auth) in landed or (_no_index(final), auth) in landed:
                    raise _Duplicate()
                landed.update({(final, auth), (_no_index(final), auth), (url, auth)})
                entry["title"] = page.title()
                if not entry["title"].strip() and (entry.get("status") or 0) < 400 and page.evaluate(FRAGMENT_JS):
                    raise _Fragment()
                entry["lazy"] = autoscroll(page)  # content that only loads while you scroll down is read too
                entry.update(page.evaluate(EXTRACT_JS))
                from ..page_status import RENDER_EVIDENCE_JS, rendered_application
                if entry.get("status") == 404:
                    evidence = page.evaluate(RENDER_EVIDENCE_JS)
                    entry["render_evidence"] = evidence
                    entry["rendered_application"] = rendered_application(entry, evidence)
                    if entry["rendered_application"]:
                        print(f"  [discovery] HTTP 404 but a usable application rendered: {url}; continuing UI tests",
                              flush=True)
                # its design (+ whether it lists items): pages of one folder with one design are ONE page type
                entry["skeleton"] = hashlib.sha1(f"{entry.get('skeleton')}|{bool(entry.get('itemLinks'))}"
                                                 .encode(), usedforsecurity=False).hexdigest()[:10]
                folder = _parent_path(url)
                if folder and page_testable(entry):
                    designs[(folder, entry["skeleton"])] = designs.get((folder, entry["skeleton"]), 0) + 1
                    counted.add(url)  # (a sample: already one of the pages its kind counts)
                    if settings.pattern_samples > 0 \
                            and designs[(folder, entry["skeleton"])] >= settings.pattern_samples and folder not in typed:
                        typed[folder] = entry["skeleton"]
                        print(f"  [discovery] the pages of {folder}/ share one design: more of them are a sample "
                              "(smoke-checked, not explored again)", flush=True)
                # embedded frames: listed with their status; a same-site frame's controls belong to this page
                entry["frames"], inner = _frame_inventory(page, base_host)
                for group, items in inner.items():
                    entry.setdefault(group, []).extend(items)
                entry["unsupported"] = entry.get("unsupported", []) + [
                    dict(u, frame=" > ".join(fr["path"])) for fr in entry["frames"] for u in fr.pop("unsupported", [])]
                merge_snapshots(entry, [entry.pop("component_snapshot", {}), *entry.pop("component_snapshots", [])], phase="initial DOM")
                # phone width (390 x 844): the controls only a phone shows (a hamburger menu, mobile filters) and the
                # layout problems there (sideways scroll, controls cut off or covered)
                look_phone = None
                if settings.mobile_check and page_testable(entry):
                    try:
                        page.set_viewport_size({"width": 390, "height": 844})
                        page.wait_for_timeout(700)
                        phone = page.evaluate(EXTRACT_JS)
                        merge_snapshots(entry, [phone.get("component_snapshot", {})], phase="mobile viewport")
                        layout = page.evaluate(LAYOUT_JS)
                        if visual.enabled():  # its look at phone width, for the visual check (backend/visual.py)
                            phone_shot = shots / f"phone_{shot_path.name}"
                            page.screenshot(path=str(phone_shot))
                            look_phone = dict(page.evaluate(visual.VISUAL_JS),
                                              shot=phone_shot.relative_to(run_dir).as_posix())
                        desk = {x.get("selector") for x in entry.get("buttons", []) + entry.get("inputs", [])}
                        entry["mobile_only"] = [dict(b, mobile_only=True) for b in phone.get("buttons", [])
                                                if b.get("selector") and b["selector"] not in desk
                                                and action_risk(b.get("text"), b.get("selector")) == "safe"][:8]
                        entry["layout"] = layout
                    except Exception as e:
                        print(f"  [discovery] phone width could not be checked on {url}: {str(e).splitlines()[0][:100]}")
                    finally:
                        try:
                            page.set_viewport_size({"width": 1366, "height": 900})
                            page.wait_for_timeout(300)
                        except Exception:
                            pass
                if not inside and app_map and not _same_app(entry, app_map[0], base_host):
                    raise _NotTheApp()
                try:  # the page's HTML code, so the report can point at the exact line to change
                    html_dir = run_dir / "html"
                    html_dir.mkdir(exist_ok=True)
                    (html_dir / f"{slug}.html").write_text(page.content(), encoding="utf-8")
                except Exception:
                    pass
                page.screenshot(path=str(shot_path), full_page=True)
                if visual.enabled():  # its look at desktop width: compared with the approved look (backend/visual.py)
                    try:
                        look = dict(page.evaluate(visual.VISUAL_JS), shot=entry["screenshot"])
                        entry["visual"] = visual.save_capture(run_dir, slug, url, look, look_phone)
                    except Exception as e:
                        print(f"  [discovery] the look of {url} could not be recorded: {str(e).splitlines()[0][:100]}")
                if not settings.discovery_only and vision.can_look(entry) and len(looks) < vision.MAX_PAGES:
                    looks[slug] = look_pool.submit(vision.look_at_page, entry, run_dir)
            except _Duplicate:
                used_slugs.discard(slug)
                if not auth and _auth_link(page.url) and not _auth_link(url):  # a visitor sent to the login page
                    routes["needs_login"].append({"url": url, "to": page.url})
                    print(f"  [discovery] needs a test account (a visitor is sent to the login page): {url}")
                else:
                    print(f"  [discovery] same page as one already found (it redirects there): {url}")
                continue
            except _Fragment:
                used_slugs.discard(slug)
                skipped[url] = "a piece of a page that its script loads (no <head>, no title), not a page"
                continue
            except _NotTheApp:
                not_app += 1
                used_slugs.discard(slug)
                skipped[url] = "a different site on the same domain (not your app)"
                print(f"  [discovery] skipped (a different site, not your app): {url}  \"{entry.get('title', '')[:60]}\"")
                continue
            except _Blocked as e:
                used_slugs.discard(slug)
                routes["redirected_out"].append({"url": url, "to": page.url.split("?")[0][:200], "reason": str(e)})
                print(f"  [discovery] not tested: {url} sent the browser outside the approved scope - {e}")
                try:
                    page.goto("about:blank")
                except Exception:
                    pass
                continue
            except _SessionLost:
                used_slugs.discard(slug)
                alive = False  # is the login really gone? the page right after login must still open logged in
                try:
                    page.goto(session["landing"], wait_until="domcontentloaded", timeout=settings.page_timeout_ms)
                    _settle(page)
                    alive = not looks_logged_out(page, session["form"])
                except Exception:
                    pass
                if alive:  # only THIS page asks for a login (e.g. it needs another user role)
                    skipped[url] = "asks to log in again although the login is still active (needs another role?)"
                    continue
                if session["relogins"] < 2:
                    session["relogins"] += 1
                    new_tab, res = log_in(contexts[True], session["login_page"], session["form"], session["user"],
                                          session["password"], scope)
                    if res["logged_in"]:
                        old, tabs[True] = tabs[True], watch(new_tab)
                        old.close()
                        try:
                            saved_login["state"] = contexts[True].storage_state()
                        except Exception:
                            pass
                        routes["session_expired"].append({"url": url, "action": "logged in again"})
                        print(f"  [discovery] login: the session expired at {url} - logged in again", flush=True)
                        queue.appendleft((url, depth, inside, auth))
                        continue
                    new_tab.close()
                routes["session_expired"].append({"url": url, "action": "stopped testing the pages behind the login"})
                login["session_expired"] = True
                print(f"  [discovery] login: the session expired at {url} and logging in again did not work - "
                      "the remaining pages behind the login are not tested", flush=True)
                for item in [q for q in queue if q[3]]:
                    queue.remove(item)
                    skipped[item[0]] = "not visited: the login expired"
                continue
            except Exception as e:
                if _gone(e) and not runctl.stopping():  # our browser went away mid-page: never the website's error
                    used_slugs.discard(slug)
                    for u in {url, entry.get("final_url") or url}:  # (read it again - not 'a page already found')
                        for k in (u, _normalize(u), _no_index(_normalize(u))):
                            landed.discard((k, auth))
                    queue.appendleft((url, depth, inside, auth))
                    if reopen():
                        continue
                    stopped = "the browser kept closing (its window was closed, or Chrome stopped)"
                    break
                if CANCELLED.search(str(e)) and (url, auth) not in cancelled and not runctl.stopping():
                    # the browser cancelled the load: the website was still moving (practicesoftwaretesting.com,
                    # Nov 3, 2026: right after the login, /account - where the login had just landed - got
                    # net::ERR_ABORTED and the whole account area was never explored). Once more, after it settles.
                    cancelled.add((url, auth))
                    used_slugs.discard(slug)
                    for k in (url, _normalize(url), _no_index(_normalize(url))):
                        landed.discard((k, auth))
                    try:
                        page.wait_for_load_state("networkidle", timeout=5000)
                    except Exception:
                        pass
                    print("      ↳ the browser cancelled the page load (the website was still moving) - once more",
                          flush=True)
                    queue.appendleft((url, depth, inside, auth))
                    continue
                if "ERR_BLOCKED_BY_CLIENT" in str(e):  # the safety rules stopped where this address leads
                    used_slugs.discard(slug)
                    reason = next((b["reason"] for b in reversed(blocked)), "blocked by the safety rules")
                    routes["redirected_out"].append({"url": url, "to": "", "reason": reason})
                    print(f"  [discovery] not tested: {url} leads outside the approved scope - {reason}")
                    continue
                if not inside:  # a page outside your app that doesn't open is not your app's problem
                    used_slugs.discard(slug)
                    continue
                if "Download is starting" in str(e):  # the address is a file the browser downloads ('.txt', '.csv'
                    used_slugs.discard(slug)          # without a known ending): no page - and no broken one
                    skipped[url] = "a file (download, picture, document), not a page"
                    continue
                entry["status"] = None
                entry["error"] = str(e).split("\n")[0][:300]
                try:
                    page.screenshot(path=str(shot_path))
                except Exception:
                    entry["screenshot"] = None

            if not auth:  # a visitor: the site asking "who is logged in?" gets 401 - normal, not the website's error
                console_errors[:] = [c for c in console_errors if not VISITOR_401.search(c)]
                failed_requests[:] = [f for f in failed_requests if f["error"] != "HTTP 401"]
            if entry.get("status") in (401, 403):  # the page itself may not be opened by this account: that is
                # "needs other permissions" (below) - its own 401 / 403 is not ALSO a console error / failed request
                own = {_normalize(url), _normalize(entry.get("final_url") or url)}
                failed_requests[:] = [f for f in failed_requests
                                      if not (f["error"] in ("HTTP 401", "HTTP 403") and _normalize(f["url"]) in own)]
                console_errors[:] = [c for c in console_errors if not re.search(r"status of 40[13]\b", c)]
            entry["console_errors"] = console_errors
            entry["failed_requests"] = failed_requests[:20]

            # Record problems found while just looking at the page. 401 / 403 = this account may not open it
            # (another role / a login is needed) - recorded as "needs other permissions", not as a broken page.
            if entry.get("status") in (401, 403):
                entry["needs_permission"] = True
                routes["needs_permission"].append({"url": url, "status": entry["status"], "logged_in": auth})
                print(f"  [discovery] needs other permissions (HTTP {entry['status']}): {url}", flush=True)
            elif entry.get("rendered_application"):
                issues.append({"type": "http_status", "url": url, "page": slug,
                               "detail": "HTTP 404 on a rendered application route. UI exploration continued; "
                                         "the server/deep-link response still needs review.",
                               "screenshot": entry["screenshot"]})
            elif entry.get("error") or (entry.get("status") or 0) >= 400:
                issues.append({"type": "page_failed", "url": url, "page": slug,
                               "detail": entry.get("error") or f"HTTP {entry['status']}",
                               "screenshot": entry["screenshot"]})
            for c in console_errors:
                issues.append({"type": "console_error", "url": url, "page": slug, "detail": c,
                               "screenshot": entry["screenshot"]})
            for f in failed_requests[:10]:
                issues.append({"type": "failed_request", "url": url, "page": slug,
                               "detail": f"{f['error']} → {f['url']}", "screenshot": entry["screenshot"]})
            for img in entry.get("brokenImages", []):
                issues.append({"type": "broken_image", "url": url, "page": slug, "detail": img,
                               "screenshot": entry["screenshot"]})
            for problem in entry.get("layout") or []:  # (at phone width - a finding, never a release blocker)
                issues.append({"type": "layout", "url": url, "page": slug,
                               "detail": f"{problem['kind']}: {problem['detail']}", "screenshot": entry["screenshot"]})

            # A login form: sign in with the test account and test the whole app behind it
            form = login_form(entry) if not auth and not login["found"] and not entry.get("error") else None
            if form and not settings.login_enabled:
                login.update(found=True, required=_login_page(entry, url, start_auth), outcome="public_only",
                             note="Public pages only was selected. Login and account creation were not attempted.")
                form = None
            if form and settings.discovery_only:
                login.update(found=True, outcome="not_attempted",
                             note="Discovery only: login was observed but not submitted. Protected pages need an authorized test run.")
                form = None
            if form:
                # the start page is (or redirected to) the login: the app can't be tested at all without logging in
                # the start page IS the login (the door to the whole app behind it) - not a page that merely shows a
                # login form among other things (a practice page with a demo login among its 38 boxes)
                door = depth == 0 and _login_page(entry, url, start_auth)
                login.update(found=True, page=url, required=door)
                # the login is the door to the whole app: test the app it belongs to - when the link you gave is (or
                # opened) that login. A login reached from a section (its header's "Sign in") keeps the section.
                if mode != "site" and door:
                    root = _app_root(entry.get("final_url") or url)
                    mode, section = ("section", root) if root else ("site", "")
                # the account: given (chat / .env) -> saved from an earlier run -> created now (only if allowed)
                site_key = state.get("site_key") or (base_host or "site")
                given = bool(settings.test_username and settings.test_password)
                tries = []
                if given:
                    tries.append(("given", {"username": settings.test_username, "password": settings.test_password}))
                elif settings.use_saved_account and load_account(site_key):
                    tries.append(("saved", load_account(site_key)))
                why_not = ""
                if True in contexts:  # (a second try - the sign-up page was found later: a fresh session)
                    cov.pop(True, None)
                    try:
                        contexts[True].close()
                    except Exception:
                        pass
                contexts[True] = new_context()
                if not settings.headless:  # (the login opens its own window: the visitor's waits minimized)
                    _window(tabs[False], "minimized")
                    in_front["auth"] = None
                tab, res, how, account = None, None, "", None
                if not tries and not settings.auto_register:
                    why_not = "creating a test account on the website was not allowed for this run"
                for _attempt in range(2):
                    if not tries and settings.auto_register and not given:
                        signup = _signup_url(entry, start_url) or _signup_url({"links": app_map[0].get("links", [])}
                                                                               if app_map else {}, start_url) \
                            or late["signup"]
                        if not signup:
                            why_not = "no sign-up page was found"
                            if not late["signup"]:  # (tried again when exploring finds it - see below)
                                late["login"] = (url, depth, inside)
                        else:
                            print(f"  [discovery] login: no test account - creating one on {signup} "
                                  "(you allowed this for this run)", flush=True)
                            made, why_not = _create_account(browser, signup)
                            if made:
                                tries.append(("created", made))
                    if not tries:
                        break
                    how, account = tries.pop(0)
                    name = _login_name(entry, form, account) if how != "given" else account["username"]
                    if tab is not None:
                        tab.close()
                    tab, res = log_in(contexts[True], url, form, name, account["password"], scope)
                    if res["outcome"] in ("mfa_required", "captcha") and not settings.headless and settings.human_wait_s:
                        # a person may complete the code / CAPTCHA in the visible window - the tester never does
                        what = "a CAPTCHA" if res["outcome"] == "captcha" else "a one-time code (2-step verification)"
                        print(f"  [discovery] login: the website asks for {what} - please complete it in the Chrome "
                              f"window (waiting up to {settings.human_wait_s} s)", flush=True)
                        _event("human", {"what": res["outcome"], "wait_s": settings.human_wait_s})
                        person = wait_for_person(tab, form, settings.human_wait_s)
                        _event("human", {"what": res["outcome"], "done": True, "ok": bool(person)})
                        if person:
                            res = dict(person, evidence=res["evidence"] + person["evidence"])
                    if res["logged_in"]:
                        account["username"] = name
                        break
                    if how != "saved":
                        break  # (a saved account that no longer works -> one more try with a new account)
                if tab is None:
                    tab = contexts[True].new_page()
                tabs[True] = watch(tab)
                outcome = res["outcome"] if res else "no_account"
                login.update(outcome=outcome, evidence=(res or {}).get("evidence", []))
                if res and res["logged_in"]:
                    _use_account(account)
                    session.update(form=form, user=account["username"], password=account["password"],
                                   landing=tab.url, login_page=url)
                    login["logged_in"] = True
                    login["account"] = {"username": account["username"], "how": how}
                    try:  # (a new browser - after its window was closed - starts with this login)
                        saved_login["state"] = contexts[True].storage_state()
                    except Exception:
                        pass
                    if how == "created":  # keep it (encrypted), so later runs log in with it instead of signing up
                        save_account(site_key, dict(account, site=base_host, created=time.strftime("%Y-%m-%d %H:%M")))
                    landing = _normalize(tab.url)
                    # don't crawl the login page again while logged in - the page it really is (a guest's 'My account'
                    # /account redirects to /login: /account itself is where the app begins after the login)
                    seen.add((_normalize(entry.get("final_url") or url), True))
                    if (landing, True) not in seen:  # depth starts again at 0: the app begins here
                        seen.add((landing, True))
                        queue.appendleft((landing, 0, True, True))
                    login["note"] = {
                        "given": "Logged in with the test account - the pages behind the login are tested too.",
                        "saved": f"Logged in with the test account I created earlier ({account['username']}) - "
                                 "the pages behind the login are tested too.",
                        "created": f"Logged in with a test account I created on the website's sign-up page "
                                   f"({account['username']}, saved encrypted in accounts/{site_key}.json) - the pages "
                                   "behind the login are tested too.",
                    }[how]
                elif how == "created" and outcome in ("failed", "invalid_credentials"):
                    login["note"] = ("I signed up with a new test account, but the website did not accept it at the "
                                     "login (the sign-up may not have completed, or the email must be confirmed first) - "
                                     "only the public pages were tested. Give a test account to test everything behind "
                                     "the login.")
                elif res:
                    login["note"] = NOTES[outcome]
                else:
                    login["note"] = ("This website has a login, but no test account was given"
                                     + (f" ({why_not})" if why_not else "") + " - only the public pages (login, "
                                     "register...) were tested. Give a test account to test everything behind the login.")
                if not login.get("logged_in"):  # no login: its empty window would stay open behind the website
                    cov.pop(True, None)          # (cms.demo.katalon.com, Nov 3, 2026) - closed; a later try opens one
                    tabs.pop(True, None)
                    try:
                        contexts.pop(True).close()
                    except Exception:
                        pass
                    in_front["auth"] = None
                print(f"  [discovery] login: {login['note']}", flush=True)
                if login["evidence"]:
                    print("  [discovery] login evidence: " + "; ".join(login["evidence"]), flush=True)

            # A test account is known but no login was found yet: open this page's "Sign in" / "Log in" /
            # "My account" links NEXT (before anything else), so the app behind the login is reached early
            if has_account and not auth and not login["found"] and not entry.get("error"):
                for l in entry.get("links", []):
                    href = _normalize(urljoin(url, (l.get("href") or "").strip()))
                    text = (l.get("text") or "").strip()
                    if urlparse(href).hostname == base_host and (SIGNIN_TEXT.search(text) or _auth_link(href)) \
                            and not SIGNUP_TEXT.search(text) and not SIGNUP_PATH.search(href + "/") \
                            and (href, False) not in seen and not _skip_reason(href):
                        seen.add((href, False))
                        queue.appendleft((href, depth + 1, True, False))

            # Queue new same-site links (specific page: none - its links are still checked by the link test)
            deep_enough = settings.max_depth and depth >= settings.max_depth
            for link in entry.get("links", []):  # (route coverage: why each same-site link is not opened)
                nxt = _normalize(urljoin(url, link["href"].strip()))
                if urlparse(nxt).scheme not in ("http", "https"):
                    continue
                if urlparse(nxt).hostname != base_host:
                    routes["external"].add(nxt.split("#")[0])
                    continue
                why = _skip_reason(nxt) or ("only this page was asked for" if mode == "page"
                                            else f"deeper than MAX_DEPTH={settings.max_depth}" if deep_enough else "")
                if why and (nxt, False) not in seen and (nxt, True) not in seen:
                    skipped.setdefault(nxt, why)
            if mode != "page" and not deep_enough:
                # outside the folder you gave, only what this page's own content links to (Step: stay in the section)
                widen = mode == "site" or start_auth or bool(login.get("required"))
                from_folder = _in_scope(entry.get("final_url") or url, section)

                def enqueue(href: str, chrome: bool = False, how: str = "link") -> bool:
                    """Queue a same-site address once; of many pages with one address pattern (/product/{id},
                    ?page=N, calendars) or one design (a folder of pages that look alike) only a sample. True =
                    queued. `how` = how it was found (link / sitemap / network / history / search / button)."""
                    nxt = _normalize(urljoin(url, href.strip()))
                    if urlparse(nxt).hostname == base_host:  # http:// and https:// are the same page
                        nxt = start_scheme + nxt.split(":", 1)[1]
                    if (nxt, auth) in seen or not _is_crawlable(nxt, base_host):
                        return False
                    # (the sitemap lists the WHOLE website: like the site-wide menu, it never leaves the section)
                    out = _leaves_section(nxt, section, widen, from_folder, chrome or how == "sitemap")
                    if out == MENU_OUTSIDE and how == "sitemap":
                        out = "listed in the sitemap, outside the section"
                    if out:  # (not "seen": the same address in another page's content may still be followed)
                        if (nxt, False) not in seen and (nxt, True) not in seen:
                            skipped.setdefault(nxt, out)
                        return False
                    seen.add((nxt, auth))
                    found_by.setdefault(nxt, how)
                    key = _pattern(nxt, auth)
                    folder = _parent_path(nxt)
                    if settings.pattern_samples > 0 and not key and folder in typed:
                        # a page of a folder whose pages share one design: its kind is
                        kind = f"{folder}/* (one design)"  # known - a sample is tested, the rest smoke-checked
                        kinds = routes.setdefault("item_types", {}).setdefault(kind, {"found": settings.pattern_samples,
                                                                                       "sampled": settings.pattern_samples,
                                                                                       "smoke": []})
                        if nxt not in counted:  # (the same address found as a visitor AND logged in: one page)
                            counted.add(nxt)
                            kinds["found"] += 1
                            routes["sampled"] += 1
                            if len(kinds["smoke"]) < 10:
                                kinds["smoke"].append(nxt)
                        skipped.setdefault(nxt, f"the same page design as {settings.pattern_samples} tested pages of "
                                                f"{folder}/ - a sample was tested")
                        return False
                    if key:
                        patterns[key] = patterns.get(key, 0) + 1
                        shown = key[1] + ("?" + "&".join(key[2]) if key[2] else "")
                        kinds = routes.setdefault("item_types", {}).setdefault(shown, {"found": 0, "sampled": 0,
                                                                                        "smoke": []})
                        kinds["found"] += 1
                        if settings.pattern_samples > 0 and patterns[key] > settings.pattern_samples:
                            routes["sampled"] += 1
                            if len(kinds["smoke"]) < 10:  # (up to 10 more of the same kind: smoke-checked by a test)
                                kinds["smoke"].append(nxt)
                            skipped.setdefault(nxt, f"more than {settings.pattern_samples} pages with the same "
                                                    f"address pattern ({shown}) - a sample was tested")
                            return False
                        kinds["sampled"] += 1
                    skipped.pop(nxt, None)
                    # (a page one step outside the section, reached from its content, is tested like the section)
                    item = (nxt, depth + 1, _in_scope(nxt, section) or not widen, auth)
                    # a page that probably shows something NEW first; more pages of a kind already seen (its address
                    # pattern, or its folder's design) later
                    known = (key and patterns.get(key, 0) > 1) or (folder and any(f == folder for f, _s in designs))
                    # a section of the site's own menu (found near the start): before every deeper page
                    menu = chrome and depth <= 2 and how == "link" and not known
                    (queue.append_menu if menu else queue.append_later if known else queue.append)(item)
                    return True

                # With full exploration, follow every listed item; otherwise visit representative examples.
                items = [l["href"] for l in (entry.get("itemLinks") or {}).get("links") or [] if l.get("href")]
                if settings.pattern_samples > 0 and len(items) >= 3:
                    odd = [h for h in (entry.get("itemLinks") or {}).get("odd") or [] if h in items][:1]
                    picked = list(dict.fromkeys([items[0], *odd, items[len(items) // 2], items[-1]]))
                else:
                    picked = list(dict.fromkeys(items))
                for href in picked:
                    enqueue(href)
                for link in entry.get("links", []):
                    enqueue(link["href"], bool(link.get("chrome")))
                # more ways to find pages: the sitemap (once, from the start page), the HTML pages this page loaded
                # by itself, and the addresses a single-page app moved to (history API)
                while extra_found:
                    u, how = extra_found.pop(0)
                    enqueue(u, how=how)
                for u in current["docs"]:
                    if _normalize(u) != url:
                        enqueue(u, how="network")
                try:
                    routes_seen = page.evaluate("() => window.__qaRoutes || []")
                except Exception:
                    routes_seen = []
                for u in routes_seen[:30]:
                    if _normalize(u) != url:
                        enqueue(u, how="history")
                # the results page of the website's search box (a search with a word of its items - safe, read only;
                # once per search form: the header's is on every page)
                names = [l.get("text") or "" for p in app_map + [entry] for l in (p.get("itemLinks") or {}).get("links") or []]
                found = _search_url(entry, url, _probe_word(names))
                if found and not widen and not _in_scope(_normalize(urljoin(url, found)), section):
                    skipped.setdefault(_normalize(urljoin(url, found)),  # (the header's search box: the whole site)
                                       "the site-wide search's results page, outside the section")
                    found = None
                if found and found.split("?")[0] not in searched and enqueue(found, how="search"):
                    searched.add(found.split("?")[0])
                    print(f"  [discovery] the search box leads to its results page: {_normalize(found)}")
                # learn what every control does, one action at a time: pages only a button (or an action, e.g.
                # 'Add to cart' -> the cart link) leads to are queued, controls revealed by an action are added,
                # and a page an action changed (the menu says 'Cart (1)' now) is read again.
                # (errors caused by these actions don't count for this page - its own tests check them)
                if inside and not entry.get("error"):
                    current["console"], current["failed"] = [], []
                    if slug in looks:  # (what the AI saw on this page: the explorer tries it too - waited for 15 s
                        try:       # at most: a slow answer is used for the report and the AI's tests, not here)
                            looks[slug].result(timeout=15)
                        except Exception:
                            pass
                    new, changed = explorer.explore(page, url, entry)
                    for nxt in explorer.fill_forms(page, url, entry):  # (filled like a person; sent only on staging)
                        if enqueue(nxt, how="form"):
                            print(f"  [discovery] a form that was sent leads to another page: {_normalize(nxt)}")
                    for done in entry.get("form_fills", []):
                        shown = [x for k in ("appeared", "turned_on", "turned_off") for x in done.get(k) or []]
                        shown += [x for c in done.get("choices") or [] for x in c.get("appeared", []) + c.get(
                            "turned_off", [])]
                        if shown:
                            print(f"  [discovery] filling '{done.get('name')}' changed the form: {', '.join(shown[:5])}")
                    for nxt in new:
                        if enqueue(nxt, how="button"):
                            print(f"  [discovery] an action revealed another page: {_normalize(nxt)}")
                    for nxt in changed:
                        nxt = _normalize(nxt)
                        done = next((p for p in app_map if p["url"] == nxt and p["auth"] == auth), None)
                        if done and (nxt, auth) not in reread:
                            reread.add((nxt, auth))
                            queue.appendleft((nxt, done["depth"], True, auth))
                            print(f"  [discovery] an action changed {nxt} - it is read again")
            if mode == "page" and inside and not entry.get("error"):
                # a specific page: what its controls do is learned too (the pages they lead to are listed, not opened)
                current["console"], current["failed"] = [], []
                new, _changed = explorer.explore(page, url, entry)
                for nxt in new:
                    if _normalize(nxt) != url:
                        skipped.setdefault(_normalize(nxt), "only this page was asked for (an action on it leads there)")

            # Keep every real link (same site AND external) so each one gets tested
            raw_links = entry.get("links", [])
            clean, seen_here = [], set()
            for l in raw_links:
                href = _normalize(urljoin(url, l["href"].strip()))
                if urlparse(href).scheme not in ("http", "https") or re.search(r"(javascript|mailto|tel):", href, re.I):
                    continue
                if l.get("toggle"):  # a tab / collapse link: a control of this page (tested as one), not a link
                    continue
                if href in seen_here:
                    continue
                seen_here.add(href)
                clean.append({"href": href, "text": l.get("text", ""), "visible": l.get("visible", True),
                              "external": urlparse(href).hostname != base_host,
                              **({"download": True} if l.get("download") else {}),
                              **({"chrome": True} if l.get("chrome") else {}),
                              **({"frame": l["frame"]} if l.get("frame") else {})})
            entry["links"] = clean[:400]
            entry["sections"] = _sections(raw_links, url, base_host)
            # inspect: what kind of page is it, which features does it really have (backend/features.py)
            entry["features"], entry["page_type"] = [], "error" if entry.get("error") else "content"
            if not entry.get("error") and not entry.get("needs_permission"):
                from ..features import page_features, page_type
                try:
                    entry["features"] = [f["kind"] for f in page_features(entry)]
                    entry["page_type"] = page_type(entry)
                except Exception as e:  # inspection must never stop the crawl
                    print(f"  [discovery] could not classify {url}: {str(e)[:120]}")
            if entry.get("error") and runctl.stopping():  # (cut off by the stop - not the website's fault: left out)
                print(f"  [discovery] {url} was cut off by the stop - not counted", flush=True)
                stopped = runctl.reason()
                queue.appendleft((url, depth, inside, auth))  # (counted as not visited)
                break
            app_map.append(entry)
            # the sign-up page is found only now (a 'Create new account' button in a login popup opens it): the account
            # step had given up at the start (advantageonlineshopping.com, Nov 3, 2026: "no sign-up page was found" -
            # its #/register was found later, so nothing behind the login was tested). Sign up and log in now: the
            # login page is read again, with the sign-up page known.
            if late["login"] and not auth and not entry.get("error") and not login.get("logged_in") \
                    and _signup_url({}, url) == url:
                at, at_depth, at_inside = late["login"]
                late.update(login=None, signup=url)
                login["found"] = False
                reread.add((at, False))
                queue.appendleft((at, at_depth, at_inside, False))
                print(f"  [discovery] login: the sign-up page was found now ({url}) - creating the test account and "
                      "logging in from the login page again", flush=True)
            learned = [b for b in entry.get("behaviour", []) if b.get("effect") not in ("error", None)]
            print(f"  [discovery] page {len(app_map)}: {entry.get('status')}  {url}"
                  + ("  (logged in)" if auth else "")
                  + (f"  - learned what {len(learned)} control(s) do" if learned else ""))
            _event("page", {"n": len(app_map), "url": url, "title": (entry.get("title") or "")[:80], "auth": auth,
                            "status": entry.get("status"), "type": entry["page_type"], "ms": entry.get("load_time_ms"),
                            "buttons": len(entry.get("buttons", [])), "inputs": len(entry.get("inputs", [])),
                            "forms": len(entry.get("forms", [])), "links": len(entry.get("links", [])),
                            "learned": len(learned), "revealed": sum(1 for x in entry.get("buttons", []) + entry.get(
                                "inputs", []) if x.get("revealed_by")),
                            "features": entry["features"], "errors": len(console_errors),
                            "needs_permission": bool(entry.get("needs_permission")), "failed": bool(entry.get("error")),
                            "screenshot": entry.get("screenshot"), "queue": len(queue)})
            if entry.get("error"):
                print(f"      ↳ could not open page: {entry['error']}")
            if cov_on:  # (the JavaScript this page ran - taken before the tab moves on to the next page)
                if cov.get(auth) is None:
                    cov[auth] = jscov.start(tabs[auth])
                else:
                    jscov.append(run_dir, "crawl", jscov.take(cov[auth]))

        if login["logged_in"]:  # the tests reuse this login (cookies + local storage), so they don't log in each time
            try:  # (kept in runs/<run>/.private/: never served by the web UI, deleted when the run ends)
                (run_dir / PRIVATE).mkdir(exist_ok=True)
                contexts[True].storage_state(path=str(run_dir / PRIVATE / "auth.json"))
            except Exception as e:
                print(f"  [discovery] could not save the login for the tests: {str(e)[:150]}")
            # several user roles: what each other role may open (its access is tested - a lower role must be refused)
            if not settings.headless:  # (each other role opens its own window: the run's windows wait minimized)
                for t in tabs.values():
                    _window(t, "minimized")
            try:
                role_map = _explore_roles(new_context, session, app_map, run_dir) if not runctl.stopping() else {}
            except Exception as e:
                role_map = {}
                print(f"  [discovery] the other roles could not be explored: {str(e).splitlines()[0][:150]}")
            if role_map:
                (run_dir / "roles.json").write_text(json.dumps(role_map, indent=2), encoding="utf-8")
        browser.close()

    # Header/footer buttons appear on every page: mark where each button is seen FIRST,
    # so it is click-tested once, not on every page.
    seen_buttons = set()
    for p in app_map:
        for b in p.get("buttons", []):
            key = (b.get("text"), b.get("selector"))
            b["first_seen"] = key not in seen_buttons
            seen_buttons.add(key)

    # route coverage: visited / not visited because of the limit / skipped on purpose / blocked by the safety rules
    pending = [u for u, _d, _i, _a in queue]
    ok = [p for p in app_map if page_testable(p)]
    crawl = {
        "start_url": start_url, "approved_hosts": list(dict.fromkeys([base_host] + scope.extra)),
        "mode": mode, "section": section, "limit": limit, "max_depth": settings.max_depth,
        "limit_reached": bool(pending), "visited": len(app_map), "visited_ok": len(ok),
        "visited_failed": len(app_map) - len(ok), "logged_in_pages": sum(1 for p in app_map if p.get("auth")),
        "not_visited_count": len(pending), "not_visited": pending[:300],
        "login_blocked": bool(login.get("found") and not login.get("logged_in")),
        "auth_outcome": login.get("outcome"),
        "skipped_count": len(skipped), "skipped": [{"url": u, "reason": r} for u, r in list(skipped.items())[:300]],
        "redirected_out": routes["redirected_out"], "blocked_count": len(blocked), "blocked_requests": blocked[:100],
        "session_expired": routes["session_expired"], "external_links": len(routes["external"]),
        "needs_permission": routes["needs_permission"], "sampled": routes["sampled"],
        # every kind of item page (one address pattern / one design): how many found, fully tested, smoke-checked
        "item_types": {k: v for k, v in (routes.get("item_types") or {}).items() if v["found"] > 1},
        "found_by": dict(Counter(p.get("found_by") or "link" for p in app_map)),
        "page_designs": dict(typed),
        "throttled": pace.events,
        "needs_login": routes["needs_login"][:100],
        "consent_closed": routes.get("consent_closed", ""),
        "time_limit_reached": time_limited, "time_limit_min": crawl_budget_min, "stopped": stopped,
        "sections_not_reached": queue.menu_left()[:100],  # (menu sections the crawl never opened - limits)
        "still_loading": [p["url"] for p in app_map if p.get("still_loading")][:100],  # (tested as they showed)
        "max_interactions_per_page": settings.max_interactions_per_page,
        "actions": explorer.summary(),  # what was tried / learned / blocked / skipped (and why) while exploring
        "page_types": {t: sum(1 for p in app_map if p.get("page_type") == t) for t in
                       sorted({p.get("page_type") or "content" for p in app_map})},
    }
    from ..page_status import exploration_status
    crawl["exploration"] = exploration_status(crawl)
    look_pool.shutdown(wait=True)  # (the AI looks at the pages it has not seen yet: what a person can use there)
    if not settings.discovery_only:
        vision.look_at_pages(app_map, run_dir)
    (run_dir / "app_map.json").write_text(json.dumps(app_map, indent=2), encoding="utf-8")
    (run_dir / "login.json").write_text(json.dumps(login, indent=2), encoding="utf-8")
    (run_dir / "crawl.json").write_text(json.dumps(crawl, indent=2), encoding="utf-8")
    from .. import registry  # every page + feature with a stable id: discovered and inspected (nothing tested yet)
    reg = registry.build(app_map, crawl)
    registry.save(reg, run_dir)
    save_inventory(run_dir, app_map, reg)
    print(f"  [discovery] registry: {len(reg['pages'])} page pattern(s), {len(reg['features'])} feature(s) / "
          f"control(s), {len(reg['edges'])} link(s) between pages")
    if blocked:
        print(f"  [discovery] the safety rules blocked {len(blocked)} request(s) (private network / outside the scope)")
    log = state.get("log", []) + [
        f"Discovery: visited {len(app_map)} pages, found {len({(i['type'], i['detail']) for i in issues})} different "
        f"issue(s) while crawling, {len(issues)} times in all "
        + (f"(STOPPED AT THE PAGE LIMIT of {limit}; {len(pending)} more pages were found but not visited)."
           if pending else "(all reachable pages within the limits were visited).")
        + (f" {len(skipped)} link(s) were skipped on purpose (see the coverage section)." if skipped else "")
    ] + ([f"Login: {login['note']}"] if login["found"] else [])
    roles = json.loads((run_dir / "roles.json").read_text(encoding="utf-8")) if (run_dir / "roles.json").exists() else {}
    return {"app_map": app_map, "crawl_issues": issues, "log": log, "login": login, "crawl": crawl, "roles": roles}


DENIED_TEXT = re.compile(r"access denied|not authori[sz]ed|forbidden|no permission|not allowed|insufficient (rights|"
                         r"permissions?)|\b403\b", re.I)


def _role_name(username: str) -> str:
    return next((a["role"] for a in settings.test_accounts if a["username"] == username), "test account")


def _explore_roles(new_context, session: dict, app_map: list[dict], run_dir: Path) -> dict:
    """Several user roles (TEST_ACCOUNTS): every OTHER role signs in once (the login form the crawl found) and opens the
    pages behind the login -> what it may open (ok), what it is refused (denied: 401 / 403 / 'access denied'), sent
    to the login page (login) or away (redirected). Its login is saved for its tests (.private/, deleted after the run);
    its password is never saved or shown."""
    main = session.get("user")
    roles = [a for a in settings.test_accounts if a["username"] != main][:5]
    if not roles or not session.get("form") or not session.get("login_page"):
        return {}
    pages = [p for p in app_map if p.get("auth") and not p.get("error")][:60]
    for p in pages:  # (the main role opened them)
        p.setdefault("roles", {})[_role_name(main)] = "denied" if p.get("needs_permission") else "ok"
    out = {}
    for a in roles:
        ctx = new_context()
        try:
            tab, res = log_in(ctx, session["login_page"], session["form"], a["username"], a["password"])
            if not res["logged_in"]:
                out[a["role"]] = {"login": res["outcome"], "pages": {}}
                print(f"  [discovery] role '{a['role']}': could not sign in ({res['outcome']})", flush=True)
                continue
            safe = re.sub(r"[^A-Za-z0-9_-]", "_", a["role"])
            (run_dir / PRIVATE).mkdir(exist_ok=True)
            ctx.storage_state(path=str(run_dir / PRIVATE / f"auth_{safe}.json"))
            seen = {}
            for p in pages:
                try:
                    resp = tab.goto(p["url"], wait_until="domcontentloaded", timeout=settings.page_timeout_ms)
                    _settle(tab)
                    status = resp.status if resp else None
                    text = tab.locator("body").inner_text(timeout=5000)[:4000]
                    if status in (401, 403) or DENIED_TEXT.search(text):
                        access = "denied"
                    elif _auth_link(tab.url) or looks_logged_out(tab, session["form"]):
                        access = "login"
                    elif urlparse(tab.url).path.rstrip("/") != urlparse(p.get("final_url") or p["url"]).path.rstrip("/"):
                        access = "redirected"
                    else:
                        access = "ok"
                    seen[p["url"]] = {"access": access, "status": status, "to": "" if access == "ok" else tab.url}
                    p.setdefault("roles", {})[a["role"]] = access
                except Exception as e:
                    seen[p["url"]] = {"access": "error", "error": str(e).splitlines()[0][:120]}
            out[a["role"]] = {"login": "success", "state": f"auth_{safe}.json", "pages": seen}
            n_ok = sum(1 for v in seen.values() if v["access"] == "ok")
            print(f"  [discovery] role '{a['role']}': may open {n_ok} of {len(seen)} page(s) behind the login", flush=True)
        except Exception as e:
            out[a["role"]] = {"login": "error", "error": str(e).splitlines()[0][:120], "pages": {}}
        finally:
            try:
                ctx.close()
            except Exception:
                pass
    return {"main": _role_name(main), "roles": out}


def restore_login(state: QAState) -> str:
    """`main.py --resume`: the saved login (.private/auth.json) was deleted when the first part of the run ended.
    Sign in once more with the same test account, so the tests still start logged in. Returns a note for the log."""
    login, run_dir = state.get("login") or {}, Path(state["run_dir"])
    if not login.get("logged_in") or (run_dir / PRIVATE / "auth.json").exists():
        return ""
    entry = next((p for p in state.get("app_map", []) if p["url"] == login.get("page")), None)
    form = login_form(entry) if entry else None
    given = bool(settings.test_username and settings.test_password)
    account = ({"username": settings.test_username, "password": settings.test_password} if given
               else load_account(state.get("site_key") or ""))
    if not form or not account:
        return "Resume: could not sign in again (no login form or test account) - the tests start logged out."
    if not given:
        _use_account(account)
    scope = Scope(_normalize(state["url"]), settings.allowed_hosts)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 1366, "height": 900}, ignore_https_errors=True,
                                          accept_downloads=False)
            guard_context(context, scope, [])
            name = account["username"] if given else _login_name(entry, form, account)
            _tab, res = log_in(context, login["page"], form, name, account["password"], scope)
            if not res["logged_in"]:
                return f"Resume: signing in again did not work ({res['outcome']}) - the tests start logged out."
            (run_dir / PRIVATE).mkdir(exist_ok=True)
            context.storage_state(path=str(run_dir / PRIVATE / "auth.json"))
        finally:
            browser.close()
    return "Resume: signed in again with the test account (the saved login is deleted when the run ends)."
