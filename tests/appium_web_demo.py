"""Replayable, handwritten live Appium demo of the existing DemoShop in Android Chrome."""

import argparse
import html
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.client_config import AppiumClientConfig
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from backend.android import DeviceLock, _adb_path
from tests import demo_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default="emulator-5554")
    parser.add_argument("--chromedriver", required=True, type=Path)
    parser.add_argument("--pause", default=4, type=float)
    parser.add_argument("--record-seconds", default=60, type=int)
    args = parser.parse_args()
    if not args.chromedriver.is_file() or not 0 <= args.pause <= 30 or not 0 <= args.record_seconds <= 180:
        parser.error("Provide a local ChromeDriver and bounded pause/recording duration.")
    run = (
        Path(__file__).resolve().parent.parent
        / "runs"
        / ("appium_web_live_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    )
    run.mkdir()
    adb = _adb_path()
    if not adb:
        raise RuntimeError("Android Platform-Tools are required")
    # Presentation changes affect only this demo process, not the reusable website fixture source.
    demo_app.PAGE = demo_app.PAGE.replace(
        "<head>",
        "<head><meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<style>body{{font:18px/1.6 system-ui;margin:20px;color:#172033}}nav{{display:flex;gap:12px;flex-wrap:wrap}}"
        "a{{color:#4338ca}}button,input{{font:inherit;padding:10px;margin:5px 0}}h1{{font-size:30px}}.product{{padding:12px;border-bottom:1px solid #ddd}}</style>",
    )
    app = demo_app.DemoApp().start()
    subprocess.run(
        [adb, "-s", args.device, "reverse", f"tcp:{app.port}", f"tcp:{app.port}"], check=True, capture_output=True
    )
    results = []
    driver = None
    recorder = None
    video_remote = f"/sdcard/blowai_appium_web_{int(time.time())}.mp4"
    print("LIVE_DEMO_URL=" + app.url, flush=True)
    print("LIVE_DEMO_REPORT=" + str(run / "report.html"), flush=True)
    try:
        with DeviceLock(args.device):
            options = UiAutomator2Options().load_capabilities(
                {
                    "platformName": "Android",
                    "browserName": "Chrome",
                    "appium:automationName": "UiAutomator2",
                    "appium:udid": args.device,
                    "appium:noReset": True,
                    "appium:chromedriverExecutable": str(args.chromedriver.resolve()),
                    "appium:chromeOptions": {"args": ["--no-first-run", "--no-default-browser-check", "--disable-fre"]},
                    "appium:newCommandTimeout": 180,
                    "appium:autoGrantPermissions": False,
                }
            )
            client = AppiumClientConfig(remote_server_addr="http://127.0.0.1:4723", timeout=90)
            driver = webdriver.Remote("http://127.0.0.1:4723", options=options, client_config=client)
            print("Connected Appium to Android Chrome: " + str(driver.capabilities.get("browserVersion")), flush=True)
            if args.record_seconds:
                recorder = subprocess.Popen(
                    [
                        adb,
                        "-s",
                        args.device,
                        "shell",
                        "screenrecord",
                        "--time-limit",
                        str(args.record_seconds),
                        "--size",
                        "540x960",
                        "--bit-rate",
                        "2000000",
                        video_remote,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            wait = WebDriverWait(driver, 20)

            def shown(selector, text):
                wait.until(
                    lambda d: d.find_element(By.CSS_SELECTOR, selector).is_displayed()
                    and text in d.find_element(By.CSS_SELECTOR, selector).text
                )

            def checkpoint(title):
                number = len(results) + 1
                filename = f"{number:02d}.png"
                driver.save_screenshot(str(run / filename))
                results.append(
                    {
                        "step": number,
                        "title": title,
                        "outcome": "passed",
                        "screenshot": filename,
                        "url": driver.current_url,
                    }
                )
                print(f"PASS {number}: {title}", flush=True)
                time.sleep(args.pause)

            driver.get(app.url)
            shown("h1", "Home")
            checkpoint("Open DemoShop in Android Chrome")
            driver.find_element(By.LINK_TEXT, "Products").click()
            shown("h1", "Products")
            assert len(driver.find_elements(By.CSS_SELECTOR, ".product")) == 3
            checkpoint("Navigate to Products and verify three items")
            driver.find_element(By.CSS_SELECTOR, "input[name=q]").send_keys("Pear")
            driver.find_element(By.CSS_SELECTOR, "form button").click()
            wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, ".product")) == 1)
            shown(".product h3", "Green Pear")
            checkpoint("Search for Pear and verify the matching product")
            driver.find_element(By.LINK_TEXT, "About").click()
            shown("h1", "About")
            driver.find_element(By.CSS_SELECTOR, "#tab-team").click()
            shown("#team", "Ravi and Anna")
            assert not driver.find_element(By.CSS_SELECTOR, "#story").is_displayed()
            checkpoint("Switch the Team tab and verify its contents")
            driver.find_element(By.CSS_SELECTOR, "#open-details").click()
            shown("dialog", "Opening hours")
            checkpoint("Open the details dialog and verify opening hours")
            driver.find_element(By.CSS_SELECTOR, "dialog button").click()
            assert not driver.find_element(By.CSS_SELECTOR, "#details").is_displayed()
            assert "/delete-all" not in app.visited and "/logout" not in app.visited
            checkpoint("Close the dialog; destructive routes were never visited")
            if recorder:
                try:
                    recorder.wait(timeout=args.record_seconds + 5)
                    subprocess.run(
                        [adb, "-s", args.device, "pull", video_remote, str(run / "live-execution.mp4")],
                        check=True,
                        capture_output=True,
                    )
                    subprocess.run(
                        [adb, "-s", args.device, "shell", "rm", video_remote], check=True, capture_output=True
                    )
                except subprocess.TimeoutExpired:
                    recorder.terminate()
            driver.quit()
            driver = None
    except Exception as error:
        results.append({"step": len(results) + 1, "title": str(error).splitlines()[0], "outcome": "failed"})
        if driver:
            driver.save_screenshot(str(run / "failure.png"))
        raise
    finally:
        if driver:
            driver.quit()
        app.stop()
        subprocess.run(
            [adb, "-s", args.device, "reverse", "--remove", f"tcp:{app.port}"], check=False, capture_output=True
        )
        (run / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        cards = "".join(
            "<section><h2>"
            + html.escape(str(row["step"]) + ". " + row["title"])
            + "</h2><p>"
            + row["outcome"]
            + "</p>"
            + ('<img src="' + row["screenshot"] + '" width="340">' if row.get("screenshot") else "")
            + "</section>"
            for row in results
        )
        video = (
            '<video controls width="420" src="live-execution.mp4"></video>'
            if (run / "live-execution.mp4").exists()
            else ""
        )
        (run / "report.html").write_text(
            "<!doctype html><meta charset='utf-8'><title>Live Appium website demo</title>"
            "<style>body{font:16px system-ui;max-width:1100px;margin:30px auto}section{display:inline-block;vertical-align:top;width:350px;padding:10px}img{border:1px solid #ddd}</style>"
            "<h1>DemoShop: Appium + Android Chrome</h1><p>Actual emulator execution. This is a handwritten demonstration, not an AI-generated test run.</p>"
            + video
            + cards,
            encoding="utf-8",
        )
    print(f"LIVE DEMO COMPLETE: {len(results)} checks passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
