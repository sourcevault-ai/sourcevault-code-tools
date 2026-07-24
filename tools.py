"""LLM-callable tools: schemas, registration, and handlers."""

import json
import os

from .formatting import _read_file_content_or_result
from .helpers import _params, _positive_int, _relative_path, _repo_name
from .transport import (
    DEFAULT_HISTORY_URL,
    DEFAULT_READ_FILE_URL,
    DEFAULT_SEARCH_URL,
    _debug,
    _post_signed_json,
)


def _register_code_search_tool(ctx, name):
    description = (
        "SourceVault local repository code search. Search indexed private repos under REPO_ROOT "
        "through sourcevault and return matching code chunks for Hermes."
    )
    ctx.register_tool(
        name=name,
        toolset="sourcevault_code_tools",
        schema={
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_name": {
                        "type": "string",
                        "description": "SourceVault repository name under REPO_ROOT, for example hello-world.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Natural-language or code search query to run against the local repo index.",
                    },
                    "n_results": {
                        "type": "integer",
                        "description": "Maximum number of matching chunks to return.",
                        "default": 5,
                    },
                    "include_content": {
                        "type": "boolean",
                        "description": "Include full chunk content in search results.",
                        "default": False,
                    },
                },
                "required": ["repo_name", "query"],
            },
        },
        handler=handle_code_search,
        description=description,
    )


def _register_code_read_tool(ctx, name):
    description = (
        "SourceVault local repository file content fetcher. Gets the exact content of a repo-confined "
        "file from a private repo under REPO_ROOT through sourcevault for Hermes. Use this when "
        "the user asks for a file's contents from an indexed local repository."
    )
    ctx.register_tool(
        name=name,
        toolset="sourcevault_code_tools",
        schema={
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_name": {
                        "type": "string",
                        "description": "SourceVault repository name under REPO_ROOT, for example hello-world.",
                    },
                    "relative_path": {
                        "type": "string",
                        "description": "Repo-relative file path to read, for example index.js.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Alias for relative_path. May be repo-relative or an absolute path inside the repo.",
                    },
                    "file": {
                        "type": "string",
                        "description": "Alias for relative_path.",
                    },
                    "filename": {
                        "type": "string",
                        "description": "Alias for relative_path.",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Alias for relative_path.",
                    },
                    "filepath": {
                        "type": "string",
                        "description": "Alias for relative_path.",
                    },
                    "relativePath": {
                        "type": "string",
                        "description": "Alias for relative_path.",
                    },
                    "max_bytes": {
                        "type": "integer",
                        "description": "Maximum bytes to read.",
                        "default": 50000,
                    },
                },
                "required": ["repo_name", "relative_path"],
            },
        },
        handler=handle_code_read_file,
        description=description,
    )


def _register_code_history_tool(ctx, name):
    description = (
        "SourceVault git-history search. Answers questions about a repo's commit history "
        "(when something changed, why, by whom) from the locally indexed history. "
        "Requires SourceVault v1.8 or newer."
    )
    ctx.register_tool(
        name=name,
        toolset="sourcevault_code_tools",
        schema={
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_name": {
                        "type": "string",
                        "description": "SourceVault repository name under REPO_ROOT, for example hello-world.",
                    },
                    "question": {
                        "type": "string",
                        "description": "Natural-language question about the repo's commit history.",
                    },
                    "n_results": {
                        "type": "integer",
                        "description": "Maximum number of matching commits to return.",
                        "default": 5,
                    },
                },
                "required": ["repo_name", "question"],
            },
        },
        handler=handle_code_history,
        description=description,
    )


def handle_code_history(params=None, **kwargs):
    _debug("code_history raw params=", params, " kwargs=", kwargs)
    params = _params(params, kwargs)
    _debug("code_history normalized params=", params)

    body = {
        "repo_name": _repo_name(params),
        "question": str(params.get("question") or params.get("query") or "").strip(),
        "n_results": _positive_int(params.get("n_results") or params.get("max_results"), 5),
    }

    result = _post_signed_json(
        os.environ.get("CODE_HISTORY_URL", DEFAULT_HISTORY_URL),
        body,
    )
    # An older SourceVault has no /api/history-search; express answers with a
    # "Cannot POST" page instead of JSON. Translate that into advice.
    if isinstance(result, str) and "Cannot POST" in result:
        return json.dumps(
            {
                "success": False,
                "ok": False,
                "error": "history_search_unsupported",
                "detail": "This SourceVault does not serve /api/history-search. Upgrade to v1.8 or newer.",
            },
            separators=(",", ":"),
        )
    return result


def handle_code_search(params=None, **kwargs):
    _debug("code_search raw params=", params, " kwargs=", kwargs)
    params = _params(params, kwargs)
    _debug("code_search normalized params=", params)

    body = {
        "repo_name": _repo_name(params),
        "query": str(params.get("query") or "").strip(),
        "n_results": _positive_int(params.get("n_results") or params.get("max_results"), 5),
    }

    if params.get("include_content"):
        body["include_content"] = True

    return _post_signed_json(
        os.environ.get("CODE_SEARCH_URL", DEFAULT_SEARCH_URL),
        body,
    )


def handle_code_read_file(params=None, **kwargs):
    _debug("code_read_file raw params=", params, " kwargs=", kwargs)
    params = _params(params, kwargs)
    _debug("code_read_file normalized params=", params)

    repo_name = _repo_name(params)
    relative_path = _relative_path(params, repo_name)
    if not relative_path:
        return json.dumps(
            {
                "success": False,
                "ok": False,
                "error": "missing_relative_path",
                "detail": (
                    "relative_path is required. Also accepted aliases: "
                    "path, file, filename, file_path, filepath, relativePath."
                ),
            },
            separators=(",", ":"),
        )

    body = {
        "repo_name": repo_name,
        "relative_path": relative_path,
        "max_bytes": _positive_int(params.get("max_bytes"), 50000),
    }

    result = _post_signed_json(
        os.environ.get("CODE_READ_FILE_URL", DEFAULT_READ_FILE_URL),
        body,
    )
    return _read_file_content_or_result(result)
