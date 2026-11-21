# Local demonstration

Start the studio from the root of the final checkout on Windows with `ui.bat`. The installer prepares Python and Chromium. The browser opens the loopback UI. Choose **Fast** for parallel browser workers and open **Live execution**. See the [deployment guide](../DEPLOYMENT.md) for configuration, worker and service operations.

## Web acceptance

To present the seeded fixture in a visible Studio window, run `.venv\Scripts\python.exe -m tests.local_studio_demo --watch`. It starts a local Studio instance on an available loopback port, opens a Fast job and watches the worker panel until the report is ready. Its screenshot and evidence go into a new `runs/local-demo/studio_*` directory. Omit `--watch` for automated verification.

From the same checkout, run the following after startup.

```powershell
.venv\Scripts\python.exe -m tests.local_demo
```

The suite starts an ephemeral loopback quote application. The expected total for two items at $10 each is $20. The seeded version displays $27. The targeted scenario runs only the configured price assertion. Each scenario uses its own fixture database, run directory and baseline. Open the HTML report referenced in `runs/local-demo/<timestamp>/evidence.json`. The command exits with an error if a scenario misses its expected result.

For simultaneous discovery and testing in a full run, set `QPILOT_CONCURRENT_CONTRACT=1`, `REVIEW=off`, `TEST_WORKERS=2` or higher, and choose headless execution. Supply an approved Web contract consisting of numeric rules against the landing page. A separate Chromium worker reads the values while the crawler inventories pages. Each result enters the ordinary report once. The demo compares the recorded assertion times with the active crawl window in `contract_overlap.json`. Mixed contracts, interactive review and resumed discovery start their contracts during the ordinary execution stage. A targeted-only run stays within its contract.

## Local model, healing and Android

- Install Ollama and a local model, then use `.venv\Scripts\python.exe -m tests.local_demo --mode clean --ollama-model qwen2.5:3b`. The model must be running locally. Inspect the provider, successful calls and output tokens in the run's `cost.json` and review the case or analysis it produced.
- Exercise locator repair and the preserved business assertion with `.venv\Scripts\python.exe -m pytest -q tests/test_end_to_end.py::test_a_repaired_script_is_run_again_and_reported_with_its_real_result`.
- Android requires JDK 17+, Android SDK, an emulator with hardware acceleration or a connected device, Appium and the UiAutomator2 driver. Build and install the controlled fixture from [its source and setup guide](../tests/android_demo/README.md). Start Appium on loopback, confirm the intended serial in `adb devices`, then run the opt-in product tests below. Use a dedicated test emulator because the tests modify the fixture's local state.

```powershell
$env:BLOWAI_ANDROID_E2E = "1"
$env:BLOWAI_ANDROID_DEVICE = "emulator-5554"
$env:BLOWAI_SECRET_DEMO_PASSWORD = "demo123"
$env:BLOWAI_ANDROID_ARTIFACTS = "$PWD/runs/local-android-demo"
.venv\Scripts\python.exe -m pytest -q tests/test_android_device.py
```

The password above belongs to the local sample app. Use the serial reported by ADB. Android reports under the selected artifact directory include the executed actions, verdict and failure evidence. For whole-project regressions use `.venv\Scripts\python.exe -m pytest -q -n 3 --dist loadfile` on Windows. Production hosting and SSO have separate acceptance procedures.

## Evidence and local readiness

The Studio website button in `frontend/chat.js` posts to `/api/runs`. The server validates the request and starts `main.py`, which runs the graph. During discovery, each SiteSwarm browser returns its requested URL, HTTP status and DOM counts. Discovery saves those observations in `swarm_work.json`. The durable supervisor then reconciles the planned pages with that file. A successful observation proves the worker read a page. The functional assertions and their outcomes are in `results.json` and the HTML report.

Inspect `swarm_evidence.json` for the original task IDs, artifact references, and blocked tasks. The report can attach a later approved assertion under `swarm.report_oracle` in `qx_applied.json`. The discovery-time queue history stays available. The coverage comparison measures the supplied list of pages. Independent full-site coverage needs a separate inventory.

For the local SQLite mode, leave `REDIS_URL` and `QPILOT_REDIS_URL` unset. When configured, Redis must be reachable. The local demonstration checks each successful worker page against the observation file and records those URLs in its evidence summary.

### Execution truth verification on November 21, 2026

The command `python -m tests.local_demo` produced `runs/local-demo/20261121_143918_099027/evidence.json`. Both full runs overlapped quote execution and discovery. The clean quote passed, the seeded quote failed as expected, and the targeted run executed one passing quote assertion. Each full run matched five worker URLs to browser observations.

The command `python -m tests.local_studio_demo` produced `runs/local-demo/studio_20261121_144118_749184/evidence.json` and `workers.png`. Studio displayed two worker cursors during execution and the run produced an HTML report with the seeded defect.

The affected pytest suite recorded 64 passed, five setup failures creating Windows symbolic links (error 1314), and seven Redis skips. To reproduce the suite from PowerShell:

```powershell
python -m pytest -q tests/test_swarm.py tests/test_swarm_protocol.py tests/test_swarm_queue.py tests/test_swarm_supervisor.py tests/test_swarm_worker_verdict.py tests/test_swarm_evidence.py tests/test_swarm_redis_default.py tests/test_apply_run.py tests/test_concurrent_contract.py tests/test_redis_queue_link.py tests/test_redis_queue.py -ra
```

Milestone 1 acceptance remains open. The local SQLite run verifies reconciliation after discovery. Browser work coordinated directly by a durable lease and the full regression suite still require verification.

A local demonstration is ready only after all of the following commands have produced their expected evidence on the present machine:

- `tests.local_demo` records a clean pass, detects the seeded quote defect and completes the targeted run in `evidence.json`.
- `tests.local_studio_demo` records `visible_cursors: true`, detects its seeded defect and writes `workers.png` plus `report.html`.
- The opt-in Android tests run against a real emulator or device, produce their HTML reports and detect the seeded Android defects.
- The locator-repair regression preserves the underlying business failure after healing.

Keep the generated evidence directory with the demo. A passing unit or mock test alone is not evidence of browser or Android execution.

Windows prerequisite for the full regression suite: its link-safety tests create symbolic links. Enable Windows Developer Mode or run with an account granted the **Create symbolic links** user right before running the full suite. Without that privilege, those tests fail with Windows error 1314. Treat that as an environment blocker and record it rather than marking the full regression suite as passed.
