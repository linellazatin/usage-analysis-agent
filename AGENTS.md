# Repository Guidelines

## Project Structure & Module Organization

- `usage_analysis_agent.py` contains the CLI, extractors, pricing logic, aggregation, reports, and JSON output.
- `README.md` is the user-facing usage and data-source reference.
- `config/pricing.jsonc` is the single runtime pricing configuration; `config/pricing.jsonc.sample` documents its format.
- `test_pricing.py` contains the focused standard-library regression tests for pricing behavior.
- `usage-all-all.json.sample` shows the shape of generated report data.
- `.gitignore` excludes local usage exports, pricing caches, Pi data, and Python cache files.
- There are no separate source, test, or asset directories. Keep small changes close to the existing module unless a new boundary is justified.

The program reads local Claude Code, OpenCode, Pi, and Codex history. Treat those paths and generated reports as potentially sensitive.

## Build, Test, and Development Commands

This project uses only the Python 3 standard library; there is no install step.

```bash
python3 usage_analysis_agent.py --help        # inspect CLI options
python3 usage_analysis_agent.py               # analyze detected agents
python3 usage_analysis_agent.py --days 30     # limit the analysis period
python3 usage_analysis_agent.py --output report.json
python3 usage_analysis_agent.py --refresh-pricing # force enabled source refresh
python3 -m unittest -v test_pricing.py        # focused pricing tests
python3 -m py_compile usage_analysis_agent.py # syntax check
```

Run commands from the repository root. The tool always reads `config/pricing.jsonc`; there is no
pricing-file CLI override. AWS CLI and network access are only needed when enabled sources need
refreshing. Fresh local caches allow offline analysis.

Pricing sources are configured, not hardcoded. Enabled sources are sorted by numeric `priority`
(lower number wins): recorded Pi/OpenCode costs and explicit overrides still take precedence.
`pi-models-store` reads `~/.pi/agent/models-store.json` and caches it as
`cache/pricing-pi-models-store.json`. Use `--refresh-pricing` to refresh all enabled sources; a
failed refresh must fall back to the last valid cache.

## Coding Style & Naming Conventions

- Follow the existing four-space Python indentation and standard-library-only approach.
- Use `snake_case` for functions, variables, and CLI destinations; `PascalCase` for classes; uppercase names for constants.
- Prefer direct helpers and preserve the existing dataclasses and type hints.
- Keep report field names stable because JSON output is consumed by downstream analysis.
- No formatter or linter is configured, so keep changes readable and run the syntax check before submitting.

## Testing Guidelines

Run `python3 -m unittest -v test_pricing.py`, `python3 -m py_compile usage_analysis_agent.py`,
and exercise the affected CLI path with representative local data or a saved sample. Tests use
`TemporaryDirectory()` and must clean up their own temporary files. Do not commit real usage
exports or generated pricing caches.

## Commit & Pull Request Guidelines

The repository has no commit history yet, so no established message convention exists. Use short, imperative subjects such as `Add Codex usage extractor` or `Fix period filtering`.

Pull requests should explain the behavior changed, list validation commands and results, note report-schema or data-source changes, and avoid personal usage data. Include sample output or screenshots only for report-format changes.

## Security & Configuration Tips

Keep credentials, local transcripts, SQLite databases, generated JSON reports, and pricing caches outside version control. Review paths and subprocess changes carefully because the tool reads user data and may invoke the AWS CLI.

Keep `config/pricing.jsonc` free of credentials. Remote source caches contain normalized pricing
metadata only. Remove temporary simulation reports, logs, and temporary configuration files after
use; retain repository `cache/pricing-*.json` files because they are the intended reusable local
caches.

Terminal reports must retain the final `Model Pricing Source: ...` line, including the source and
cache/catalog path used. Do not claim a remote source supplied pricing when a local catalog or
recorded usage cost actually won resolution.
