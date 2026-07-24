"""Response parsing and output formatting (pure, stdlib-only)."""

import json


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


def _format_history_command_output(result):
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
        or f"Found {len(results)} matching commit(s)",
    ]

    for index, item in enumerate(results, start=1):
        short = item.get("short") or str(item.get("commit") or "")[:7] or "<unknown>"
        meta = f"#{index} {short} ({item.get('date') or '?'}) {item.get('author') or ''}".rstrip()
        if item.get("ai_authored"):
            meta += " [ai]"
        lines.append(meta)

        subject = " ".join(str(item.get("subject") or "").split())
        if subject:
            lines.append(f"  {subject}")

        preview = " ".join(str(item.get("preview") or "").split())
        if preview and preview != subject:
            if len(preview) > 180:
                preview = f"{preview[:177]}..."
            lines.append(f"  {preview}")

    return "\n".join(lines)


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
