<img src="logo.png" alt="SourceVault" width="84" />

# sourcevault-code-tools

![tests](https://github.com/sourcevault-ai/sourcevault-code-tools/actions/workflows/test.yml/badge.svg)

A [Hermes Agent](https://github.com/nousresearch/hermes-agent) plugin that
gives Hermes **persistent, private memory of your codebases** — semantic code
search, exact file reads, and grounded repo Q&A with file-and-line citations.
Everything runs on your machine over localhost; no source code leaves it.

Works in Hermes CLI, Telegram, and Hermes Desktop.

![Hermes /code-ask answering a question about a private repo with file-and-line citations](demo.gif)

```text
/code_ask my-api "Where do we validate JWTs, and what happens on expiry?"
→ grounded answer citing the exact files and line ranges
```

## What it adds

**Slash commands** (deterministic — work reliably with any local model):

| Command | What it does |
|---|---|
| `/code-help` | Command reference |
| `/code-status` | Integration health check |
| `/code-repos` | List indexed repos |
| `/code-sync <repo>` | Fast-forward the repo mirror |
| `/code-read <repo> <path>` | Read an exact file |
| `/code-search <repo> "query"` | Hybrid semantic + literal search |
| `/code-context <repo> "query"` | Retrieve a compact context pack |
| `/code-ask <repo> "question"` | Retrieve + answer with citations (add an optional `"query"` before the question to steer retrieval) |
| `/code-history <repo> "question"` | Search indexed git commit history (SourceVault v1.8+; index every commit via the dashboard's Full git history setting) |

Telegram uses underscore forms (`/code_ask`, …).

> **Repo names are case-sensitive.** `repo_name` is the literal directory name
> under `REPO_ROOT` (Linux filesystem semantics): if the folder is `My-Repo`,
> then `/code-read my-repo …` fails and `/code-read My-Repo …` works. Run
> `/code-repos` to see the exact names.

**LLM-callable tools** (for models that handle structured tool use):
`code_search`, `code_read_file`, and `code_history`, plus `sourcevault_search` /
`sourcevault_read` / `sourcevault_history` aliases for Hermes Tool Search
discoverability.

## Requires a SourceVault backend

This plugin is the Hermes-side client. Indexing, embeddings (Ollama +
nomic-embed-text), the vector store (ChromaDB), and the signed API are
provided by **SourceVault**, a local-first private code-memory server — the
plugin is useless without it. The server's retrieval engine does the heavy
lifting behind every answer: hybrid search with cross-encoder reranking,
symbol-graph context, git-history answers ("why was this changed?"), and
benchmark-verified grounding (see [sourcevault.ai/benchmark](https://sourcevault.ai/benchmark/)).

Get SourceVault (one-command private install, free 7-day trial, no
per-seat fees): **<https://sourcevault.ai>**

## Install

Clone (or download) this plugin, then copy the plugin folder into
`~/.hermes/plugins/` — note the source path is the plugin directory, wherever
you cloned it, not `.`:

```bash
git clone https://github.com/sourcevault-ai/sourcevault-code-tools /tmp/sourcevault-code-tools
mkdir -p ~/.hermes/plugins
cp -R /tmp/sourcevault-code-tools ~/.hermes/plugins/sourcevault-code-tools
```

If you have the SourceVault server repo, use its installer instead — it also
configures Hermes and validates the env:

```bash
cd ~/Development/sourcevault
./scripts/install-hermes-integration.sh --configure-sourcevault --restart-hermes
```

Enable in `~/.hermes/config.yaml`:

```yaml
plugins:
  enabled:
    - sourcevault-code-tools

platform_toolsets:
  cli:
    - sourcevault_code_tools
  telegram:
    - sourcevault_code_tools
```

Point the gateway at your SourceVault instance
(`~/.config/systemd/user/hermes-gateway.env` or equivalent):

```env
CODE_SEARCH_URL=http://127.0.0.1:9000/api/search-codebase
CODE_READ_FILE_URL=http://127.0.0.1:9000/api/read-file
CODE_HISTORY_URL=http://127.0.0.1:9000/api/history-search
CODE_SEARCH_HMAC_SECRET=<same value as the SourceVault server>
```

Restart Hermes (`systemctl --user restart hermes-gateway` or relaunch the
Desktop app) and run `/code-status`.

## Try it

Replace `hello-world` below with one of your indexed repo names — copied
exactly as `/code-repos` prints it (case-sensitive).

```text
# 1. Health and inventory
/code-status
/code-repos

# 2. Read an exact file (path is repo-relative)
/code-read hello-world README.md
/code-read hello-world src/index.js 20000

# 3. Search — semantic or literal, your choice of phrasing
/code-search hello-world "where errors get logged" 5
/code-search hello-world "config.js" 3

# 4. Context pack — retrieve snippets, then ask follow-ups in plain chat
/code-context hello-world "startup and initialization flow" 6

# 5. Grounded Q&A — your question retrieves on its own; add a query first to steer
/code-ask hello-world "How are user inputs validated, and where could that fail?"
/code-ask hello-world "database connection setup" "Walk me through how a connection is opened, reused, and closed." 8
```

Usage notes:

- Quote any multi-word argument; arguments are shell-split, so an unbalanced
  quote returns a usage error.
- The optional trailing number is `n_results` (default 5). Raise it to 8–10
  for architecture-wide questions; keep it low for pinpoint lookups.
- `/code-ask` answers only from retrieved chunks and says what's missing
  rather than guessing. If it reports missing context, retry with a broader
  search query or higher `n_results`.
- After `/code-sync`, reindex from the SourceVault side before searching
  again, or results will cite stale code.

## Configuration reference

| Env var | Default | Purpose |
|---|---|---|
| `CODE_SEARCH_URL` | `http://127.0.0.1:9000/api/search-codebase` | SourceVault search endpoint |
| `CODE_READ_FILE_URL` | `http://127.0.0.1:9000/api/read-file` | SourceVault file-read endpoint |
| `CODE_HISTORY_URL` | `http://127.0.0.1:9000/api/history-search` | SourceVault history-search endpoint (v1.8+) |
| `CODE_SEARCH_HMAC_SECRET` | — | Request-signing secret (required) |
| `REPO_ROOT` | `~/.hermes/repos` | Local repo mirrors for `/code-repos`, `/code-sync` |
| `SOURCEVAULT_CODE_TOOLS_DEBUG` | off | Log argument shapes (no secrets) |

## Security notes

- All requests are HMAC-signed and travel over localhost only.
- The plugin never executes retrieved code; `/code-sync` runs only
  `git pull --ff-only` inside the configured repo root.
- Repo paths are confined to `REPO_ROOT`; traversal attempts are rejected.
- No telemetry, no external network calls.

## License

MIT — see [LICENSE](LICENSE). The SourceVault server is a separate,
commercially licensed product.
