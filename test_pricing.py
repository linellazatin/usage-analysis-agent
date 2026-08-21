import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import usage_analysis_agent as app


class PricingTests(unittest.TestCase):
    def test_cli_has_no_pricing_file_override(self):
        with patch("sys.argv", ["usage_analysis_agent.py", "--pricing-file", "x"]):
            with self.assertRaises(SystemExit):
                app.parse_args()

    def test_jsonc_and_override_precedence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "pricing.jsonc"
            config.write_text("""
            {
              // comment
              "sources": {},
              "overrides": {
                "litellm-proxy/sonnet": {"input": 2, "output": 10,},
              },
            }
            """)
            resolver = app.PricingResolver(config, root / "cache")
            result = resolver.resolve("litellm-proxy", "sonnet")
            self.assertEqual(result["status"], "configured")
            self.assertEqual(result["pricing"]["output"], 10)

    def test_provider_match_and_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "pricing.jsonc"
            config.write_text(json.dumps({"sources": {}, "overrides": {}}))
            resolver = app.PricingResolver(config, root / "cache")
            resolver._add("provider", "model", {"input": 1, "output": 2}, "local")
            self.assertEqual(resolver.resolve("provider", "model")["status"], "cached")
            self.assertEqual(resolver.resolve("other", "missing")["status"], "unknown")

    def test_source_priority_selects_lower_number(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = app.PricingResolver(Path(temp) / "pricing.jsonc", Path(temp) / "cache")
            resolver._add("provider", "model", {"input": 9, "output": 9}, "later", priority=3)
            resolver._add("provider", "model", {"input": 1, "output": 1}, "earlier", priority=1)
            self.assertEqual(resolver.resolve("provider", "model")["source"], "earlier")

    def test_pi_models_store_is_configured_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pi_dir = root / ".pi" / "agent"
            pi_dir.mkdir(parents=True)
            (pi_dir / "models-store.json").write_text(json.dumps({
                "provider": {"models": [{
                    "id": "model",
                    "cost": {"input": 1, "output": 2},
                }]}
            }))
            config = root / "pricing.jsonc"
            config.write_text(json.dumps({"sources": {
                "pi-models-store": {
                    "enabled": True, "priority": 2, "refreshDays": 15
                }
            }}))
            with patch.object(app.Path, "home", return_value=root):
                resolver = app.PricingResolver(config, root / "cache")
            result = resolver.resolve("provider", "model")
            self.assertEqual(result["source"], "pi-models-store")
            self.assertEqual(result["pricing"]["output"], 2)
            self.assertTrue((root / "cache" / "pricing-pi-models-store.json").exists())

    @patch("usage_analysis_agent.subprocess.run")
    def test_aws_command_uses_configured_profile_and_region(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = json.dumps({"PriceList": []})
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "pricing.jsonc"
            config.write_text(json.dumps({"sources": {
                "aws-bedrock": {"enabled": True, "profile": "p", "region": "r"}
            }}))
            app.PricingResolver(config, root / "cache")
        command = run.call_args.args[0]
        self.assertEqual(command[:4], ["aws", "pricing", "get-products", "--profile"])
        self.assertIn("p", command)
        self.assertIn("r", command)

    def test_stale_cache_fallback_and_force_refresh(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cache = root / "cache"
            cache.mkdir()
            cached = {
                "schema_version": 1, "source": "models-dev",
                "fetched_at": "2000-01-01T00:00:00",
                "models": {"provider/model": {"input": 1, "output": 2}},
            }
            (cache / "pricing-models-dev.json").write_text(json.dumps(cached))
            config = root / "pricing.jsonc"
            config.write_text(json.dumps({"sources": {
                "models-dev": {"enabled": True, "url": "http://invalid", "refreshDays": 1}
            }}))
            with patch.object(app.PricingResolver, "_fetch", side_effect=OSError("offline")):
                resolver = app.PricingResolver(config, cache)
            self.assertEqual(resolver.resolve("provider", "model")["status"], "cached")
            self.assertTrue(resolver.warnings)

            fresh = dict(cached)
            fresh["fetched_at"] = app.datetime.now().isoformat()
            (cache / "pricing-models-dev.json").write_text(json.dumps(fresh))
            with patch.object(app.PricingResolver, "_fetch", return_value={
                "provider/model": {"input": 3, "output": 4}
            }) as fetch:
                app.PricingResolver(config, cache, force_refresh=True)
            fetch.assert_called_once()

    def test_recorded_cost_precedence(self):
        with tempfile.TemporaryDirectory() as temp:
            usage = app.UsageEntry(
                agent="pi", model_id="model", timestamp="2026-08-21T00:00:00",
                input_tokens=10, output_tokens=10, cache_read_tokens=0,
                cache_write_tokens=0, total_tokens=20, cost=7.5,
                cost_breakdown={"total": 7.5}, provider="provider",
                cost_status="recorded",
            )
            resolver = app.PricingResolver(Path(temp) / "missing.jsonc", Path(temp) / "cache")
            resolver._add("provider", "model", {"input": 1, "output": 1}, "local")
            app.apply_pricing([usage], resolver)
            self.assertEqual(usage.cost, 7.5)
            self.assertEqual(usage.cost_status, "recorded")


if __name__ == "__main__":
    unittest.main()
