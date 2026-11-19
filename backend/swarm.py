"""Workers share a website.

Every safe page is given to a worker. The workers open their own pages at the
same time, then close. Payment and checkout links are never handed to a worker.
A long product list can still keep a short sample for the deeper crawl.
"""
import re
from urllib.parse import unquote, urlsplit

_PAYMENT_PATH = re.compile(
    r"(?:^|/)(?:check-?outs?|payments?|place-?orders?|buy-now|paypal)"
    r"(?:\.[a-z0-9]+)?(?:/|$)",
    re.I,
)
_PAYMENT_HOST = re.compile(r"(?:^|\.)paypal\.com$", re.I)


def sample_limit(swarm_sample: int, pattern_samples: int) -> int:
    """How many pages of one kind to open. The swarm size wins when it is set."""
    if swarm_sample > 0:
        return swarm_sample
    return max(0, pattern_samples)


def is_payment_url(url: str) -> bool:
    """True when the address itself is a checkout or payment step."""
    parts = urlsplit(url or "")
    host = parts.hostname or ""
    if _PAYMENT_HOST.search(host):
        return True
    path = unquote(parts.path).replace("_", "-")
    return bool(_PAYMENT_PATH.search(path))


_QUOTED = re.compile(r"""['"]([^'"]+)['"]""")


def control_opens_payment(page_url: str, href: str = "", form_action: str = "", onclick: str = "") -> bool:
    """True when the control's address is checkout or payment, whatever its label says."""
    from urllib.parse import urljoin

    base = page_url or ""
    for raw in (href or "", form_action or ""):
        text = raw.strip()
        if not text or text.startswith("#") or text.lower().startswith("javascript:"):
            continue
        if is_payment_url(urljoin(base, text)):
            return True
    for quoted in _QUOTED.findall(onclick or ""):
        text = quoted.strip()
        if not text or text.startswith("#") or text.lower().startswith("javascript:"):
            continue
        if is_payment_url(urljoin(base, text)):
            return True
    return False


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
                if on_status:
                    on_status(worker, "opened", url)
                done.append({**row, "status": "opened"})
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

    def __init__(self, worker_count: int, limit: int, session, on_status=None):
        import queue
        import threading

        self.worker_count = max(1, int(worker_count or 1))
        self.limit = max(0, int(limit or 0))
        self._session = session
        self._on_status = on_status
        self._seen: set[str] = set()
        self._lock = threading.Lock()
        self._queues = {n: queue.Queue() for n in range(1, self.worker_count + 1)}
        self.rows: list[dict] = []
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
                self._seen.add(row["url"])
                self.rows.append(row)
                self._queues[row["worker"]].put(row["url"])
            return list(plan)

    def _run(self, worker: int) -> None:
        open_page, close = self._session()
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
                    found = open_page(url)
                except Exception:
                    if self._on_status:
                        self._on_status(worker, "stopped", url)
                    continue
                if landed_on_payment(found):
                    final = str(found.get("final_url") or url)
                    if self._on_status:
                        self._on_status(worker, "blocked", final)
                    with self._lock:
                        for row in self.rows:
                            if row.get("worker") == worker and row.get("url") == url and "work" not in row:
                                row["status"] = "blocked"
                                row["work"] = found
                                break
                    continue
                summary = ""
                if isinstance(found, dict):
                    summary = str(found.get("summary") or "")
                    with self._lock:
                        for row in self.rows:
                            if row.get("worker") == worker and row.get("url") == url and "work" not in row:
                                row["work"] = found
                                break
                if self._on_status:
                    detail = f"{url} | {summary}" if summary else url
                    self._on_status(worker, "read", detail)
        finally:
            close()

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
