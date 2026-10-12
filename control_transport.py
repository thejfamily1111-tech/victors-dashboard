"""Fixed-path, authenticated desired-state mailbox for Victor's paper services.

Operator requests are optimistic SHA updates. Device reports never change desired
state. A transport receipt means queued, never that a Mac applied the request.
"""
from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
import hashlib
import json
import re
import ssl
import uuid
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler

REPOSITORY = "thejfamily1111-tech/victor-terminal-research"
BRANCH = "vic-premarket-handoff"
DESIRED_PATH = "handoffs/control/desired.json"
STATUS_PATH = "handoffs/control/status.json"
CONTROL_KEYS = (
    "qqq_trading_enabled", "qqq_research_enabled",
    "overnight_research_enabled", "vic_enabled", "beta_engine_enabled",
)
SERVICES = ("qqq", "beta", "overnight", "vic")
MAX_BYTES = 64_000
MAX_RESPONSE_BYTES = 128_000
VERSION = "victor-control-v1"
STATUS_VERSION = "victor-control-status-v1"
TIMEOUT_SECONDS = 8
HEARTBEAT_MAX_AGE_SECONDS = 90
_DEVICE = re.compile(r"[A-Za-z0-9_-]{1,80}")
_SHA = re.compile(r"[a-f0-9]{40}")
_CODE = re.compile(r"[A-Z0-9_]{1,64}")


class ControlError(Exception):
    """Safe error: deliberately retains no HTTP body, URL or credentials."""
    def __init__(self, code, status=None):
        self.code = code
        self.status = status
        super().__init__(code)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ControlError("REDIRECT_REJECTED")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _device(value):
    if not isinstance(value, str) or not _DEVICE.fullmatch(value):
        raise ControlError("INVALID_DEVICE")
    return value


def _revision(value):
    if type(value) is not int or not 0 <= value <= 2**53 - 1:
        raise ControlError("INVALID_REVISION")
    return value


def _timestamp(value, optional=False):
    if value is None and optional:
        return None
    if not isinstance(value, str) or len(value) > 50:
        raise ControlError("INVALID_TIMESTAMP")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError):
        raise ControlError("INVALID_TIMESTAMP") from None


def _controls(value, partial=False):
    if not isinstance(value, dict) or not value or set(value) - set(CONTROL_KEYS):
        raise ControlError("INVALID_CONTROLS")
    if not partial and set(value) != set(CONTROL_KEYS):
        raise ControlError("INVALID_CONTROLS")
    if any(type(item) is not bool for item in value.values()):
        raise ControlError("INVALID_CONTROLS")
    return dict(value)


def _request_id(value):
    try:
        if not isinstance(value, str) or str(uuid.UUID(value)) != value:
            raise ValueError()
    except (ValueError, AttributeError):
        raise ControlError("INVALID_REQUEST_ID") from None
    return value


def default_desired(device_id):
    return {"version": VERSION, "device_id": _device(device_id), "revision": 0,
            "controls": {key: False for key in CONTROL_KEYS},
            "updated_at": "1970-01-01T00:00:00+00:00", "request_id": None,
            "recent_requests": []}


def validate_desired(value, device_id):
    if not isinstance(value, dict) or value.get("version") != VERSION:
        raise ControlError("INVALID_DESIRED")
    if _device(value.get("device_id")) != _device(device_id):
        raise ControlError("DEVICE_MISMATCH")
    revision = _revision(value.get("revision"))
    request_id = value.get("request_id")
    if revision or request_id is not None:
        _request_id(request_id)
    history = value.get("recent_requests", [])
    if not isinstance(history, list) or len(history) > 32:
        raise ControlError("INVALID_DESIRED")
    clean_history = []
    for item in history:
        if not isinstance(item, dict) or not re.fullmatch(r"[a-f0-9]{64}", str(item.get("digest", ""))):
            raise ControlError("INVALID_DESIRED")
        item_revision = _revision(item.get("revision"))
        if item_revision > revision:
            raise ControlError("INVALID_DESIRED")
        clean_history.append({"request_id": _request_id(item.get("request_id")),
                              "digest": item["digest"], "revision": item_revision})
    return {"version": VERSION, "device_id": device_id, "revision": revision,
            "controls": _controls(value.get("controls")),
            "updated_at": _timestamp(value.get("updated_at")),
            "request_id": request_id, "recent_requests": clean_history}


def sanitize_status(value, device_id=None):
    """Validate and project onto the credential-free, fixed status schema."""
    if not isinstance(value, dict) or value.get("version") != STATUS_VERSION:
        raise ControlError("INVALID_STATUS")
    found_device = _device(value.get("device_id"))
    if device_id is not None and found_device != _device(device_id):
        raise ControlError("DEVICE_MISMATCH")
    services = value.get("services", {})
    if not isinstance(services, dict):
        raise ControlError("INVALID_STATUS")
    clean = {}
    for name in SERVICES:
        service = services.get(name, {})
        if not isinstance(service, dict):
            raise ControlError("INVALID_STATUS")
        state = service.get("state", "UNKNOWN")
        if state not in ("RUNNING", "STOPPED", "STARTING", "ERROR", "UNKNOWN"):
            raise ControlError("INVALID_STATUS")
        pid = service.get("pid")
        if pid is not None and (type(pid) is not int or not 1 <= pid < 2**31):
            raise ControlError("INVALID_STATUS")
        revision = service.get("control_revision")
        if revision is not None:
            _revision(revision)
        clean[name] = {"state": state, "pid": pid,
                       "heartbeat_at": _timestamp(service.get("heartbeat_at"), optional=True),
                       "control_revision": revision}
    error = value.get("error_code")
    if error is not None and (not isinstance(error, str) or not _CODE.fullmatch(error)):
        raise ControlError("INVALID_STATUS")
    return {"version": STATUS_VERSION, "device_id": found_device,
            "revision": _revision(value.get("revision")),
            "controls": _controls(value.get("controls")),
            "observed_at": _timestamp(value.get("observed_at")),
            "services": clean, "error_code": error}


def _json_bytes(value):
    try:
        result = json.dumps(value, allow_nan=False, ensure_ascii=True,
                            separators=(",", ":"), sort_keys=True).encode()
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise ControlError("INVALID_PAYLOAD") from None
    if len(result) > MAX_BYTES:
        raise ControlError("PAYLOAD_TOO_LARGE")
    return result


def _decode(data):
    try:
        value = json.loads(data, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (UnicodeDecodeError, TypeError, ValueError, RecursionError):
        raise ControlError("INVALID_RESPONSE") from None


def _request(token, path, method="GET", body=None):
    if path not in (DESIRED_PATH, STATUS_PATH) or method not in ("GET", "PUT"):
        raise ControlError("PATH_NOT_ALLOWED")
    if not isinstance(token, str) or not 10 <= len(token) <= 512 or not re.fullmatch(r"[A-Za-z0-9_]+", token):
        raise ControlError("NOT_CONFIGURED")
    url = "https://api.github.com/repos/" + REPOSITORY + "/contents/" + path
    if method == "GET":
        url += "?ref=" + BRANCH
    try:
        import certifi
        opener = build_opener(_NoRedirect(), HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())))
        req = Request(url, method=method, data=body, headers={
            "Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
            "Content-Type": "application/json", "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Victor-paper-control-v1", "Cache-Control": "no-cache",
        })
        with opener.open(req, timeout=TIMEOUT_SECONDS) as response:
            data = response.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            raise ControlError("RESPONSE_TOO_LARGE")
        return _decode(data)
    except ControlError:
        raise
    except HTTPError as exc:
        status = exc.code
        exc.close()
        code = ("AUTH_OR_ACCESS_ERROR" if status in (401, 403) else
                "NOT_FOUND" if status == 404 else "CONFLICT" if status in (409, 422) else
                "RATE_LIMITED" if status == 429 else "REDIRECT_REJECTED" if 300 <= status < 400 else "HTTP_ERROR")
        raise ControlError(code, status) from None
    except (OSError, ValueError, TypeError, ImportError):
        raise ControlError("NETWORK_ERROR") from None


def _read(token, path):
    item = _request(token, path)
    if item.get("type") != "file" or item.get("path") != path or item.get("encoding") != "base64":
        raise ControlError("INVALID_RESPONSE")
    sha, content, size = item.get("sha"), item.get("content"), item.get("size")
    if not isinstance(sha, str) or not _SHA.fullmatch(sha) or not isinstance(content, str):
        raise ControlError("INVALID_RESPONSE")
    if type(size) is not int or not 0 <= size <= MAX_BYTES:
        raise ControlError("PAYLOAD_TOO_LARGE")
    try:
        decoded = base64.b64decode("".join(content.split()), validate=True)
    except (ValueError, binascii.Error):
        raise ControlError("INVALID_RESPONSE") from None
    if len(decoded) != size or len(decoded) > MAX_BYTES:
        raise ControlError("INVALID_RESPONSE")
    return _decode(decoded), sha


def _write(token, path, payload, sha):
    encoded = _json_bytes(payload)
    body = {"message": "Update Victor paper control " + ("request" if path == DESIRED_PATH else "status"),
            "branch": BRANCH, "content": base64.b64encode(encoded).decode("ascii")}
    if sha is not None:
        if not isinstance(sha, str) or not _SHA.fullmatch(sha):
            raise ControlError("INVALID_SHA")
        body["sha"] = sha
    response = _request(token, path, "PUT", json.dumps(body, separators=(",", ":")).encode())
    content = response.get("content")
    if not isinstance(content, dict) or content.get("path") != path or not _SHA.fullmatch(str(content.get("sha", ""))):
        raise ControlError("WRITE_NOT_ACKNOWLEDGED")
    return {"ok": True, "sha": content["sha"]}


def _desired_with_sha(token, device_id):
    try:
        value, sha = _read(token, DESIRED_PATH)
    except ControlError as exc:
        if exc.code != "NOT_FOUND":
            raise
        return default_desired(device_id), None
    return validate_desired(value, device_id), sha


def get_desired(token, device_id):
    """Device GET only. Missing mailbox returns all-off, never enables work."""
    return _desired_with_sha(token, device_id)[0]


def publish_status(token, payload):
    """Device status PUT only; never writes desired state or executes a command."""
    clean = sanitize_status(payload)
    try:
        old, sha = _read(token, STATUS_PATH)
        old = sanitize_status(old, clean["device_id"])
        if clean["revision"] < old["revision"] or clean["observed_at"] < old["observed_at"]:
            raise ControlError("STALE_STATUS")
    except ControlError as exc:
        if exc.code != "NOT_FOUND":
            raise
        sha = None
    return _write(token, STATUS_PATH, clean, sha)


class ControlClient:
    """Dashboard server-side operator client; the token must never reach HTML."""
    def __init__(self, token, device_id, role="operator"):
        if role != "operator":
            raise ControlError("ROLE_NOT_ALLOWED")
        if not isinstance(token, str) or not token.strip():
            raise ControlError("NOT_CONFIGURED")
        self._token = token.strip()
        self.device_id = _device(device_id)

    @classmethod
    def from_settings(cls, settings, role="operator"):
        token = settings.get("CONTROL_GITHUB_TOKEN")
        device = settings.get("CONTROL_DEVICE_ID")
        if not token or not device:
            raise ControlError("NOT_CONFIGURED")
        return cls(token, device, role)

    def _status(self, desired):
        try:
            value, _ = _read(self._token, STATUS_PATH)
            applied = sanitize_status(value, self.device_id)
        except ControlError as exc:
            if exc.code != "NOT_FOUND":
                raise
            applied = None
        return {"desired": desired, "applied": applied, "server_time": _now(),
                "heartbeat_max_age_seconds": HEARTBEAT_MAX_AGE_SECONDS}

    def read_status(self):
        desired = get_desired(self._token, self.device_id)
        return self._status_or_error(desired)

    def _status_or_error(self, desired):
        # A broken/missing heartbeat must not hide the user's ability to send
        # a durable OFF request when the desired-state mailbox is reachable.
        try:
            return self._status(desired)
        except ControlError as exc:
            return {"desired": desired, "applied": None, "server_time": _now(),
                    "heartbeat_max_age_seconds": HEARTBEAT_MAX_AGE_SECONDS,
                    "status_error": exc.code}

    def request_controls(self, changes, expected_revision, request_id):
        changes = _controls(changes, partial=True)
        expected_revision = _revision(expected_revision)
        request_id = _request_id(request_id)
        desired, sha = _desired_with_sha(self._token, self.device_id)
        digest = hashlib.sha256(_json_bytes({"changes": changes, "expected_revision": expected_revision})).hexdigest()
        for prior in desired["recent_requests"]:
            if prior["request_id"] == request_id:
                if prior["digest"] != digest:
                    raise ControlError("REQUEST_ID_REUSED")
                result = self._status_or_error(desired)
                result["request"] = {"request_id": request_id, "revision": prior["revision"], "replayed": True}
                return result
        if desired["revision"] != expected_revision:
            raise ControlError("CONFLICT")
        if desired["revision"] >= 2**53 - 1:
            raise ControlError("REVISION_EXHAUSTED")
        desired["revision"] += 1
        desired["controls"].update(changes)
        desired["updated_at"] = _now()
        desired["request_id"] = request_id
        desired["recent_requests"] = (desired["recent_requests"] + [
            {"request_id": request_id, "digest": digest, "revision": desired["revision"]}])[-32:]
        # Do not retry conflicts: a stale browser must refresh current controls.
        receipt = _write(self._token, DESIRED_PATH, desired, sha)
        # Once the request is committed, a failed status fetch cannot erase the
        # receipt or tempt the caller to submit a second distinct request.
        result = self._status_or_error(desired)
        result["request"] = {"request_id": request_id, "revision": desired["revision"],
                             "replayed": False, "sha": receipt["sha"]}
        return result
