"""A small shop as Android Chrome shows it, driven through the same WebDriver calls Blow AI makes (no device).

The page inventory is what backend.android_web.DOM_SCRIPT returns from a real page, built in Python from a page model:
a phone menu button ("Categories") with a sub-menu, footer sections that open on a tap, product cards, a product page
with a quantity box and controls below the first screen, a cart that really adds / updates / removes, search, sort,
register / login / log out, a contact form, a newsletter box, a JavaScript alert after Add to cart, and Checkout /
Place order buttons that must never be pressed. An optional bot-check page (Cloudflare "Just a moment...") can clear
after some reads, only when a person completes it, or never.

`dialogs=True` makes it demoblaze-like (run android_20261110_113902_88059d): "Log in", "Sign up" and "Contact" are
`<a href="#">` navbar links that open a pop-up dialog whose boxes sit outside any <form>, with "×" and "Close" buttons
before a type=button submit, answering with browser alerts ("Sign up successful.", "User does not exist.", "Wrong
password.", "Thanks for the message!!") and a "Welcome <user>" text after the login. `toggle_bug=True` repeats the
page reader's old mistake (the links flagged as menu toggles; Contact a plain toggle without the dialog flag).
"""

import re
from urllib.parse import parse_qs, urlsplit

from selenium.common.exceptions import (
    NoAlertPresentException,
    StaleElementReferenceException,
    UnexpectedAlertPresentException,
)

from backend.android_web import CLEAR_STORAGE, DOM_SCRIPT, SCROLL_STEP

BASE = "https://shop.example.test"
VIEW = 800  # the phone's screen height in CSS pixels
PRODUCTS = {"/laptop-pro": ("Laptop Pro", 1200), "/desk-lamp": ("Desk Lamp", 40), "/coffee-mug": ("Coffee Mug", 9)}
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)


def node(sel, tag, text="", **extra):
    return {"sel": sel, "tag": tag, "text": text, **extra}


class Live:
    """An element of the page it was found on: after the page changes it is stale, as in a real browser."""

    def __getattribute__(self, name):
        if (not name.startswith("_") and name not in ("shop", "page")
                and object.__getattribute__(self, "page") != object.__getattribute__(self, "shop").generation):
            raise StaleElementReferenceException("stale element reference: the page was replaced")
        return object.__getattribute__(self, name)


class FakeElement(Live):
    def __init__(self, shop, item):
        self.shop, self.item = shop, item
        self.page = shop.generation
        self.id = "el-" + item["sel"]

    @property
    def tag_name(self):
        return self.item["tag"]

    @property
    def text(self):
        self.shop.command()
        return "" if self.item.get("input") else self.item.get("text", "")

    def is_displayed(self):
        return True

    def is_enabled(self):
        return True

    def is_selected(self):
        return bool(self.shop.fields.get(self.item["sel"], self.item.get("checked")))

    def get_property(self, name):
        if name == "value":
            return self.shop.fields.get(self.item["sel"], "")
        if name == "tagName":
            return self.item["tag"].upper()
        return None

    def get_dom_attribute(self, name):
        return None

    def get_attribute(self, name):
        keys = {"id": self.item.get("dom_id", ""), "name": self.item.get("name", ""),
                "aria-label": self.item.get("label", ""), "type": self.item.get("type", ""), "title": "",
                "href": self.shop.url(self.item["href"]) if self.item.get("href") else "",
                "value": self.item.get("value", ""), "class": self.item.get("cls", "")}
        return keys.get(name)

    def clear(self):
        self.shop.fields[self.item["sel"]] = ""

    def send_keys(self, value):
        self.shop.fields[self.item["sel"]] = self.shop.fields.get(self.item["sel"], "") + value

    def click(self):
        self.shop.command()
        self.shop.click(self.item)

    def find_elements(self, _by, value):
        # Selenium's Select helper: the options of this drop-down
        options = [FakeOption(self.shop, self.item, option) for option in self.item.get("options", [])]
        match = re.search(r'value\s*=\s*"([^"]*)"', value)
        return [o for o in options if o.option["value"] == match.group(1)] if match else options


class FakeOption(Live):
    def __init__(self, shop, select, option):
        self.shop, self.select, self.option = shop, select, option
        self.page = shop.generation
        self.tag_name = "option"

    @property
    def text(self):
        return self.option["text"]

    def is_displayed(self):
        return True

    def is_enabled(self):
        return True

    def is_selected(self):
        return self.option.get("selected", False)

    def get_attribute(self, name):
        return self.option.get(name)

    def get_property(self, name):
        return "OPTION" if name == "tagName" else self.option.get(name)

    def click(self):
        self.shop.choose(self.select, self.option["value"])


class FakeAlert:
    def __init__(self, shop):
        self.shop = shop
        self.text = shop.alert

    def accept(self):
        self.shop.alert = None

    def dismiss(self):
        self.shop.alert = None


class SwitchTo:
    """driver.switch_to: the open JavaScript alert, if any."""

    def __init__(self, shop):
        self.shop = shop

    @property
    def alert(self):
        if self.shop.alert is None:
            raise NoAlertPresentException()
        return FakeAlert(self.shop)

    def context(self, _name):
        pass


class FakeShop:
    """The website and the browser in one: `driver` methods are the WebDriver calls Blow AI uses."""

    current_context = "CHROMIUM"
    capabilities = {"platformVersion": "16"}

    def __init__(self, bot: str = "", bot_reads: int = 3, dialogs: bool = False, toggle_bug: bool = False):
        self.bot, self.bot_reads = bot, bot_reads  # "" | "clears" | "person" | "never"
        self.dialogs, self.toggle_bug = dialogs, toggle_bug
        self.dialog = ""  # the open pop-up: "login" | "signup" | "contact" | ""
        self.accounts = {}
        self.path, self.query = "/", {}
        self.sid = 0
        self.sessions = {}
        self.cookies = {"cf_clearance": True}
        self.fields, self.storage = {}, {"seen": "1"}
        self.alert = None
        self.menu = self.sub = self.footer = False
        self.message = ""
        self.scroll = 0
        self.pressed = []        # every control tapped, by its text / selector (checked by the tests)
        self.resets = 0
        self.generation = 0
        self.switch_to = SwitchTo(self)

    # -------- the browser
    def command(self):
        """Chrome's answer to a WebDriver call while an alert is open: it closes it and says so."""
        if self.alert is not None:
            text, self.alert = self.alert, None
            raise UnexpectedAlertPresentException(alert_text=text)

    @property
    def session(self):
        if "sid" not in self.cookies:
            self.sid += 1
            self.cookies["sid"] = self.sid
        return self.sessions.setdefault(self.cookies["sid"], {"cart": {}, "user": None, "wishlist": 0})

    def url(self, path):
        return path if path.startswith("http") else BASE + path

    @property
    def current_url(self):
        self.command()
        query = "&".join(f"{k}={v}" for k, v in self.query.items())
        return BASE + self.path + ("?" + query if query else "") if not self.path.startswith("http") else self.path

    @property
    def title(self):
        self.command()
        return self.inventory()["title"]

    def get(self, url):
        self.command()
        parts = urlsplit(url)
        if parts.netloc and parts.netloc != urlsplit(BASE).netloc:
            self.path, self.query = url, {}
            return
        self.go(parts.path or "/", {k: v[0] for k, v in parse_qs(parts.query).items()})

    def go(self, path, query=None):
        self.path, self.query, self.message = path, query or {}, ""
        self.fields, self.menu, self.sub, self.footer, self.scroll = {}, False, False, False, 0
        self.dialog = ""
        self.generation += 1
        if path == "/logout":
            self.session["user"] = None
            self.path = "/"
        if path.startswith("/customer") and not self.session["user"]:
            self.path, self.query = "/login", {"returnUrl": path}

    def get_cookies(self):
        self.command()
        return [{"name": name} for name in self.cookies]

    def delete_cookie(self, name):
        self.cookies.pop(name, None)
        if name == "sid":
            self.resets += 1

    def execute_script(self, script, *args):
        if script == DOM_SCRIPT:
            self.command()
            if self.bot and self.bot_reads != 0 and not self.path.startswith("http"):
                if self.bot == "clears":
                    self.bot_reads -= 1
                return self.interstitial()
            data = self.inventory(test_mode=bool(args and args[0].get("test_mode")))
            return data
        self.command()
        if script == CLEAR_STORAGE:
            self.storage.clear()
            return True
        if script == SCROLL_STEP:
            total = self.inventory()["viewport"]["page_height"]
            self.scroll = min(total - VIEW, self.scroll + int(VIEW * 0.8))
            return [self.scroll, VIEW, total]
        if script.startswith("window.scrollTo"):
            self.scroll = 0
            return True
        return None

    def find_elements(self, _using, value):
        self.command()
        if value == "html":
            return [FakeElement(self, node("html", "html"))]
        items = self.inventory()["_nodes"]
        if value.endswith(" option:checked"):
            select = next((i for i in items if i["sel"] == value[:-len(" option:checked")]), None)
            option = next((o for o in (select or {}).get("options", []) if o.get("selected")), None)
            return [FakeOption(self, select, option)] if option else []
        return [FakeElement(self, i) for i in items if i["sel"] == value]

    def save_screenshot(self, path):
        with open(path, "wb") as image:
            image.write(b"png")
        return True

    def quit(self):
        pass

    def back(self):
        self.go("/")

    # -------- what a tap does
    def click(self, item):
        self.pressed.append(item.get("text") or item.get("label") or item["sel"])
        session = self.session
        action = item.get("do")
        if action and action.startswith("dialog:"):
            self.dialog = action[len("dialog:"):]  # a pop-up opens; "" closes it (the "×" / Close button)
            return
        if action == "logout2":
            session["user"] = None  # demoblaze logs out by script, staying on the page
            return
        if item.get("href"):
            return self.get(self.url(item["href"]))
        if action == "menu":
            self.menu = not self.menu
        elif action == "sub":
            self.sub = not self.sub
        elif action == "footer":
            self.footer = not self.footer
        elif action and action.startswith("add:"):
            path = action[4:]
            qty = int(self.fields.get("#qty", "1") or 1) if self.path == path else 1
            session["cart"][path] = session["cart"].get(path, 0) + qty
            self.alert = "The product has been added to your cart"
        elif action == "wishlist":
            session["wishlist"] += 1
        elif action == "update":
            for index, path in enumerate(list(session["cart"]), 1):
                value = self.fields.get(f"#cart > tr:nth-of-type({index}) > td > input")
                if value and value.isdigit():
                    session["cart"][path] = int(value)
        elif action and action.startswith("remove:"):
            session["cart"].pop(action[7:], None)
        elif action in ("checkout", "place"):
            pass  # recorded in self.pressed; the tests prove it never happens
        elif action == "search":
            self.go("/search", {"q": self.fields.get("#q", "")})
        elif action == "subscribe":
            email = self.fields.get("#newsletter-email", "")
            self.message = "Thank you for signing up!" if EMAIL.match(email) else "Enter a valid email"
        elif action == "register":
            self.register()
        elif action == "login":
            self.login()
        elif action == "login2":
            self.login_dialog()
        elif action == "signup2":
            self.signup_dialog()
        elif action == "send":
            self.send_message()
        elif action == "contact":
            name, email, text = (self.fields.get(k, "") for k in ("#contact-name", "#contact-email", "#enquiry"))
            self.message = ("Your enquiry has been successfully sent" if name and EMAIL.match(email) and text
                            else "Please fill in every box with valid details")

    def choose(self, select, value):
        if select["sel"] == "#orderby":
            self.go(self.path, {"orderby": value})

    def register(self):
        first, last, email = (self.fields.get(k, "") for k in ("#FirstName", "#LastName", "#Email"))
        password, confirm = self.fields.get("#Password", ""), self.fields.get("#ConfirmPassword", "")
        if not (first and last and EMAIL.match(email) and len(password) >= 6 and password == confirm):
            self.message = "Please correct the errors in the form"
        elif email in self.accounts:
            self.message = "The specified email already exists"
        else:
            self.accounts[email] = password
            self.session["user"] = email
            self.go("/registerresult")

    def login(self):
        email, password = self.fields.get("#LoginEmail", ""), self.fields.get("#LoginPassword", "")
        if not email:
            self.message = "Please enter your email"
        elif self.accounts.get(email) != password:
            self.message = "Login was unsuccessful."
        else:
            self.session["user"] = email
            self.go("/")

    # the demoblaze-like pop-up dialogs (dialogs=True)
    def login_dialog(self):
        user, password = self.fields.get("#loginusername", ""), self.fields.get("#loginpassword", "")
        if not user or not password:
            self.alert = "Please fill out Username and Password."
        elif user not in self.accounts:
            self.alert = "User does not exist."
        elif self.accounts[user] != password:
            self.alert = "Wrong password."
        else:
            self.session["user"] = user
            self.dialog = ""

    def signup_dialog(self):
        user, password = self.fields.get("#sign-username", ""), self.fields.get("#sign-password", "")
        if not user or not password:
            self.alert = "Please fill out Username and Password."
        elif user in self.accounts:
            self.alert = "This user already exist."
        else:
            self.accounts[user] = password
            self.alert = "Sign up successful."
            self.dialog = ""

    def send_message(self):
        # demoblaze checks nothing: an empty message is thanked for too (the tester records that as a finding)
        self.alert = "Thanks for the message!!"
        self.dialog = ""

    def dialog_links(self, user):
        """The navbar's dialog openers, as the page reader sees them (or saw them, with toggle_bug)."""
        bug = self.toggle_bug
        if user:
            links = [node("#nameofuser", "a", f"Welcome {user}", region="nav"),
                     node("#logout2", "a", "Log out", href="#", do="logout2", region="nav")]
        else:
            links = [node("#login2", "a", "Log in", href="#", do="dialog:login", region="nav", opens_dialog=True,
                          toggle=bug),
                     node("#signin2", "a", "Sign up", href="#", do="dialog:signup", region="nav", opens_dialog=True,
                          toggle=bug)]
        # With the reader's mistake, Contact is a plain menu toggle (no dialog flag) that happens to open a dialog
        links.append(node("#contact2", "a", "Contact", href="" if bug else "#", do="dialog:contact", region="nav",
                          opens_dialog=not bug, toggle=bug))
        return links

    def modal(self):
        """The open pop-up: boxes outside any <form>, "×" and Close before the type=button submit (demoblaze)."""
        kind = self.dialog
        if not kind:
            return []
        box = {"login": "#logInModal", "signup": "#signInModal", "contact": "#exampleModal"}[kind]
        title = {"login": "Log in", "signup": "Sign up", "contact": "New message"}[kind]

        def part(sel, tag, text="", **extra):
            return node(sel, tag, text, region="dialog", group=box, **extra)
        items = [part(box + " h5", "h5", title, kind="text"), part(box + " button.close", "button", "×", label="Close",
                                                                    do="dialog:")]
        if kind == "login":
            items += [part("#loginusername", "input", input=True, type="text", label="Username:"),
                      part("#loginpassword", "input", input=True, type="password", label="Password:")]
            submit = part(box + " button.btn-primary", "button", "Log in", do="login2")
        elif kind == "signup":
            items += [part("#sign-username", "input", input=True, type="text", label="Username:"),
                      part("#sign-password", "input", input=True, type="password", label="Password:")]
            submit = part(box + " button.btn-primary", "button", "Sign up", do="signup2")
        else:
            items += [part("#recipient-email", "input", input=True, type="text", label="Contact Email:"),
                      part("#recipient-name", "input", input=True, type="text", label="Contact Name:"),
                      part("#message-text", "textarea", input=True, type="textarea", label="Message:")]
            submit = part(box + " button.btn-primary", "button", "Send message", do="send")
        return items + [part(box + " button.btn-secondary", "button", "Close", do="dialog:"), submit]

    # -------- the pages
    def interstitial(self):
        return {"url": self.current_url, "title": "Just a moment...", "ready": "complete", "busy": 0, "total": 3,
                "elements": [self.element(node("h2", "h2", "Performing security verification"), 0)],
                "texts": [], "viewport": {"height": VIEW, "width": 400, "scroll_y": 0, "page_height": VIEW},
                "challenge": {"frames": ["challenges.cloudflare.com"], "markers": ["#challenge-running"], "groups": [],
                              "text": "shop.example.test\nPerforming security verification\nThis website uses a "
                                      "security service to protect against malicious bots. Ray ID: 9a"}}

    def page(self):
        session, user = self.session, self.session["user"]
        if self.dialogs:
            header = self.dialog_links(user)
        else:
            header = [node("a.ico-register", "a", "Register", href="/register", region="header")]
            if user:
                header += [node("a.ico-account", "a", "My account", href="/customer/info", region="header"),
                           node("a.ico-logout", "a", "Log out", href="/logout", region="header")]
            else:
                header.append(node("a.ico-login", "a", "Log in", href="/login", region="header"))
        count = sum(session["cart"].values())
        header += [node("a.ico-cart", "a", "Shopping cart", href="/cart", region="header"),
                   node("span.cart-qty", "span", f"({count})", region="header", kind="text"),
                   node("#q", "input", input=True, type="text", label="Search store", region="header", group="#search"),
                   node("#search-button", "button", "Search", do="search", region="header", group="#search",
                        submission=True),
                   node("div.menu-toggle", "div", "Categories", do="menu", toggle=True, region="nav")]
        if self.menu:
            header += [node('a[href="/computers"]', "a", "Computers", href="/computers", region="nav"),
                       node("div.sublist-toggle", "div", "", label="Show the Computers sub-menu", do="sub",
                            toggle=True, region="nav")]
            if self.sub:
                header.append(node('a[href="/desktops"]', "a", "Desktops", href="/desktops", region="nav"))
            header.append(node('a[href="/books"]', "a", "Books", href="/books", region="nav"))
        footer = [node("div.footer-title", "div", "Information", do="footer", toggle=True, region="footer")]
        if self.footer:
            footer += [node('a[href="/about-us"]', "a", "About us", href="/about-us", region="footer"),
                       node('a[href="/contactus"]', "a", "Contact us", href="/contactus", region="footer"),
                       node('a[href="/privacy"]', "a", "Privacy notice", href="/privacy", region="footer"),
                       node('a[href="https://facebook.com/shop"]', "a", "Facebook", href="https://facebook.com/shop",
                            region="footer")]
        footer += [node('a[href="/sitemap"]', "a", "Sitemap", href="/sitemap", region="footer"),
                   node('a[href="/onepagecheckout"]', "a", "Go to checkout", href="/onepagecheckout", region="footer"),
                   node("#newsletter-email", "input", input=True, type="email", label="Sign up for our newsletter",
                        region="footer", group="#newsletter"),
                   node("#newsletter-subscribe", "button", "Subscribe", do="subscribe", region="footer",
                        group="#newsletter")]
        title, main = self.main()
        if self.message:
            main.insert(0, node("div.message", "div", self.message, kind="text", message=True))
        return title, header + main + footer + self.modal()

    def main(self):
        path, session = self.path, self.session
        if path == "/":
            items = [node("h2.welcome", "h2", "Welcome to our store")]
            for index, (href, (name, _)) in enumerate(PRODUCTS.items(), 1):
                card = f"div.grid > div.card:nth-of-type({index})"
                items += [node(f'a[href="{href}"]', "a", name, href=href, pos=card + " > h2 > a"),
                          node(card + " > button", "button", "Add to cart", do="add:" + href, pos=card + " > button")]
            return "Shop. Home", items
        if path in PRODUCTS:
            name, price = PRODUCTS[path]
            items = [node("h1.product-name", "h1", name), node("span.price", "span", f"${price}", kind="text"),
                     node("#qty", "input", input=True, type="text", label="Qty", name="qty", group="#product-form"),
                     node("#add-to-cart", "button", "Add to cart", do="add:" + path, group="#product-form"),
                     node("#add-to-wishlist", "button", "Add to wishlist", do="wishlist", group="#product-form"),
                     node("span.wishlist-qty", "span", f"Wishlist ({session['wishlist']})", kind="text")]
            items += [node(f"p.spec:nth-of-type({i})", "p", f"Specification line {i}", kind="text") for i in range(1, 15)]
            items.append(node('a[href="/reviews"]', "a", "Read the reviews", href="/reviews"))
            return f"Shop. {name}", items
        if path == "/cart":
            if not session["cart"]:
                return "Shop. Shopping cart", [node("h1", "h1", "Shopping cart"),
                                               node("div.empty", "div", "Your Shopping Cart is empty!", kind="text")]
            items = [node("h1", "h1", "Shopping cart")]
            for index, (href, qty) in enumerate(session["cart"].items(), 1):
                row = f"#cart > tr:nth-of-type({index})"
                items += [node(row + " > td > a", "a", PRODUCTS[href][0], href=href, kind="text"),
                          node(row + " > td > input", "input", input=True, type="text", label="Qty.", value=str(qty),
                               group="#cart-form"),
                          node(row + " > td > button", "button", "", icon="remove btn remove from cart",
                               do="remove:" + href, group="#cart-form"),
                          node(row + " > td > span", "span", f"${PRODUCTS[href][1] * qty}", kind="text")]
            items += [node("#updatecart", "button", "Update shopping cart", do="update", group="#cart-form"),
                      node("#checkout", "button", "Checkout", do="checkout", group="#cart-form"),
                      node("#place-order", "button", "Place order", do="place", group="#cart-form")]
            return "Shop. Shopping cart", items
        if path in ("/computers", "/search"):
            names = sorted(n for n, _ in PRODUCTS.values())
            if path == "/search":
                word = self.query.get("q", "").casefold()
                names = [n for n in names if word and word in n.casefold()]
            elif self.query.get("orderby") != "name":
                names = [n for n, _ in PRODUCTS.values()]
            items = [node("h1", "h1", "Computers" if path == "/computers" else "Search")]
            if path == "/computers":
                items.append(node("#orderby", "select", input=True, type="select", label="Sort by", name="orderby",
                                  options=[{"text": "Position", "value": "position",
                                            "selected": self.query.get("orderby") != "name"},
                                           {"text": "Name: A to Z", "value": "name",
                                            "selected": self.query.get("orderby") == "name"}]))
            if path == "/search" and not names:
                items.append(node("div.no-result", "div", "No products were found", kind="text"))
            items += [node(f"div.list > div.row:nth-of-type({i})", "div", n, kind="text") for i, n in enumerate(names, 1)]
            return "Shop. " + items[0]["text"], items
        if path == "/register":
            return "Shop. Register", [
                node("h1", "h1", "Register"),
                *[node(sel, "input", input=True, type=kind, label=text, group="#register-form", required=True)
                  for sel, kind, text in (("#FirstName", "text", "First name"), ("#LastName", "text", "Last name"),
                                          ("#Email", "email", "Email"), ("#Password", "password", "Password"),
                                          ("#ConfirmPassword", "password", "Confirm password"))],
                node("#register-button", "button", "Register", do="register", group="#register-form", submission=True)]
        if path == "/registerresult":
            return "Shop. Register", [node("h1", "h1", "Your registration completed")]
        if path == "/login":
            return "Shop. Login", [
                node("h1", "h1", "Welcome, please sign in"),
                node("#LoginEmail", "input", input=True, type="email", label="Email", group="#login-form"),
                node("#LoginPassword", "input", input=True, type="password", label="Password", group="#login-form"),
                node("button.login-button", "button", "Log in", do="login", group="#login-form", submission=True)]
        if path == "/customer/info":
            return "Shop. Customer info", [
                node("h1", "h1", "My account - Customer info"),
                node('a[href="/order/history"]', "a", "Orders", href="/order/history", region="aside"),
                node('a[href="/customer/changepassword"]', "a", "Change password", href="/customer/changepassword",
                     region="aside")]
        if path == "/contactus":
            return "Shop. Contact Us", [
                node("h1", "h1", "Contact Us"),
                node("#contact-name", "input", input=True, type="text", label="Your name", group="#contact-form"),
                node("#contact-email", "input", input=True, type="email", label="Your email", group="#contact-form"),
                node("#enquiry", "textarea", input=True, type="textarea", label="Enquiry", group="#contact-form"),
                node("#contact-submit", "button", "Submit", do="contact", group="#contact-form", submission=True)]
        names = {"/about-us": "About us", "/privacy": "Privacy notice", "/sitemap": "Sitemap", "/desktops": "Desktops",
                 "/books": "Books", "/order/history": "My account - Orders", "/reviews": "Product reviews"}
        if path in names:
            return "Shop. " + names[path], [node("h1", "h1", names[path])]
        return "Shop. Page not found", [node("h1", "h1", "Page not found")]

    def element(self, item, y):
        input_type = item.get("type", "")
        return {"selector": item["sel"], "tag": item["tag"], "role": "", "text": "" if item.get("input") else item["text"],
                "text_comparable": True, "focus_only": False, "label": item.get("label", ""),
                # an id only when the selector IS an id (the real reader uses e.id; "#modal button.x" has none)
                "dom_id": item["sel"][1:] if re.fullmatch(r"#[\w-]+", item["sel"]) else "", "input": bool(item.get("input")),
                "enabled": True, "href": self.url(item["href"]) if item.get("href") else "", "expands": False,
                "submission": bool(item.get("submission")), "download": False,
                "clickable": item["tag"] in ("a", "button") or bool(item.get("toggle")),
                "options": [{"text": o["text"], "label": o["text"], "disabled": False, "value": o["value"],
                             "selected": o["selected"]} for o in item.get("options", [])],
                "pos": item.get("pos", item["sel"]), "icon": item.get("icon", ""), "toggle": bool(item.get("toggle")),
                "opens_dialog": bool(item.get("opens_dialog")), "expanded": "", "name": item.get("name", ""),
                "input_type": "select" if item["tag"] == "select" else input_type,
                "checked": False, "required": bool(item.get("required")), "autocomplete": "",
                "href_raw": item.get("href", ""), "region": item.get("region", "main"), "group": item.get("group", ""),
                "page_y": y, "height": 40}

    def inventory(self, test_mode=True):
        title, items = self.page()
        nodes, elements, texts = [], [], []
        for index, item in enumerate(items):
            y = index * 70
            nodes.append(item)
            if item.get("kind") != "text" or item["tag"] == "a":
                elements.append(self.element(item, y))
            if item.get("text") and not item.get("input"):
                texts.append({"selector": item["sel"], "pos": item.get("pos", item["sel"]), "text": item["text"],
                              "region": item.get("region", "main"), "page_y": y, "message": bool(item.get("message"))})
        height = max(VIEW, len(items) * 70)
        return {"url": self.current_url, "title": title, "ready": "complete", "busy": 0, "elements": elements,
                "total": len(elements), "texts": texts, "_nodes": nodes,
                "viewport": {"height": VIEW, "width": 400, "scroll_y": self.scroll, "page_height": height},
                "challenge": {"frames": [], "markers": [], "groups": [], "text": title}}
