# Usage Analysis

`usage_analysis_agent.py` is a read-only command-line report generator for token usage, estimated cost, and model activity across supported coding-agent harnesses.

It reports:

- Input, output, cache-read, and cache-write tokens
- Estimated model cost in USD
- Usage by model and analysis period
- Sessions and daily activity
- Model requests
- Model turns
- Model tool calls
- Per-agent and combined comparison totals
- JSON output for downstream analysis

Token and cost calculations are kept separate from request, turn, and tool-call metrics.

## Supported agents

| Agent | Data source | Metrics |
|---|---|---|
| Claude Code | `~/.claude/stats-cache.json` and `~/.claude/**/*.jsonl` | Tokens/cost from stats cache; requests, turns, and `tool_use` calls from transcripts |
| OpenCode | `~/.local/share/opencode/opencode.db` | Token aggregates from `session`; assistant requests/turns from `message`; tool calls from `part` records |
| Pi Coding Agent | `~/.pi/agent/sessions/**/*.jsonl` | Assistant usage records, user-to-assistant turns, and `toolResult` calls |
| Codex | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` | Deduplicated token events, task turns, and function/custom tool calls |

Agents are auto-detected when their expected local data exists.

## Requirements

### Required

- Python 3
- Local usage data for at least one supported agent
- Read access to the agent data directories listed above

### Optional

- AWS CLI, if `aws-bedrock` is enabled in `config/pricing.jsonc`
- Pi `models.json` or `models-store.json` at `~/.pi/agent/`, used as local catalogs

The script uses only Python standard-library modules. There is no `pip install` step and no `requirements.txt`.

## Installation

No installation is required. Run the script from this directory:

```bash
cd /Users/lines/services/usage_analysis
python3 usage_analysis_agent.py
```

Alternatively:

```bash
chmod +x usage_analysis_agent.py
./usage_analysis_agent.py
```

## Usage

Analyze all detected agents:

```bash
python3 usage_analysis_agent.py
```

Analyze one or more agents:

```bash
python3 usage_analysis_agent.py --agent claude-code
python3 usage_analysis_agent.py --agent pi codex
```

Select an analysis period:

```bash
python3 usage_analysis_agent.py --days 30
python3 usage_analysis_agent.py --weeks 4
python3 usage_analysis_agent.py --months 3
python3 usage_analysis_agent.py --quarters 2
python3 usage_analysis_agent.py --years 1
python3 usage_analysis_agent.py --ytd
```

Save a machine-readable report:

```bash
python3 usage_analysis_agent.py \
  --agent all \
  --days 30 \
  --output usage-report.json
```

`--agent all` cannot be combined with individual agent names.

Pricing options:

```bash
python3 usage_analysis_agent.py --refresh-pricing
```

The tool always reads `config/pricing.jsonc`; there is no pricing-file CLI override.
For development checks:

```bash
python3 -m unittest -v test_pricing.py
python3 -m py_compile usage_analysis_agent.py
```

Run `python3 usage_analysis_agent.py --help` for the complete option list.

## Report sections

For each agent, the terminal report includes:

- **Total Usage**: all-model token, cost, request, turn, and tool-call totals
- **Breakdown by Model**: token, cost, request, turn, and tool-call totals per model
- **Cost Projections per Time Period**: daily, weekly, monthly, quarterly, and yearly estimates
- **Token Volume per Time Period**: normalized token volume estimates
- **Model Activity Volume per Time Period**: normalized request, turn, and tool-call volume
- **Daily Activity**: tokens and cost by date
- **Summary Statistics**: sessions, usage entries, and unique models
- **Cache Effectiveness**: cache-read and cache-write ratios
- **Cost Analysis**: actual and per-model cost summary

When multiple agents are selected, **Comparison Summary** includes per-agent and combined totals for tokens, requests, turns, tool calls, and cost.

## Metric definitions

- **Model request**: one assistant/provider model response represented by a usage-bearing model event or assistant message.
- **Model turn**: one user-initiated agent interaction. A turn can contain multiple model requests.
- **Model tool call**: one assistant-issued tool invocation. Tool result events are not counted as additional calls.

These are intentionally separate metrics. A single user turn may produce multiple model requests and multiple tool calls.

## Pricing and cost behavior

Pricing configuration is JSONC in `config/pricing.jsonc` (comments and trailing commas are supported).
`config/pricing.jsonc.sample` documents the supported sources and overrides. Remote sources are
opt-in through `"enabled": true`. The tool always reads `config/pricing.jsonc`.

Generated caches are stored beside the script:

```text
cache/pricing-aws-bedrock.json
cache/pricing-models-dev.json
```

Caches contain normalized model prices, source configuration, schema version, and fetch time.
They are ignored by git and never contain credentials or raw authenticated responses. Fresh caches
are used offline; stale or missing caches are refreshed. If refresh fails, the last valid cache is
used and a warning is emitted. `--refresh-pricing` forces a refresh.

Temporary simulation reports, logs, and temporary pricing configurations should be removed after
use. The repository-level `cache/` files are intentionally retained because they are reusable
local caches.

Cost precedence is: recorded OpenCode/Pi cost, explicit config override, exact provider/model
catalog entries (`models.json`, `models-store.json`, or AWS cache), generic Models.dev pricing,
then unknown. Unknown prices are reported with `cost_status: "unknown"` and contribute zero to
numeric totals. Reports include `pricing_source`, `pricing_fetched_at`, and unknown-cost counts.

## JSON output

The `--output` file contains:

```json
{
  "analysis_period": {
    "start": "...",
    "end": "...",
    "label": "..."
  },
  "agents_analyzed": ["..."],
  "agent_stats": {
    "agent-name": {
      "model_requests": 0,
      "model_turns": 0,
      "model_tool_calls": 0,
      "total_input_tokens": 0,
      "total_output_tokens": 0,
      "total_cache_read_tokens": 0,
      "total_cache_write_tokens": 0,
      "total_tokens": 0,
      "total_cost": 0.0
    }
  }
}
```

Additional per-model and daily activity fields are included in the actual output.

## References and source formats

The extractor implementations and source assumptions are in:

- `usage_analysis_agent.py`: unified CLI, extractors, aggregation, reports, and JSON output
- `~/.claude/stats-cache.json`: Claude Code aggregate token and model data
- `~/.claude/**/*.jsonl`: Claude Code transcript events
- `~/.local/share/opencode/opencode.db`: OpenCode SQLite database
- `~/.pi/agent/sessions/**/*.jsonl`: Pi session events
- `~/.codex/sessions/**/*.jsonl`: Codex rollout events
- `~/.pi/agent/models.json` and `~/.pi/agent/models-store.json`: optional local model pricing metadata
- `cache/pricing-*.json`: generated local pricing caches

The tool does not call agent APIs or upload usage data. It reads local files and SQLite records only, apart from the optional AWS CLI pricing refresh.

## Limitations

- Counts depend on the event formats emitted by each harness.
- Historical request/turn/tool-call counts are unavailable when the underlying transcript or event data has been deleted.
- Cost is unknown when pricing is unavailable or a model is not recognized; no silent fallback estimate is applied.
- OpenCode token totals are sourced from session-level aggregates, while activity counts are sourced from message and part events.
- The tool does not modify agent history or usage databases.
