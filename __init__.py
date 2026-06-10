"""Hermes plugin exposing sourcevault code tools."""

import hashlib
import hmac
import json
import logging
import os
import pathlib
import shlex
import subprocess
import urllib.error
import urllib.request
import uuid


DEFAULT_SEARCH_URL = "http://127.0.0.1:9000/api/search-codebase"
DEFAULT_READ_FILE_URL = "http://127.0.0.1:9000/api/read-file"
logger = logging.getLogger("sourcevault_code_tools")


def register(ctx):
    _register_code_command(
        ctx,
        ("code-help", "code_help"),
        _handle_code_help_command,
        "Show sourcevault code-memory slash command help.",
    )
    _register_code_search_tool(ctx, "code_search")
    _register_code_search_tool(ctx, "sourcevault_search")
    _register_code_read_tool(ctx, "code_read_file")
    _register_code_read_tool(ctx, "code_read")
    _register_code_read_tool(ctx, "sourcevault_read")

    _register_code_command(
        ctx,
        ("code-read", "code_read"),
        _handle_code_read_command,
        "Read a file from an indexed local repo.",
    )
    _register_code_command(
        ctx,
        ("code-search", "code_search"),
        _handle_code_search_command,
        "Search an indexed local repo.",
    )
    _register_code_command(
        ctx,
        ("code-context", "code_context"),
        _handle_code_context_command,
        "Search an indexed local repo and return code context for reasoning.",
    )
    _register_code_command(
        ctx,
        ("code-ask", "code_ask"),
        lambda raw_args: _handle_code_ask_command(raw_args, ctx),
        "Build a SourceVault code context prompt for a repo question.",
    )
    _register_code_command(
        ctx,
        ("code-status", "code_status"),
        _handle_code_status_command,
        "Show sourcevault code-memory integration status.",
    )
    _register_code_command(
        ctx,
        ("code-repos", "code_repos"),
        _handle_code_repos_command,
        "List local repos available to code-memory tools.",
    )
    _register_code_command(
        ctx,
        ("code-sync", "code_sync"),
        _handle_code_sync_command,
        "Run git pull --ff-only for a local repo mirror.",
    )


def _register_code_command(ctx, names, handler, description):
    for name in names:
        ctx.register_command(
            name,
            handler=handler,
            description=description,
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


def _handle_code_read_command(raw_args):
    try:
        args = shlex.split(raw_args or "")
    except ValueError as error:
        return f"Usage: /code-read <repo_name> <relative_path> [max_bytes]\nError: {error}"

    if len(args) < 2:
        return "Usage: /code-read <repo_name> <relative_path> [max_bytes]"

    result = handle_code_read_file(
        {
            "repo_name": args[0],
            "relative_path": args[1],
            "max_bytes": args[2] if len(args) > 2 else 50000,
        }
    )

    return _read_file_command_output(result)


def _handle_code_help_command(raw_args):
    del raw_args
    return "\n".join(
        [
            "SourceVault code memory commands:",
            "/code-status",
            "/code_status",
            "/code-repos",
            "/code_repos",
            "/code-sync <repo_name>",
            "/code_sync <repo_name>",
            "/code-search <repo_name> \"query\" [n_results]",
            "/code_search <repo_name> \"query\" [n_results]",
            "/code-context <repo_name> \"query\" [n_results]",
            "/code_context <repo_name> \"query\" [n_results]",
            "/code-ask <repo_name> \"query\" \"question\" [n_results]",
            "/code_ask <repo_name> \"query\" \"question\" [n_results]",
            "/code-read <repo_name> <relative_path> [max_bytes]",
            "/code_read <repo_name> <relative_path> [max_bytes]",
            "",
            "Use underscore commands from Telegram; hyphen commands are best for Hermes CLI.",
            "Repos live under REPO_ROOT, usually ~/.hermes/repos.",
            "After syncing a repo, reindex from sourcevault:",
            "npm run sync-and-reindex -- <repo_name>",
        ]
    )


def _handle_code_search_command(raw_args):
    try:
        args = shlex.split(raw_args or "")
    except ValueError as error:
        return f"Usage: /code-search <repo_name> <query> [n_results]\nError: {error}"

    if len(args) < 2:
        return "Usage: /code-search <repo_name> <query> [n_results]"

    result = handle_code_search(
        {
            "repo_name": args[0],
            "query": args[1],
            "n_results": args[2] if len(args) > 2 else 5,
        }
    )

    return _format_search_command_output(result)


def _handle_code_context_command(raw_args):
    try:
        args = shlex.split(raw_args or "")
    except ValueError as error:
        return f"Usage: /code-context <repo_name> <query> [n_results]\nError: {error}"

    if len(args) < 2:
        return "Usage: /code-context <repo_name> <query> [n_results]"

    result = handle_code_search(
        {
            "repo_name": args[0],
            "query": args[1],
            "n_results": args[2] if len(args) > 2 else 5,
            "include_content": True,
        }
    )

    return _format_context_command_output(result)


def _handle_code_ask_command(raw_args, ctx=None):
    try:
        args = shlex.split(raw_args or "")
    except ValueError as error:
        return f"Usage: /code-ask <repo_name> <query> <question> [n_results]\nError: {error}"

    if len(args) < 3:
        return "Usage: /code-ask <repo_name> <query> <question> [n_results]"

    repo_name = args[0]
    query = args[1]
    question = args[2]
    n_results = args[3] if len(args) > 3 else 5

    result = _search_context(repo_name, query, n_results)
    prompt = _format_ask_command_output(result, question=question)

    if not ctx or not hasattr(ctx, "llm"):
        return prompt

    try:
        followup_query = _suggest_followup_query(ctx, result, question)
        if followup_query:
            followup_result = _search_context(repo_name, followup_query, n_results)
            result = _merge_search_results(result, followup_result)
            prompt = _format_ask_command_output(result, question=question)
        response = ctx.llm.complete(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are SourceVault's local code analysis assistant. "
                        "Use retrieved SourceVault chunks as evidence. "
                        "Separate observed facts from general best-practice suggestions. "
                        "Do not claim a file, dependency, script, test, or behavior exists unless it appears in the provided context. "
                        "Reference file paths, chunk numbers, and function names when useful. "
                        "If the retrieved context is insufficient, say exactly what is missing."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            timeout=120,
            purpose="sourcevault_code_ask",
        )
        text = str(getattr(response, "text", "") or "").strip()
        return text or prompt
    except Exception as error:
        return "\n".join(
            [
                "SourceVault retrieved the repository context, but Hermes LLM completion failed.",
                f"Error: {error}",
                "",
                "Fallback prompt pack:",
                "",
                prompt,
            ]
        )


def _search_context(repo_name, query, n_results):
    return handle_code_search(
        {
            "repo_name": repo_name,
            "query": query,
            "n_results": n_results,
            "include_content": True,
        }
    )


def _suggest_followup_query(ctx, result, question):
    parsed = _parse_successful_search_result(result)
    if not isinstance(parsed, dict):
        return ""

    results = parsed.get("results") or []
    if not results:
        return ""

    context_summary = _context_index_lines(parsed)
    try:
        followup = _complete_followup_plan(ctx, question, context_summary)
    except Exception as error:
        _debug("follow-up retrieval planning failed:", error)
        return ""

    if not followup or followup.get("needs_more_context") is not True:
        return ""

    query = str(followup.get("query") or "").strip()
    if len(query) < 3 or len(query) > 240:
        return ""

    original_query = str(parsed.get("query") or "").strip().lower()
    if query.lower() == original_query:
        return ""

    _debug("follow-up retrieval query=", query, " reason=", followup.get("reason") or "")
    return query


def _complete_followup_plan(ctx, question, context_summary):
    instructions = (
        "Decide whether one follow-up SourceVault search query is needed before answering. "
        "Return needs_more_context=false when the current chunks are enough. "
        "If more context is needed, return one concise search query."
    )
    prompt = "\n".join(
        [
            f"User question: {question}",
            "",
            "Current retrieved chunks:",
            context_summary,
        ]
    )
    schema = {
        "type": "object",
        "properties": {
            "needs_more_context": {"type": "boolean"},
            "query": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["needs_more_context", "query", "reason"],
    }

    if hasattr(ctx.llm, "complete_structured"):
        response = ctx.llm.complete_structured(
            instructions=instructions,
            input=[{"type": "text", "text": prompt}],
            json_schema=schema,
            schema_name="sourcevault.followup_query",
            temperature=0,
            timeout=60,
            purpose="sourcevault_code_ask_followup",
        )
        if getattr(response, "parsed", None):
            return response.parsed
        return _extract_json_object(str(getattr(response, "text", "") or "").strip())

    response = ctx.llm.complete(
        messages=[
            {
                "role": "system",
                "content": f"{instructions} Return only compact JSON matching this schema: {json.dumps(schema)}",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0,
        timeout=60,
        purpose="sourcevault_code_ask_followup",
    )
    return _extract_json_object(str(getattr(response, "text", "") or "").strip())


def _extract_json_object(text):
    if not text:
        return {}

    candidates = [text]
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    return {}


def _handle_code_status_command(raw_args):
    del raw_args
    search_url = os.environ.get("CODE_SEARCH_URL", DEFAULT_SEARCH_URL)
    read_url = os.environ.get("CODE_READ_FILE_URL", DEFAULT_READ_FILE_URL)
    health_url = search_url.split("/api/", 1)[0].rstrip("/") + "/health"

    try:
        with urllib.request.urlopen(health_url, timeout=5) as response:
            body = response.read().decode("utf-8")
    except Exception as error:
        return f"sourcevault: FAIL {error}\nsearch_url: {search_url}\nread_file_url: {read_url}"

    secret_state = "set" if os.environ.get("CODE_SEARCH_HMAC_SECRET") else "missing"
    return "\n".join(
        [
            "sourcevault: OK",
            f"health: {body}",
            f"search_url: {search_url}",
            f"read_file_url: {read_url}",
            f"code_search_hmac_secret: {secret_state}",
        ]
    )


def _handle_code_repos_command(raw_args):
    del raw_args
    repo_root = os.environ.get("REPO_ROOT", os.path.expanduser("~/.hermes/repos"))
    root_path = pathlib.Path(repo_root)
    if not root_path.is_dir():
        return f"repo_root missing: {repo_root}"

    repos = []
    for child in sorted(root_path.iterdir(), key=lambda item: item.name.lower()):
        if child.is_dir():
            suffix = " (git)" if (child / ".git").exists() else ""
            repos.append(f"- {child.name}{suffix}")

    if not repos:
        return f"No repositories found under {repo_root}"

    return "\n".join([f"Repositories under {repo_root}:"] + repos)


def _handle_code_sync_command(raw_args):
    try:
        args = shlex.split(raw_args or "")
    except ValueError as error:
        return f"Usage: /code-sync <repo_name>\nError: {error}"

    if len(args) != 1:
        return "Usage: /code-sync <repo_name>"

    repo_name = _clean_repo_name(args[0])
    if not repo_name:
        return "Usage: /code-sync <repo_name>"

    repo_root = pathlib.Path(
        os.environ.get("REPO_ROOT", os.path.expanduser("~/.hermes/repos"))
    ).resolve()
    repo_path = (repo_root / repo_name).resolve()
    if repo_path == repo_root or repo_root not in repo_path.parents:
        return f"invalid repo_name: {args[0]}"
    if not repo_path.is_dir():
        return f"Repository not found: {repo_name}"
    if not (repo_path / ".git").exists():
        return f"Repository is not a git repo: {repo_path}"

    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_path), "pull", "--ff-only"],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except Exception as error:
        return f"git pull failed: {error}"

    output = (completed.stdout + completed.stderr).strip()
    if completed.returncode != 0:
        return f"git pull failed for {repo_name}:\n{output}"

    return output or f"{repo_name} already up to date."


def _params(params, kwargs):
    merged = _coerce_mapping(params)
    merged.update(_coerce_mapping(kwargs))

    for key in ("arguments", "args", "input", "parameters", "params"):
        nested = _coerce_mapping(merged.get(key))
        if nested:
            merged.update(nested)

    return merged


def _coerce_mapping(value):
    if isinstance(value, dict):
        return dict(value)

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}

        if isinstance(parsed, dict):
            return dict(parsed)

    return {}


def _read_file_content_or_result(result):
    try:
        parsed = json.loads(result)
    except (TypeError, json.JSONDecodeError):
        return result

    if not isinstance(parsed, dict):
        return result

    if parsed.get("ok") is True and isinstance(parsed.get("content"), str):
        relative_path = parsed.get("relative_path")
        file_path = parsed.get("fullPath") or parsed.get("path")
        return json.dumps(
            {
                "ok": True,
                "repo_name": parsed.get("repo_name"),
                "relative_path": relative_path,
                "file_path": file_path,
                "content": parsed["content"],
                "response_instruction": (
                    "When answering the user, copy the content field exactly. "
                    "Do not add markdown, punctuation, semicolons, explanations, or formatting."
                ),
            },
            separators=(",", ":"),
        )

    return result


def _read_file_command_output(result):
    try:
        parsed = json.loads(result)
    except (TypeError, json.JSONDecodeError):
        return result

    if not isinstance(parsed, dict):
        return result

    if parsed.get("ok") is True and isinstance(parsed.get("content"), str):
        return parsed["content"]

    return result


def _format_search_command_output(result):
    try:
        parsed = json.loads(result)
    except (TypeError, json.JSONDecodeError):
        return result

    if not isinstance(parsed, dict):
        return result

    if parsed.get("ok") is False or parsed.get("success") is False:
        return result

    results = parsed.get("results") or []
    lines = [
        parsed.get("summary")
        or f"Found {len(results)} result(s) for {parsed.get('query') or 'query'}",
    ]

    for index, item in enumerate(results, start=1):
        file_name = item.get("file") or item.get("fullPath") or "<unknown>"
        chunk = item.get("chunk")
        distance = item.get("distance")
        preview = " ".join(str(item.get("preview") or "").split())
        if len(preview) > 180:
            preview = f"{preview[:177]}..."

        meta = f"#{index} {file_name}"
        if chunk is not None:
            meta += f" chunk={chunk}"
        if isinstance(distance, (int, float)):
            meta += f" distance={distance:.4f}"

        lines.append(meta)
        if preview:
            lines.append(f"  {preview}")

    return "\n".join(lines)


def _format_context_command_output(result):
    parsed = _parse_successful_search_result(result)
    if not isinstance(parsed, dict):
        return parsed

    return _context_lines(parsed).rstrip()


def _format_ask_command_output(result, question):
    parsed = _parse_successful_search_result(result)
    if not isinstance(parsed, dict):
        return parsed

    lines = [
        "Use the SourceVault repository context below to answer the user question.",
        "Do not call tools.",
        "Do not ask for a repo path.",
        "Use the retrieved chunks as evidence.",
        "Separate observed facts from general best-practice suggestions.",
        "Do not claim a file, dependency, script, test, or behavior exists unless it appears in the snippets below.",
        "Reference file paths, chunk numbers, and function names when useful.",
        "Use this answer shape:",
        "1. Observed From Retrieved Context",
        "2. Answer",
        "3. Suggested Improvements",
        "4. Missing Context, if any",
        "",
        f"User question: {question}",
        "",
        _context_lines(parsed),
        "",
        "Answer the user question now.",
    ]
    return "\n".join(lines).rstrip()


def _merge_search_results(primary_result, followup_result):
    primary = _parse_successful_search_result(primary_result)
    followup = _parse_successful_search_result(followup_result)
    if not isinstance(primary, dict):
        return primary_result
    if not isinstance(followup, dict):
        return primary_result

    merged = dict(primary)
    seen = set()
    results = []

    for round_name, parsed in (("initial", primary), ("followup", followup)):
        for item in parsed.get("results") or []:
            key = (
                item.get("file"),
                item.get("chunk"),
                item.get("preview") or item.get("content"),
            )
            if key in seen:
                continue
            seen.add(key)
            enriched = dict(item)
            enriched["retrievalRound"] = round_name
            results.append(enriched)

    merged["results"] = results
    merged["count"] = len(results)
    merged["summary"] = f"Found {len(results)} matching chunks across initial and follow-up retrieval"
    merged["retrieval"] = {
        "mode": "multi-hop",
        "initial_query": primary.get("query") or "",
        "followup_query": followup.get("query") or "",
    }
    return json.dumps(merged, separators=(",", ":"))


def _parse_successful_search_result(result):
    try:
        parsed = json.loads(result)
    except (TypeError, json.JSONDecodeError):
        return result

    if not isinstance(parsed, dict):
        return result

    if parsed.get("ok") is False or parsed.get("success") is False:
        return result

    return parsed


def _context_index_lines(parsed):
    results = parsed.get("results") or []
    if not results:
        return "No matching chunks found."

    lines = []
    for index, item in enumerate(results, start=1):
        file_name = item.get("file") or item.get("fullPath") or "<unknown>"
        chunk = item.get("chunk")
        distance = item.get("distance")
        symbols = _format_symbols(item)
        meta = f"- Result {index}: file={file_name}"
        if chunk is not None:
            meta += f" chunk={chunk}"
        if isinstance(distance, (int, float)):
            meta += f" distance={distance:.4f}"
        if item.get("retrievalRound"):
            meta += f" round={item.get('retrievalRound')}"
        if symbols:
            meta += f" symbols={symbols}"
        lines.append(meta)

    return "\n".join(lines)


def _context_lines(parsed):
    results = parsed.get("results") or []
    repo_name = parsed.get("repo_name") or (results[0].get("repoName") if results else "")
    query = parsed.get("query") or ""
    lines = [
        "SourceVault repository context",
        f"repo_name: {repo_name}",
        f"query: {query}",
        f"results: {len(results)}",
        "",
        "Use the snippets below as the repo context for the user's next question.",
        "Reference file paths and function names when making suggestions.",
        "",
    ]

    if not results:
        lines.append("No matching chunks found.")
        return "\n".join(lines)

    retrieval = parsed.get("retrieval") or {}
    if retrieval.get("mode"):
        lines.append(f"retrieval_mode: {retrieval.get('mode')}")
        if retrieval.get("followup_query"):
            lines.append(f"followup_query: {retrieval.get('followup_query')}")
        lines.append("")

    lines.append("Retrieved chunk index:")
    lines.append(_context_index_lines(parsed))
    lines.append("")

    for index, item in enumerate(results, start=1):
        file_name = item.get("file") or item.get("fullPath") or "<unknown>"
        chunk = item.get("chunk")
        distance = item.get("distance")
        heading = f"## Result {index}: {file_name}"
        if chunk is not None:
            heading += f" chunk={chunk}"
        if isinstance(distance, (int, float)):
            heading += f" distance={distance:.4f}"
        if item.get("retrievalRound"):
            heading += f" round={item.get('retrievalRound')}"
        symbols = _format_symbols(item)

        content = str(item.get("content") or item.get("preview") or "").strip()
        if len(content) > 4000:
            content = f"{content[:4000].rstrip()}\n... [truncated]"

        lines.extend(
            [
                heading,
                *(["symbols: " + symbols] if symbols else []),
                "```",
                content,
                "```",
                "",
            ]
        )

    return "\n".join(lines).rstrip()


def _format_symbols(item):
    names = [part for part in str(item.get("symbolNames") or "").split(",") if part]
    kinds = [part for part in str(item.get("symbolKinds") or "").split(",") if part]
    if not names:
        return ""

    pairs = []
    for index, name in enumerate(names[:8]):
        kind = kinds[index] if index < len(kinds) else "symbol"
        pairs.append(f"{kind}:{name}")
    return ",".join(pairs)


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


def _positive_int(value, default):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default

    return parsed if parsed > 0 else default


def _repo_name(params):
    explicit = str(params.get("repo_name") or params.get("repo") or "").strip()
    if explicit:
        return explicit

    path = str(params.get("repo_path") or params.get("path") or "").strip()
    if not path:
        return ""

    return pathlib.PurePosixPath(path).name


def _clean_repo_name(value):
    return "".join(
        char for char in str(value or "").strip()
        if char.isalnum() or char in {".", "_", "-"}
    )[:120]


def _relative_path(params, repo_name):
    explicit = str(
        params.get("relative_path")
        or params.get("relativePath")
        or params.get("file_path")
        or params.get("filepath")
        or params.get("file")
        or params.get("filename")
        or ""
    ).strip()
    if explicit:
        return explicit

    path = str(params.get("path") or "").strip()
    if not path:
        return ""

    pure_path = pathlib.PurePosixPath(path)
    parts = pure_path.parts
    if repo_name in parts:
        repo_index = parts.index(repo_name)
        relative_parts = parts[repo_index + 1 :]
        if relative_parts:
            return str(pathlib.PurePosixPath(*relative_parts))

    return pure_path.name
