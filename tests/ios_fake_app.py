"""A small iOS app as an Appium XCUITest driver would show it - stateful, so discovery, replayed paths, taps, the
native / WebView contexts and assertions behave like a session on a simulator. Screens:
  home  : 'Shop' (-> shop), 'Help' (-> help), 'Delete account' (risky: must never be tapped)
  shop  : 'Add to cart' increments the cart badge; 'Back' -> home
  help  : a native header + a WKWebView (inspectable unless inspectable=False) with #faq and #shipping
The cart badge starts at 0 at each launch; `bug=True` makes 'Add to cart' do nothing (a real application defect)."""
from appium.webdriver.common.appiumby import AppiumBy


class El:
    def __init__(self, app, kind, name, label="", value="", on_tap=None, web=False):
        self.app, self.kind, self.name, self.label, self.value, self.on_tap, self.web = (
            app, kind, name, label, value, on_tap, web)

    def is_displayed(self):
        return True

    def click(self):
        self.app.taps.append(self.name or self.label)
        if self.on_tap:
            self.on_tap()

    def send_keys(self, v):
        self.value += v

    def clear(self):
        self.value = ""

    def get_attribute(self, k):
        return {"label": self.label, "value": self.value, "name": self.name}.get(k)


class FakeIosApp:
    def __init__(self, inspectable=True, bug=False):
        self.inspectable, self.bug = inspectable, bug
        self.taps, self.launches, self.shots, self.current_context = [], 0, 0, "NATIVE_APP"
        self.switch_to = type("S", (), {"context": lambda _s, name: setattr(self, "current_context", name)})()
        self.activate_app("com.example.shop")

    # -- app lifecycle
    def terminate_app(self, bundle):
        self.screen = None

    def activate_app(self, bundle):
        if getattr(self, "screen", None) is None:
            self.launches += 1
            self.screen, self.cart, self.current_context = "home", 0, "NATIVE_APP"

    def go(self, where):
        self.screen = where

    def add(self):
        if not self.bug:
            self.cart += 1

    # -- what the screen shows
    def elements(self):
        if self.screen == "home":
            return [El(self, "StaticText", "homeTitle", "Welcome"),
                    El(self, "Button", "shopButton", "Shop", on_tap=lambda: self.go("shop")),
                    El(self, "Button", "helpButton", "Help", on_tap=lambda: self.go("help")),
                    El(self, "Button", "deleteAccount", "Delete account", on_tap=lambda: self.go("deleted"))]
        if self.screen == "shop":
            return [El(self, "NavigationBar", "Products", "Products"),
                    El(self, "Button", "addToCart", "Add to cart", on_tap=self.add),
                    El(self, "StaticText", "cartBadge", str(self.cart), str(self.cart)),
                    El(self, "Button", "backButton", "Back", on_tap=lambda: self.go("home"))]
        if self.screen == "help":
            return [El(self, "NavigationBar", "HelpHeader", "Help"),
                    El(self, "WebView", "", ""),
                    El(self, "Button", "closeHelp", "Close", on_tap=lambda: self.go("home"))]
        return [El(self, "StaticText", "gone", "Account deleted")]

    @property
    def page_source(self):
        rows = "".join(f'<XCUIElementType{e.kind} type="XCUIElementType{e.kind}" name="{e.name}" label="{e.label}" '
                       f'value="{e.value}" visible="true" enabled="true"/>' for e in self.elements())
        return f'<AppiumAUT><XCUIElementTypeApplication name="Shop">{rows}</XCUIElementTypeApplication></AppiumAUT>'

    @property
    def contexts(self):
        return ["NATIVE_APP"] + (["WEBVIEW_77.1"] if self.screen == "help" and self.inspectable else [])

    def execute_script(self, script, *args):
        assert self.current_context.startswith("WEBVIEW"), "a page script runs only inside the WebView"
        if "document.title" in script:
            return "Help center"
        if "[id]" in script:
            return ["faq", "shipping"]
        if "h1,h2,h3" in script:
            return ["Frequently asked questions"]
        return None

    def find_elements(self, by, value):
        if self.current_context.startswith("WEBVIEW"):
            ids = {"#faq": "Frequently asked questions", "#shipping": "Shipping takes 3 days"}
            return [El(self, "web", value, ids[value], web=True)] if by == AppiumBy.CSS_SELECTOR and value in ids \
                else []
        if by == AppiumBy.CSS_SELECTOR:
            return []
        els = self.elements()
        if by == AppiumBy.ACCESSIBILITY_ID:
            return [e for e in els if e.name == value]
        if by == AppiumBy.IOS_PREDICATE and value.startswith("label == "):
            want = value.split("==", 1)[1].strip().strip('"')
            return [e for e in els if e.label == want]
        return []

    def back(self):
        self.screen = "home"

    def get_screenshot_as_file(self, path):
        self.shots += 1
        open(path, "wb").write(b"\x89PNG\r\n\x1a\nfake")
        return True

    def get_screenshot_as_png(self):
        return b"\x89PNG\r\n\x1a\nfake"

    def quit(self):
        pass
