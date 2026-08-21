#!/usr/bin/env python3
"""Unified usage analysis for AI coding agents: Claude Code, OpenCode, Pi Agent."""

import json
import argparse
import sqlite3
import os
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass, asdict
import sys

# ============================================================================
# COLOR SUPPORT (ANSI codes for terminal, disables for file output)
# ============================================================================

class Colors:
    """ANSI color codes for terminal output."""
    # Agent-specific colors
    claude_code = "\033[38;5;208m"  # Orange
    opencode = "\033[38;5;45m"      # Cyan
    pi = "\033[38;5;129m"          # Red/Pink
    codex = "\033[38;5;228m"       # Yellow
    reset = "\033[0m"
    
    @classmethod
    def disable(cls):
        """Disable colors (for file output or non-terminal)."""
        for attr in dir(cls):
            if not attr.startswith('_') and attr != 'disable':
                setattr(cls, attr, "")


def should_colorize() -> bool:
    """Check if we should use colors (not outputting to file, terminal supports it)."""
    return sys.stdout.isatty()


# ============================================================================
# MODEL PRICING (loaded from ~/.cache/amazon-bedrock-pricing.json - SINGLE SOURCE OF TRUTH)
# ============================================================================

class PricingLoader:
    """Load model pricing from AWS Pricing API cache as single source of truth."""
    
    _pricing_cache: Dict[str, Dict[str, float]] = None
    _loaded = False
    _cache_dir = Path.home() / ".cache"
    _aws_pricing_cache_file = _cache_dir / "amazon-bedrock-pricing.json"
    _cache_max_age_days = 7
    
    @classmethod
    def _should_refresh_aws_cache(cls) -> bool:
        """Check if AWS pricing cache needs refresh."""
        if not cls._aws_pricing_cache_file.exists():
            return True
        
        try:
            with open(cls._aws_pricing_cache_file) as f:
                cache_data = json.load(f)
            
            cached_date_str = cache_data.get('lastUpdated', '')
            if not cached_date_str:
                return True
            
            cached_date = datetime.fromisoformat(cached_date_str)
            age = datetime.now() - cached_date
            return age >= timedelta(days=cls._cache_max_age_days)
        except (json.JSONDecodeError, ValueError, KeyError):
            return True
    
    @classmethod
    def _fetch_aws_pricing(cls) -> Dict[str, Dict]:
        """Fetch pricing from AWS Pricing API and supplement with models-store.json data."""
        # Check cache first
        if not cls._should_refresh_aws_cache():
            try:
                with open(cls._aws_pricing_cache_file) as f:
                    cache_data = json.load(f)
                return cache_data.get('models', {})
            except (json.JSONDecodeError, KeyError):
                pass
        
        # Need to fetch from AWS
        import subprocess
        aws_models = {}
        
        try:
            # Fetch from AWS Pricing API
            result = subprocess.run(
                ['aws', 'pricing', 'get-products', 
                 '--profile', 'use1-sit',
                 '--region', 'us-east-1',
                 '--service-code', 'AmazonBedrock'],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0:
                pricing_data = json.loads(result.stdout)
                aws_models = cls._parse_aws_pricing(pricing_data)
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            pass
        except Exception as e:
            print(f"Warning: Could not fetch AWS pricing: {e}")
        
        # Merge with models-store.json data (fill gaps for newer models)
        model_store_models = {}
        model_store_path = Path.home() / ".pi" / "agent" / "models-store.json"
        if model_store_path.exists():
            try:
                with open(model_store_path) as f:
                    data = json.load(f)
                
                bedrock_models = data.get('amazon-bedrock', {}).get('models', [])
                
                for model in bedrock_models:
                    model_id = model.get('id', '')
                    cost = model.get('cost', {})
                    
                    if model_id and cost:
                        # Only add if not already from AWS Pricing API
                        if model_id not in aws_models:
                            model_store_models[model_id] = {
                                'input': cost.get('input', 0),
                                'output': cost.get('output', 0),
                                'cacheRead': cost.get('cacheRead', 0),
                                'cacheWrite': cost.get('cacheWrite', 0)
                            }
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Error loading models-store.json: {e}")
        
        # Combine AWS and models-store data
        combined_models = {**aws_models, **model_store_models}
        
        # Create normalized versions
        normalized_models = {}
        for model_name, pricing in combined_models.items():
            # Normalize model name to match our IDs
            normalized = model_name.lower().replace(' ', '-').replace('.', '-')
            if normalized not in combined_models:  # Avoid overwriting existing
                normalized_models[normalized] = pricing
                
            # Create prefix-stripped versions
            for prefix in ['global.', 'openai.', 'anthropic.', 'au.anthropic.', 'eu.anthropic.', 'us.anthropic.', 'jp.anthropic.', 'moonshotai.', 'minimax.', 'mistral.', 'meta.', 'google.', 'nvidia.', 'deepseek.']:
                if model_name.startswith(prefix):
                    short_id = model_name[len(prefix):]
                    if short_id not in combined_models:
                        normalized_models[short_id] = pricing
        
        # Merge everything
        all_models = {**combined_models, **normalized_models}
        
        # Save to cache - THIS IS NOW THE SINGLE SOURCE OF TRUTH
        cls._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_data = {
            'lastUpdated': datetime.now().isoformat(),
            'source': 'combined-aws-and-models-store',
            'models': all_models
        }
        with open(cls._aws_pricing_cache_file, 'w') as f:
            json.dump(cache_data, f, indent=2)
        
        return all_models
    
    @classmethod
    def _parse_aws_pricing(cls, pricing_data: Dict) -> Dict[str, Dict]:
        """Parse AWS Pricing API response into model pricing dict."""
        models = {}
        
        for item_str in pricing_data.get('PriceList', []):
            try:
                item = json.loads(item_str)
                attrs = item.get('product', {}).get('attributes', {})
                
                region = attrs.get('regionCode', '')
                model = attrs.get('model', '')
                inference_type = attrs.get('inferenceType', '')
                
                if not model or region != 'us-east-1':
                    continue
                
                # Get price
                terms = item.get('terms', {}).get('OnDemand', {})
                for term_data in terms.values():
                    for pd_data in term_data.get('priceDimensions', {}).values():
                        price_str = pd_data.get('pricePerUnit', {}).get('USD', '0')
                        price_per_1k = float(price_str)
                        price_per_million = price_per_1k * 1000
                        
                        # Determine token type
                        if 'Input' in inference_type and 'Cache' not in inference_type and 'priority' not in inference_type.lower():
                            token_type = 'input'
                        elif 'Output' in inference_type:
                            token_type = 'output'
                        elif 'Cache read' in inference_type or 'cacheRead' in inference_type.lower():
                            token_type = 'cacheRead'
                        elif 'Cache write' in inference_type or 'Cache creation' in inference_type:
                            token_type = 'cacheWrite'
                        else:
                            continue
                        
                        if model not in models:
                            models[model] = {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0}
                        models[model][token_type] = price_per_million
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
        
        return models
    
    @classmethod
    def _load_pricing(cls) -> Dict[str, Dict[str, float]]:
        """Load pricing data - USE AWS Pricing API cache AS SINGLE SOURCE OF TRUTH."""
        if cls._loaded:
            return cls._pricing_cache or {}
        
        cls._loaded = True
        cls._pricing_cache = {}
        
        # ONLY source: AWS Pricing API cache (~/.cache/amazon-bedrock-pricing.json)
        # This cache includes BOTH AWS Pricing API data AND models-store.json data
        aws_models = cls._fetch_aws_pricing()
        
        # Use the cache as THE SINGLE SOURCE OF TRUTH
        for model_name, pricing in aws_models.items():
            cls._pricing_cache[model_name] = pricing
        
        # Add local model (no cost) - always present
        cls._pricing_cache['local.gemma4-12b'] = {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0}
        
        return cls._pricing_cache
    
    @classmethod
    def get_pricing(cls, model_id: str) -> Optional[Dict[str, float]]:
        """Get pricing for a specific model from AWS Pricing API cache."""
        pricing = cls._load_pricing()
        
        # Try exact match
        if model_id in pricing:
            return pricing[model_id]
        
        # Try stripping prefixes (common provider prefixes)
        for prefix in ['global.', 'openai.', 'anthropic.', 'au.anthropic.', 'eu.anthropic.', 'us.anthropic.', 'jp.anthropic.', 'moonshotai.', 'zai.', 'minimax.', 'mistral.', 'meta.', 'google.', 'nvidia.', 'deepseek.']:
            if model_id.startswith(prefix):
                short_id = model_id[len(prefix):]
                if short_id in pricing:
                    return pricing[short_id]
        
        return None


def calculate_cost(input_tokens: int, output_tokens: int, cache_read_tokens: int, 
                   cache_write_tokens: int, model_id: str) -> float:
    """Calculate cost in USD based on token counts and model pricing from AWS Pricing API cache."""
    pricing = PricingLoader.get_pricing(model_id)
    
    # Default pricing if model not found (conservative Claude-like estimate)
    if not pricing:
        pricing = {'input': 3, 'output': 15, 'cacheRead': 0.3, 'cacheWrite': 3.75}
    
    # Calculate cost (prices are per million tokens)
    cost = (
        (input_tokens / 1_000_000) * pricing['input'] +
        (output_tokens / 1_000_000) * pricing['output'] +
        (cache_read_tokens / 1_000_000) * pricing.get('cacheRead', 0) +
        (cache_write_tokens / 1_000_000) * pricing.get('cacheWrite', 0)
    )
    
    return cost


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class UsageEntry:
    """Token usage plus optional request, turn, and tool metrics."""
    agent: str
    model_id: str
    timestamp: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    total_tokens: int
    cost: float
    cost_breakdown: Dict[str, float]
    is_aggregated: bool = False
    session_id: Optional[str] = None
    model_requests: int = 0
    model_turns: int = 0
    model_tool_calls: int = 0
    is_metric_only: bool = False


@dataclass
class UsageMetrics:
    """Counts are separate because one turn may contain many requests/tools."""
    model_requests: int = 0
    model_turns: int = 0
    model_tool_calls: int = 0


@dataclass
class AgentStats:
    """Aggregated statistics for an agent."""
    agent: str
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_write_tokens: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    daily_cost: float = 0.0
    weekly_cost: float = 0.0
    monthly_cost: float = 0.0
    quarterly_cost: float = 0.0
    yearly_cost: float = 0.0
    unique_models: Set[str] = None
    usage_entries: int = 0
    sessions_count: int = 0
    model_breakdown: Dict[str, Dict] = None  # Per-model token/cost breakdown
    daily_activity: Dict[str, Dict] = None  # Per-day token/cost activity
    total_model_requests: int = 0
    total_model_turns: int = 0
    total_model_tool_calls: int = 0
    
    def __post_init__(self):
        if self.unique_models is None:
            self.unique_models = set()
        if self.model_breakdown is None:
            self.model_breakdown = {}
        if self.daily_activity is None:
            self.daily_activity = {}


# ============================================================================
# AGENT DATA LOCATIONS
# ============================================================================

class AgentPaths:
    """Configuration for agent data locations."""
    
    @staticmethod
    def claude_code() -> Optional[Path]:
        path = Path.home() / ".claude" / "stats-cache.json"
        return path if path.exists() else None
    
    @staticmethod
    def claude_transcripts() -> List[Path]:
        return list((Path.home() / ".claude").glob("**/*.jsonl"))
    
    @staticmethod
    def opencode() -> Optional[Path]:
        path = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
        return path if path.exists() else None
    
    @staticmethod
    def pi_agent() -> Optional[Path]:
        path = Path.home() / ".pi" / "agent" / "sessions"
        return path if path.exists() and any(path.iterdir()) else None
    
    @staticmethod
    def codex() -> Optional[Path]:
        path = Path.home() / ".codex" / "sessions"
        return path if path.exists() and any(path.glob("*/*/*/rollout-*.jsonl")) else None
    
    @staticmethod
    def detect_agents() -> List[str]:
        """Return list of installed agents based on data files."""
        agents = []
        if AgentPaths.claude_code():
            agents.append('claude-code')
        if AgentPaths.opencode():
            agents.append('opencode')
        if AgentPaths.pi_agent():
            agents.append('pi')
        if AgentPaths.codex():
            agents.append('codex')
        return agents


# ============================================================================
# AGENT-SPECIFIC DATA EXTRACTORS
# ============================================================================

class ClaudeCodeExtractor:
    """Extract usage data from Claude Code stats-cache.json."""
    
    @staticmethod
    def extract_usage() -> List[UsageEntry]:
        """Extract usage data from Claude Code JSON cache."""
        cache_path = AgentPaths.claude_code()
        if not cache_path:
            return []
        
        try:
            with open(cache_path, 'r') as f:
                stats = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error reading Claude Code data: {e}")
            return []
        
        usages = []
        transcript_metrics = ClaudeCodeExtractor.extract_transcript_metrics()
        
        # Extract data from modelUsage
        if 'modelUsage' in stats:
            for model_id, usage_data in stats['modelUsage'].items():
                input_tok = usage_data.get('inputTokens', 0)
                output_tok = usage_data.get('outputTokens', 0)
                cache_read_tok = usage_data.get('cacheReadInputTokens', 0)
                cache_write_tok = usage_data.get('cacheCreationInputTokens', 0)
                total_tok = input_tok + output_tok + cache_read_tok + cache_write_tok
                
                # Calculate cost using Bedrock pricing (Claude Code costUSD is always 0)
                cost = calculate_cost(
                    input_tok, output_tok,
                    cache_read_tok, cache_write_tok,
                    model_id
                )
                
                usages.append(UsageEntry(
                    agent='claude-code',
                    model_id=model_id,
                    timestamp=str(stats.get('lastComputedDate', '')),
                    input_tokens=input_tok,
                    output_tokens=output_tok,
                    cache_read_tokens=cache_read_tok,
                    cache_write_tokens=cache_write_tok,
                    total_tokens=total_tok,
                    cost=cost,
                    cost_breakdown={'total': cost},
                    is_aggregated=True,
                    model_requests=transcript_metrics.get(model_id, UsageMetrics()).model_requests,
                    model_turns=transcript_metrics.get(model_id, UsageMetrics()).model_turns,
                    model_tool_calls=transcript_metrics.get(model_id, UsageMetrics()).model_tool_calls
                ))
        
        return usages

    @staticmethod
    def extract_transcript_metrics() -> Dict[str, UsageMetrics]:
        metrics = defaultdict(UsageMetrics)
        for path in AgentPaths.claude_transcripts():
            try:
                events = []
                for line in path.open(errors='replace'):
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
                by_id = {event.get('uuid'): event for event in events}
                for event in events:
                    if event.get('type') != 'assistant':
                        continue
                    message = event.get('message', {})
                    model = message.get('model')
                    if not model or not message.get('usage'):
                        continue
                    item = metrics[model]
                    item.model_requests += 1
                    if by_id.get(event.get('parentUuid'), {}).get('type') == 'user':
                        item.model_turns += 1
                    content = message.get('content', [])
                    if isinstance(content, list):
                        item.model_tool_calls += sum(
                            1 for block in content
                            if isinstance(block, dict) and block.get('type') == 'tool_use'
                        )
            except OSError:
                continue
        return dict(metrics)


class OpenCodeExtractor:
    """Extract usage and event metrics from OpenCode SQLite storage."""

    @staticmethod
    def extract_usage() -> List[UsageEntry]:
        db_path = AgentPaths.opencode()
        if not db_path:
            return []
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            usages = []
            for session_id, timestamp_ms, model_json, input_tokens, output_tokens, cache_read, cache_write, cost in cursor.execute("""
                SELECT id, time_created, model, tokens_input, tokens_output,
                       tokens_cache_read, tokens_cache_write, cost
                FROM session
                WHERE tokens_input > 0 OR tokens_output > 0 OR tokens_cache_read > 0 OR tokens_cache_write > 0 OR cost > 0
                ORDER BY time_created
            """):
                try:
                    model_data = json.loads(model_json or '{}')
                    model_id = model_data.get('id', 'unknown').split('.')[-1]
                except json.JSONDecodeError:
                    model_id = str(model_json or 'unknown')
                total_tokens = sum((input_tokens or 0, output_tokens or 0, cache_read or 0, cache_write or 0))
                usages.append(UsageEntry(
                    agent='opencode', model_id=model_id, timestamp=str(timestamp_ms),
                    input_tokens=input_tokens or 0, output_tokens=output_tokens or 0,
                    cache_read_tokens=cache_read or 0, cache_write_tokens=cache_write or 0,
                    total_tokens=total_tokens, cost=cost or 0.0,
                    cost_breakdown={'total': cost or 0.0}, session_id=session_id
                ))

            messages = cursor.execute("""
                SELECT id, session_id, time_created, data FROM message
            """).fetchall()
            message_roles = {}
            for message_id, session_id, timestamp_ms, message_json in messages:
                try:
                    message = json.loads(message_json or '{}')
                except json.JSONDecodeError:
                    continue
                message_roles[message_id] = message.get('role')
                if message.get('role') != 'assistant':
                    continue
                usages.append(UsageEntry(
                    agent='opencode', model_id=message.get('modelID', 'unknown'), timestamp=str(timestamp_ms),
                    input_tokens=0, output_tokens=0, cache_read_tokens=0, cache_write_tokens=0,
                    total_tokens=0, cost=0.0, cost_breakdown={}, session_id=session_id,
                    model_requests=1,
                    model_turns=1 if message_roles.get(message.get('parentID')) == 'user' else 0,
                    is_metric_only=True
                ))

            tools = cursor.execute("""
                SELECT p.session_id, p.time_created, p.data, s.model FROM part p
                JOIN session s ON s.id = p.session_id
                WHERE json_extract(p.data, '$.type') = 'tool'
            """).fetchall()
            for session_id, timestamp_ms, part_json, model_json in tools:
                try:
                    model_id = json.loads(model_json or '{}').get('id', 'unknown').split('.')[-1]
                except json.JSONDecodeError:
                    model_id = 'unknown'
                usages.append(UsageEntry(
                    agent='opencode', model_id=model_id, timestamp=str(timestamp_ms),
                    input_tokens=0, output_tokens=0, cache_read_tokens=0, cache_write_tokens=0,
                    total_tokens=0, cost=0.0, cost_breakdown={}, session_id=session_id,
                    model_tool_calls=1, is_metric_only=True
                ))
            conn.close()
            return usages
        except sqlite3.Error as e:
            print(f"Error reading OpenCode database: {e}")
            return []


class PiAgentExtractor:
    """Extract usage data from Pi agent session files."""
    
    @staticmethod
    def get_all_session_files() -> List[Path]:
        """Get all session JSONL files from pi agent sessions directory."""
        base_dir = Path.home() / ".pi" / "agent" / "sessions"
        session_files = []
        
        if not base_dir.exists():
            return session_files
        
        for session_dir in base_dir.iterdir():
            if session_dir.is_dir():
                for file in session_dir.glob("*.jsonl"):
                    session_files.append(file)
        
        return session_files
    
    @staticmethod
    def parse_session_line(line: str) -> Optional[Dict]:
        """Parse a single session line and return event dict."""
        try:
            return json.loads(line.strip())
        except json.JSONDecodeError:
            return None
    
    @staticmethod
    def extract_usage_from_session(session_file: Path) -> List[UsageEntry]:
        """Extract usage data from a session file."""
        usages = []
        
        try:
            with open(session_file, 'r') as f:
                events = []
                for line in f:
                    event = PiAgentExtractor.parse_session_line(line)
                    if event:
                        events.append(event)
            by_id = {event.get('id'): event for event in events}
            for event in events:
                if event.get('type') != 'message':
                    continue
                msg = event.get('message', {})
                usage = msg.get('usage')
                timestamp = event.get('timestamp', '')
                session_id = event.get('sessionId')
                if usage and usage.get('totalTokens', 0) > 0:
                    model_id = msg.get('model', '')
                    parent = by_id.get(event.get('parentId'), {}).get('message', {})
                    usages.append(UsageEntry(
                        agent='pi', model_id=model_id, timestamp=timestamp,
                        input_tokens=usage.get('input', 0), output_tokens=usage.get('output', 0),
                        cache_read_tokens=usage.get('cacheRead', 0), cache_write_tokens=usage.get('cacheWrite', 0),
                        total_tokens=usage.get('totalTokens', 0), cost=usage.get('cost', {}).get('total', 0),
                        cost_breakdown=usage.get('cost', {}), session_id=session_id,
                        model_requests=1, model_turns=1 if parent.get('role') == 'user' else 0
                    ))
                elif msg.get('role') == 'toolResult':
                    usages.append(UsageEntry(
                        agent='pi', model_id='', timestamp=timestamp,
                        input_tokens=0, output_tokens=0, cache_read_tokens=0, cache_write_tokens=0,
                        total_tokens=0, cost=0.0, cost_breakdown={}, session_id=session_id,
                        model_tool_calls=1, is_metric_only=True
                    ))
        except IOError as e:
            print(f"Error reading session file {session_file}: {e}")
        
        return usages
    
    @staticmethod
    def extract_usage() -> List[UsageEntry]:
        """Extract all usage data from Pi agent."""
        session_files = PiAgentExtractor.get_all_session_files()
        all_usages = []
        
        for session_file in session_files:
            usages = PiAgentExtractor.extract_usage_from_session(session_file)
            all_usages.extend(usages)
        
        return all_usages


class CodexExtractor:
    """Extract usage data from Codex rollout JSONL files."""
    
    @staticmethod
    def get_all_session_files() -> List[Path]:
        """Get all rollout JSONL files from Codex sessions directory."""
        base_dir = Path.home() / ".codex" / "sessions"
        session_files = []
        
        if not base_dir.exists():
            return session_files
        
        # Codex stores sessions in YYYY/MM/DD structure
        for year_dir in base_dir.iterdir():
            if year_dir.is_dir() and year_dir.name.isdigit():
                for month_dir in year_dir.iterdir():
                    if month_dir.is_dir() and month_dir.name.isdigit():
                        for day_dir in month_dir.iterdir():
                            if day_dir.is_dir():
                                for file in day_dir.glob("rollout-*.jsonl"):
                                    session_files.append(file)
        
        return session_files
    
    @staticmethod
    def extract_usage_from_session(session_file: Path) -> List[UsageEntry]:
        """Extract usage data from a Codex rollout session file."""
        usages = []
        current_model = 'unknown'
        seen_token_events = set()
        
        try:
            with open(session_file, 'r') as f:
                for line in f:
                    try:
                        event = json.loads(line.strip())
                        event_type = event.get('type')
                        
                        # Track model from turn_context
                        if event_type == 'turn_context':
                            payload = event.get('payload', {})
                            current_model = payload.get('model', 'unknown')
                        
                        # Extract token usage from token_count events
                        elif event_type == 'event_msg':
                            payload = event.get('payload', {})
                            if payload.get('type') == 'token_count':
                                info = payload.get('info', {})
                                last_usage = info.get('last_token_usage', {})
                                
                                if last_usage:
                                    timestamp = event.get('timestamp', '')
                                    turn_id = payload.get('turn_id')
                                    request_key = (turn_id, timestamp, tuple(sorted(last_usage.items())))
                                    if request_key in seen_token_events:
                                        continue
                                    seen_token_events.add(request_key)
                                    input_tok = last_usage.get('input_tokens', 0)
                                    output_tok = last_usage.get('output_tokens', 0)
                                    cache_read_tok = last_usage.get('cached_input_tokens', 0)
                                    cache_write_tok = last_usage.get('cache_write_input_tokens', 0)
                                    total_tok = last_usage.get('total_tokens', 0)
                                    
                                    # Calculate cost using Bedrock pricing
                                    cost = calculate_cost(
                                        input_tok, output_tok, 
                                        cache_read_tok, cache_write_tok,
                                        current_model
                                    )
                                    
                                    usages.append(UsageEntry(
                                        agent='codex',
                                        model_id=current_model,
                                        timestamp=timestamp,
                                        input_tokens=input_tok,
                                        output_tokens=output_tok,
                                        cache_read_tokens=cache_read_tok,
                                        cache_write_tokens=cache_write_tok,
                                        total_tokens=total_tok,
                                        cost=cost,
                                        cost_breakdown={'total': cost},
                                        is_aggregated=False,
                                        model_requests=1
                                    ))
                            elif payload.get('type') == 'task_started':
                                usages.append(UsageEntry(
                                    agent='codex', model_id=current_model,
                                    timestamp=event.get('timestamp', ''), input_tokens=0,
                                    output_tokens=0, cache_read_tokens=0, cache_write_tokens=0,
                                    total_tokens=0, cost=0.0, cost_breakdown={},
                                    model_turns=1, is_metric_only=True
                                ))
                        elif event_type == 'response_item':
                            payload = event.get('payload', {})
                            if payload.get('type') in ('function_call', 'custom_tool_call'):
                                usages.append(UsageEntry(
                                    agent='codex', model_id=current_model,
                                    timestamp=event.get('timestamp', ''), input_tokens=0,
                                    output_tokens=0, cache_read_tokens=0, cache_write_tokens=0,
                                    total_tokens=0, cost=0.0, cost_breakdown={},
                                    model_tool_calls=1, is_metric_only=True
                                ))
                    except json.JSONDecodeError:
                        continue
        except IOError as e:
            print(f"Error reading Codex session file {session_file}: {e}")
        
        return usages
    
    @staticmethod
    def extract_usage() -> List[UsageEntry]:
        """Extract all usage data from Codex."""
        session_files = CodexExtractor.get_all_session_files()
        
        if not session_files:
            return []
        
        all_usages = []
        for session_file in session_files:
            usages = CodexExtractor.extract_usage_from_session(session_file)
            all_usages.extend(usages)
        
        return all_usages


# ============================================================================
# DATA PROCESSING AND ANALYSIS
# ============================================================================

class UsageAnalyzer:
    """Core analysis logic matching pi.py output format."""
    
    @staticmethod
    def extract_date_from_timestamp(timestamp: str) -> Optional[datetime.date]:
        """Extract date from ISO timestamp or epoch timestamp."""
        try:
            if 'T' in timestamp:
                date_str = timestamp.split('T')[0]
                return datetime.strptime(date_str, '%Y-%m-%d').date()
            elif timestamp.isdigit():
                return datetime.fromtimestamp(int(timestamp) / 1000).date()
        except (ValueError, IndexError):
            pass
        return None
    
    @staticmethod
    def filter_by_date_range(usages: List[UsageEntry], start_date: datetime.date, 
                           end_date: datetime.date) -> List[UsageEntry]:
        """Filter usage entries by date range. Skip aggregated data."""
        filtered = []
        for usage in usages:
            if getattr(usage, 'is_aggregated', False):
                filtered.append(usage)
                continue
            
            date = UsageAnalyzer.extract_date_from_timestamp(usage.timestamp)
            if date and start_date <= date <= end_date:
                filtered.append(usage)
        return filtered
    
    @staticmethod
    def analyze_agent(agent: str, usages: List[UsageEntry], start_date: datetime.date, 
                     end_date: datetime.date, period_label: str) -> AgentStats:
        """Analyze usage data for a single agent."""
        filtered_usages = UsageAnalyzer.filter_by_date_range(usages, start_date, end_date)
        
        if not filtered_usages:
            return AgentStats(agent=agent)
        
        stats = AgentStats(agent=agent)
        model_tokens = defaultdict(lambda: {
            'input': 0, 'output': 0, 'cache_read': 0, 'cache_write': 0, 'cost': 0.0,
            'model_requests': 0, 'model_turns': 0, 'model_tool_calls': 0
        })
        daily_tokens = defaultdict(lambda: {'tokens': 0, 'cost': 0.0})
        sessions = set()
        
        for usage in filtered_usages:
            stats.total_model_requests += usage.model_requests
            stats.total_model_turns += usage.model_turns
            stats.total_model_tool_calls += usage.model_tool_calls
            model_tokens[usage.model_id]['model_requests'] += usage.model_requests
            model_tokens[usage.model_id]['model_turns'] += usage.model_turns
            model_tokens[usage.model_id]['model_tool_calls'] += usage.model_tool_calls
            if usage.is_metric_only:
                continue
            stats.usage_entries += 1
            stats.unique_models.add(usage.model_id)
            
            session_id = getattr(usage, 'session_id', None)
            if session_id:
                sessions.add(session_id)
            
            model_tokens[usage.model_id]['input'] += usage.input_tokens
            model_tokens[usage.model_id]['output'] += usage.output_tokens
            model_tokens[usage.model_id]['cache_read'] += usage.cache_read_tokens
            model_tokens[usage.model_id]['cache_write'] += usage.cache_write_tokens
            model_tokens[usage.model_id]['cost'] += usage.cost
            
            stats.total_input_tokens += usage.input_tokens
            stats.total_output_tokens += usage.output_tokens
            stats.total_cache_read_tokens += usage.cache_read_tokens
            stats.total_cache_write_tokens += usage.cache_write_tokens
            stats.total_tokens += usage.total_tokens
            stats.total_cost += usage.cost
            
            date = UsageAnalyzer.extract_date_from_timestamp(usage.timestamp)
            if date:
                date_str = date.strftime('%Y-%m-%d')
                daily_tokens[date_str]['tokens'] += usage.total_tokens
                daily_tokens[date_str]['cost'] += usage.cost
        
        stats.sessions_count = len(sessions)
        stats.model_breakdown = dict(model_tokens)
        stats.daily_activity = dict(daily_tokens)
        
        total_days = (end_date - start_date).days + 1
        if total_days > 0:
            stats.daily_cost = stats.total_cost / total_days
            stats.weekly_cost = stats.daily_cost * 7
            stats.monthly_cost = stats.daily_cost * 30
            stats.quarterly_cost = stats.daily_cost * 90
            stats.yearly_cost = stats.daily_cost * 365
        
        return stats


# Color mapping for agent headers
AGENT_COLORS = {
    'claude-code': Colors.claude_code,
    'opencode': Colors.opencode,
    'pi': Colors.pi,
    'codex': Colors.codex,
}

AGENT_NAMES = {
    'claude-code': 'CLAUDE CODE',
    'opencode': 'OPENCODE',
    'pi': 'PI CODING AGENT',
    'codex': 'CODEX',
}


def print_agent_header(agent: str, title: str = "USAGE ANALYSIS"):
    """Print color-coded agent header."""
    color = AGENT_COLORS.get(agent, Colors.reset)
    name = AGENT_NAMES.get(agent, agent.upper())
    
    print(f"{color}{'=' * 80}{Colors.reset}")
    print(f"{color}{name} {title}{Colors.reset}")
    print(f"{color}{'=' * 80}{Colors.reset}")


def print_single_agent_report(agent: str, usages: List[UsageEntry], 
                             stats: AgentStats, start_date: datetime.date, 
                             end_date: datetime.date, period_label: str):
    """Print detailed report for a single agent in pi.py format."""
    color = AGENT_COLORS.get(agent, Colors.reset)
    
    # Print header with color
    print_agent_header(agent)
    
    print(f"\n{color}Analysis Period: {start_date} to {end_date} ({period_label}){Colors.reset}")
    
    if not usages:
        print(f"\n{color}No usage data found for {AGENT_NAMES.get(agent, agent.upper())}{Colors.reset}")
        return
    
    print(f"\n{color}Found {stats.usage_entries} usage entries{Colors.reset}")
    
    # ===== TOTAL USAGE SECTION =====
    print(f"\n{color}{'=' * 80}{Colors.reset}")
    print(f"{color}TOTAL USAGE (ALL MODELS){Colors.reset}")
    print(f"{color}{'=' * 80}{Colors.reset}")
    
    print(f"\nModel requests:        {stats.total_model_requests:>15,}")
    print(f"Model turns:           {stats.total_model_turns:>15,}")
    print(f"Model tool calls:      {stats.total_model_tool_calls:>15,}")
    print(f"\nInput tokens:          {stats.total_input_tokens:>15,}")
    print(f"Output tokens:         {stats.total_output_tokens:>15,}")
    print(f"Cache read tokens:     {stats.total_cache_read_tokens:>15,}")
    print(f"Cache creation tokens: {stats.total_cache_write_tokens:>15,}")
    print(f"GRAND TOTAL TOKENS:    {stats.total_tokens:>15,}")
    print(f"\nTOTAL COST:            ${stats.total_cost:>14,.6f}")
    
    # ===== BREAKDOWN BY MODEL SECTION =====
    print(f"\n{color}{'=' * 80}{Colors.reset}")
    print(f"{color}BREAKDOWN BY MODEL{Colors.reset}")
    print(f"{color}{'=' * 80}{Colors.reset}")
    
    sorted_models = sorted(
        stats.model_breakdown.items(),
        key=lambda x: x[1]['cost'],
        reverse=True
    )
    
    for model_id, model_data in sorted_models:
        total_model_tokens = (model_data['input'] + model_data['output'] + 
                             model_data['cache_read'] + model_data['cache_write'])
        print(f"\n{model_id}:")
        print(f"  Input tokens:         {model_data['input']:>15,}")
        print(f"  Output tokens:        {model_data['output']:>15,}")
        print(f"  Cache read tokens:    {model_data['cache_read']:>15,}")
        print(f"  Cache creation tokens:{model_data['cache_write']:>15,}")
        print(f"  TOTAL TOKENS:         {total_model_tokens:>15,}")
        print(f"  Cost:                 ${model_data['cost']:>14,.6f}")
        print(f"  Model requests:       {model_data['model_requests']:>15,}")
        print(f"  Model turns:          {model_data['model_turns']:>15,}")
        print(f"  Model tool calls:     {model_data['model_tool_calls']:>15,}")
    
    # ===== COST PROJECTIONS PER TIME PERIOD =====
    print(f"\n{color}{'=' * 80}{Colors.reset}")
    print(f"{color}COST PROJECTIONS PER TIME PERIOD{Colors.reset}")
    print(f"{color}{'=' * 80}{Colors.reset}")
    
    days_active = len(stats.daily_activity) if stats.daily_activity else 1
    total_days = (end_date - start_date).days + 1
    
    print(f"\nDaily (across all {total_days} days):        ${stats.daily_cost:>14,.6f}")
    print(f"Daily (active days only, {days_active} days): ${stats.daily_cost if days_active > 0 else 0:>14,.6f}")
    print(f"Weekly (across {total_days/7:.1f} weeks):            ${stats.weekly_cost:>14,.6f}")
    print(f"Monthly (30-day avg, {total_days/30:.1f} months):      ${stats.monthly_cost:>14,.6f}")
    print(f"Quarterly (90-day avg, {total_days/90:.1f} quarters): ${stats.quarterly_cost:>14,.6f}")
    print(f"Yearly (365-day avg, {total_days/365:.2f} years):      ${stats.yearly_cost:>14,.6f}")
    
    # ===== TOKEN VOLUME PER TIME PERIOD =====
    print(f"\n{color}{'=' * 80}{Colors.reset}")
    print(f"{color}TOKEN VOLUME PER TIME PERIOD{Colors.reset}")
    print(f"{color}{'=' * 80}{Colors.reset}")
    
    token_daily_avg = stats.total_tokens / total_days if total_days > 0 else 0
    token_weekly = token_daily_avg * 7
    token_monthly = token_daily_avg * 30
    token_quarterly = token_daily_avg * 90
    token_yearly = token_daily_avg * 365
    
    print(f"\nDaily (across all days):     {token_daily_avg:>15,.0f} tokens")
    print(f"Daily (active days only):    {token_daily_avg:>15,.0f} tokens")
    print(f"Weekly:                      {token_weekly:>15,.0f} tokens")
    print(f"Monthly (30-day avg):        {token_monthly:>15,.0f} tokens")
    print(f"Quarterly (90-day avg):      {token_quarterly:>15,.0f} tokens")
    print(f"Yearly (365-day avg):        {token_yearly:>15,.0f} tokens")

    # ===== MODEL ACTIVITY VOLUME PER TIME PERIOD =====
    print(f"\n{color}{'=' * 80}{Colors.reset}")
    print(f"{color}MODEL ACTIVITY VOLUME PER TIME PERIOD{Colors.reset}")
    print(f"{color}{'=' * 80}{Colors.reset}")

    activity_periods = (
        ('Daily (across all days):', 1),
        ('Weekly:', 7),
        ('Monthly (30-day avg):', 30),
        ('Quarterly (90-day avg):', 90),
        ('Yearly (365-day avg):', 365),
    )
    activity_daily = {
        'requests': stats.total_model_requests / total_days if total_days > 0 else 0,
        'turns': stats.total_model_turns / total_days if total_days > 0 else 0,
        'tool_calls': stats.total_model_tool_calls / total_days if total_days > 0 else 0,
    }

    print(f"\n{'Period':<28} {'Requests':>15} {'Turns':>15} {'Tool calls':>15}")
    print('-' * 76)
    for label, multiplier in activity_periods:
        print(
            f"{label:<28} "
            f"{activity_daily['requests'] * multiplier:>15,.0f} "
            f"{activity_daily['turns'] * multiplier:>15,.0f} "
            f"{activity_daily['tool_calls'] * multiplier:>15,.0f}"
        )

    # ===== DAILY ACTIVITY =====
    print(f"\n{color}{'=' * 80}{Colors.reset}")
    print(f"{color}DAILY ACTIVITY{Colors.reset}")
    print(f"{color}{'=' * 80}{Colors.reset}")
    print(f"{'Date':<12} {'Tokens':>15} {'Cost':>12}")
    print("-" * 43)
    
    if stats.daily_activity:
        for date in sorted(stats.daily_activity.keys()):
            data = stats.daily_activity[date]
            print(f"{date:<12} {data['tokens']:>15,} ${data['cost']:>11,.6f}")
    else:
        print("No daily activity data available.")
    
    # ===== SUMMARY STATISTICS =====
    print(f"\n{color}{'=' * 80}{Colors.reset}")
    print(f"{color}SUMMARY STATISTICS{Colors.reset}")
    print(f"{color}{'=' * 80}{Colors.reset}")
    
    print(f"\nTotal sessions: {stats.sessions_count}")
    print(f"Total messages (usage entries): {stats.usage_entries}")
    print(f"Unique models used: {len(stats.unique_models)}")
    
    # ===== CACHE EFFECTIVENESS =====
    print(f"\n{color}{'=' * 80}{Colors.reset}")
    print(f"{color}CACHE EFFECTIVENESS{Colors.reset}")
    print(f"{color}{'=' * 80}{Colors.reset}")
    
    total_cache_tokens = stats.total_cache_read_tokens + stats.total_cache_write_tokens
    if total_cache_tokens > 0:
        cache_ratio = stats.total_cache_read_tokens / total_cache_tokens
        print(f"Cache read ratio: {cache_ratio:.1%} ({stats.total_cache_read_tokens:,} / {total_cache_tokens:,})")
    
    if stats.total_cache_read_tokens > 0 and stats.total_cache_write_tokens > 0:
        efficiency = stats.total_cache_read_tokens / stats.total_cache_write_tokens
        print(f"Cache efficiency ratio: {efficiency:.1f}:1")
    
    # ===== COST ANALYSIS =====
    print(f"\n{color}{'=' * 80}{Colors.reset}")
    print(f"{color}COST ANALYSIS{Colors.reset}")
    print(f"{color}{'=' * 80}{Colors.reset}")
    
    actual_cost = stats.total_cost
    
    print(f"\nActual reported cost:                  ${actual_cost:>14,.6f}")
    print(f"Cost by pricing model estimate:        ${actual_cost:>14,.6f}")
    
    print("\nCost by top models:")
    top_models = sorted_models[:5] if len(sorted_models) > 5 else sorted_models
    for model_id, model_data in top_models:
        if model_data['cost'] > 0:
            pct = (model_data['cost'] / actual_cost * 100) if actual_cost > 0 else 0
            print(f"  {model_id}: ${model_data['cost']:>12,.2f} ({pct:.1f}%)")
    print("=" * 80)


def print_summary_comparison(all_stats: Dict[str, AgentStats]):
    """Print comparison summary across multiple agents."""
    # Use reset colors for comparison (header is already colored per-agent)
    print(f"\n{'=' * 80}")
    print("COMPARISON SUMMARY")
    print("=" * 80)
    
    print(f"\n{'Agent':<15} {'Total Tokens':>15} {'Requests':>12} {'Turns':>12} {'Tool Calls':>12} {'Total Cost':>15} {'Avg Daily Cost':>15}")
    print("-" * 105)
    
    combined_tokens = 0
    combined_requests = 0
    combined_turns = 0
    combined_tool_calls = 0
    combined_cost = 0.0
    
    for agent, stats in all_stats.items():
        if stats.usage_entries > 0:
            agent_name = agent.replace('-', ' ').title()
            print(
                f"{agent_name:<15} {stats.total_tokens:>15,} "
                f"{stats.total_model_requests:>12,} {stats.total_model_turns:>12,} "
                f"{stats.total_model_tool_calls:>12,} ${stats.total_cost:>14,.2f} "
                f"${stats.daily_cost:>14,.2f}"
            )
            combined_tokens += stats.total_tokens
            combined_requests += stats.total_model_requests
            combined_turns += stats.total_model_turns
            combined_tool_calls += stats.total_model_tool_calls
            combined_cost += stats.total_cost
        else:
            print(f"{agent.replace('-', ' ').title():<15} {'No data':>15} {'-':>12} {'-':>12} {'-':>12} {'-':>15} {'-':>15}")
    
    print("-" * 105)
    print(
        f"{'COMBINED TOTAL':<15} {combined_tokens:>15,} "
        f"{combined_requests:>12,} {combined_turns:>12,} {combined_tool_calls:>12,} "
        f"${combined_cost:>14,.2f}"
    )
    print("=" * 105)


# ============================================================================
# COMMAND LINE INTERFACE
# ============================================================================

def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Unified usage analysis for AI coding agents.'
    )
    
    # Agent selection - multiple values allowed
    parser.add_argument('--agent', nargs='+', 
                       choices=['claude-code', 'opencode', 'pi', 'codex', 'all'],
                       default='all',
                       help='Agent(s) to analyze. Use "all" for all detected agents, or list multiple: --agent claude-code opencode')
    
    # Time period flags
    parser.add_argument('-w', '--weeks', type=int, default=None,
                       help='Last N weeks (each week = 7 days)')
    parser.add_argument('-d', '--days', type=int, default=None,
                       help='Last N days')
    parser.add_argument('-m', '--months', type=int, default=None,
                       help='Last N months (each month = 30 days)')
    parser.add_argument('-q', '--quarters', type=int, default=None,
                       help='Last N quarters (each quarter = 90 days)')
    parser.add_argument('-y', '--years', type=int, default=None,
                       help='Last N years (each year = 360 days)')
    parser.add_argument('--ytd', action='store_true',
                       help='Year-to-date for current year')
    
    # Output options
    parser.add_argument('--output', type=str,
                       help='Save results to file (JSON format)')
    
    return parser.parse_args()


def get_date_range(args: argparse.Namespace) -> Tuple[datetime.date, datetime.date, str]:
    """Calculate date range based on flags."""
    now = datetime.now()
    
    if args.ytd:
        start = datetime(now.year, 1, 1)
        end = now
        return start.date(), end.date(), 'YTD'
    
    no_flags = (args.days is None and args.months is None and 
                args.quarters is None and args.years is None and 
                args.weeks is None and not args.ytd)
    
    if no_flags:
        end = now
        return None, end.date(), 'ALL TIME'
    
    # Calculate based on flags
    if args.years:
        days = args.years * 360
        label = f"{args.years}y"
    elif args.quarters:
        days = args.quarters * 90
        label = f"{args.quarters}q"
    elif args.months:
        days = args.months * 30
        label = f"{args.months}m"
    elif args.weeks:
        days = args.weeks * 7
        label = f"{args.weeks}w"
    elif args.days:
        days = args.days
        label = f"{args.days}d"
    else:
        days = 7
        label = "1w"
    
    start = now - timedelta(days=days)
    end = now
    return start.date(), end.date(), label


def main():
    """Main entry point."""
    args = parse_args()
    
    # Disable colors if outputting to file
    if args.output:
        Colors.disable()
    
    # Get date range
    start_date, end_date, period_label = get_date_range(args)
    
    # Handle 'all' vs specific agents
    if 'all' in args.agent:
        if len(args.agent) > 1:
            print("Error: 'all' cannot be combined with other agents.")
            print("Usage: --agent all OR --agent claude-code opencode")
            return
        agents_to_analyze = AgentPaths.detect_agents()
        if not agents_to_analyze:
            print("No agents detected. Check if any agents are installed.")
            return
    else:
        agents_to_analyze = args.agent
    
    print(f"Analyzing agents: {', '.join(agents_to_analyze)}")
    
    # Collect data from each agent
    agent_data = {}
    for agent in agents_to_analyze:
        print(f"\nCollecting data from {agent}...")
        
        if agent == 'claude-code':
            usages = ClaudeCodeExtractor.extract_usage()
        elif agent == 'opencode':
            usages = OpenCodeExtractor.extract_usage()
        elif agent == 'pi':
            usages = PiAgentExtractor.extract_usage()
        elif agent == 'codex':
            usages = CodexExtractor.extract_usage()
        else:
            print(f"Unknown agent: {agent}")
            continue
        
        if usages:
            print(f"  Found {len(usages)} usage entries")
            agent_data[agent] = usages
        else:
            print(f"  No usage data found for {agent}")
    
    # Analyze each agent
    all_stats = {}
    for agent, usages in agent_data.items():
        print(f"\nAnalyzing {agent}...")
        
        actual_start_date = start_date
        if start_date is None and usages:
            dates = []
            for usage in usages:
                date = UsageAnalyzer.extract_date_from_timestamp(usage.timestamp)
                if date:
                    dates.append(date)
            
            if dates:
                actual_start_date = min(dates)
                period_label = f"ALL TIME (data from {actual_start_date})"
            else:
                actual_start_date = datetime.now().date()
        
        stats = UsageAnalyzer.analyze_agent(
            agent, usages, actual_start_date, end_date, period_label
        )
        
        all_stats[agent] = stats
        
        # Print agent report (with color coding)
        print_single_agent_report(
            agent, usages, stats, actual_start_date, end_date, period_label
        )
    
    # Print multi-agent comparison if analyzing multiple agents
    if len(agent_data) > 1:
        print_summary_comparison(all_stats)
    
    # Write JSON output if --output flag provided
    if args.output:
        output_result = {
            'analysis_period': {
                'start': str(start_date) if start_date else 'ALL TIME',
                'end': str(end_date),
                'label': period_label
            },
            'agents_analyzed': list(all_stats.keys()),
            'agent_stats': {}
        }
        
        for agent, stats in all_stats.items():
            output_result['agent_stats'][agent] = {
                'model_requests': stats.total_model_requests,
                'model_turns': stats.total_model_turns,
                'model_tool_calls': stats.total_model_tool_calls,
                'total_input_tokens': stats.total_input_tokens,
                'total_output_tokens': stats.total_output_tokens,
                'total_cache_read_tokens': stats.total_cache_read_tokens,
                'total_cache_write_tokens': stats.total_cache_write_tokens,
                'total_tokens': stats.total_tokens,
                'total_cost': stats.total_cost,
                'daily_cost': stats.daily_cost,
                'weekly_cost': stats.weekly_cost,
                'monthly_cost': stats.monthly_cost,
                'quarterly_cost': stats.quarterly_cost,
                'yearly_cost': stats.yearly_cost,
                'usage_entries': stats.usage_entries,
                'unique_models': list(stats.unique_models),
                'model_breakdown': stats.model_breakdown,
                'daily_activity': stats.daily_activity
            }
        
        # Add combined summary if multiple agents
        if len(all_stats) > 1:
            combined_tokens = sum(s.total_tokens for s in all_stats.values())
            combined_cost = sum(s.total_cost for s in all_stats.values())
            output_result['combined_summary'] = {
                'total_tokens': combined_tokens,
                'total_cost': combined_cost
            }
        
        # Write to file
        import json as json_module
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json_module.dump(output_result, f, indent=2)
        print(f"\nResults saved to: {args.output}")


if __name__ == "__main__":
    # Enable colors if output is to terminal
    if should_colorize():
        pass  # Colors already enabled
    else:
        Colors.disable()
    
    main()
