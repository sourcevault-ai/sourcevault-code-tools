"""Signed HTTP transport (module named transport, not http: a module called
http here shadows the stdlib http package whenever the plugin directory is on
sys.path, breaking urllib) to the SourceVault API, plus debug logging."""

import hashlib
import hmac
import json
import logging
import os
import time
import urllib.error
import urllib.request
import uuid

from .formatting import _error_hint


DEFAULT_SEARCH_URL = "http://127.0.0.1:9000/api/search-codebase"
DEFAULT_READ_FILE_URL = "http://127.0.0.1:9000/api/read-file"
DEFAULT_HISTORY_URL = "http://127.0.0.1:9000/api/history-search"
logger = logging.getLogger("sourcevault_code_tools")


def _signing_identity():
    """Return (key_bytes, agent_name) for request signing.

    With both SOURCEVAULT_AGENT_NAME and SOURCEVAULT_AGENT_TOKEN set, sign as
    that agent: the server keeps only sha256(token) and uses that hex digest
    string as the HMAC key (agent-tokens.js keyHex), so the key here is the
    UTF-8 bytes of the lowercase hex string — not the raw digest bytes.
    Otherwise fall back to the shared CODE_SEARCH_HMAC_SECRET with no agent.
    """
    name = os.environ.get("SOURCEVAULT_AGENT_NAME", "").strip()
    token = os.environ.get("SOURCEVAULT_AGENT_TOKEN", "").strip()
    if name and token:
        key = hashlib.sha256(token.encode("utf-8")).hexdigest().encode("utf-8")
        return key, name
    if name or token:
        _debug(
            "agent identity ignored: need BOTH SOURCEVAULT_AGENT_NAME and "
            "SOURCEVAULT_AGENT_TOKEN; falling back to CODE_SEARCH_HMAC_SECRET"
        )
    secret = os.environ.get("CODE_SEARCH_HMAC_SECRET", "")
    return (secret.encode("utf-8") if secret else b""), ""


def _post_signed_json(url, body):
    _debug("POST ", url, " body=", body)
    raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
    key, agent = _signing_identity()

    headers = {
        "Content-Type": "application/json",
        "X-Request-Id": str(uuid.uuid4()),
    }

    if key:
        # Timestamped (replay-protected) signature: sign f"{ts}.{nonce}." + body
        # and send the companion headers. Matches createTimestampedHmacHeaders
        # in services/security/hmac.js; the server rejects stale timestamps and
        # reused nonces, so a captured request cannot be replayed.
        timestamp = str(int(time.time() * 1000))
        nonce = str(uuid.uuid4())
        signed = f"{timestamp}.{nonce}.".encode("utf-8") + raw
        digest = hmac.new(key, signed, hashlib.sha256).hexdigest()
        headers["X-Code-Search-Signature"] = f"sha256={digest}"
        headers["X-Code-Search-Signature-Timestamp"] = timestamp
        headers["X-Code-Search-Signature-Nonce"] = nonce
        if agent:
            # Naming an agent commits to its key: the server hard-fails on an
            # unknown name rather than falling back to the shared secret, so
            # the header is only ever sent alongside an agent-keyed signature.
            headers["X-Code-Search-Signature-Agent"] = agent

    request = urllib.request.Request(url, data=raw, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        payload = {
            "success": False,
            "ok": False,
            "error": "sourcevault_http_error",
            "status": error.code,
            "detail": detail,
        }
        try:
            parsed = json.loads(detail)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and parsed.get("error"):
            payload["error"] = str(parsed["error"])
            payload["detail"] = str(parsed.get("detail") or "")
        if error.code == 429:
            retry_after = error.headers.get("Retry-After") if error.headers else None
            if retry_after:
                payload["retry_after"] = str(retry_after).strip()
        hint = _error_hint(payload)
        if hint:
            payload["hint"] = hint
        return json.dumps(payload)
    except Exception as error:
        return json.dumps(
            {
                "success": False,
                "ok": False,
                "error": "sourcevault_request_failed",
                "detail": str(error),
            }
        )


def _debug(*parts):
    if os.environ.get("SOURCEVAULT_CODE_TOOLS_DEBUG", "").lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return

    logger.info("[sourcevault-code-tools] %s", " ".join(str(part) for part in parts))
