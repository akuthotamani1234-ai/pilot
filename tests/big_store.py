"""BigStore - a LARGE local shop (no internet): 2,000 products in 20 categories, to prove that a big website is tested
by page TYPE within its budget (Steps 17 + 19): a sample of each kind fully tested, more of them smoke-checked, the
rest counted - "Product pages: 3 fully tested, 10 smoke-checked, 2,000 found".

  /                         20 category links, 8 featured products, the search box
  /category/<cat>?page=N    100 products per category, 24 per page (5 pages); sort (name, price low -> high, price
                            high -> low) and an "In stock only" filter - each card shows its name, price and stock
  /product/<n>              (BigStore(slugs=True): /products/<adjective>-<material>-<noun>, no number in the address)
                            the product: name, price, stock, quantity, Add to cart
  /search?q=word            the products whose name has the word
  /cart                     the cart: lines, quantities, line totals, Total; Checkout (protected - never used)
  /login                    e-mail + password (ACCOUNT) -> /account, /orders (behind the login)
  /sitemap.xml              every category and product address (so the run can count all 2,000)

BigStore(bugs=True) has 3 PLANTED BUGS (tests/truth/big_store.json):
  S1 the search also lists a product without the word      S2 'Price: low to high' is not sorted
  S3 the cart total ignores the quantity

    python tests/big_store.py 8770 [bugs] [slugs]
"""
import html
import http.server
import random
import secrets
import sys
import threading
from urllib.parse import parse_qs, urlparse

EMAIL, PASSWORD = "shopper@big.test", "Big#Store2026"
CATS = ["Lamps", "Chairs", "Tables", "Rugs", "Mugs", "Vases", "Clocks", "Mirrors", "Shelves", "Pillows", "Towels",
        "Plates", "Bowls", "Candles", "Frames", "Baskets", "Blankets", "Curtains", "Kettles", "Planters"]
ADJ = ["red", "blue", "green", "black", "white", "golden", "silver", "rustic", "modern", "classic"]
MAT = ["oak", "pine", "steel", "glass", "linen", "wool", "clay", "bamboo", "marble", "copper"]
PER_PAGE = 24


def _products(slugs: bool) -> list[dict]:
    out = []
    for c, cat in enumerate(CATS):
        noun = cat.rstrip("s").lower()
        for k in range(100):
            n = c * 100 + k + 1
            adj, mat = ADJ[k // 10], MAT[k % 10]
            name = f"{adj.title()} {mat.title()} {noun.title()}"
            slug = f"{adj}-{mat}-{noun}"
            out.append({"id": n, "name": name, "cat": cat, "price": round(5 + (n * 37 % 200) + (n % 7) * 0.25, 2),
                        "stock": n % 5 != 0, "url": f"/products/{slug}" if slugs else f"/product/{n}"})
    return out


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>{title} - BigStore</title>
<style>body{{font-family:sans-serif;margin:0}} nav a{{margin-right:8px}} main{{padding:12px}}
.card{{display:inline-block;width:200px;border:1px solid #ddd;margin:4px;padding:6px;vertical-align:top}}</style></head>
<body><header><nav class="main-nav"><a href="/">Home</a> <a href="/cart">Cart ({cart})</a> <a href="/account">My account</a>
<form action="/search" method="get" style="display:inline"><input type="search" name="q" placeholder="Search products">
<button>Search</button></form></nav></header><main><h1>{title}</h1>{body}</main>
<footer><p>BigStore demo · <a href="/sitemap.xml">Sitemap</a></p></footer></body></html>"""


class BigStore:
    def __init__(self, port: int = 0, bugs: bool = False, slugs: bool = False):
        self.bugs, self.slugs = bugs, slugs
        self.products = _products(slugs)
        self.by_url = {p["url"]: p for p in self.products}
        self.carts: dict[str, dict[int, int]] = {}
        self.sessions: set[str] = set()
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.visited: list[str] = []
        self.posts: list[dict] = []

    def start(self) -> "BigStore":
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def _card(self, p: dict) -> str:
        return (f'<div class="card product"><a class="name" href="{p["url"]}">{html.escape(p["name"])}</a>'
                f'<p class="price">${p["price"]:.2f}</p><p class="stock">{"In stock" if p["stock"] else "Out of stock"}'
                '</p></div>')

    def _handler(self):
        app = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _sid(self):
                for part in (self.headers.get("Cookie") or "").split(";"):
                    k, _, v = part.strip().partition("=")
                    if k == "bsid":
                        return v
                return ""

            def _send(self, status, body, ctype="text/html; charset=utf-8", headers=None):
                data = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def _page(self, title, body, status=200, headers=None):
                cart = sum(app.carts.get(self._sid(), {}).values())
                self._send(status, PAGE.format(title=title, body=body, cart=cart), headers=headers)

            def _redirect(self, to, headers=None):
                self._send(303, "", headers=dict({"Location": to}, **(headers or {})))

            def do_GET(self):
                u = urlparse(self.path)
                path, q = u.path.rstrip("/") or "/", parse_qs(u.query)
                get = lambda k: (q.get(k) or [""])[0]  # noqa: E731
                app.visited.append(path)
                if path == "/":
                    cats = "".join(f'<li><a href="/category/{c.lower()}">{c}</a></li>' for c in CATS)
                    featured = "".join(app._card(p) for p in app.products[::250])
                    return self._page("BigStore", f"<h2>Categories</h2><ul class='cats'>{cats}</ul>"
                                                  f"<h2>Featured</h2><section class='grid'>{featured}</section>")
                if path == "/sitemap.xml":
                    locs = [f"{app.url}/category/{c.lower()}" for c in CATS] + [app.url + p["url"] for p in app.products]
                    xml = ('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/'
                           'sitemap/0.9">' + "".join(f"<url><loc>{l}</loc></url>" for l in locs) + "</urlset>")
                    return self._send(200, xml, "application/xml")
                if path.startswith("/category/"):
                    cat = next((c for c in CATS if c.lower() == path.split("/")[2]), None)
                    if not cat:
                        return self._page("Not found", "<p>No such category.</p>", 404)
                    items = [p for p in app.products if p["cat"] == cat and (get("instock") != "1" or p["stock"])]
                    sort = get("sort")
                    if sort == "name":
                        items.sort(key=lambda p: p["name"])
                    elif sort in ("price", "price_desc"):
                        items.sort(key=lambda p: p["price"], reverse=sort == "price_desc")
                        if app.bugs and sort == "price":  # (S2: low -> high is not sorted)
                            random.Random(7).shuffle(items)
                    page = max(1, int(get("page") or 1)) if (get("page") or "1").isdigit() else 1
                    pages = max(1, -(-len(items) // PER_PAGE))
                    shown = items[(page - 1) * PER_PAGE:page * PER_PAGE]
                    base = f"/category/{cat.lower()}?sort={sort}&instock={get('instock')}"
                    nav = (f'<a rel="prev" href="{base}&page={page - 1}">Previous</a> ' if page > 1 else "") + \
                          f"Page {page} of {pages}" + (f' <a rel="next" href="{base}&page={page + 1}">Next</a>'
                                                        if page < pages else "")
                    tools = (f'<form method="get" action="/category/{cat.lower()}"><label for="sort">Sort by</label> '
                             '<select id="sort" name="sort" onchange="this.form.submit()"><option value="">Featured</option>'
                             f'<option value="name"{" selected" if sort == "name" else ""}>Name</option>'
                             f'<option value="price"{" selected" if sort == "price" else ""}>Price: low to high</option>'
                             f'<option value="price_desc"{" selected" if sort == "price_desc" else ""}>Price: high to low'
                             '</option></select> <label><input type="checkbox" name="instock" value="1"'
                             f'{" checked" if get("instock") == "1" else ""} onchange="this.form.submit()"> In stock only'
                             '</label></form>')
                    return self._page(cat, tools + f"<section class='grid'>{''.join(app._card(p) for p in shown)}</section>"
                                               f"<p class='pagination'>{nav}</p>")
                if path in app.by_url:
                    p = app.by_url[path]
                    return self._page(p["name"], f'<p class="price">${p["price"]:.2f}</p>'
                                                 f'<p class="stock">{"In stock" if p["stock"] else "Out of stock"}</p>'
                                                 f'<form method="post" action="/cart/add"><input type="hidden" name="id" value="{p["id"]}">'
                                                 '<label for="qty">Quantity</label> <input id="qty" name="qty" type="number" '
                                                 'min="1" max="10" value="1"> <button type="submit">Add to cart</button></form>'
                                                 f'<p><a href="/category/{p["cat"].lower()}">Back to {p["cat"]}</a></p>')
                if path == "/search":
                    word = get("q").strip().lower()
                    hits = [p for p in app.products if word and word in p["name"].lower()][:48]
                    if app.bugs and hits:  # (S1: one product without the word is listed too)
                        hits.insert(1, next(p for p in app.products if word not in p["name"].lower()))
                    body = ("".join(app._card(p) for p in hits) if hits else
                            f"<p>No products match '{html.escape(word)}'.</p>")
                    return self._page(f"Search: {html.escape(word)}", f"<section class='grid'>{body}</section>")
                if path == "/cart":
                    cart = app.carts.get(self._sid(), {})
                    lines, total = "", 0.0
                    for pid, n in cart.items():
                        p = app.products[pid - 1]
                        total += p["price"] * (1 if app.bugs else n)  # (S3: the total ignores the quantity)
                        lines += (f'<tr><td>{html.escape(p["name"])}</td><td class="qty">{n}</td>'
                                  f'<td>${p["price"]:.2f}</td><td>${p["price"] * n:.2f}</td></tr>')
                    body = (f"<table id='cart'><thead><tr><th>Item</th><th>Qty</th><th>Price</th><th>Line total</th></tr>"
                            f"</thead><tbody>{lines}</tbody></table><p class='total'>Total: ${total:.2f}</p>"
                            '<button type="button" id="checkout">Checkout</button>' if cart else "<p>Your cart is empty.</p>")
                    return self._page("Cart", body)
                if path == "/login":
                    return self._page("Log in", '<form method="post" action="/login"><label for="email">E-mail</label> '
                                                '<input id="email" name="email" type="email"> <label for="password">Password'
                                                '</label> <input id="password" name="password" type="password"> '
                                                '<button type="submit">Log in</button></form>')
                if path in ("/account", "/orders"):
                    if self._sid() not in app.sessions:
                        return self._redirect("/login")
                    body = ("<p>Signed in as shopper.</p><p><a href='/orders'>My orders</a> · <a href='/logout'>Log out</a></p>"
                            if path == "/account" else "<ul><li>Order 1001 - 2 items</li><li>Order 1002 - 1 item</li></ul>")
                    return self._page("My account" if path == "/account" else "My orders", body)
                if path == "/logout":
                    app.sessions.discard(self._sid())
                    return self._redirect("/")
                return self._page("Not found", "<p>This page does not exist.</p>", 404)

            def do_POST(self):
                u = urlparse(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode("utf-8")).items()}
                app.posts.append({"path": u.path, "fields": sorted(form)})
                sid = self._sid() or secrets.token_hex(8)
                cookie = {"Set-Cookie": f"bsid={sid}; Path=/"}
                if u.path == "/cart/add":
                    pid, n = int(form.get("id") or 0), max(1, int(form.get("qty") or 1))
                    if 1 <= pid <= len(app.products):
                        cart = app.carts.setdefault(sid, {})
                        cart[pid] = cart.get(pid, 0) + n
                    return self._redirect("/cart", cookie)
                if u.path == "/login":
                    if form.get("email") == EMAIL and form.get("password") == PASSWORD:
                        app.sessions.add(sid)
                        return self._redirect("/account", cookie)
                    return self._page("Log in", '<p class="err" role="alert">Wrong e-mail or password</p>', 401)
                return self._send(405, "method not allowed")

        return Handler


if __name__ == "__main__":
    store = BigStore(int(sys.argv[1]) if len(sys.argv) > 1 else 8770, bugs="bugs" in sys.argv[2:],
                     slugs="slugs" in sys.argv[2:]).start()
    print(f"BigStore running at {store.url} ({len(store.products)} products{', planted bugs' if store.bugs else ''}"
          f"{', slug addresses' if store.slugs else ''}) - account {EMAIL} / {PASSWORD} - Ctrl+C to stop")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        store.stop()
