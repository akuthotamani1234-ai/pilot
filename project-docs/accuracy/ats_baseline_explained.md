# Why the AutomationTestStore baseline verified so little

Run `automationteststore.com_20261027_235636`. Pages: the report's page coverage (a page counts as verified when a test case that visits it passed). Features: the registry (`registry.json`).

## Pages not verified

| Page | Its test cases | Why |
|---|---|---|
| `/index.php?rt=account/invoice` | 1 (1 failed) | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total; A3 the item list was the header menu / every link; A4 the search word came from a heading |
| `/index.php?rt=product/category&path=68_69` | 1 (1 failed) | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total |
| `/index.php?rt=product/category&path=68_70` | 1 (1 failed) | A1 bundled: one large case per page, failed by other steps; hover menu did not open in the test |
| `/index.php?rt=product/manufacturer&manufacturer_id=12` | 1 (1 failed) | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total; A4 the search word came from a heading |
| `/index.php?rt=product/manufacturer&manufacturer_id=17` | 1 (1 failed) | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total |
| `/index.php?rt=product/manufacturer&manufacturer_id=11` | 1 (1 failed) | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total |
| `/index.php?rt=product/product&path=68&product_id=122` | 1 (1 failed) | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total; A3 the item list was the header menu / every link; A4 the search word came from a heading |
| `/index.php?rt=product/product&path=68&product_id=118` | 1 (1 failed) | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total; A3 the item list was the header menu / every link; A4 the search word came from a heading |
| `/index.php?rt=product/search&keyword=cheeks` | 2 (2 failed) | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total; A3 the item list was the header menu / every link; A4 the search word came from a heading |
| `/index.php?rt=product/product&manufacturer_id=12&product_id=58` | 1 (1 failed) | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total; A3 the item list was the header menu / every link; A4 the search word came from a heading |
| `/index.php?rt=product/product&manufacturer_id=12&product_id=52` | 1 (1 failed) | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total; A3 the item list was the header menu / every link; A4 the search word came from a heading |
| `/index.php?rt=product/product&manufacturer_id=12&product_id=51` | 1 (1 failed) | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total; A3 the item list was the header menu / every link; A4 the search word came from a heading |
| `/index.php?rt=product/search&keyword=fashion` | 1 (1 failed) | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total; A3 the item list was the header menu / every link; A4 the search word came from a heading |
| `/index.php?rt=product/product&keyword=cheeks&product_id=50` | 2 (2 failed) | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total; A3 the item list was the header menu / every link; A4 the search word came from a heading |
| `/index.php?rt=product/product&keyword=cheeks&product_id=51` | 1 (1 failed) | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total; A3 the item list was the header menu / every link; A4 the search word came from a heading |

14 of 29 pages verified.

## Features not verified

| Feature | Status | Its test cases | Why |
|---|---|---|---|
| Search Keywords (feature) | failed | 2 | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total; A4 the search word came from a heading |
| items (feature) | failed | 1 | A7 tab link taken for a broken #section (the <base href>) |
| Add to Cart (feature) | failed | 1 | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total; A4 the search word came from a heading |
| Subscribe (feature) | blocked | 1 | protected action - never performed (correct) |
| form 'Subscribe' (feature) | blocked | 0 | protected action - never performed (correct) |
| Add to Cart (control) | failed | 17 | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total; A3 the item list was the header menu / every link; A4 the search word came from a heading |
| Subscribe (control) | blocked | 0 | protected action - never performed (correct) |
| Back to top (control) | failed | 1 | A2 the cart menu's address held its count / total; A3 the item list was the header menu / every link; A7 effect not observable (print dialog / view already shown / scroll) |
| Search Keywords (control) | failed | 32 | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total; A3 the item list was the header menu / every link; A4 the search word came from a heading; A7 e-mail / quantity text box expected to refuse values (form never sent); hover menu did not open in the test |
| Subscribe to Newsletter (control) | failed | 1 | A7 e-mail / quantity text box expected to refuse values (form never sent) |
| Search Keywords (feature) | failed | 29 | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total; A3 the item list was the header menu / every link; A4 the search word came from a heading; hover menu did not open in the test |
| items (feature) | failed | 2 | A3 the item list was the header menu / every link; A7 tab link taken for a broken #section (the <base href>) |
| Subscribe (feature) | blocked | 0 | protected action - never performed (correct) |
| login form (feature) | failed | 1 | A1 bundled: one large case per page, failed by other steps; A3 the item list was the header menu / every link; A4 the search word came from a heading |
| form 'Continue' (feature) | failed | 1 | A1 bundled: one large case per page, failed by other steps; A3 the item list was the header menu / every link; A4 the search word came from a heading |
| form 'Subscribe' (feature) | blocked | 2 | protected action - never performed (correct) |
| Continue (control) | failed | 1 | A1 bundled: one large case per page, failed by other steps; A3 the item list was the header menu / every link; A4 the search word came from a heading |
| Login (control) | failed | 1 | A1 bundled: one large case per page, failed by other steps; A3 the item list was the header menu / every link; A4 the search word came from a heading |
| Subscribe (control) | blocked | 2 | protected action - never performed (correct) |
| Register Account (control) | failed | 1 | A1 bundled: one large case per page, failed by other steps; A3 the item list was the header menu / every link; A4 the search word came from a heading |
| Guest Checkout (control) | failed | 1 | A1 bundled: one large case per page, failed by other steps; A3 the item list was the header menu / every link; A4 the search word came from a heading |
| Login Name: (control) | failed | 2 | A1 bundled: one large case per page, failed by other steps; A3 the item list was the header menu / every link; A4 the search word came from a heading; A7 e-mail / quantity text box expected to refuse values (form never sent) |
| Password: (control) | failed | 2 | A1 bundled: one large case per page, failed by other steps; A3 the item list was the header menu / every link; A4 the search word came from a heading; A7 e-mail / quantity text box expected to refuse values (form never sent) |
| Sort By (feature) | failed | 1 | A3 the item list was the header menu / every link |
| Add to Cart (feature) | failed | 16 | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total; A3 the item list was the header menu / every link; A4 the search word came from a heading |
| form 'form' (feature) | unresolved | 0 | no test was generated for it |
| form 'form' (feature) | unresolved | 0 | no test was generated for it |
| btn btn orange (control) | failed | 1 | A2 the cart menu's address held its count / total; A3 the item list was the header menu / every link; A7 effect not observable (print dialog / view already shown / scroll) |
| Date Old > New (control) | failed | 2 | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total; A3 the item list was the header menu / every link; A4 the search word came from a heading |
| 10 (control) | failed | 1 | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total; A4 the search word came from a heading |
| form 'Continue' (feature) | unresolved | 0 | no test was generated for it |
| Order ID (control) | failed | 1 | A7 e-mail / quantity text box expected to refuse values (form never sent) |
| E-Mail (control) | failed | 1 | A7 e-mail / quantity text box expected to refuse values (form never sent) |
| form 'form' (feature) | unresolved | 0 | no test was generated for it |
| Add to Cart (control) | unresolved | 0 | no test was generated for it |
| Print (control) | failed | 1 | A2 the cart menu's address held its count / total; A3 the item list was the header menu / every link; A7 effect not observable (print dialog / view already shown / scroll) |
| Qty: (control) | failed | 1 | A7 e-mail / quantity text box expected to refuse values (form never sent) |
| All Categories (control) | failed | 1 | A7 e-mail / quantity text box expected to refuse values (form never sent) |
| All Categories (control) | failed | 2 | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total |
| Search in product descriptions (control) | failed | 2 | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total |
| Search in product model (control) | failed | 2 | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total |
| ------ (control) | unresolved | 0 | no test was generated for it |
| Light Blue (993298 In Stock) (feature) | unresolved | 0 | no test was generated for it |
| Light Blue (993298 In Stock) (control) | failed | 1 | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total; A3 the item list was the header menu / every link; A4 the search word came from a heading |
| Small Out of Stock (control) | unresolved | 0 | no test was generated for it |
| black (control) | failed | 1 | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total; A3 the item list was the header menu / every link; A4 the search word came from a heading |
| red (control) | failed | 1 | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total; A3 the item list was the header menu / every link; A4 the search word came from a heading |
| green (control) | failed | 1 | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total; A3 the item list was the header menu / every link; A4 the search word came from a heading |
| blue (control) | failed | 1 | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total; A3 the item list was the header menu / every link; A4 the search word came from a heading |
| white (control) | failed | 1 | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total; A3 the item list was the header menu / every link; A4 the search word came from a heading |
| Brown $5.00 (983 In Stock) (control) | failed | 1 | A1 bundled: one large case per page, failed by other steps; A2 the cart menu's address held its count / total; A3 the item list was the header menu / every link; A4 the search word came from a heading |
| Shopping journey: search → open a produc (workflow) | failed | 1 | A3 the item list was the header menu / every link |

How often each cause is behind a feature that is not verified (a feature can have several): A1 x26, A3 x26, A4 x23, A2 x21, A7 x13, unresolved x8, blocked x6, hover menu did not open in the test x2
