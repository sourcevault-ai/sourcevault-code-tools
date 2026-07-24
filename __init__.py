"""Hermes plugin exposing sourcevault code tools.

Package layout:
    helpers.py     parameter/naming helpers (pure)
    formatting.py  response parsing and output formatting (pure)
    http.py        HMAC-signed transport to the SourceVault API
    tools.py       LLM-callable tool schemas and handlers
    commands.py    deterministic slash-command handlers

`register(ctx)` below is the Hermes entry point.
"""

from .commands import (
    _handle_code_ask_command,
    _handle_code_context_command,
    _handle_code_help_command,
    _handle_code_read_command,
    _handle_code_history_command,
    _handle_code_repos_command,
    _handle_code_search_command,
    _handle_code_status_command,
    _handle_code_sync_command,
    _register_code_command,
)
from .formatting import (
    _context_index_lines,
    _extract_json_object,
    _format_ask_command_output,
    _format_context_command_output,
    _format_search_command_output,
    _format_symbols,
    _merge_search_results,
    _parse_successful_search_result,
    _read_file_command_output,
    _read_file_content_or_result,
)
from .helpers import (
    _clean_repo_name,
    _coerce_mapping,
    _params,
    _positive_int,
    _relative_path,
    _repo_name,
)
from .transport import DEFAULT_READ_FILE_URL, DEFAULT_SEARCH_URL, _debug, _post_signed_json
from .tools import (
    _register_code_history_tool,
    _register_code_read_tool,
    _register_code_search_tool,
    handle_code_history,
    handle_code_read_file,
    handle_code_search,
)


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
    _register_code_history_tool(ctx, "code_history")
    _register_code_history_tool(ctx, "sourcevault_history")

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
        ("code-history", "code_history"),
        _handle_code_history_command,
        "Search an indexed repo's git commit history.",
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
