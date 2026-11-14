"""Expiring, process-local Studio configurations consumed by an approved MCP start."""
import copy
import inspect
import json
import secrets
import threading
import time
from pathlib import Path
from typing import Literal

from fastapi import HTTPException, UploadFile
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, create_model
from starlette.concurrency import run_in_threadpool

from .privacy import public_policy

REQUEST_TTL_S = 15 * 60
MAX_PREPARED_REQUESTS = 16
PRIVATE_FIELDS = {"api_key", "test_username", "test_password", "test_totp_secret"}


class Preparation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: Literal["android", "web"]
    target: str = Field(min_length=1, max_length=4096)
    task: str = Field(min_length=1, max_length=4000)
    settings: dict = Field(max_length=70)
    avd_name: str = Field(default="", max_length=200)


class StartPrepared(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authorized: StrictBool = False


class PreparedRequests:
    def __init__(self, clock=time.monotonic):
        self.clock, self.lock, self.entries = clock, threading.Lock(), {}

    def _expire(self):
        self.entries = {key: value for key, value in self.entries.items() if value["expires"] > self.clock()}

    def put(self, entry):
        with self.lock:
            self._expire()
            if len(self.entries) >= MAX_PREPARED_REQUESTS:
                raise HTTPException(429, "Too many prepared requests. Revoke one or wait for expiry.")
            identifier = secrets.token_urlsafe(32)
            self.entries[identifier] = {**copy.deepcopy(entry), "expires": self.clock() + REQUEST_TTL_S,
                                        "state": "ready", "result": None}
            return identifier

    def claim(self, identifier, mode):
        with self.lock:
            self._expire()
            entry = self.entries.get(identifier)
            if entry is None:
                raise HTTPException(410, "This request expired, was revoked, or the UI restarted. Prepare it again.")
            if entry["mode"] != mode:
                raise HTTPException(409, "Privacy settings changed. Review and prepare the request again.")
            if entry["state"] == "done":
                return {"result": copy.deepcopy(entry["result"])}
            if entry["state"] != "ready":
                raise HTTPException(409, "This request was already submitted. Check run history before preparing another.")
            entry["state"] = "starting"
            return copy.deepcopy(entry)

    def finish(self, identifier, result):
        with self.lock:
            entry = self.entries.get(identifier)
            if entry is not None:
                # Drop credentials as soon as startup completes, retaining only the idempotent public response.
                self.entries[identifier] = {"mode": entry["mode"], "expires": entry["expires"],
                                            "state": "done", "result": copy.deepcopy(result)}

    def fail(self, identifier):
        with self.lock:
            if identifier in self.entries:
                entry = self.entries[identifier]
                self.entries[identifier] = {"mode": entry["mode"], "expires": entry["expires"],
                                            "state": "failed", "result": None}

    def revoke(self, identifier):
        with self.lock:
            self.entries.pop(identifier, None)


def register_prepared_api(app, web_model, web_start, mobile_start, prepare_device, prepare_model,
                          select_provider, key_provider, key_env):
    store = PreparedRequests()
    app.state.prepared_mcp_requests = store
    mobile_fields = {name: (parameter.annotation, parameter.default)
                     for name, parameter in inspect.signature(mobile_start).parameters.items() if name != "apk"}
    mobile_model = create_model("PreparedAndroidSettings", __config__=ConfigDict(extra="forbid"), **mobile_fields)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        if request.url.path.startswith(("/api/settings/mcp-requests", "/api/mcp/prepared/")):
            return JSONResponse(status_code=422, content={"detail": "Invalid prepared-request fields. Check the configuration; private values were omitted."})
        return await request_validation_exception_handler(request, error)

    @app.post("/api/settings/mcp-requests")
    def prepare(body: Preparation):
        # Studio-only: middleware denies /api/settings to MCP clients. No device or test starts here.
        from .android import AndroidEnvironmentError, validate_apk, validate_mobile_config
        from .mcp_bridge import website_url
        from .safety import redact, redact_data

        policy = public_policy()
        if not policy["mcp_allowed"]:
            raise HTTPException(403, "Approve your assistant in Privacy settings before preparing a request.")
        values = dict(body.settings)
        if values.get("authorized") is not True:
            raise HTTPException(400, "Confirm ownership or permission for this target.")
        if len(json.dumps(values)) > 100000:
            raise HTTPException(413, "Configuration is too large. Split the workflows into separate runs.")
        try:
            if not body.task.strip() or any(values.get(key) is not None and not isinstance(values[key], str)
                                            for key in PRIVATE_FIELDS | {"llm_provider", "llm_model"}):
                raise ValueError("Invalid text setting")
            provider = values.get("llm_provider") or None
            if values.get("api_key") and provider is None:
                provider = key_provider(values["api_key"].strip())
            values["llm_provider"] = select_provider(provider, values.get("privacy_mode"))
            if values.get("api_key") and not key_env.get(values["llm_provider"]):
                raise ValueError("API key requires a cloud provider")
            values.update(workflow="mcp", privacy_mode=policy["mode"])
            values["requirements"] = "\n".join(v for v in (values.get("requirements"), body.task) if v)
            apk_path = None
            if body.platform == "android":
                mode = values.get("app_mode")
                values.update(package_name=body.target if mode == "installed" else "",
                              start_url=body.target if mode == "web" else "")
                if mode == "web":
                    values["app_activity"] = ""
                values = mobile_model.model_validate(values).model_dump()
                config = validate_mobile_config({k: v for k, v in values.items() if k not in PRIVATE_FIELDS})
                for key in values.keys() & config.keys():
                    values[key] = config[key]
                for key in ("qa_contract", "expected_destinations", "expected_values"):
                    if not isinstance(values[key], str):
                        values[key] = json.dumps(values[key])
                if mode == "apk":
                    apk_path = str(validate_apk(Path(body.target).expanduser()).resolve())
                target = Path(apk_path).name if apk_path else body.target
            else:
                values.update(source=website_url(body.target), website_only=True)
                if set(values) - web_model.model_fields.keys():
                    raise ValueError("Unknown web setting")
                values = web_model.model_validate(values).model_dump()
                from .qa_contracts import parse_contract
                parse_contract(values.get("qa_contract"))
                target = values["source"]
        except HTTPException:
            raise
        except (ValueError, TypeError, OSError, AndroidEnvironmentError) as error:
            # ValidationError contains input values; never echo it into the page or assistant transcript.
            raise HTTPException(400, "Invalid test settings. Check the target, APK path, limits, provider and approved workflows.") from error
        identifier = store.put({"platform": body.platform, "settings": values, "apk_path": apk_path,
                                "avd_name": body.avd_name, "mode": policy["mode"]})
        private = [values[key] for key in PRIVATE_FIELDS if isinstance(values.get(key), str) and values[key]]
        public = {key: value for key, value in values.items() if key not in PRIVATE_FIELDS}
        return {"request_id": identifier, "expires_in_s": REQUEST_TTL_S, "target": redact(target, private),
                "platform": body.platform, "settings": redact_data(public, private), "task": redact(body.task, private),
                "private_inputs_configured": any(values.get(key) for key in PRIVATE_FIELDS),
                "note": "Configuration prepared locally. Nothing has executed. Private inputs expire after 15 minutes."}

    @app.delete("/api/settings/mcp-requests/{identifier}")
    def revoke(identifier: str):
        store.revoke(identifier)
        return {"revoked": True}

    @app.post("/api/mcp/prepared/{identifier}/start")
    async def start(identifier: str, body: StartPrepared):
        if body.authorized is not True:
            raise HTTPException(400, "Explicit permission is required to start the prepared test.")
        policy = public_policy()
        if not policy["mcp_allowed"]:
            raise HTTPException(403, "MCP access needs approval in Privacy settings.")
        entry = store.claim(identifier, policy["mode"])
        if "result" in entry and entry.get("platform") is None:
            return entry["result"]
        try:
            values = entry["settings"]
            if entry["platform"] == "web":
                result = await run_in_threadpool(web_start, web_model.model_validate(values))
            else:
                ready = await prepare_device(prepare_model(device_id=values["device_id"], avd_name=entry["avd_name"],
                                             appium_url=values["appium_url"], authorized=True))
                values["device_id"] = ready["device_id"]
                if entry["apk_path"]:
                    from .android import validate_apk
                    path = validate_apk(Path(entry["apk_path"]))
                    with path.open("rb") as stream:
                        upload = UploadFile(file=stream, filename=path.name)
                        result = await mobile_start(**values, apk=upload)
                else:
                    result = await mobile_start(**values, apk=None)
        except BaseException:
            store.fail(identifier)
            raise
        store.finish(identifier, result)
        return result
