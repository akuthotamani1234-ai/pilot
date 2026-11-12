# Android: test like a real user (test mode)

Without test mode, an Android run only *looks*: it opens screens and pages and checks that controls are shown.
With **test mode** it also *uses* the app or website the way a manual tester does: every menu, every page, every
button and form - **everything except checkout**.

Tick test mode only for a **test build of an app** or a **test / demo website you are allowed to test**.

## What test mode does

### Websites in Android Chrome (for example demo.nopcommerce.com, demoblaze.com)

1. **Every menu first.** It taps the phone menu button, opens each category and sub-menu, opens the footer
   sections, and taps every menu, header and footer link that stays on the website. Each page must open; it is
   recorded with a screenshot.
2. **Every page to its end.** It scrolls each page to the bottom, like a person, so content that loads late appears.
   Controls below the first screen are recorded with how to reach them ("scroll down about 2 screens").
3. **Every feature.** For example on a shop:
   - search (with a word from a real product, and with an empty box), sort, page size, filters, currency
   - a product page: quantity, **Add to cart** (the cart count must change), wishlist, compare, reviews
   - the cart: it must list the product; change the quantity; remove the product
   - sign-up with test data (addresses end in `@example.com`), then **log in with that new account** (or with
     your test account), the pages behind the login (My account, Orders), and **log out**
   - wrong input: an empty login, a wrong password, a wrong e-mail address, a made-up coupon code
   - contact form, newsletter, "email a friend"
   - browser messages (JavaScript alerts such as "Product added.") are read, checked and closed

   **Pop-up windows count as pages.** On a site like demoblaze.com, *Log in*, *Sign up* and *Contact* do not open a
   new page: they open a small window (a dialog) on the same page. Blow AI opens each one like a menu entry, fills
   every box in it with its test data and presses its button, exactly as for a page form: sign-up first, then login
   with the account it just made, an empty login and a wrong password (both must be refused), then the contact
   form. The *Close* and *×* buttons are not taken for the submit button. In the report these results are listed
   under the window's own name, for example `'Log in' on STORE — /`.

### Apps (APK upload, or an app installed on an emulator - for example the Sauce Labs My Demo App)

1. **The app menu first.** It opens the menu (the drawer) and every item in it, and checks that each item's screen
   opens (its heading). Screens for a device feature (QR Code Scanner, Geo Location, FingerPrint, Virtual USB) may
   open, but the feature itself (scanning, locating, the fingerprint switch) is never used. When Android asks for a
   permission, test mode answers **Don't allow** and says so in the report.
2. **Every screen.** The first product of a list (one card stands for all), its **+ / -** (the count must change and
   never go below 1), **Add To Cart** (the cart badge shows 1; twice gives 2), one rating star, the **Sort** button with
   **every** sort option (the first product must change), the cart (it must list the product; **Remove Item** shows
   "No Items"; **Go Shopping** goes back), and the other buttons - at most 12 per screen.
3. **Login like a user:** empty fields, a wrong password, the app's locked-out sample user, the app's sample user (or
   your test account), then **Log Out** from the menu.
4. Rotate, leave and come back, the Back button; crash and "not responding" detection.

Discovery itself also got faster: controls that every screen shows (View menu, View cart) are explored once, a
dialog is closed with its own Continue / Close / OK button or Back before the app is restarted, and the soft keyboard
is hidden instead of being taken for another app.

## What test mode never does

| Never pressed | Why |
|---|---|
| Checkout, payment, place / confirm order, buy now, purchase, book now | No order and no payment is ever made |
| Paid subscriptions, upgrades, free trials | Nothing is bought |
| Delete or close an account, change password | The account stays usable |
| Crash and force-close buttons | They only stop the app |
| Reset App State | Test mode already clears the app's data before every check |
| A device feature: camera / scanner, location, fingerprint, USB; Android permission prompts are declined | Nothing on the phone is used or allowed |
| Share, "send to" other apps, calls, SMS | Nothing leaves the device |
| Links to other websites (Facebook, payment pages) | Only the website you named is tested |
| A page whose address is a checkout or payment step | Even when a harmless-looking link leads there |

Each of these is listed in the report as **Not tested**, with the reason.
Blow AI **never** fakes a browser identity, hides from a bot check, or solves a CAPTCHA.

## Bot checks ("Just a moment...", "Verify you are human")

Some websites (demo.nopcommerce.com uses Cloudflare) show a security check before the real page.

1. Blow AI waits up to **30 seconds** for it to finish by itself, as it does for a normal visitor.
2. If it does not finish, the chat says *"The website shows a security check"*. Please complete it yourself in the
   **Android emulator window**. Blow AI waits up to **3 minutes** and goes on as soon as the real website appears.
3. If nobody completes it, the run stops and the report says so **at the top**: nothing behind the check was tested,
   and no test was made from the check page.

## How every user-like test is made

1. A fresh start: for an app, its data is cleared; for a website, **only that website's cookies and storage** are
   cleared and the start page is loaded again (other websites in Chrome are not touched).
2. The action is done once and Blow AI notes what changed on the screen.
3. Fresh start again, and the whole test is **replayed**.
4. The test is kept only if the replay passes, so a result that does not repeat never becomes a flaky test.
   Exception: a check *every* tester expects (a wrong password must be refused, the cart must list what was added)
   is kept even when it fails. That failure is a real finding.

## How to run it

1. Close the old Blow AI window and double-click **ui.bat** again, so the new code is loaded.
2. Start the emulator and Appium as usual.
3. Choose **Android testing - Appium**, then either:
   - **Website in Chrome**: enter the address, for example `https://demo.nopcommerce.com`, or
   - **Upload an APK**, for example `demo-apps/mda-2.3.0-27.apk` (Sauce Labs My Demo App).
4. Optional: in *Advanced checks*, enter a test account (for My Demo App: `bob@example.com` / `10203040`).
   Without one, test mode registers its own test account on a website and uses that.
5. Tick **"This is a test build or a test / demo website I may test: test it like a real user."**
6. Tick the permission box and click **Start Android test**.
7. Keep the emulator window visible: if a security check appears, complete it there.

After updating Blow AI, always restart **ui.bat**: an old window keeps the old limits. With an AI key typed in the
*API key* box and *Use configured provider* selected, the provider is taken from the key (`sk-ant-` = Anthropic).

A full website run takes long: up to **45 minutes** of user-like testing (every test is done twice), then the
final run of the kept tests.

## Reading the report

- **What was tested** (in `report.html`, also `summary.json` -> `user_like_coverage`): one row per menu entry,
  page, form, cart step, drop-down and control, with
  **Tested - passed**, **Tested - failed** (the reason and a screenshot) or **Not tested** (the reason: never
  pressed, another website, limit reached, not reached in time, no visible change, ...). Nothing is left out silently.
- **Every control** (`report.html`, also `summary.json` -> `controls` and `coverage.json` -> `controls`): every
  button, link and input box found, with *Tested - passed*, *Tested - failed* or *Not tested* and the reason
  (never pressed, device feature, at most 12 per screen, time limit, not reached).
- A **Stopped early** box at the top when a limit, the Stop button or too much recovering ended the run early, with
  how many checks were not reached.
- **User-like testing** section: what was tried and the findings to review (for example "Login with a wrong
  password was accepted", "The cart did not list the product").
- A red box at the top when the website's **bot check** stopped the run.
- `auto_flows.json`: the kept tests as reusable flows (they contain only references to passwords, never the
  passwords themselves). They can be pasted into *Advanced workflow JSON* for a later run **with test mode ticked**.

## Limits

| Setting | Default | Allowed |
|---|---|---|
| User-like tries (each try and each replay counts; field *Test mode: user-like tries*) | 300 | 0-500 |
| User-like testing time (field *Test mode: time limit*) | 2700 s (45 min) | 30-3600 s |
| Wait for a bot check to finish by itself | 30 s | 0-120 s |
| Wait for a person to complete the bot check | 180 s | 0-900 s |
| Pages recorded on a website | the *Maximum screens* setting (40) | 1-100 |
| Controls explored per app screen (menu items and tabs first) | 12 | 1-100 |

- Menus come first in the budget. One control of a repeated kind (one product card, one star of five) stands for all.
- When a limit is reached, every check not reached is listed as *Not tested* with that reason.
- An app already installed on a **physical phone** is not tested in test mode (it would clear that phone's app data).
  Use an emulator or upload the APK.
