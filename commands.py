"""Deterministic slash-command handlers."""

import json
import os
import pathlib
import shlex
import subprocess
import urllib.request

from .formatting import (
    _context_index_lines,
    _extract_json_object,
    _format_ask_command_output,
    _format_context_command_output,
    _format_history_command_output,
    _format_search_command_output,
    _merge_search_results,
    _parse_successful_search_result,
    _read_file_command_output,
)
from .helpers import _clean_repo_name
from .transport import DEFAULT_READ_FILE_URL, DEFAULT_SEARCH_URL, _debug
from .tools import handle_code_history, handle_code_read_file, handle_code_search


def _register_code_command(ctx, names, handler, description):
    for name in names:
        ctx.register_command(
            name,
            handler=handler,
            description=description,
        )


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
            "/code-ask <repo_name> \"question\" [n_results]",
            "/code_ask <repo_name> \"question\" [n_results]",
            "/code-ask <repo_name> \"retrieval query\" \"question\" [n_results]",
            "/code-history <repo_name> \"question\" [n_results]",
            "/code_history <repo_name> \"question\" [n_results]",
            "/code-read <repo_name> <relative_path> [max_bytes]",
            "/code_read <repo_name> <relative_path> [max_bytes]",
            "",
            "Use underscore commands from Telegram; hyphen commands are best for Hermes CLI.",
            "Repos live under REPO_ROOT, usually ~/.hermes/repos.",
            "After syncing a repo, reindex from sourcevault:",
            "npm run sync-and-reindex -- <repo_name>",
        ]
    )


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


def _handle_code_history_command(raw_args):
    try:
        args = shlex.split(raw_args or "")
    except ValueError as error:
        return f'Usage: /code-history <repo_name> "question" [n_results]\nError: {error}'

    if len(args) < 2:
        return 'Usage: /code-history <repo_name> "question" [n_results]'

    result = handle_code_history(
        {
            "repo_name": args[0],
            "question": args[1],
            "n_results": args[2] if len(args) > 2 else 5,
        }
    )

    return _format_history_command_output(result)


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


_ASK_USAGE = (
    'Usage: /code-ask <repo_name> "<question>" [n_results]\n'
    '   or: /code-ask <repo_name> "<retrieval query>" "<question>" [n_results]'
)


def _handle_code_ask_command(raw_args, ctx=None):
    try:
        args = shlex.split(raw_args or "")
    except ValueError as error:
        return f"{_ASK_USAGE}\nError: {error}"

    if len(args) < 2:
        return _ASK_USAGE

    # The question is the only required input; it doubles as the retrieval
    # query unless an explicit query is given (mirrors the dashboard).
    # Forms: <repo> <question>            | <repo> <question> <n>
    #        <repo> <query> <question>    | <repo> <query> <question> <n>
    repo_name = args[0]
    rest = args[1:]
    n_results = 5
    if len(rest) > 1 and rest[-1].isdigit():
        n_results = rest[-1]
        rest = rest[:-1]

    if len(rest) == 1:
        query = question = rest[0]
    elif len(rest) == 2:
        query, question = rest
    else:
        return _ASK_USAGE

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
