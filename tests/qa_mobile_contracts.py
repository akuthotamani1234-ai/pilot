"""Fixture-specific example contracts; reusable runtime contains no demo app names."""


def locator(value, strategy="accessibility_id"):
    return {"strategy": strategy, "value": value}


def tap(value, form=False):
    return {"action": "tap", "locator": locator(value), "purpose": "test_form" if form else "navigation"}


def fill(label, value=None, secret=None):
    return {"action": "fill", "locator": locator(label), **({"secret_ref": secret} if secret else {"value": value})}


def text(label, expected, strategy="accessibility_id"):
    return {"action": "assert_text", "locator": locator(label, strategy), "value": expected}


def screen(name):
    return {"action": "assert_screen", "value": name}


def flow(identifier, title, steps, authentication=False):
    return {"id": identifier, "title": title, "approved": True, "authentication": authentication, "steps": steps}


def native_contract(url):
    login_start = [tap("Open login screen"), fill("Username", "demo")]
    hybrid_start = [
        tap("Hybrid demo"),
        {"action": "context", "value": "webview"},
        text("#heading", "Embedded quote", "css"),
    ]
    return {
        "version": 1,
        "test_environment": True,
        "allowed_origins": [url],
        "flows": [
            flow(
                "valid_login",
                "Approved credentials reach Dashboard",
                login_start
                + [fill("Password", secret="BLOWAI_SECRET_DEMO_PASSWORD"), tap("Login", True), screen("Dashboard")],
                True,
            ),
            flow(
                "invalid_login",
                "Invalid credentials are rejected",
                login_start
                + [
                    fill("Password", secret="BLOWAI_SECRET_INVALID_PASSWORD"),
                    tap("Login", True),
                    text("Use the local demo account only", "Invalid demo credentials"),
                ],
            ),
            flow(
                "invalid_registration",
                "Invalid email is rejected",
                [
                    tap("Registration"),
                    fill("Email", "invalid-address"),
                    tap("Register", True),
                    text("No real account will be created", "Enter a valid email"),
                ],
            ),
            flow(
                "valid_registration",
                "Valid test email is accepted locally",
                [
                    tap("Registration"),
                    fill("Email", "fixture@example.test"),
                    tap("Register", True),
                    text("No real account will be created", "Local registration accepted"),
                ],
            ),
            flow(
                "required_name",
                "An empty required name must be rejected",
                [
                    tap("Form validation"),
                    fill("Required name", ""),
                    tap("Submit", True),
                    text("Name is required", "Name is required"),
                ],
            ),
            flow(
                "valid_name",
                "Valid test form input is accepted",
                [
                    tap("Form validation"),
                    fill("Required name", "Fixture user"),
                    tap("Submit", True),
                    text("Name is required", "Local form accepted"),
                ],
            ),
            flow("open_cart", "Cart screen is reachable", [tap("Cart"), screen("Cart")]),
            flow("open_hybrid", "Embedded WebView content is reachable", hybrid_start),
            flow(
                "hybrid_journey",
                "Native to WebView and back to native",
                hybrid_start
                + [
                    {"action": "tap", "locator": locator("#webConfirm", "css")},
                    text("#message", "Quote checked", "css"),
                    {"action": "context", "value": "native"},
                    tap("Home"),
                    screen("Home"),
                ],
            ),
        ],
        "rules": [
            {
                "id": "cart_total",
                "title": "Cart quantity multiplied by unit price",
                "setup_flow": "open_cart",
                "actual": locator("Cart total"),
                "variables": {"quantity": {"locator": locator("Cart quantity")}, "price": {"number": "10"}},
                "expression": "quantity * price",
            },
            {
                "id": "hybrid_total",
                "title": "Embedded total follows the same pricing rule",
                "setup_flow": "open_hybrid",
                "actual": locator("#total", "css"),
                "variables": {
                    "quantity": {"locator": locator("#quantity", "css")},
                    "price": {"locator": locator("#price", "css")},
                },
                "expression": "quantity * price",
            },
        ],
        "checks": [
            {
                "id": "api_total",
                "title": "API confirms the cart expectation",
                "kind": "http",
                "setup_flow": "open_cart",
                "url": url + "/api/state",
                "json_pointer": "/total",
                "expected": 0,
            },
            {
                "id": "database_total",
                "title": "Read-only database confirms cart expectation",
                "kind": "sqlite",
                "setup_flow": "open_cart",
                "database_ref": "BLOWAI_DB_DEMO",
                "query": "SELECT total FROM quotes WHERE id = ?",
                "parameters": [1],
                "expected": 0,
            },
        ],
    }
