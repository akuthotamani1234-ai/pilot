"""Phone-level checks: deep links, dark mode / large font / language, device-only features, start time, memory."""
from types import SimpleNamespace

from backend import android_checks as ac

DUMPSYS = """
Activity Resolver Table:
  Non-Data Actions:
      android.intent.action.MAIN:
        a1b2c3 com.shop/.MainActivity filter 1
Packages:
  Package [com.shop]
    Activities:
      d4e5f6 com.shop/.ProductActivity filter 2
        Action: "android.intent.action.VIEW"
        Category: "android.intent.category.DEFAULT"
        Category: "android.intent.category.BROWSABLE"
        Scheme: "myshop"
        Authority: "product" -1
        Path: "PatternMatcher{PREFIX: /item}"
      a7b8c9 com.shop/.WebActivity filter 3
        Action: "android.intent.action.VIEW"
        Category: "android.intent.category.BROWSABLE"
        Scheme: "https"
        Authority: "www.shop.example" -1
      aaaaaa com.shop/.ShareActivity filter 4
        Action: "android.intent.action.SEND"
        Scheme: "content"
"""


def test_the_apps_own_deep_links_are_found_and_web_links_left_out():
    assert ac.deep_links(DUMPSYS, "com.shop") == ["myshop://product/item"]


def test_cut_off_or_off_screen_text_is_a_layout_problem():
    normal = {"elements": [{"resource_id": "title", "text": "Sauce Labs Backpack", "bounds": "[10,10][500,60]"},
                           {"resource_id": "desc", "text": "A bag…", "bounds": "[10,70][500,90]"}]}
    big = {"elements": [{"resource_id": "title", "text": "Sauce Labs Backp…", "bounds": "[10,10][1200,60]"},
                        {"resource_id": "desc", "text": "A bag…", "bounds": "[10,70][500,90]"},
                        {"resource_id": "price", "text": "$29.99", "bounds": "[10,100][200,140]"}]}
    problems = ac.layout_problems(big, width=1080, baseline=normal)
    assert problems == ["'Sauce Labs Backp…' runs past the edge of the screen"]  # (desc was cut off already)
    assert ac.layout_problems(normal, width=1080) == ["'A bag…' is cut off"]  # (without a baseline)


def test_start_time_and_memory_are_read_from_android():
    assert ac.start_time_ms("Status: ok\nLaunchState: COLD\nTotalTime: 1234\nWaitTime: 1250") == 1234
    assert ac.memory_kb("** MEMINFO in pid 123 [com.shop] **\n   TOTAL PSS:    85432  TOTAL RSS: 1") == 85432
    assert ac.memory_kb("        TOTAL    91000    80000") == 91000


def test_camera_scanner_and_fingerprint_need_a_real_phone():
    screens = [{"screen_name": "QR Code Scanner", "elements": [{"text": "Scan a barcode"}]},
               {"screen_name": "FingerPrint", "elements": []}, {"screen_name": "Products", "elements": []}]
    assert {"qr", "scanner", "finger print", "fingerprint"} & set(ac.device_only_features(screens))
    assert ac.is_emulator("emulator-5554") and not ac.is_emulator("R58M123", "0")


def test_a_full_run_puts_every_phone_setting_back(tmp_path, monkeypatch):
    monkeypatch.setattr(ac.time, "sleep", lambda s: None)
    shell, scripts = [], []
    screen = {"screen_name": "Products", "elements": [{"text": "Products", "bounds": "[0,0][300,50]"}]}

    class Driver:
        current_package = "com.shop"

        def execute_script(self, name, args):
            scripts.append((name, args))

        def terminate_app(self, package):
            pass

        def activate_app(self, package):
            pass

        def get_window_size(self):
            return {"width": 1080, "height": 2400}

    answers = {("dumpsys", "package"): DUMPSYS, ("settings", "get"): "1.0",
               ("cmd", "package"): "priority=0\ncom.shop/.MainActivity", ("am", "start"): "TotalTime: 6200",
               ("dumpsys", "meminfo"): "TOTAL PSS: 70000", ("getprop", "ro.kernel.qemu"): "1"}

    checks = ac.Checks(Driver(), {"package_name": "com.shop", "device_id": "emulator-5554"}, "adb", tmp_path,
                       lambda: screen, SimpleNamespace(findings=[], tried=[]))
    monkeypatch.setattr(checks, "shell", lambda *a, timeout=20: shell.append(a) or answers.get(a[:2], ""))
    results = checks.run_all([{"screen_name": "QR Code Scanner", "elements": []}])
    assert scripts == [("mobile: deepLink", {"url": "myshop://product/item", "package": "com.shop"})]
    assert results["deep_links"] == [{"url": "myshop://product/item", "opened": True, "why": ""}]
    assert [a["look"] for a in results["appearance"]] == ["dark mode", "large font (130%)", "German language"]
    # every change put back
    assert ("cmd", "uimode", "night", "no") in shell and ("settings", "put", "system", "font_scale", "1.0") in shell
    assert ("cmd", "locale", "set-app-locales", "com.shop", "--locales", "") in shell
    assert results["performance"]["cold_start_ms"] == 6200 and results["performance"]["memory_kb"] == 70000
    findings = [f["finding"] for f in checks.session.findings]
    assert any("takes 6.2 s to start" in f for f in findings)  # (slow start: a finding)
    assert any(t["outcome"] == "not testable here" for t in checks.session.tried)  # (QR on an emulator)
    assert (tmp_path / "android_checks.json").exists()


def test_a_setting_is_put_back_even_when_the_app_breaks(tmp_path, monkeypatch):
    monkeypatch.setattr(ac.time, "sleep", lambda s: None)
    shell = []

    class Driver:
        current_package = "com.shop"

        def terminate_app(self, p):
            pass

        def activate_app(self, p):
            if any(a[:2] == ("cmd", "uimode") and a[-1] == "yes" for a in shell[-1:]):
                raise RuntimeError("crashed in dark mode")

        def get_window_size(self):
            return {"width": 1080}

    checks = ac.Checks(Driver(), {"package_name": "com.shop", "device_id": "emulator-5554"}, "adb", tmp_path,
                       lambda: {"elements": []}, SimpleNamespace(findings=[], tried=[]))
    monkeypatch.setattr(checks, "shell", lambda *a, timeout=20: shell.append(a) or "")
    checks.run_appearance()
    assert ("cmd", "uimode", "night", "no") in shell  # (dark mode switched off again after the failure)
