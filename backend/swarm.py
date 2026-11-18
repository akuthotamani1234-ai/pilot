"""A small swarm for a large shop.

The results page may list hundreds of products. One leader keeps two or three.
Each chosen product is given to its own worker. Payment and checkout links are
never handed to a worker.
"""
import re
from urllib.parse import urlsplit

_PAYMENT_PATH = re.compile(
    r"(?:^|/)(?:check-?outs?|payments?|place-?orders?|buy-now|paypal)(?:/|$)",
    re.I,
)


def sample_limit(swarm_sample: int, pattern_samples: int) -> int:
    """How many pages of one kind to open. The swarm size wins when it is set."""
    if swarm_sample > 0:
        return swarm_sample
    return max(0, pattern_samples)


def is_payment_url(url: str) -> bool:
    """True when the address itself is a checkout or payment step."""
    path = urlsplit(url or "").path.replace("_", "-")
    return bool(_PAYMENT_PATH.search(path))


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


def perform(assignments: list[dict], open_page, *, on_status=None) -> list[dict]:
    """Open each worker's product at the same time. A payment address is not opened."""
    from concurrent.futures import ThreadPoolExecutor

    def run(row: dict) -> dict:
        worker = int(row.get("worker") or 0)
        url = str(row.get("url") or "")
        if on_status:
            on_status(worker, "opening", url)
        if not url or is_payment_url(url):
            if on_status:
                on_status(worker, "blocked", url)
            return {**row, "status": "blocked"}
        try:
            open_page(url)
        except Exception:
            if on_status:
                on_status(worker, "stopped", url)
            return {**row, "status": "stopped"}
        if on_status:
            on_status(worker, "opened", url)
        return {**row, "status": "opened"}

    if not assignments:
        return []
    with ThreadPoolExecutor(max_workers=min(len(assignments), 4)) as pool:
        done = list(pool.map(run, assignments))
    return done
