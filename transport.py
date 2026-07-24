"""Signed HTTP transport (module named transport, not http: a module called
http here shadows the stdlib http package whenever the plugin directory is on
sys.path, breaking urllib) to the SourceVault API, plus debug logging."""

import hashlib
import hmac
import json
import logging
import os
import urllib.error
import urllib.request
import uuid


DEFAULT_SEARCH_URL = "http://127.0.0.1:9000/api/search-codebase"
DEFAULT_READ_FILE_URL = "http://127.0.0.1:9000/api/read-file"
DEFAULT_HISTORY_URL = "http://127.0.0.1:9000/api/history-search"
logger = logging.getLogger("sourcevault_code_tools")


def _post_signed_json(url, body):
    _debug("POST ", url, " body=", body)
    raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
    secret = os.environ.get("CODE_SEARCH_HMAC_SECRET", "")

    headers = {
        "Content-Type": "application/json",
        "X-Request-Id": str(uuid.uuid4()),
    }

    if secret:
        digest = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        headers["X-Code-Search-Signature"] = f"sha256={digest}"

    request = urllib.request.Request(url, data=raw, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        return json.dumps(
            {
                "success": False,
                "ok": False,
                "error": "sourcevault_http_error",
                "status": error.code,
                "detail": detail,
            }
        )
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
