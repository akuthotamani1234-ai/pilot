"""ClassicShop - a small local online shop built the way many older template shops are. No internet needed.

It has the page structures that made real shops of this kind hard to test (and tests/test_classic_shop.py proves
the agent handles them): ONE index.php that picks the page with ?rt=<route>; a header menu of plain lists (no
<header> / <nav>); product cards as plain <div>s inside <body class="product-category">; hover dropdowns whose text
changes with the cart ('0 ITEMS - $0.00'); product tabs linking to '#review' while a <base href> points to the home
page; a TEXT box for the quantity; an e-mail box of type "text"; 'Print' (window.print) and 'Back to top' (scrolls).

  public:  /  (= index.php)                        featured products
           ?rt=product/category&path=10|20|30      a category (sort, items per page, Grid / List; Makeup has 2 pages)
           ?rt=product/special                     special offers
           ?rt=product/search&keyword=...          search (advanced search form, results, "no product matches")
           ?rt=product/product&product_id=N        product: an option (some), quantity, Add to Cart, tabs, Print
           ?rt=checkout/cart                       the cart: lines, quantity boxes + Update, totals (Checkout: protected)
           ?rt=account/login                       new customer (Register / Guest + Continue), returning customer
           ?rt=account/create                      the sign-up form          ?rt=account/invoice   "Check your order"
           ?rt=content/contact                     contact form              ?rt=content/content&content_id=1|2
  behind the login (EMAIL / PASSWORD):  ?rt=account/account  ?rt=account/history
  in every footer: the newsletter form (Subscribe - protected, never sent) and 'Back to top'
  never to use: Checkout / Confirm Order, Subscribe, Submit (contact), sign-up, Logout (every request is recorded)

ClassicShop(bugs=True) has 3 PLANTED BUGS, each in ONE feature (to prove that a broken feature fails its own test
and nothing else, see classic_shop_truth.json): the search also lists items that don't match · 'Price Low > High' is
not sorted · the cart total ignores the quantity.

Start by hand:  python tests/classic_shop.py 8767 [bugs]      then open http://127.0.0.1:8767
In tests:       shop = ClassicShop().start(); ...; shop.stop()
"""
import html
import http.server
import json
import secrets
import sys
import threading
from urllib.parse import parse_qs, quote, urlparse

EMAIL, PASSWORD = "classic@shop.test", "Classic#2024"
CATEGORIES = {10: "Makeup", 20: "Skincare", 30: "Fragrance"}
SUBCATEGORIES = {10: {11: "Eyes", 12: "Lips"}}
# (id, category, sub-category, name, price, option)
PRODUCTS = [
    (1, 10, 12, "Velvet Matte Lipstick", 18.50, None), (2, 10, 11, "Silk Eye Shadow Palette", 32.00, "Shade"),
    (3, 10, 11, "Long Lash Mascara", 14.25, None), (4, 10, 12, "Rose Gloss Lip Tint", 9.90, None),
    (5, 10, 11, "Liquid Eyeliner Pen", 12.75, None), (6, 10, 12, "Coral Lip Liner", 7.40, None),
    (7, 10, 11, "Brow Shaping Pencil", 11.20, None), (8, 10, 12, "Velvet Lip Balm", 6.80, None),
    (9, 10, 11, "Glitter Eye Primer", 15.60, None), (10, 10, 12, "Cherry Lip Stain", 10.30, None),
    (11, 20, 0, "Hydrating Day Cream", 45.00, "Size"), (12, 20, 0, "Night Repair Serum", 59.00, None),
    (13, 20, 0, "Gentle Foam Cleanser", 16.20, None), (14, 20, 0, "Clay Face Mask", 22.80, None),
    (15, 30, 0, "Citrus Eau de Toilette", 49.50, None), (16, 30, 0, "Amber Night Perfume", 74.00, None),
    (17, 30, 0, "Ocean Breeze Cologne", 38.00, None), (18, 30, 0, "Vanilla Body Mist", 19.90, None),
]
PRODUCTS = [{"id": i, "cat": c, "sub": s, "name": n, "price": p, "option": o} for i, c, s, n, p, o in PRODUCTS]
OPTIONS = {"Shade": [("smoky", "Smoky"), ("nude", "Nude")], "Size": [("50ml", "50 ml"), ("100ml", "100 ml")]}
SPECIALS = [2, 12, 16, 4, 17]
FEATURED = [1, 11, 15, 3, 12, 18]
SORTS = [("p.sort_order-ASC", "Default"), ("pd.name-ASC", "Name A - Z"), ("pd.name-DESC", "Name Z - A"),
         ("p.price-ASC", "Price Low > High"), ("p.price-DESC", "Price High > Low")]
PICTURE = ("data:image/svg+xml;utf8," + quote('<svg xmlns="http://www.w3.org/2000/svg" width="120" height="90">'
                                              '<rect width="120" height="90" fill="#f4d9e4"/></svg>'))

STYLE = """body{font-family:Arial,sans-serif;margin:0;color:#333} a{color:#c2185b}
.headerstrip{background:#222;color:#fff;padding:8px 16px;display:flex;flex-wrap:wrap;gap:18px;align-items:center}
.headerstrip a{color:#fff;text-decoration:none} .headerstrip ul{list-style:none;margin:0;padding:0;display:flex;gap:14px}
.dropdown{position:relative} .dropdown-menu{display:none;position:absolute;top:100%;left:0;background:#fff;
 border:1px solid #ccc;padding:8px;z-index:20;min-width:180px;flex-direction:column}
.dropdown-menu a{color:#c2185b} .headerstrip ul.dropdown-menu{display:none}
.headerstrip .dropdown:hover>ul.dropdown-menu,.headerstrip .dropdown.open>ul.dropdown-menu{display:flex}
.categorymenu{list-style:none;margin:0;padding:6px 16px;background:#f5f5f5;display:flex;gap:22px}
.categorymenu>li{position:relative} .subcategories{display:none;position:absolute;top:100%;left:0;background:#fff;
 border:1px solid #ccc;padding:8px;z-index:20;min-width:140px} .categorymenu>li:hover .subcategories{display:block}
.subcategories ul{list-style:none;margin:0;padding:0}
#maincontainer{padding:16px} .breadcrumb{list-style:none;padding:0;display:flex;gap:8px;font-size:13px}
.thumbnails{display:flex;flex-wrap:wrap;gap:12px} .thumbnails.list{flex-direction:column}
.col-md-3{width:200px;border:1px solid #ddd;padding:8px} .oneprice,.productfilneprice{font-weight:bold}
.nav-tabs{list-style:none;padding:0;display:flex;gap:10px;border-bottom:1px solid #ccc}
.tab-pane{display:none;padding:10px} .tab-pane.active{display:block}
.alert-error{color:#b71c1c;border:1px solid #b71c1c;padding:8px;margin:8px 0}
.alert-success{color:#1b5e20;border:1px solid #1b5e20;padding:8px;margin:8px 0}
.help-block{color:#b71c1c;font-size:13px} #footer{background:#eee;padding:16px;margin-top:500px}
table.cart td,table.cart th{border-bottom:1px solid #ddd;padding:6px 10px}"""

TABS_JS = """<script>
document.querySelectorAll('[data-toggle=tab]').forEach(a => a.addEventListener('click', e => {
  e.preventDefault();
  const id = a.getAttribute('href').slice(1);
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.toggle('active', p.id === id));
  document.querySelectorAll('.nav-tabs li').forEach(li => li.classList.toggle('active', li.contains(a)));
}));
</script>"""

COMMON_JS = """<script>
document.querySelectorAll('.dropdown > a.dropdown-toggle[href="#"]').forEach(a => a.addEventListener('click', e => {
  e.preventDefault(); a.parentElement.classList.toggle('open'); }));
document.getElementById('gotop').addEventListener('click', e => { e.preventDefault(); window.scrollTo(0, 0); });
function search_submit() { document.getElementById('search_form').submit(); }
async function add_to_cart(id, link) {
  const r = await fetch('index.php?rt=checkout/cart', {method: 'POST',
    headers: {'Content-Type': 'application/x-www-form-urlencoded', 'X-Requested-With': 'XMLHttpRequest'},
    body: 'product_id=' + id + '&quantity=1'});
  const d = await r.json();
  document.querySelector('.cart_total_text').textContent = d.count + ' ITEMS - ' + d.total;
  document.getElementById('topcart_lines').innerHTML = d.lines;
  link.classList.add('added_to_cart'); link.setAttribute('title', 'Added to cart');
}
</script>"""


def money(value: float, eur: bool = False) -> str:
    return f"€{value * 0.9:.2f}" if eur else f"${value:.2f}"


class ClassicShop:
    def __init__(self, port: int = 0, bugs: bool = False):
        self.bugs = bugs  # the 3 planted bugs (see the top of this file)
        self.sessions: dict[str, dict] = {}
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.visited: list[str] = []  # every request: "GET product/category", "POST checkout/cart" ...

    def start(self) -> "ClassicShop":
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    # ---------------------------------------------------------------- the shop's rules
    def total(self, s: dict) -> float:
        """The cart total: price x quantity of every line (planted bug: the quantity is ignored)."""
        return sum(self.product(k.split(":")[0])["price"] * (1 if self.bugs else q) for k, q in s["cart"].items())

    @staticmethod
    def product(pid) -> dict | None:
        return next((p for p in PRODUCTS if str(p["id"]) == str(pid)), None)

    def listed(self, items: list[dict], sort: str, keyword: str = "") -> list[dict]:
        key = {"pd.name-ASC": (lambda p: p["name"], False), "pd.name-DESC": (lambda p: p["name"], True),
               "p.price-ASC": (lambda p: p["price"], False), "p.price-DESC": (lambda p: p["price"], True)}.get(sort)
        items = sorted(items, key=key[0], reverse=key[1]) if key else list(items)
        if self.bugs and sort == "p.price-ASC" and len(items) > 2:  # planted bug: not sorted
            items[0], items[1] = items[1], items[0]
        return items

    def _handler(self):
        shop = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            # ---------------------------------------------------------------- plumbing
            def _send(self, status, body="", headers=None, ctype="text/html; charset=utf-8"):
                data = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                if self._new_sid:
                    self.send_header("Set-Cookie", f"csid={self._new_sid}; Path=/; HttpOnly")
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def _session(self) -> dict:
                self._new_sid = ""
                for part in (self.headers.get("Cookie") or "").split(";"):
                    k, _, v = part.strip().partition("=")
                    if k == "csid" and v in shop.sessions:
                        return shop.sessions[v]
                self._new_sid = secrets.token_hex(12)
                shop.sessions[self._new_sid] = {"cart": {}, "user": None, "eur": False}
                return shop.sessions[self._new_sid]

            def _go(self, to):
                self._send(303, "", {"Location": to})

            def _form(self) -> dict:
                n = int(self.headers.get("Content-Length") or 0)
                return {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8")).items()}

            def _money(self, value):
                return money(value, self.s["eur"])

            # ---------------------------------------------------------------- the page around the content
            def _header(self) -> str:
                s, here = self.s, html.escape(self.path)
                sep = "&amp;" if "?" in self.path else "?"
                cats = "".join(
                    f'<li><a href="index.php?rt=product/category&amp;path={c}">{n}</a>'
                    + ('<div class="subcategories"><ul>' + "".join(
                        f'<li><a href="index.php?rt=product/category&amp;path={c}_{sc}">{sn}</a></li>'
                        for sc, sn in SUBCATEGORIES[c].items()) + "</ul></div>" if c in SUBCATEGORIES else "")
                    + "</li>" for c, n in CATEGORIES.items())
                count = sum(s["cart"].values())
                return f"""<div id="topnav" class="headerstrip">
<a class="logo" href="index.php"><img src="{PICTURE}" alt="ClassicShop" width="40" height="30"></a>
<ul id="main_menu_top">
 <li><a href="index.php?rt=account/login">Login or register</a></li>
 <li><a href="index.php?rt=product/special">Specials</a></li>
 <li><a href="index.php?rt=account/account">Account</a></li>
 <li><a href="index.php?rt=account/invoice">Check Your Order</a></li>
 <li><a href="index.php?rt=checkout/cart">Cart</a></li>
 <li><a href="index.php?rt=checkout/checkout">Checkout</a></li>
</ul>
<ul class="topcart">
 <li class="dropdown hover"><a class="dropdown-toggle" href="#">{'€ EURO' if s['eur'] else '$ US DOLLAR'}</a>
  <ul class="dropdown-menu currency"><li><a href="{here}{sep}currency=EUR">€ Euro</a></li>
   <li><a href="{here}{sep}currency=USD">$ US Dollar</a></li></ul></li>
 <li class="dropdown hover"><a class="dropdown-toggle" href="index.php?rt=checkout/cart"><span
   class="cart_total_text">{count} ITEMS - {self._money(shop.total(s))}</span></a>
  <ul class="dropdown-menu topcartopen"><li id="topcart_lines">{self._top_lines()}</li>
   <li><a href="index.php?rt=checkout/cart">View Cart</a></li></ul></li>
</ul>
<form id="search_form" action="index.php" method="get"><input type="hidden" name="rt" value="product/search">
 <input type="text" id="filter_keyword" name="keyword" autocomplete="off" placeholder="Search Keywords">
 <div class="button-in-search" title="Go" onclick="search_submit()">&#128269;</div></form>
</div>
<ul class="categorymenu"><li><a href="index.php">Home</a></li>{cats}</ul>"""

            def _top_lines(self) -> str:
                lines = [f"{q} x {html.escape(shop.product(k.split(':')[0])['name'])}" for k, q in self.s["cart"].items()]
                return "<br>".join(lines) if lines else "Your shopping cart is empty!"

            def _footer(self) -> str:
                return """<div id="footer"><div class="info"><a href="index.php?rt=content/content&amp;content_id=1">About Us</a>
 · <a href="index.php?rt=content/content&amp;content_id=2">Privacy Policy</a>
 · <a href="index.php?rt=content/contact">Contact Us</a> · <a href="index.php?rt=content/sitemap">Site Map</a></div>
<form id="subscribeFrm" action="index.php?rt=account/subscriber" method="post">
 <input type="text" placeholder="Subscribe to Newsletter" name="email" id="appendedInputButton">
 <button class="btn btn-orange" type="submit">Subscribe</button></form>
<p>ClassicShop &copy; 2026 · <a id="gotop" href="#">Back to top</a></p></div>"""

            def _page(self, title, body, status=200, route="", base=False):
                css_class = (route or "index/home").replace("/", "-")
                doc = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(title)}</title>'
                       + (f'<base href="{shop.url}/">' if base else "")
                       + f"<style>{STYLE}</style></head><body class=\"{css_class}\">{self._header()}"
                       f'<div id="maincontainer"><div class="container">{body}</div></div>{self._footer()}'
                       f"{COMMON_JS}</body></html>")
                self._send(status, doc)

            def _cards(self, items: list[dict]) -> str:
                if not items:
                    return '<div class="contentpanel">There is no product that matches the search criteria.</div>'
                cards = []
                for p in items:
                    href = f"index.php?rt=product/product&amp;path={p['cat']}&amp;product_id={p['id']}"
                    add = (f'<a href="{href}" class="productcart" title="Add to Cart">&#128722;</a>' if p["option"] else
                           f'<a data-id="{p["id"]}" href="#" class="productcart" title="Add to Cart" '
                           f'onclick="add_to_cart({p["id"]}, this); return false;">&#128722;</a>')
                    cards.append(f"""<div class="col-md-3 col-sm-6 col-xs-12">
 <div class="fixed_wrapper"><div class="fixed"><a class="prdocutname" href="{href}" title="{html.escape(p['name'])}">{html.escape(p['name'])}</a></div></div>
 <div class="thumbnail"><a href="{href}"><img src="{PICTURE}" alt="{html.escape(p['name'])}" width="120" height="90"></a>
  <div class="pricetag">{add}<div class="price"><div class="oneprice">{self._money(p['price'])}</div></div></div></div>
</div>""")
                return '<div class="thumbnails grid row list-inline">' + "".join(cards) + "</div>"

            def _sorter(self, route: str, extra: str, sort: str, limit: int) -> str:
                base = f"index.php?rt={route}{extra}"
                opts = "".join(f'<option value="{v}"{" selected" if v == sort else ""}>{t}</option>' for v, t in SORTS)
                lims = "".join(f'<option value="{n}"{" selected" if n == limit else ""}>{n}</option>' for n in (8, 20, 50))
                return f"""<div class="sorting well"><form class="form-inline">Sort By:
 <select name="sort" id="sort" onchange="location = '{base}&amp;limit={limit}&amp;sort=' + this.value">{opts}</select>
 Per page: <select name="limit" id="limit" onchange="location = '{base}&amp;sort={sort}&amp;limit=' + this.value">{lims}</select>
 </form><div class="btn-group"><button class="btn btn-orange" id="list" type="button"
 onclick="document.querySelector('.thumbnails').classList.add('list')">&#9776;</button>
 <button class="btn btn-orange" id="grid" type="button"
 onclick="document.querySelector('.thumbnails').classList.remove('list')">&#9638;</button></div></div>"""

            def _listing(self, title, route, extra, items, q, crumbs=""):
                sort, limit = q.get("sort", SORTS[0][0]), int(q.get("limit") or 8)
                page = max(1, int(q.get("page") or 1)) if (q.get("page") or "1").isdigit() else 1
                items = shop.listed(items, sort)
                pages = (len(items) + limit - 1) // limit
                shown = items[(page - 1) * limit: page * limit]
                pager = ""
                if pages > 1:
                    links = "".join(f'<li><a href="index.php?rt={route}{extra}&amp;sort={sort}&amp;limit={limit}'
                                    f'&amp;page={n}">{n}</a></li>' for n in range(1, pages + 1) if n != page)
                    if page < pages:
                        links += (f'<li><a href="index.php?rt={route}{extra}&amp;sort={sort}&amp;limit={limit}'
                                  f'&amp;page={page + 1}">&gt;</a></li>')
                    pager = f'<ul class="pagination">{links}</ul>'
                body = (f'<ul class="breadcrumb"><li><a href="index.php">Home</a></li>{crumbs}</ul><h1>{html.escape(title)}</h1>'
                        + (self._sorter(route, extra, sort, limit) if items else "") + self._cards(shown) + pager)
                self._page(title, body, route=route)

            # ---------------------------------------------------------------- GET
            def do_GET(self):
                self.s = self._session()
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                if u.path not in ("/", "/index.php"):
                    return self._send(404, "<h1>Not found</h1>")
                route = q.get("rt", "")
                shop.visited.append("GET " + (route or "index/home"))
                if q.get("currency") in ("EUR", "USD"):  # a display setting: the same page in another currency
                    self.s["eur"] = q["currency"] == "EUR"
                if route in ("", "index/home"):
                    feat = [shop.product(i) for i in FEATURED]
                    return self._page("ClassicShop - a place to practise testing", "<h1>Welcome to ClassicShop!</h1>"
                                      "<h2>Featured</h2>" + self._cards(feat))
                if route == "product/category":
                    c, _, sub = (q.get("path") or "").partition("_")
                    if not c.isdigit() or int(c) not in CATEGORIES:
                        return self._page("Category not found", "<h1>Category not found!</h1>", 404, route)
                    items = [p for p in PRODUCTS if p["cat"] == int(c) and (not sub or str(p["sub"]) == sub)]
                    name = CATEGORIES[int(c)] + (f" - {SUBCATEGORIES[int(c)][int(sub)]}" if sub.isdigit()
                                                 and int(sub) in SUBCATEGORIES.get(int(c), {}) else "")
                    return self._listing(name, route, f"&amp;path={html.escape(q['path'])}", items, q,
                                         f'<li><a href="index.php?rt=product/category&amp;path={c}">{CATEGORIES[int(c)]}</a></li>')
                if route == "product/special":
                    return self._listing("Special Offers", route, "", [shop.product(i) for i in SPECIALS], q,
                                         '<li><a href="index.php?rt=product/special">Special Offers</a></li>')
                if route == "product/search":
                    return self._search(q)
                if route == "product/product":
                    return self._product(q)
                if route == "checkout/cart":
                    return self._cart(q)
                if route == "checkout/checkout":
                    if not self.s["cart"]:
                        return self._go("index.php?rt=checkout/cart")
                    return self._page("Checkout Confirmation", f"""<h1>Checkout Confirmation</h1>
<p>{sum(self.s['cart'].values())} item(s), total {self._money(shop.total(self.s))}</p>
<form method="post" action="index.php?rt=checkout/confirm"><button id="checkout_btn" type="submit" class="btn">Confirm Order</button></form>""", route=route)
                if route == "account/login":
                    return self._login("")
                if route == "account/create":
                    return self._page("Create Account", REGISTER_FORM, route=route)
                if route == "account/invoice":
                    return self._page("Order Details", INVOICE_FORM.format(error=""), route=route)
                if route in ("account/account", "account/history"):
                    if not self.s["user"]:
                        return self._go("index.php?rt=account/login")
                    if route == "account/history":
                        return self._page("Order History", """<h1>Order History</h1><table class="cart">
<tr><th>Order ID</th><th>Status</th><th>Total</th></tr><tr><td>#1001</td><td>Complete</td><td>$56.25</td></tr>
<tr><td>#1002</td><td>Pending</td><td>$18.50</td></tr></table>""", route=route)
                    return self._page("My Account", f"""<h1>My Account</h1><p>Welcome back, {html.escape(self.s['user'])}.</p>
<ul class="myaccount"><li><a href="index.php?rt=account/history">Order history</a></li>
<li><a href="index.php?rt=account/logout">Logoff</a></li></ul>""", route=route)
                if route == "account/logout":
                    self.s["user"] = None
                    return self._go("index.php")
                if route == "content/contact":
                    return self._page("Contact Us", CONTACT_FORM, route=route)
                if route == "content/content" and q.get("content_id") in ("1", "2"):
                    title = {"1": "About Us", "2": "Privacy Policy"}[q["content_id"]]
                    return self._page(title, f"<h1>{title}</h1><p>ClassicShop is a practice shop for automated "
                                             "testing. It keeps no personal data.</p>", route=route)
                if route == "content/sitemap":
                    links = "".join(f'<li><a href="index.php?rt=product/category&amp;path={c}">{n}</a></li>'
                                    for c, n in CATEGORIES.items())
                    links += ('<li><a href="index.php?rt=account/create">Register</a></li>'
                              '<li><a href="index.php?rt=account/invoice">Check Your Order</a></li>'
                              '<li><a href="index.php?rt=checkout/cart">Shopping Cart</a></li>')
                    return self._page("Site Map", f"<h1>Site Map</h1><ul>{links}</ul>", route=route)
                return self._page("Page not found", "<h1>The page you requested cannot be found.</h1>", 404, route)

            def _search(self, q):
                word = (q.get("keyword") or "").strip()
                cat = q.get("category_id") or "0"
                in_desc = q.get("description") == "true"
                items = [p for p in PRODUCTS if word and (word.lower() in p["name"].lower()
                                                          or (in_desc and word.lower() in CATEGORIES[p["cat"]].lower()))
                         and (cat == "0" or str(p["cat"]) == cat)]
                if shop.bugs and word:  # planted bug: the search also lists 2 items that don't match
                    items += [p for p in PRODUCTS if word.lower() not in p["name"].lower()][:2]
                cats = "".join(f'<option value="{c}"{" selected" if str(c) == cat else ""}>{n}</option>'
                               for c, n in CATEGORIES.items())
                form = f"""<h1>Search</h1><form id="advanced_search" action="index.php" method="get" class="form-inline">
<input type="hidden" name="rt" value="product/search">
<label for="keyword">Search Criteria</label> <input type="text" id="keyword" name="keyword" value="{html.escape(word)}">
<select id="category_id" name="category_id"><option value="0">All Categories</option>{cats}</select>
<label><input type="checkbox" id="description" name="description" value="true"{" checked" if in_desc else ""}>
 Search in product descriptions</label>
<button type="submit" id="search_button" class="btn" title="Search">Search</button></form>
<h2>Products meeting the search criteria</h2>"""
                sort, limit = q.get("sort", SORTS[0][0]), int(q.get("limit") or 8)
                listed = shop.listed(items, sort)[:limit]
                extra = f"&amp;keyword={html.escape(quote(word))}&amp;category_id={cat}"
                body = form + (self._sorter("product/search", extra, sort, limit) if listed else "") + self._cards(listed)
                self._page("Search", body, route="product/search")

            def _product(self, q, error=""):
                p = shop.product(q.get("product_id"))
                if not p:
                    return self._page("Product not found", "<h1>Product not found!</h1>", 404, "product/product")
                option = ""
                if p["option"]:
                    opts = "".join(f'<option value="{v}">{t}</option>' for v, t in OPTIONS[p["option"]])
                    option = (f'<div class="form-group"><label for="option_{p["option"].lower()}">{p["option"]}</label> '
                              f'<select id="option_{p["option"].lower()}" name="option">'
                              f'<option value="">--- Please Select ---</option>{opts}</select></div>')
                crumbs = (f'<li><a href="index.php">Home</a></li><li><a href="index.php?rt=product/category&amp;path='
                          f'{p["cat"]}">{CATEGORIES[p["cat"]]}</a></li><li><a href="index.php?rt=product/product&amp;'
                          f'product_id={p["id"]}">{html.escape(p["name"])}</a></li>')
                body = f"""<ul class="breadcrumb">{crumbs}</ul>
{f'<div class="alert alert-error">{html.escape(error)}</div>' if error else ''}
<h1 class="productname"><span class="bgnone">{html.escape(p['name'])}</span></h1>
<div class="productfilneprice">{self._money(p['price'])}</div>
<form id="product" action="index.php?rt=checkout/cart" method="post"><input type="hidden" name="product_id" value="{p['id']}">
{option}<div class="form-group"><label for="product_quantity">Qty:</label>
 <input type="text" id="product_quantity" name="quantity" value="1" size="3" class="form-control short"></div>
<a href="#" onclick="document.getElementById('product').submit(); return false;" class="cart">Add to Cart</a></form>
<a class="productprint btn btn-large" href="javascript:window.print();">Print</a>
<ul class="nav nav-tabs"><li class="active"><a href="#description" data-toggle="tab">Description</a></li>
 <li><a href="#review" data-toggle="tab">Reviews (0)</a></li><li><a href="#producttag" data-toggle="tab">Tags:</a></li></ul>
<div class="tab-content"><div class="tab-pane active" id="description"><p>{html.escape(p['name'])} - a ClassicShop favourite.</p></div>
 <div class="tab-pane" id="review"><p>There are no reviews for this product.</p></div>
 <div class="tab-pane" id="producttag"><p>{CATEGORIES[p['cat']].lower()}, classic</p></div></div>{TABS_JS}"""
                self._page(p["name"], body, route="product/product", base=True)

            def _cart(self, q, message=""):
                s = self.s
                if q.get("remove"):  # (a GET link that changes the cart: never followed by the crawler)
                    s["cart"].pop(q["remove"], None)
                    return self._go("index.php?rt=checkout/cart")
                if not s["cart"]:
                    return self._page("Shopping Cart", "<h1>Shopping Cart</h1>" + message
                                      + "<p>Your shopping cart is empty!</p>", route="checkout/cart")
                rows = []
                for key, qty in s["cart"].items():
                    pid, _, opt = key.partition(":")
                    p = shop.product(pid)
                    opt_text = dict(OPTIONS.get(p["option"]) or []).get(opt, "")
                    rows.append(f"""<tr><td><img src="{PICTURE}" alt="" width="40" height="30"></td>
<td class="align_left"><a href="index.php?rt=product/product&amp;product_id={p['id']}">{html.escape(p['name'])}</a>
{f'<div><small>- {p["option"]}: {opt_text}</small></div>' if opt_text else ''}</td><td>MODEL-{p['id']}</td>
<td class="align_right">{self._money(p['price'])}</td>
<td><input type="text" name="quantity[{key}]" value="{qty}" size="2" class="short" aria-label="Quantity"></td>
<td class="align_right">{self._money(p['price'] * qty)}</td>
<td><a href="index.php?rt=checkout/cart&amp;remove={quote(key)}" class="btn btn-sm" title="Remove">&#128465; Remove</a></td></tr>""")
                total = self._money(shop.total(s))
                body = f"""<h1>Shopping Cart</h1>{message}<form id="cart" action="index.php?rt=checkout/cart" method="post">
<table class="table cart"><tr><th>Image</th><th>Name</th><th>Model</th><th>Unit Price</th><th>Quantity</th><th>Total</th><th>Remove</th></tr>
{''.join(rows)}</table><button id="cart_update" type="submit" class="btn" title="Update">Update</button></form>
<table id="totals_table"><tr><td>Sub-Total:</td><td>{total}</td></tr><tr><td><b>Total:</b></td><td class="total">{total}</td></tr></table>
<a href="index.php?rt=checkout/checkout" id="cart_checkout1" class="btn btn-orange">Checkout</a>"""
                self._page("Shopping Cart", body, route="checkout/cart")

            def _login(self, error: str):
                return self._page("Account Login", LOGIN_PAGE.format(
                    error=f'<div class="alert alert-error"><button type="button" class="close">&times;</button>{error}</div>'
                    if error else ""), route="account/login")

            # ---------------------------------------------------------------- POST
            def do_POST(self):
                self.s = self._session()
                u = urlparse(self.path)
                route = {k: v[0] for k, v in parse_qs(u.query).items()}.get("rt", "")
                shop.visited.append("POST " + route)
                f = self._form()
                if route == "checkout/cart":
                    if "product_id" in f:  # Add to Cart
                        p = shop.product(f["product_id"])
                        if not p:
                            return self._send(400, "unknown product")
                        qty = int(f["quantity"]) if (f.get("quantity") or "").isdigit() and int(f["quantity"]) > 0 else 1
                        if p["option"] and not f.get("option"):
                            return self._product({"product_id": p["id"]}, "Please select all required options!")
                        key = f"{p['id']}:{f.get('option', '')}"
                        self.s["cart"][key] = self.s["cart"].get(key, 0) + qty
                        if self.headers.get("X-Requested-With") == "XMLHttpRequest":
                            return self._send(200, json.dumps({
                                "count": sum(self.s["cart"].values()), "total": self._money(shop.total(self.s)),
                                "lines": self._top_lines()}), ctype="application/json")
                        return self._go("index.php?rt=checkout/cart")
                    for k, v in f.items():  # Update: the quantity boxes
                        if k.startswith("quantity[") and k[9:-1] in self.s["cart"]:
                            if v.isdigit() and int(v) > 0:
                                self.s["cart"][k[9:-1]] = int(v)
                    return self._go("index.php?rt=checkout/cart")
                if route == "account/login":
                    if f.get("account") == "register":
                        return self._go("index.php?rt=account/create")
                    if f.get("account") == "guest":
                        return self._go("index.php?rt=checkout/cart")
                    if f.get("loginname") == EMAIL and f.get("password") == PASSWORD:
                        self.s["user"] = EMAIL
                        return self._go("index.php?rt=account/account")
                    return self._login("Error: Incorrect login or password provided.")
                if route == "account/invoice":
                    if not f.get("order_id") or not f.get("email"):
                        return self._page("Order Details", INVOICE_FORM.format(
                            error='<div class="alert alert-error">Please enter the Order ID and the E-Mail of the '
                                  'order.</div>'), route=route)
                    return self._page("Order Details", "<h1>Order Details</h1><p>No order was found with these "
                                      "details.</p>", route=route)
                # sign-up, contact, newsletter, confirm order: real actions - recorded, never needed by the tester
                return self._page("Not available", "<h1>This action is not available in the practice shop.</h1>",
                                  405, route)

        return Handler


LOGIN_PAGE = """<ul class="breadcrumb"><li><a href="index.php">Home</a></li><li><a href="index.php?rt=account/login">Login</a></li></ul>
<h1>Account Login</h1>{error}
<div class="newcustomer"><h2>I am a new customer.</h2><p>Checkout Options:</p>
<form id="accountFrm" action="index.php?rt=account/login" method="post">
 <label><input type="radio" id="accountFrm_accountregister" name="account" value="register" checked> Register Account</label>
 <label><input type="radio" id="accountFrm_accountguest" name="account" value="guest"> Guest Checkout</label>
 <button type="submit" class="btn btn-orange" title="Continue">Continue</button></form></div>
<div class="returncustomer"><h2>Returning Customer</h2><p>I am a returning customer.</p>
<form id="loginFrm" action="index.php?rt=account/login" method="post">
 <label for="loginFrm_loginname">Login Name:</label> <input type="text" name="loginname" id="loginFrm_loginname">
 <label for="loginFrm_password">Password:</label> <input type="password" name="password" id="loginFrm_password">
 <button type="submit" class="btn btn-orange" title="Login">Login</button></form></div>"""

REGISTER_FORM = """<h1>Create Account</h1><form id="AccountFrm" action="index.php?rt=account/create" method="post">
<label for="AccountFrm_firstname">First Name:</label> <input type="text" id="AccountFrm_firstname" name="firstname" required>
<label for="AccountFrm_lastname">Last Name:</label> <input type="text" id="AccountFrm_lastname" name="lastname" required>
<label for="AccountFrm_email">E-Mail:</label> <input type="text" id="AccountFrm_email" name="email" required>
<label for="AccountFrm_loginname">Login name:</label> <input type="text" id="AccountFrm_loginname" name="loginname" required>
<label for="AccountFrm_password">Password:</label> <input type="password" id="AccountFrm_password" name="password" required>
<label for="AccountFrm_confirm">Password Confirm:</label> <input type="password" id="AccountFrm_confirm" name="confirm" required>
<label><input type="checkbox" id="AccountFrm_agree" name="agree" value="1"> I have read and agree to the Privacy Policy</label>
<button type="submit" class="btn btn-orange" title="Continue">Continue</button></form>"""

INVOICE_FORM = """<h1>Order Details</h1>{error}<p>Check the status of your order.</p>
<form id="CheckOrderFrm" action="index.php?rt=account/invoice" method="post">
<label for="CheckOrderFrm_order_id">Order ID:</label> <input type="text" id="CheckOrderFrm_order_id" name="order_id" required>
<label for="CheckOrderFrm_email">E-Mail:</label> <input type="text" id="CheckOrderFrm_email" name="email" required>
<button type="submit" class="btn btn-orange" title="Continue">Continue</button></form>"""

CONTACT_FORM = """<h1>Contact Us</h1><form id="ContactUsFrm" action="index.php?rt=content/contact" method="post">
<label for="ContactUsFrm_first_name">First name:</label> <input type="text" id="ContactUsFrm_first_name" name="first_name" required>
<label for="ContactUsFrm_email">Email:</label> <input type="email" id="ContactUsFrm_email" name="email" required>
<label for="ContactUsFrm_enquiry">Enquiry:</label> <textarea id="ContactUsFrm_enquiry" name="enquiry" required></textarea>
<button type="submit" class="btn btn-orange" title="Submit">Submit</button></form>"""


if __name__ == "__main__":
    shop = ClassicShop(int(sys.argv[1]) if len(sys.argv) > 1 else 8767, bugs="bugs" in sys.argv[2:]).start()
    print(f"ClassicShop{' WITH PLANTED BUGS' if shop.bugs else ''} running at {shop.url}  "
          f"(login '{EMAIL}', password '{PASSWORD}') - press Ctrl+C to stop")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        shop.stop()
