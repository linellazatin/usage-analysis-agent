# Repository Guidelines

## Project Structure & Module Organization

- `usage_analysis_agent.py` contains the CLI, extractors, pricing logic, aggregation, reports, and JSON output.
- `README.md` is the user-facing usage and data-source reference.
- `usage-all-all.json.sample` shows the shape of generated report data.
- `.gitignore` excludes local usage exports, Pi data, and Python cache files.
- There are no separate source, test, or asset directories. Keep small changes close to the existing module unless a new boundary is justified.

The program reads local Claude Code, OpenCode, Pi, and Codex history. Treat those paths and generated reports as potentially sensitive.

## Build, Test, and Development Commands

This project uses only the Python 3 standard library; there is no install step.

```bash
python3 usage_analysis_agent.py --help        # inspect CLI options
python3 usage_analysis_agent.py               # analyze detected agents
python3 usage_analysis_agent.py --days 30     # limit the analysis period
python3 usage_analysis_agent.py --output report.json
python3 -m py_compile usage_analysis_agent.py # syntax check
```

Run commands from the repository root. AWS CLI access is optional and only refreshes the local Bedrock pricing cache.

## Coding Style & Naming Conventions

- Follow the existing four-space Python indentation and standard-library-only approach.
- Use `snake_case` for functions, variables, and CLI destinations; `PascalCase` for classes; uppercase names for constants.
- Prefer direct helpers and preserve the existing dataclasses and type hints.
- Keep report field names stable because JSON output is consumed by downstream analysis.
- No formatter or linter is configured, so keep changes readable and run the syntax check before submitting.

## Testing Guidelines

There is no automated test suite or coverage requirement. Run `python3 -m py_compile usage_analysis_agent.py` and exercise the affected CLI path with representative local data or a saved sample. Do not commit real usage exports or pricing caches.

## Commit & Pull Request Guidelines

The repository has no commit history yet, so no established message convention exists. Use short, imperative subjects such as `Add Codex usage extractor` or `Fix period filtering`.

Pull requests should explain the behavior changed, list validation commands and results, note report-schema or data-source changes, and avoid personal usage data. Include sample output or screenshots only for report-format changes.

## Security & Configuration Tips

Keep credentials, local transcripts, SQLite databases, generated JSON reports, and pricing caches outside version control. Review paths and subprocess changes carefully because the tool reads user data and may invoke the AWS CLI.
