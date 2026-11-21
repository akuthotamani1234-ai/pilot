"""Workers share a website.

Every safe page is given to a worker. The workers open their own pages at the
same time, then close. Payment and checkout links are never handed to a worker.
A long product list can still keep a short sample for the deeper crawl.
"""
import json
import re
from urllib.parse import unquote, urlsplit

_PAYMENT_PATH = re.compile(
    r"(?:^|/)(?:check-?outs?|payments?|place-?orders?|buy-now|paypal)"
    r"(?:\.[a-z0-9]+)?(?:/|$)",
    re.I,
)
_PAYMENT_HOST = re.compile(r"(?:^|\.)paypal\.com$", re.I)
# A one-script shop picks the page in the query: index.php?rt=checkout/cart is the cart.
_ROUTE_KEY = re.compile(
    r"^(?:rt|route|r|controller|ctrl|action|act|task|cmd|do|page|step|view|screen)$",
    re.I,
)
_PAY_STEP = re.compile(r"^(?:check-?outs?|payments?|place-?orders?|buy-now|paypal)$", re.I)
_CART_STEP = re.compile(r"^(?:cart|basket|bag|trolley)$", re.I)


def sample_limit(swarm_sample: int, pattern_samples: int) -> int:
    """How many pages of one kind to open. The swarm size wins when it is set."""
    if swarm_sample > 0:
        return swarm_sample
    return max(0, pattern_samples)


def _route_bits_are_payment(value: str) -> bool:
    """True when a route's pieces pick checkout or payment, and not the cart."""
    bits = [bit for bit in re.split(r"[/.]", unquote(value or "").replace("_", "-")) if bit]
    if not bits or not any(_PAY_STEP.fullmatch(bit) for bit in bits):
        return False
    cart = bool(_CART_STEP.fullmatch(bits[-1])) and any(
        re.fullmatch(r"check-?outs?", bit, re.I) for bit in bits[:-1])
    return not cart


def _query_route_is_payment(query: str) -> bool:
    """True when the query picks a checkout or payment step, and not the cart."""
    from urllib.parse import parse_qsl

    for key, value in parse_qsl(query or "", keep_blank_values=True):
        if _ROUTE_KEY.match(key) and _route_bits_are_payment(value):
            return True
    return False


def _fragment_route_is_payment(fragment: str) -> bool:
    """True when a single-page #/route or #!/route picks checkout, and not the cart.

    A normal #section anchor is not a page.
    """
    route = fragment or ""
    if route.startswith("!/"):
        route = route[1:]
    if not route.startswith("/"):
        return False
    return _route_bits_are_payment(route.split("?", 1)[0])


def is_payment_url(url: str) -> bool:
    """True when the address itself is a checkout or payment step."""
    parts = urlsplit(url or "")
    host = parts.hostname or ""
    if _PAYMENT_HOST.search(host):
        return True
    path = unquote(parts.path).replace("_", "-")
    if _PAYMENT_PATH.search(path):
        return True
    if _query_route_is_payment(parts.query):
        return True
    return _fragment_route_is_payment(parts.fragment)


_QUOTED = re.compile(r"""['"]([^'"]+)['"]""")


def _script_opens_payment(base: str, script: str) -> bool:
    """True when a javascript: address quotes a checkout or payment URL."""
    from urllib.parse import urljoin

    for quoted in _QUOTED.findall(script or ""):
        text = quoted.strip()
        if not text or text.startswith("#") or text.lower().startswith("javascript:"):
            continue
        if is_payment_url(urljoin(base, text)):
            return True
    return False


def control_opens_payment(page_url: str, href: str = "", form_action: str = "", onclick: str = "") -> bool:
    """True when the control's address is checkout or payment, whatever its label says."""
    from urllib.parse import urljoin

    base = page_url or ""
    for raw in (href or "", form_action or ""):
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        if text.lower().startswith("javascript:"):
            if _script_opens_payment(base, text):
                return True
            continue
        if is_payment_url(urljoin(base, text)):
            return True
    return _script_opens_payment(base, onclick or "")


def stored_control_opens_payment(page_url: str, control: dict | None) -> bool:
    """True when a saved button, link, or form opens checkout or payment."""
    item = control or {}
    return control_opens_payment(
        page_url,
        str(item.get("href") or item.get("to") or ""),
        str(item.get("form_action") or item.get("formaction") or item.get("action") or ""),
        str(item.get("onclick") or ""),
    )


def choose_listing(urls: list[str], sample_size: int) -> tuple[list[str], list[tuple[str, str]]]:
    """Pick the first products a shopper sees. Leave the rest of that list.

    Returns (chosen, skipped). Skipped items are (url, reason). Checkout and
    payment addresses are skipped even when they sit at the top of the list.
    """
    chosen: list[str] = []
    skipped: list[tuple[str, str]] = []
    seen: set[str] = set()
    products: list[str] = []
    for raw in urls:
        url = (raw or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        if is_payment_url(url):
            skipped.append((url, "checkout, payment and placing an order are never tested"))
            continue
        products.append(url)
    if sample_size <= 0 or len(products) <= sample_size:
        return products, skipped
    chosen = products[:sample_size]
    reason = (f"swarm left this product; {sample_size} of {len(products)} "
              f"on this list were chosen")
    skipped.extend((url, reason) for url in products[sample_size:])
    return chosen, skipped


def assign_workers(urls: list[str], worker_count: int) -> list[dict]:
    """Give each chosen product its own worker, reusing workers only when there are fewer browsers."""
    if not urls:
        return []
    count = max(1, min(int(worker_count or 1), len(urls)))
    return [{"worker": (index % count) + 1, "url": url} for index, url in enumerate(urls)]


def partition_site(urls: list[str], worker_count: int, limit: int | None = None) -> list[dict]:
    """Give every safe page to a worker. Payment addresses are left out.

    Pages from different parts of the site are taken in turn, so a long product
    list does not crowd out the home page, account, or other sections.
    ``limit`` stops this pass at the crawl's page budget.
    """
    buckets: dict[str, list[str]] = {}
    order: list[str] = []
    seen: set[str] = set()
    for raw in urls:
        url = (raw or "").strip()
        if not url or url in seen or is_payment_url(url):
            continue
        seen.add(url)
        folder = urlsplit(url).path.strip("/").split("/", 1)[0]
        if folder not in buckets:
            buckets[folder] = []
            order.append(folder)
        buckets[folder].append(url)
    picked: list[str] = []
    cap = limit if limit and limit > 0 else None
    while order and (cap is None or len(picked) < cap):
        folder = order.pop(0)
        pages = buckets[folder]
        picked.append(pages.pop(0))
        if pages:
            order.append(folder)
    return assign_workers(picked, worker_count)


def landed_on_payment(found) -> bool:
    """True when a page that looked safe ended on checkout or payment."""
    if not isinstance(found, dict):
        return False
    if found.get("status") == "blocked":
        return True
    return is_payment_url(str(found.get("final_url") or ""))


def observed_page(found, url: str) -> bool:
    """A navigation observation belongs to the requested URL and has an HTTP response."""
    return (isinstance(found, dict) and found.get("url") == url
            and type(found.get("status")) is int and 100 <= found["status"] <= 599)


def _payment_block(url: str, final: str) -> dict:
    return {
        "url": url,
        "final_url": final,
        "status": "blocked",
        "summary": "checkout, payment and placing an order are never tested",
    }


def open_guarded(page, address: str, *, timeout: int = 20000):
    """Open one worker page. A checkout document, including after a redirect, is not loaded.

    A navigation the browser cancels is tried once more.
    """
    from .payment_nav import _CANCELLED, follow_get

    def once():
        try:
            current, landed = follow_get(page.request.get, address, timeout=timeout)
        except Exception:
            # The probe never ran. Do not open checkout, and abort a redirect into it.
            if is_payment_url(address):
                return None, _payment_block(address, address)
            from .payment_nav import open_falling_back
            _response, blocked_url = open_falling_back(page, address, timeout=timeout)
            final = blocked_url or str(getattr(page, "url", "") or "")
            if blocked_url or is_payment_url(final):
                return None, _payment_block(address, final or address)
            return _response, None
        if landed:
            return None, _payment_block(address, landed)
        response = page.goto(current, wait_until="domcontentloaded", timeout=timeout)
        final = page.url or current
        if is_payment_url(final):
            return None, _payment_block(address, final)
        return response, None

    try:
        return once()
    except Exception as exc:
        if not _CANCELLED.search(str(exc)):
            raise
        return once()


def perform(assignments: list[dict], open_page, *, on_status=None, session=None) -> list[dict]:
    """Each worker opens its own pages, then finishes. Workers run at the same time.

    ``session`` returns ``(open_page, close)`` for one worker's own browser.
    Without it, every worker uses the shared ``open_page``. A payment address
    is not opened.
    """
    from collections import defaultdict
    from concurrent.futures import ThreadPoolExecutor

    groups: dict[int, list[dict]] = defaultdict(list)
    order: list[int] = []
    for row in assignments:
        worker = int(row.get("worker") or 0)
        if worker not in groups:
            order.append(worker)
        groups[worker].append(row)

    def run_group(worker: int) -> list[dict]:
        own_open, close = session() if session else (open_page, lambda: None)
        done: list[dict] = []
        try:
            for row in groups[worker]:
                url = str(row.get("url") or "")
                if on_status:
                    on_status(worker, "opening", url)
                if not url or is_payment_url(url):
                    if on_status:
                        on_status(worker, "blocked", url)
                    done.append({**row, "status": "blocked"})
                    continue
                try:
                    found = own_open(url)
                except Exception:
                    if on_status:
                        on_status(worker, "stopped", url)
                    done.append({**row, "status": "stopped"})
                    continue
                if landed_on_payment(found):
                    final = str(found.get("final_url") or url) if isinstance(found, dict) else url
                    if on_status:
                        on_status(worker, "blocked", final)
                    done.append({**row, "status": "blocked", "work": found})
                    continue
                status = "opened" if observed_page(found, url) else "stopped"
                if on_status:
                    on_status(worker, status, url)
                done.append({**row, "status": status, "work": found})
            if on_status:
                on_status(worker, "finished", "")
        finally:
            close()
        return done

    if not assignments:
        return []
    with ThreadPoolExecutor(max_workers=max(1, len(order))) as pool:
        parts = list(pool.map(run_group, order))
    return [row for part in parts for row in part]


class WorkerBrowser:
    """One worker's browser. After a login is saved, later pages use that session."""

    def __init__(self, browser, login_state: dict):
        self.browser = browser
        self.login_state = login_state if isinstance(login_state, dict) else {}
        self.context = None
        self.authed = False

    def page(self):
        state = self.login_state.get("state")
        if self.context is None or (state and not self.authed):
            if self.context is not None:
                self.context.close()
            if state:
                self.context = self.browser.new_context(storage_state=state)
                self.authed = True
            else:
                self.context = self.browser.new_context()
                self.authed = False
        return self.context.new_page()

    def close(self) -> None:
        if self.context is None:
            return
        try:
            self.context.close()
        except Exception:
            pass
        self.context = None


class SiteSwarm:
    """Workers that stay up for the whole crawl.

    Pages are handed over as they are found, up to the run's page budget.
    Each worker opens its own pages. ``finish`` closes the browsers.
    """

    def __init__(self, worker_count: int, limit: int, session, on_status=None,
                 durable_queue=None, run_id: str = "", evidence_dir=None):
        import queue
        import threading

        self.worker_count = max(1, int(worker_count or 1))
        self.limit = max(0, int(limit or 0))
        self._session = session
        self._on_status = on_status
        self._durable_queue = durable_queue
        self._run_id = str(run_id or "")
        self._evidence_dir = evidence_dir
        self._seen: set[str] = set()
        self._lock = threading.Lock()
        self._queues = {n: queue.Queue() for n in range(1, self.worker_count + 1)}
        self.rows: list[dict] = []
        self.errors: list[dict] = []  # worker errors (a worker records them and goes on with its next page)
        self._closed = False
        self._threads = [
            threading.Thread(target=self._run, args=(n,), name=f"swarm-{n}", daemon=True)
            for n in range(1, self.worker_count + 1)
        ]
        for thread in self._threads:
            thread.start()

    def submit(self, urls: list[str]) -> list[dict]:
        """Give new safe pages to the workers. Payment addresses and repeats are skipped."""
        with self._lock:
            if self._closed:
                return []
            fresh = []
            for raw in urls:
                url = (raw or "").strip()
                if not url or url in self._seen or is_payment_url(url):
                    continue
                fresh.append(url)
            if not fresh:
                return []
            room = None if self.limit <= 0 else self.limit - len(self.rows)
            if room is not None and room <= 0:
                return []
            plan = partition_site(fresh, self.worker_count, room)
            for row in plan:
                row["worker"] = len(self.rows) % self.worker_count + 1
                if self._durable_queue is not None:
                    durable = self._durable_queue.enqueue(
                        run_id=self._run_id,
                        role="browser",
                        payload={
                            "url": row["url"],
                            "worker": row["worker"],
                            "source": "site_swarm",
                        },
                        idempotency_key=f"browser:{row['url']}",
                    )
                    row["task_id"] = durable["task_id"]
                    row["durable_status"] = durable.get("status")
                self._seen.add(row["url"])
                self.rows.append(row)
                self._queues[row["worker"]].put(row["url"])
            return list(plan)

    def _run(self, worker: int) -> None:
        session = {"open": None, "close": None}
        if self._durable_queue is None:
            session["open"], session["close"] = self._session()
        try:
            while True:
                url = self._queues[worker].get()
                if url is None:
                    if self._on_status:
                        self._on_status(worker, "finished", "")
                    return
                if self._on_status:
                    self._on_status(worker, "opening", url)
                try:
                    self._one(worker, url, session)
                except Exception as exc:  # a worker never dies silently: record it, release its task, go on
                    self._worker_error(worker, url, exc)
        finally:
            if session["close"] is not None:
                session["close"]()

    def _worker_error(self, worker: int, url: str, exc: Exception) -> None:
        detail = f"{type(exc).__name__}: {str(exc)[:300]}"
        durable_worker = f"browser-{self._run_id or 'run'}-{worker}"
        with self._lock:
            self.errors.append({"worker": worker, "url": url, "error": detail})
            row = next((c for c in self.rows if c.get("worker") == worker and c.get("url") == url), None)
            leased = bool(row and row.get("durable_status") == "leased" and row.get("task_id"))
            if row is not None:
                row["status"] = "stopped"
                row["durable_status"] = "failed" if leased else row.get("durable_status", "not_claimed")
        if leased and self._durable_queue is not None:
            try:
                self._durable_queue.fail(row["task_id"], durable_worker, error_class="worker_crash", detail=detail)
            except Exception:
                pass
        if self._on_status:
            self._on_status(worker, "stopped", f"{url} | worker error: {detail}")

    def _one(self, worker: int, url: str, session: dict) -> None:
        """One page for one worker: claim its durable task, open it, record the observation."""
        row = None
        with self._lock:
            for candidate in self.rows:
                if candidate.get("worker") == worker and candidate.get("url") == url:
                    row = candidate
                    break
        durable = None
        durable_worker = f"browser-{self._run_id or 'run'}-{worker}"
        if self._durable_queue is not None:
            if not row or not row.get("task_id"):
                if self._on_status:
                    self._on_status(worker, "stopped", url)
                return
            durable = self._durable_queue.claim_task(
                row["task_id"], worker_id=durable_worker,
            )
            if not durable:
                with self._lock:
                    row["status"] = "stopped"
                    row["durable_status"] = "not_claimed"
                if self._on_status:
                    self._on_status(worker, "stopped", url)
                return
            with self._lock:
                row["durable_status"] = "leased"
        if session["open"] is None or session["close"] is None:
            try:
                session["open"], session["close"] = self._session()
            except Exception as exc:
                if durable is not None:
                    self._durable_queue.fail(
                        durable["task_id"], durable_worker,
                        error_class="worker_crash", detail=str(exc)[:500],
                    )
                    with self._lock:
                        row["durable_status"] = "failed"
                if self._on_status:
                    self._on_status(worker, "stopped", url)
                return
        try:
            found = session["open"](url)
        except Exception as exc:
            if durable is not None:
                self._durable_queue.fail(
                    durable["task_id"], durable_worker,
                    error_class="worker_crash", detail=str(exc)[:500],
                )
                with self._lock:
                    row["durable_status"] = "failed"
            if self._on_status:
                self._on_status(worker, "stopped", url)
            return
        if landed_on_payment(found):
            final = str(found.get("final_url") or url)
            if self._on_status:
                self._on_status(worker, "blocked", final)
            with self._lock:
                for candidate in self.rows:
                    if (candidate.get("worker") == worker
                            and candidate.get("url") == url and "work" not in candidate):
                        candidate["status"] = "blocked"
                        candidate["work"] = found
                        if durable is not None:
                            candidate["durable_status"] = "blocked"
                        break
            if durable is not None:
                self._durable_queue.block(
                    durable["task_id"], durable_worker,
                    error_class="policy_blocked",
                    reason="checkout or payment navigation was blocked",
                )
            return
        if not observed_page(found, url):
            if durable is not None:
                self._durable_queue.fail(
                    durable["task_id"], durable_worker,
                    error_class="evidence_missing",
                    detail="browser returned no HTTP observation",
                )
                with self._lock:
                    row["durable_status"] = "failed"
            if self._on_status:
                self._on_status(worker, "stopped", url)
            return
        summary = ""
        if isinstance(found, dict):
            summary = str(found.get("summary") or "")
            with self._lock:
                for candidate in self.rows:
                    if (candidate.get("worker") == worker
                            and candidate.get("url") == url and "work" not in candidate):
                        candidate["work"] = found
                        break
        if durable is not None:
            from .finalization import write_text_unless_linked
            artifact = f"browser_observation_{durable['task_id']}.json"
            written = bool(
                self._evidence_dir
                and write_text_unless_linked(
                    self._evidence_dir, artifact,
                    json.dumps({
                        "task_id": durable["task_id"],
                        "worker_id": durable_worker,
                        "url": url,
                        "observation": found,
                    }, indent=2),
                )
            )
            result = {
                "ok": written,
                "url": url,
                "role": "browser",
                "evidence": ([{
                    "kind": "browser_observation",
                    "artifact": artifact,
                    "task_id": durable["task_id"],
                }] if written else []),
            }
            ok, _reason = self._durable_queue.complete(
                durable["task_id"], durable_worker, result,
            ) if written else self._durable_queue.fail(
                durable["task_id"], durable_worker,
                error_class="evidence_missing",
                detail="browser observation artifact could not be written",
            )
            with self._lock:
                row["durable_status"] = "succeeded" if ok and written else "failed"
        if self._on_status:
            detail = f"{url} | {summary}" if summary else url
            self._on_status(worker, "read", detail)

    def finish(self) -> list[dict]:
        """Tell every worker to close, then wait until they have."""
        with self._lock:
            if self._closed:
                return list(self.rows)
            self._closed = True
        for worker_queue in self._queues.values():
            worker_queue.put(None)
        for thread in self._threads:
            thread.join(timeout=60)
        return list(self.rows)
