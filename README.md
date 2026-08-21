# Usage Analysis

Read-only Python3 CLI for token, cost, session, request, turn, and tool-call
metrics from Claude Code, OpenCode, Pi, and Codex history.

## Run

```bash
python3 usage_analysis_agent.py                 # detected agents
python3 usage_analysis_agent.py --agent pi --weeks 1
python3 usage_analysis_agent.py --agent codex --days 30
python3 usage_analysis_agent.py --agent all --days 30 --output report.json
python3 usage_analysis_agent.py --refresh-pricing
```

`--agent all` cannot be combined with individual agents. The tool always reads
`config/pricing.jsonc`; there is no pricing-file CLI override.

Development checks:

```bash
python3 -m unittest -v test_pricing.py
python3 -m py_compile usage_analysis_agent.py
```

## Data sources

| Agent | Local data |
|---|---|
| Claude Code | `~/.claude/stats-cache.json`, `~/.claude/**/*.jsonl` |
| OpenCode | `~/.local/share/opencode/opencode.db` |
| Pi | `~/.pi/agent/sessions/**/*.jsonl` |
| Codex | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` |

## Pricing

Configure sources and overrides in `config/pricing.jsonc`.

```jsonc
{
  // Remote sources are disabled by default in the sample. Copy to pricing.jsonc
  // and enable only the sources you trust.
  "sources": {
    "aws-bedrock": {
      "enabled": false,
      "priority": 1,
      "profile": "use1-personal",
      "region": "us-east-1",
      "refreshDays": 7
    },
    "pi-models-store": {
      "enabled": false,
      "priority": 2,
      "refreshDays": 15
    },
    "models-dev": {
      "enabled": false,
      "priority": 3,
      "url": "https://models.dev/api.json",
      "refreshDays": 7
    }
  },
  "overrides": {
    // "litellm-proxy/claude-sonnet-4-6": {
    //   "input": 2.0,
    //   "output": 10.0,
    //   "cacheRead": 0.2,
    //   "cacheWrite": 2.5
    // }
  }
}
```

`pi-models-store` reads `~/.pi/agent/models-store.json`.

Caches:

```text
cache/pricing-aws-bedrock.json
cache/pricing-pi-models-store.json
cache/pricing-models-dev.json
```

Workflow:

1. Recorded Pi/OpenCode cost wins.
2. Explicit overrides win next.
3. Enabled sources are checked by `priority` (lower number wins).
4. Matching uses exact `provider/model`, model ID, then normalized model ID.
5. Missing or stale caches refresh; `--refresh-pricing` forces refresh.
6. Refresh failures fall back to the last valid cache. Unknown prices contribute
   zero and are counted.

Each terminal report ends with the resolved source and path:

```text
Model Pricing Source: aws-bedrock (cache/pricing-aws-bedrock.json)
```

## Reports

Terminal and JSON reports include:

- token totals and cache-read/write metrics
- model, daily, session, request, turn, and tool-call breakdowns
- cost projections and `cost_status`
- `pricing_source`, `pricing_fetched_at`, and unknown-cost counts

Generated reports, credentials, usage history, and pricing caches are local
data. Do not commit them. Remove temporary simulation reports, logs, and
temporary configs after use; retain repository `cache/` files for offline reuse.

## Limitations

- Historical activity is unavailable when source history was deleted.
- Cost is unknown when no recorded, configured, or cached price matches.
- OpenCode token totals come from session aggregates; activity counts come from
  messages and parts.
