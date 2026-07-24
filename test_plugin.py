"""Tests for the plugin's pure helpers and registration surface.

Stdlib only (unittest) — no network, no Hermes, no SourceVault required.
Run directly:

    python3 integrations/hermes/plugins/sourcevault-code-tools/test_plugin.py

The loader below imports the plugin as a proper package (with
submodule_search_locations), so it works for both the current single-file
layout and a future multi-module package using relative imports.
"""

import importlib.util
import json
import pathlib
import sys
import unittest

PLUGIN_DIR = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "sourcevault_code_tools",
    PLUGIN_DIR / "__init__.py",
    submodule_search_locations=[str(PLUGIN_DIR)],
)
plugin = importlib.util.module_from_spec(_spec)
sys.modules["sourcevault_code_tools"] = plugin
_spec.loader.exec_module(plugin)


class StubCtx:
    """Captures Hermes plugin-API registrations."""

    def __init__(self):
        self.commands = {}
        self.tools = {}

    def register_command(self, name, handler=None, description=""):
        self.commands[name] = {"handler": handler, "description": description}

    def register_tool(self, name, toolset=None, schema=None, handler=None, description=""):
        self.tools[name] = {
            "toolset": toolset,
            "schema": schema,
            "handler": handler,
            "description": description,
        }


class TestRegistration(unittest.TestCase):
    def test_registers_expected_commands_and_tools(self):
        ctx = StubCtx()
        plugin.register(ctx)

        base_commands = [
            "code-help", "code-read", "code-search", "code-context",
            "code-ask", "code-history", "code-status", "code-repos", "code-sync",
        ]
        for name in base_commands:
            self.assertIn(name, ctx.commands, f"missing hyphen command {name}")
            self.assertIn(name.replace("-", "_"), ctx.commands, f"missing underscore command {name}")
            self.assertTrue(callable(ctx.commands[name]["handler"]))

        for tool in ["code_search", "sourcevault_search", "code_read_file", "code_read", "sourcevault_read"]:
            self.assertIn(tool, ctx.tools, f"missing tool {tool}")
            self.assertEqual(ctx.tools[tool]["toolset"], "sourcevault_code_tools")
            self.assertTrue(callable(ctx.tools[tool]["handler"]))
            schema = ctx.tools[tool]["schema"]
            self.assertEqual(schema["name"], tool)
            self.assertIn("repo_name", schema["parameters"]["properties"])


class TestParams(unittest.TestCase):
    def test_merges_params_and_kwargs(self):
        merged = plugin._params({"a": 1}, {"b": 2})
        self.assertEqual(merged["a"], 1)
        self.assertEqual(merged["b"], 2)

    def test_unwraps_nested_argument_containers(self):
        merged = plugin._params({"arguments": {"repo_name": "x"}}, {})
        self.assertEqual(merged["repo_name"], "x")

    def test_unwraps_json_string_containers(self):
        merged = plugin._params({"input": json.dumps({"query": "q"})}, {})
        self.assertEqual(merged["query"], "q")

    def test_coerce_mapping_rejects_non_dict_json(self):
        self.assertEqual(plugin._coerce_mapping("[1, 2]"), {})
        self.assertEqual(plugin._coerce_mapping("not json"), {})
        self.assertEqual(plugin._coerce_mapping(None), {})

    def test_coerce_mapping_copies_dicts(self):
        original = {"k": "v"}
        out = plugin._coerce_mapping(original)
        self.assertEqual(out, original)
        self.assertIsNot(out, original)


class TestScalarHelpers(unittest.TestCase):
    def test_positive_int(self):
        self.assertEqual(plugin._positive_int("5", 3), 5)
        self.assertEqual(plugin._positive_int(0, 3), 3)
        self.assertEqual(plugin._positive_int(-2, 3), 3)
        self.assertEqual(plugin._positive_int("nope", 3), 3)
        self.assertEqual(plugin._positive_int(None, 3), 3)

    def test_repo_name_prefers_explicit(self):
        self.assertEqual(plugin._repo_name({"repo_name": "alpha"}), "alpha")
        self.assertEqual(plugin._repo_name({"repo": "beta"}), "beta")

    def test_repo_name_falls_back_to_path_basename(self):
        self.assertEqual(plugin._repo_name({"path": "/home/u/.hermes/repos/gamma"}), "gamma")
        self.assertEqual(plugin._repo_name({}), "")

    def test_clean_repo_name_strips_unsafe_characters(self):
        self.assertEqual(plugin._clean_repo_name("  my-repo_1.2  "), "my-repo_1.2")
        self.assertEqual(plugin._clean_repo_name("a/../b"), "a..b")
        self.assertEqual(len(plugin._clean_repo_name("x" * 300)), 120)
        self.assertEqual(plugin._clean_repo_name(None), "")


class TestRelativePath(unittest.TestCase):
    def test_explicit_aliases_win(self):
        for alias in ["relative_path", "relativePath", "file_path", "filepath", "file", "filename"]:
            self.assertEqual(
                plugin._relative_path({alias: "src/a.js"}, "repo"),
                "src/a.js",
                f"alias {alias}",
            )

    def test_path_containing_repo_name_is_made_relative(self):
        out = plugin._relative_path({"path": "/home/u/.hermes/repos/myrepo/src/a.js"}, "myrepo")
        self.assertEqual(out, "src/a.js")

    def test_path_without_repo_name_falls_back_to_basename(self):
        out = plugin._relative_path({"path": "/somewhere/else/a.js"}, "myrepo")
        self.assertEqual(out, "a.js")

    def test_empty_when_nothing_provided(self):
        self.assertEqual(plugin._relative_path({}, "repo"), "")


class TestJsonExtraction(unittest.TestCase):
    def test_plain_object(self):
        self.assertEqual(plugin._extract_json_object('{"a": 1}'), {"a": 1})

    def test_object_embedded_in_prose(self):
        out = plugin._extract_json_object('Sure! Here you go: {"needs_more_context": false} hope that helps')
        self.assertEqual(out, {"needs_more_context": False})

    def test_garbage_and_non_dict(self):
        self.assertEqual(plugin._extract_json_object("no json here"), {})
        self.assertEqual(plugin._extract_json_object("[1,2,3]"), {})
        self.assertEqual(plugin._extract_json_object(""), {})


class TestResponseParsing(unittest.TestCase):
    def test_successful_result_parses(self):
        parsed = plugin._parse_successful_search_result(json.dumps({"ok": True, "results": []}))
        self.assertIsInstance(parsed, dict)

    def test_failure_passes_through_raw(self):
        raw = json.dumps({"ok": False, "error": "x"})
        self.assertEqual(plugin._parse_successful_search_result(raw), raw)

    def test_non_dict_json_passes_through_raw(self):
        self.assertEqual(plugin._parse_successful_search_result("[1]"), "[1]")
        self.assertEqual(plugin._parse_successful_search_result("plain"), "plain")

    def test_read_file_command_output_returns_content(self):
        raw = json.dumps({"ok": True, "content": "hello"})
        self.assertEqual(plugin._read_file_command_output(raw), "hello")

    def test_read_file_command_output_passthrough_on_error(self):
        raw = json.dumps({"ok": False, "error": "not_found"})
        self.assertEqual(plugin._read_file_command_output(raw), raw)

    def test_read_file_content_or_result_wraps_with_instruction(self):
        raw = json.dumps({"ok": True, "content": "x", "repo_name": "r", "relative_path": "a.js"})
        out = json.loads(plugin._read_file_content_or_result(raw))
        self.assertTrue(out["ok"])
        self.assertEqual(out["content"], "x")
        self.assertIn("response_instruction", out)


class TestFormatting(unittest.TestCase):
    def test_search_output_lists_results_with_truncated_preview(self):
        raw = json.dumps({
            "ok": True,
            "query": "q",
            "results": [
                {"file": "a.js", "chunk": 0, "distance": 0.1234567, "preview": "p" * 300},
            ],
        })
        out = plugin._format_search_command_output(raw)
        self.assertIn("#1 a.js chunk=0", out)
        self.assertIn("...", out)
        self.assertNotIn("p" * 200, out)

    def test_format_symbols_pairs_and_caps(self):
        item = {
            "symbolNames": ",".join(f"f{i}" for i in range(12)),
            "symbolKinds": "function,function",
        }
        out = plugin._format_symbols(item)
        pairs = out.split(",")
        self.assertEqual(len(pairs), 8)
        self.assertEqual(pairs[0], "function:f0")
        self.assertEqual(pairs[2], "symbol:f2")
        self.assertEqual(plugin._format_symbols({}), "")

    def test_context_index_lines_empty(self):
        self.assertEqual(plugin._context_index_lines({"results": []}), "No matching chunks found.")


class TestMergeSearchResults(unittest.TestCase):
    def _result(self, query, items):
        return json.dumps({"ok": True, "query": query, "results": items})

    def test_merges_and_dedupes_tagging_rounds(self):
        primary = self._result("q1", [
            {"file": "a.js", "chunk": 0, "preview": "A"},
            {"file": "b.js", "chunk": 1, "preview": "B"},
        ])
        followup = self._result("q2", [
            {"file": "a.js", "chunk": 0, "preview": "A"},  # duplicate
            {"file": "c.js", "chunk": 2, "preview": "C"},
        ])
        merged = json.loads(plugin._merge_search_results(primary, followup))
        self.assertEqual(merged["count"], 3)
        rounds = {item["file"]: item["retrievalRound"] for item in merged["results"]}
        self.assertEqual(rounds["a.js"], "initial")
        self.assertEqual(rounds["c.js"], "followup")
        self.assertEqual(merged["retrieval"]["mode"], "multi-hop")
        self.assertEqual(merged["retrieval"]["followup_query"], "q2")

    def test_failed_followup_keeps_primary(self):
        primary = self._result("q1", [{"file": "a.js", "chunk": 0, "preview": "A"}])
        failed = json.dumps({"ok": False, "error": "x"})
        self.assertEqual(plugin._merge_search_results(primary, failed), primary)




class TestAskCommandForms(unittest.TestCase):
    """Argument forms for /code-ask. _search_context is stubbed (no network)."""

    def setUp(self):
        self.commands = sys.modules["sourcevault_code_tools.commands"]
        self.calls = []
        self._real = self.commands._search_context

        def stub(repo_name, query, n_results):
            self.calls.append({"repo": repo_name, "query": query, "n": n_results})
            return json.dumps({"ok": True, "repo_name": repo_name, "query": query, "results": [
                {"file": "a.js", "chunk": 0, "content": "code", "preview": "code"},
            ]})

        self.commands._search_context = stub

    def tearDown(self):
        self.commands._search_context = self._real

    def test_question_only(self):
        out = plugin._handle_code_ask_command('myrepo "How does auth work?"')
        self.assertEqual(self.calls[0]["query"], "How does auth work?")
        self.assertEqual(self.calls[0]["n"], 5)
        self.assertIn("How does auth work?", out)

    def test_question_only_with_count(self):
        plugin._handle_code_ask_command('myrepo "How does auth work?" 8')
        self.assertEqual(self.calls[0]["query"], "How does auth work?")
        self.assertEqual(self.calls[0]["n"], "8")

    def test_query_and_question(self):
        plugin._handle_code_ask_command('myrepo "hmac signature" "Is this replay-safe?"')
        self.assertEqual(self.calls[0]["query"], "hmac signature")

    def test_query_question_and_count(self):
        plugin._handle_code_ask_command('myrepo "hmac" "Is this safe?" 9')
        self.assertEqual(self.calls[0]["query"], "hmac")
        self.assertEqual(self.calls[0]["n"], "9")

    def test_too_few_args_shows_usage(self):
        out = plugin._handle_code_ask_command("myrepo")
        self.assertIn("Usage:", out)
        self.assertEqual(self.calls, [])

    def test_numeric_question_is_not_eaten_as_count(self):
        # A lone trailing number with nothing else is the question, not n.
        plugin._handle_code_ask_command('myrepo "404"')
        self.assertEqual(self.calls[0]["query"], "404")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class HistoryToolTests(unittest.TestCase):
    def test_history_tools_registered(self):
        ctx = StubCtx()
        plugin.register(ctx)
        for name in ("code_history", "sourcevault_history"):
            self.assertIn(name, ctx.tools, f"missing history tool {name}")
            schema = ctx.tools[name]["schema"]
            self.assertEqual(schema["parameters"]["required"], ["repo_name", "question"])

    def test_handle_code_history_posts_expected_body(self):
        captured = {}

        def fake_post(url, body):
            captured["url"] = url
            captured["body"] = body
            return json.dumps({"success": True, "ok": True, "results": []})

        original = plugin.tools._post_signed_json
        plugin.tools._post_signed_json = fake_post
        try:
            plugin.handle_code_history(
                {"repo_name": "myrepo", "question": "when did auth change", "n_results": "3"}
            )
        finally:
            plugin.tools._post_signed_json = original

        self.assertTrue(captured["url"].endswith("/api/history-search"))
        self.assertEqual(
            captured["body"],
            {"repo_name": "myrepo", "question": "when did auth change", "n_results": 3},
        )

    def test_handle_code_history_accepts_query_alias(self):
        captured = {}

        def fake_post(url, body):
            captured["body"] = body
            return json.dumps({"success": True, "ok": True, "results": []})

        original = plugin.tools._post_signed_json
        plugin.tools._post_signed_json = fake_post
        try:
            plugin.handle_code_history({"repo_name": "myrepo", "query": "why refactor"})
        finally:
            plugin.tools._post_signed_json = original

        self.assertEqual(captured["body"]["question"], "why refactor")

    def test_handle_code_history_translates_missing_route(self):
        original = plugin.tools._post_signed_json
        plugin.tools._post_signed_json = lambda url, body: "<html>Cannot POST /api/history-search</html>"
        try:
            result = json.loads(plugin.handle_code_history({"repo_name": "r", "question": "q"}))
        finally:
            plugin.tools._post_signed_json = original

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "history_search_unsupported")
        self.assertIn("v1.8", result["detail"])

    def test_format_history_command_output(self):
        payload = json.dumps({
            "success": True,
            "ok": True,
            "summary": "Found 2 matching commits",
            "results": [
                {
                    "short": "abc1234",
                    "date": "2026-01-02",
                    "author": "Dev One",
                    "subject": "fix: tighten header parsing",
                    "preview": "commit abc1234 (2026-01-02) by Dev One fix: tighten header parsing",
                    "ai_authored": True,
                },
                {
                    "commit": "def5678901234",
                    "date": "2026-01-01",
                    "author": "Dev Two",
                    "subject": "refactor router",
                    "preview": "",
                },
            ],
        })
        text = plugin.formatting._format_history_command_output(payload)
        self.assertIn("Found 2 matching commits", text)
        self.assertIn("#1 abc1234 (2026-01-02) Dev One [ai]", text)
        self.assertIn("  fix: tighten header parsing", text)
        self.assertIn("#2 def5678 (2026-01-01) Dev Two", text)
        self.assertNotIn("def5678 (2026-01-01) Dev Two [ai]", text)

    def test_history_command_usage_and_wiring(self):
        usage = plugin.commands._handle_code_history_command("")
        self.assertIn("Usage: /code-history", usage)

        captured = {}

        def fake_post(url, body):
            captured["body"] = body
            return json.dumps({
                "success": True, "ok": True, "summary": "Found 1 matching commit",
                "results": [{"short": "aaa1111", "date": "2026-02-03", "author": "A", "subject": "s"}],
            })

        original = plugin.tools._post_signed_json
        plugin.tools._post_signed_json = fake_post
        try:
            out = plugin.commands._handle_code_history_command('myrepo "when did tests move" 2')
        finally:
            plugin.tools._post_signed_json = original

        self.assertEqual(captured["body"]["n_results"], 2)
        self.assertIn("Found 1 matching commit", out)
        self.assertIn("#1 aaa1111", out)
