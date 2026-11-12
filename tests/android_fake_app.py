"""A small shop app shaped like the Sauce Labs My Demo App, driven through the same Appium calls Blow AI makes.

Products with a menu button (a drawer with Catalog, About, Drawing, QR Code Scanner, Geo Location, FingerPrint,
Reset App State, Log In / Log Out), a Sort button with its options sheet, product cards (picture, title, price, five
rating stars), a product page with - / + and Add To Cart, a cart badge, a cart with + / -, Remove Item and Proceed To
Checkout, an empty-cart screen with Go Shopping, a login screen with sample users (one locked out), a log-out
confirmation, and Android's permission prompt in front of the app for the scanner and location screens. Options:
`keyboard_ime`  the soft keyboard reports its own package while a box has focus;
`cover_password` after a login try the keyboard covers the password box until it is hidden.
"""

import re
from xml.etree import ElementTree

from defusedxml import ElementTree as SafeTree
from selenium.common.exceptions import NoSuchElementException

PACKAGE = "com.example.mydemo"
PERMISSIONS = "com.google.android.permissioncontroller"
IME = "com.google.android.inputmethod.latin"
PRODUCTS = [("Sauce Labs Backpack", 29.99), ("Sauce Labs Bike Light", 9.99), ("Sauce Labs Onesie", 7.99)]
SORTS = {"Name - Ascending": ("name", False), "Name - Descending": ("name", True),
         "Price - Ascending": ("price", False), "Price - Descending": ("price", True)}
MENU = ["Catalog", "About", "Drawing", "QR Code Scanner", "Geo Location", "FingerPrint", "Reset App State"]
USERS = {"bob@example.com": "10203040", "alice@example.com (locked out)": "10203040"}


def rid(name):
    return f"{PACKAGE}:id/{name}"


class Node:
    def __init__(self, cls, key="", text="", desc="", click=False, **extra):
        self.cls, self.key, self.text, self.desc, self.click = cls, key, text, desc, click
        self.extra = extra
        self.children = []

    def add(self, *children):
        self.children.extend(children)
        return self


class FakeAppElement:
    def __init__(self, app, attrs):
        self.app, self.attrs = app, attrs
        self.id = "el-" + attrs.get("blowai", "")

    def is_displayed(self):
        return True

    def is_enabled(self):
        return True

    @property
    def text(self):
        key = self.attrs.get("resource-id", "")
        if self.attrs.get("class", "").endswith("EditText"):
            return self.app.fields.get(key, "") or self.attrs.get("hint", "")
        return self.attrs.get("text", "")

    @property
    def rect(self):
        return {"x": 0, "y": 0, "width": 100, "height": 40}

    def get_attribute(self, name):
        if name == "showing-hint":
            return "true" if not self.app.fields.get(self.attrs.get("resource-id", "")) else "false"
        if name == "class":
            return self.attrs.get("class")
        return {"resource-id": self.attrs.get("resource-id"), "content-desc": self.attrs.get("content-desc"),
                "password": self.attrs.get("password", "false"), "checkable": self.attrs.get("checkable", "false"),
                "checked": self.attrs.get("checked", "false")}.get(name)

    def clear(self):
        self.app.fields[self.attrs.get("resource-id", "")] = ""

    def send_keys(self, value):
        key = self.attrs.get("resource-id", "")
        self.app.fields[key] = self.app.fields.get(key, "") + value
        self.app.keyboard = True

    def click(self):
        self.app.tap(self.attrs)


class FakeDemoApp:
    """The app, Android around it, and the Appium driver calls in one object."""

    current_context = "NATIVE_APP"
    capabilities = {"platformVersion": "16"}

    class SwitchTo:
        def context(self, _name):
            pass

    switch_to = SwitchTo()

    def __init__(self, keyboard_ime=False, cover_password=False, accept_wrong=False, allow_zero=False, prompt_delay=0):
        self.keyboard_ime, self.cover_password, self.accept_wrong = keyboard_ime, cover_password, accept_wrong
        # allow_zero: '-' goes below 1 (live run android_20261110_110821_90cd6d); prompt_delay: the permission
        # prompt is in front for this many lookups before its buttons can be found (it is still opening)
        self.allow_zero, self.prompt_delay, self.prompt_lookups = allow_zero, prompt_delay, 0
        self.pressed, self.declined, self.orientation_changes, self.resets = [], [], 0, 0
        self.reset()

    def reset(self):
        self.screen, self.drawer, self.sheet, self.dialog = "products", False, False, ""
        self.cart, self.qty, self.product, self.order = {}, 1, PRODUCTS[0][0], ("default", False)
        self.user, self.message, self.fields, self.keyboard, self.prompt = None, "", {}, False, ""
        self.covered = False

    # -------- Android around the app
    @property
    def current_package(self):
        if self.prompt:
            return PERMISSIONS
        if self.keyboard and self.keyboard_ime:
            return IME
        return PACKAGE

    current_activity = ".view.activities.MainActivity"

    def is_keyboard_shown(self):
        return self.keyboard

    def hide_keyboard(self):
        self.keyboard, self.covered = False, False

    def back(self):
        if self.prompt:
            self.prompt = ""
        elif self.keyboard:
            self.hide_keyboard()
        elif self.dialog or self.sheet or self.drawer:
            self.dialog, self.sheet, self.drawer = "", False, False
        else:
            self.screen = "products"

    @property
    def orientation(self):
        return "PORTRAIT"

    @orientation.setter
    def orientation(self, _value):
        self.orientation_changes += 1

    def background_app(self, _seconds):
        pass

    def activate_app(self, _package):
        self.prompt = ""

    def terminate_app(self, _package):
        self.screen, self.drawer, self.sheet, self.dialog = "products", False, False, ""

    def execute_script(self, name, args=None):
        if name == "mobile: clearApp":
            self.resets += 1
            self.reset()
        if name == "mobile: getPermissions":
            return []
        return []

    def save_screenshot(self, path):
        with open(path, "wb") as image:
            image.write(b"png")
        return True

    def quit(self):
        pass

    # -------- the screens
    def toolbar(self, title=""):
        bar = Node("android.view.ViewGroup", "toolbar")
        bar.add(Node("android.widget.ImageView", "menuIV", desc="View menu", click=True))
        if self.screen == "products":
            bar.add(Node("android.widget.ImageView", "sortIV",
                         desc="Shows current sorting order and displays available sorting options", click=True))
        cart = Node("android.widget.RelativeLayout", "cartRL", desc="View cart", click=True)
        if self.cart:
            cart.add(Node("android.widget.TextView", "cartTV", text=str(sum(self.cart.values()))))
        bar.add(cart)
        if title:
            bar.add(Node("android.widget.TextView", "productTV" if self.screen == "products" else "titleTV",
                         text=title, desc="title" if self.screen == "products" else ""))
        return bar

    def products(self):
        items = sorted(PRODUCTS, key=lambda p: p[0 if self.order[0] == "name" else 1],
                       reverse=self.order[1]) if self.order[0] != "default" else PRODUCTS
        listing = Node("androidx.recyclerview.widget.RecyclerView", "productRV",
                       desc="Displays all products of catalog", scrollable="true")
        for name, price in items:
            card = Node("android.view.ViewGroup")
            card.add(Node("android.widget.ImageView", "productIV", desc="Product Image", click=True, product=name),
                     Node("android.widget.TextView", "titleTV", text=name, desc="Product Title"),
                     Node("android.widget.TextView", "priceTV", text=f"$ {price}", desc="Product Price"),
                     *[Node("android.widget.ImageView", f"start{i}IV", click=True, star=True) for i in range(1, 6)])
            listing.add(card)
        # The real app gives Products and Login the same scroll view description (it names a "screen")
        return [self.toolbar("Products"), Node("android.widget.ScrollView", "scrollView", scrollable="true",
                                               desc="Scrollview manages views in given screen size").add(listing)]

    def page(self):
        if self.screen == "products":
            nodes = self.products()
        elif self.screen == "detail":
            price = dict(PRODUCTS)[self.product]
            nodes = [self.toolbar(), Node("android.widget.ScrollView", "scrollView", scrollable="true").add(
                Node("android.widget.TextView", "productTV", text=self.product),
                Node("android.widget.TextView", "priceTV", text=f"$ {price}"),
                Node("android.widget.ImageView", "minusIV", desc="Decrease item quantity", click=True),
                Node("android.widget.TextView", "noTV", text=str(self.qty)),
                Node("android.widget.ImageView", "plusIV", desc="Increase item quantity", click=True),
                Node("android.widget.Button", "cartBt", text="Add To Cart", desc="Tap to add product to cart",
                     click=True))]
        elif self.screen == "cart" and self.cart:
            nodes = [self.toolbar("My Cart")]
            for index, (name, qty) in enumerate(self.cart.items()):
                nodes.append(Node("android.view.ViewGroup").add(
                    Node("android.widget.TextView", "titleTV" if index == 0 else f"titleTV{index}", text=name),
                    Node("android.widget.TextView", "noTV", text=str(qty)),
                    Node("android.widget.ImageView", "plusIV", desc="Increase item quantity", click=True),
                    Node("android.widget.ImageView", "minusIV", desc="Decrease item quantity", click=True),
                    Node("android.widget.TextView", "removeBt", text="Remove Item", desc="Removes product from cart",
                         click=True)))
            total = sum(dict(PRODUCTS)[n] * q for n, q in self.cart.items())
            nodes += [Node("android.widget.TextView", "totalPriceTV", text=f"$ {total:.2f}"),
                      Node("android.widget.Button", "cartBt", text="Proceed To Checkout",
                           desc="Confirms products for checkout", click=True)]
        elif self.screen == "cart":
            nodes = [self.toolbar(), Node("android.widget.TextView", "noItemTitleTV", text="No Items"),
                     Node("android.widget.TextView", "noItemDescTV", text="Oh no! Your cart is empty."),
                     Node("android.widget.Button", "shoppingBt", text="Go Shopping", click=True)]
        elif self.screen == "login":
            nodes = [self.toolbar("Login"), Node("android.widget.ScrollView", "scrollView", scrollable="true",
                                                 desc="Scrollview manages views in given screen size")]
            nodes[1].add(*self.login_nodes())
        else:
            nodes = self.other_page()
        return self.overlays(nodes)

    def login_nodes(self):
        nodes = [Node("android.widget.TextView", "instructionTV",
                      text="Select a username and password from the list below, or click on the usernames to "
                           "automatically populate the username and password.")]
        for index, (user, password) in enumerate(USERS.items(), 1):
            nodes += [Node("android.widget.TextView", f"username{index}TV", text=user, click=True),
                      Node("android.widget.TextView", f"password{index}TV", text=password)]
        nodes += [Node("android.widget.EditText", "nameET", hint="Username")]
        if not self.covered:
            nodes.append(Node("android.widget.EditText", "passwordET", hint="Password", password="true"))
        nodes.append(Node("android.widget.Button", "loginBtn", text="Login", desc="Tap to login with given credentials",
                          click=True))
        if self.message:
            nodes.append(Node("android.widget.TextView", "errorTV", text=self.message))
        return nodes

    def other_page(self):
        titles = {"about": "About", "drawing": "Drawing", "qr": "QR Code Scanner", "geo": "Geo Location",
                  "fingerprint": "FingerPrint"}
        nodes = [self.toolbar(titles[self.screen])]
        if self.screen == "drawing":
            nodes.append(Node("android.widget.Button", "clearBt", text="Clear", click=True))
        if self.screen == "qr":
            nodes.append(Node("android.widget.Button", "scanBt", text="Scan a QR code", click=True))
        if self.screen == "geo":
            nodes.append(Node("android.widget.Button", "locateBt", text="Show my location", click=True))
        if self.screen == "fingerprint":
            nodes.append(Node("android.widget.Switch", "fingerSw", text="Use fingerprint to login", click=True,
                              checkable="true"))
        return nodes

    def overlays(self, nodes):
        if self.sheet:
            sheet = Node("android.widget.FrameLayout", "sortSheet")
            sheet.add(Node("android.widget.TextView", "sortTV", text="Sort by:"))
            for index, label in enumerate(SORTS, 1):
                sheet.add(Node("android.widget.TextView", f"sortOption{index}", text=label, click=True))
            nodes.append(sheet)
        if self.dialog:
            dialog = Node("android.widget.FrameLayout", "android:id/parentPanel")
            if self.dialog == "review":
                dialog.add(Node("android.widget.TextView", "sortTV", text="Thank you for submitting your review!"),
                           Node("android.widget.Button", "closeBt", text="Continue", desc="Closes review dialog",
                                click=True))
            elif self.dialog == "logout":
                dialog.add(Node("android.widget.TextView", "android:id/alertTitle", text="Log Out"),
                           Node("android.widget.TextView", "android:id/message", text="Are you sure you want to logout?"),
                           Node("android.widget.Button", "android:id/button1", text="LOGOUT", click=True),
                           Node("android.widget.Button", "android:id/button2", text="CANCEL", click=True))
            elif self.dialog == "loggedout":
                dialog.add(Node("android.widget.TextView", "android:id/message", text="You are successfully logged out."),
                           Node("android.widget.Button", "android:id/button1", text="OK", click=True))
            nodes.append(dialog)
        if self.drawer:
            drawer = Node("androidx.recyclerview.widget.RecyclerView", "menuRV", desc="Recycler view for menu")
            for label in MENU + ["Log Out" if self.user else "Log In"]:
                drawer.add(Node("android.widget.TextView", "itemTV", text=label, click=True,
                                desc=f"{label} Menu Item".replace(" ", "")[:40] if label in ("Log In", "Log Out") else ""))
            return [Node("androidx.drawerlayout.widget.DrawerLayout", "drawer").add(*nodes, drawer)]
        return nodes

    def prompt_xml(self):
        return ('<hierarchy><node package="' + PERMISSIONS + '" class="android.widget.TextView" '
                'resource-id="com.android.permissioncontroller:id/permission_message" text="Allow My Demo App to '
                + self.prompt + '?" bounds="[0,0][1080,100]"/>'
                '<node package="' + PERMISSIONS + '" class="android.widget.Button" resource-id="com.android.'
                'permissioncontroller:id/permission_allow_foreground_only_button" text="While using the app" '
                'clickable="true" bounds="[0,100][1080,200]"/>'
                '<node package="' + PERMISSIONS + '" class="android.widget.Button" resource-id="com.android.'
                'permissioncontroller:id/permission_deny_button" text="Don’t allow" clickable="true" '
                'bounds="[0,200][1080,300]"/></hierarchy>')

    @property
    def page_source(self):
        if self.prompt:
            return self.prompt_xml()
        root = ElementTree.Element("hierarchy")
        counter = [0]

        def emit(parent, node):
            counter[0] += 1
            top = counter[0] * 60
            key = node.key if ":" in node.key else rid(node.key) if node.key else ""
            attrs = {"package": PACKAGE, "class": node.cls, "resource-id": key, "content-desc": node.desc,
                     "text": node.text, "clickable": "true" if node.click else "false",
                     "bounds": f"[0,{top}][1080,{top + 50}]", "blowai": str(counter[0]),
                     **{k: str(v) for k, v in node.extra.items() if k in ("scrollable", "hint", "password",
                                                                         "checkable")}}
            if node.cls.endswith("EditText"):
                attrs["text"] = self.fields.get(key, "") or node.extra.get("hint", "")
            element = ElementTree.SubElement(parent, "node", attrs)
            element.set("blowai-extra", repr({k: v for k, v in node.extra.items() if k in ("product", "star")}))
            bottom = top + 50
            for child in node.children:
                bottom = max(bottom, emit(element, child))
            element.set("bounds", f"[0,{top}][1080,{bottom}]")  # a container encloses its children
            return bottom
        # The app's full-screen content frame, as on a phone (Android clips what lies outside it)
        emit(root, Node("android.widget.FrameLayout", "android:id/content").add(*self.page()))
        return ElementTree.tostring(root, encoding="unicode")

    # -------- finding controls (the locator shapes discovery records)
    def find_elements(self, using, value):
        root = SafeTree.fromstring(self.page_source)
        nodes = list(root.iter("node"))
        parents = {child: parent for parent in root.iter() for child in parent}
        if using == "accessibility id":
            found = [n for n in nodes if n.get("content-desc") == value]
        elif using == "id":
            if self.prompt and self.prompt_lookups < self.prompt_delay:
                self.prompt_lookups += 1  # the prompt is still opening: its buttons are not there yet
                return []
            found = [n for n in nodes if n.get("resource-id") == value]
        elif using == "-android uiautomator":
            text = re.search(r'text\("(.*)"\)', value).group(1).encode().decode("unicode_escape")
            found = [n for n in nodes if n.get("text") == text]
        elif using == "xpath":
            found = self.xpath(nodes, parents, value)
        else:
            raise NoSuchElementException(using)
        return [FakeAppElement(self, dict(n.attrib)) for n in found]

    @staticmethod
    def xpath(nodes, parents, value):
        indexed = re.fullmatch(r"\(//\*\[@([\w-]+)=(['\"])(.*?)\2\]\)\[(\d+)\]", value)
        if indexed:
            matches = [n for n in nodes if n.get(indexed.group(1)) == indexed.group(3)]
            position = int(indexed.group(4)) - 1
            return matches[position:position + 1]
        match = re.fullmatch(r"//\*\[@([\w-]+)=(['\"])(.*?)\2\]((?:/\.\.)*)(?://\*\[@([\w-]+)=(['\"])(.*?)\6\])?", value)
        if not match:
            simple = re.fullmatch(r"//\*\[@class='([\w.$]+)'\]", value)
            return [n for n in nodes if simple and n.get("class") == simple.group(1)]
        anchors = [n for n in nodes if n.get(match.group(1)) == match.group(3)]
        out = []
        for anchor in anchors:
            scope = anchor
            for _ in range(match.group(4).count("..")):
                scope = parents.get(scope, scope)
            if match.group(5):
                out += [n for n in scope.iter("node") if n.get(match.group(5)) == match.group(7)]
            else:
                out.append(scope)
        return out

    # -------- what a tap does
    def tap(self, attrs):
        key = attrs.get("resource-id", "").rsplit("/", 1)[-1]
        text = attrs.get("text", "")
        extra = eval(attrs.get("blowai-extra", "{}"))  # noqa: S307 - the fake's own repr of a small literal dict
        self.pressed.append(text or attrs.get("content-desc") or key)
        if self.prompt:
            if "deny" in key:
                self.declined.append(self.prompt)
            self.prompt = ""
            return
        if self.dialog:
            if self.dialog == "logout" and key == "button1":
                self.user, self.dialog = None, "loggedout"
            else:
                self.dialog = ""
            return
        if self.sheet:
            if text in SORTS:
                self.order, self.sheet = SORTS[text], False
            return
        if self.drawer:
            self.drawer = False
            target = {"Catalog": "products", "About": "about", "Drawing": "drawing", "QR Code Scanner": "qr",
                      "Geo Location": "geo", "FingerPrint": "fingerprint", "Log In": "login"}.get(text)
            if text == "Log Out":
                self.dialog = "logout"
            elif text == "Reset App State":
                self.reset()
            elif target:
                self.screen = target
                if target in ("qr", "geo"):
                    self.prompt = "take pictures and record video" if target == "qr" else "access this device’s location"
            return
        if key == "menuIV":
            self.drawer = True
        elif key == "sortIV":
            self.sheet = True
        elif key == "cartRL":
            self.screen = "cart"
        elif key == "productIV":
            self.screen, self.product, self.qty = "detail", extra.get("product", PRODUCTS[0][0]), 1
        elif extra.get("star"):
            self.dialog = "review"
        elif key == "plusIV":
            if self.screen == "detail":
                self.qty += 1
            else:
                first = next(iter(self.cart))
                self.cart[first] += 1
        elif key == "minusIV":
            if self.screen == "detail":
                self.qty = max(0 if self.allow_zero else 1, self.qty - 1)
            else:
                first = next(iter(self.cart))
                self.cart[first] = max(1, self.cart[first] - 1)
        elif key == "cartBt" and self.screen == "detail":
            self.cart[self.product] = self.cart.get(self.product, 0) + self.qty
        elif key == "removeBt":
            self.cart.pop(next(iter(self.cart)), None)
        elif key == "shoppingBt":
            self.screen = "products"
        elif key.startswith("username") and key.endswith("TV"):
            user = text
            self.fields[rid("nameET")] = user
            self.fields[rid("passwordET")] = USERS[user]
        elif key == "loginBtn":
            self.login()
        elif key == "cartBt" and self.screen == "cart":
            pass  # Proceed To Checkout: recorded in self.pressed; the tests prove it never happens

    def login(self):
        user, password = self.fields.get(rid("nameET"), ""), self.fields.get(rid("passwordET"), "")
        if self.cover_password:
            self.keyboard, self.covered = True, True
        if not user:
            self.message = "Username is required"
        elif "locked out" in user:
            self.message = "Sorry this user has been locked out."
        elif USERS.get(user) == password or self.accept_wrong:
            self.user, self.screen, self.message, self.fields = user, "products", "", {}
            self.covered = False
        else:
            self.message = "Provided credentials do not match any user in this service."
