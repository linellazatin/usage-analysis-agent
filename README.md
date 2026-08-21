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
- Pi `models-store.json` at `~/.pi/agent/`, when `pi-models-store` is enabled

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
cache/pricing-pi-models-store.json
cache/pricing-models-dev.json
```

Caches contain normalized model prices, source configuration, schema version, and fetch time.
They are ignored by git and never contain credentials or raw authenticated responses. Fresh caches
are used offline; stale or missing caches are refreshed. If refresh fails, the last valid cache is
used and a warning is emitted. `--refresh-pricing` forces a refresh.

Temporary simulation reports, logs, and temporary pricing configurations should be removed after
use. The repository-level `cache/` files are intentionally retained because they are reusable
local caches.

Cost precedence is: recorded OpenCode/Pi cost, explicit config override, then enabled pricing
sources ordered by their numeric `priority` (lower number wins), followed by unknown. Unknown
prices are reported with `cost_status: "unknown"` and contribute zero to numeric totals. Reports include
`pricing_source`, `pricing_fetched_at`, and unknown-cost counts.

### Configured pricing-source workflow

Enable both sources in the single runtime configuration:

```jsonc
{
  "sources": {
    "aws-bedrock": {
      "enabled": true,
      "priority": 1,
      "profile": "use1-sit",
      "region": "us-east-1",
      "refreshDays": 7
    },
    "pi-models-store": {
      "enabled": false,
      "priority": 2,
      "refreshDays": 15
    },
    "models-dev": {
      "enabled": true,
      "priority": 3,
      "url": "https://models.dev/api.json",
      "refreshDays": 7
    }
  },
  "overrides": {}
}
```

For each run, the tool:

1. Reads enabled sources and their priorities from `config/pricing.jsonc`.
2. Uses fresh source caches when available.
3. Refreshes missing or stale enabled caches. Use `--refresh-pricing` to force refreshes.
4. Fetches AWS pricing with the configured profile and region when `aws-bedrock` is enabled.
5. Reads Pi’s default `~/.pi/agent/models-store.json` when `pi-models-store` is enabled.
6. Fetches Models.dev from its configured URL when `models-dev` is enabled.
7. Resolves each model by exact `provider/model`, then model ID, then normalized model ID.
8. Uses recorded Pi/OpenCode costs before any configured pricing source.

If multiple enabled sources provide the same unresolved key, the source with the lower
`priority` wins. A failed source does not fail analysis: the last valid cache is used, or the
model remains unknown if no cache exists.

Each terminal agent report ends with the source used, for example:

```text
Model Pricing Source: aws-bedrock (cache/pricing-aws-bedrock.json)
```

Recorded costs show `recorded (recorded usage data)` instead of a cache path.

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
- `~/.pi/agent/models-store.json`: input for the configurable `pi-models-store` source
- `cache/pricing-*.json`: generated local pricing caches

The tool does not call agent APIs or upload usage data. It reads local files and SQLite records only, apart from the optional AWS CLI pricing refresh.

## Limitations

- Counts depend on the event formats emitted by each harness.
- Historical request/turn/tool-call counts are unavailable when the underlying transcript or event data has been deleted.
- Cost is unknown when pricing is unavailable or a model is not recognized; no silent fallback estimate is applied.
- OpenCode token totals are sourced from session-level aggregates, while activity counts are sourced from message and part events.
- The tool does not modify agent history or usage databases.
