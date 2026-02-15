# Sovereign Hive V4: Implementation Roadmap

> A Decentralized Trading Firm for Polymarket

---

## Executive Summary

The Sovereign Hive is a multi-agent autonomous trading system where each agent operates as an independent process, communicating through a shared "Blackboard" (state store). This architecture enables:

- **Separation of Concerns**: Each agent has one job
- **Fault Isolation**: One agent crashing doesn't kill the system
- **Parallel Evolution**: Agents can be upgraded independently
- **Auditability**: Every decision is logged and traceable

---

## CRITICAL: Latency Architecture

> **The Latency Trap is the #1 killer of autonomous bots.**
>
> If your Scout finds a trade but your Analyst takes 15 seconds to "think" about the news, the profit is already gone. High-frequency bots have already closed the gap while your AI was still reading the headline.

### The Problem with Polling

```
CURRENT (SLOW):
┌─────────┐    Poll every 10s    ┌─────────┐
│  Scout  │ ─────────────────▶  │   API   │
└─────────┘                      └─────────┘
     │
     │ 10 seconds later...
     ▼
┌─────────┐    LLM call (~5s)    ┌─────────┐
│ Analyst │ ─────────────────▶  │ Claude  │
└─────────┘                      └─────────┘
     │
     │ 5 seconds later...
     ▼
┌─────────┐
│ Sniper  │  ──▶ OPPORTUNITY GONE (15s total latency)
└─────────┘
```

### The Solution: Event-Driven + Parallel Architecture

```
TARGET (FAST):
                                    ┌──────────────────┐
                                    │  SENTIMENT CACHE │
                                    │     (Redis)      │
                                    │   Pre-digested   │
                                    │   news/context   │
                                    └────────▲─────────┘
                                             │ Continuous
                                             │ background
                                             │ updates
┌─────────────────┐                 ┌────────┴─────────┐
│   WebSocket     │   Push (1ms)   │     Analyst      │
│   Listener      │ ◀───────────── │  (Background)    │
│   (Alpha)       │                 └──────────────────┘
└────────┬────────┘
         │ Event triggers
         │ instant lookup
         ▼
┌─────────────────┐   Cache hit    ┌──────────────────┐
│  In-Memory      │ ◀──(100ms)──── │     Sniper       │
│  State (Redis)  │                │    (Gamma)       │
└─────────────────┘                └──────────────────┘

TOTAL LATENCY: ~150ms (vs 15,000ms before)
```

---

## Latency Optimization Components

### L1. WebSocket Listener (Kill the Polling)

**Current**: REST polling every 10 seconds
**Target**: WebSocket push with <10ms reaction time

```python
# sovereign_hive/core/ws_listener.py

import asyncio
import websockets
import json
from datetime import datetime

class MarketWebSocket:
    """
    Event-driven market listener.
    Reacts to price changes in real-time instead of polling.
    """

    def __init__(self, on_event_callback):
        self.ws_url = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
        self.callback = on_event_callback
        self.connected = False
        self.last_heartbeat = None

    async def connect(self, token_ids: list):
        """Subscribe to real-time updates for specific markets."""
        async with websockets.connect(self.ws_url) as ws:
            self.connected = True

            # Subscribe to markets
            subscribe_msg = {
                "type": "subscribe",
                "channel": "market",
                "assets_ids": token_ids
            }
            await ws.send(json.dumps(subscribe_msg))

            # Listen for events
            async for message in ws:
                self.last_heartbeat = datetime.utcnow()
                data = json.loads(message)

                if data.get("event_type") == "price_change":
                    # Trigger callback immediately
                    await self.callback(data)

    async def health_check(self):
        """Guardian calls this to verify connection is alive."""
        if not self.connected:
            return False
        if self.last_heartbeat:
            seconds_since = (datetime.utcnow() - self.last_heartbeat).seconds
            return seconds_since < 5
        return False
```

**Implementation Tasks**:
- [ ] Create `core/ws_listener.py`
- [ ] Map Polymarket WebSocket protocol
- [ ] Implement auto-reconnect on disconnect
- [ ] Add Guardian heartbeat monitoring

### L2. In-Memory State (Redis)

**Current**: File-based `blackboard.json` (slow, lock-prone)
**Target**: Redis for hot state, JSON for cold storage

```python
# sovereign_hive/core/redis_state.py

import redis
import json
from typing import Optional

class RedisState:
    """
    In-memory state management for real-time trading.
    File-based blackboard becomes "cold storage" for audit logs.
    """

    def __init__(self, host='localhost', port=6379):
        self.client = redis.Redis(host=host, port=port, decode_responses=True)

        # Key prefixes
        self.OPPORTUNITIES = "hive:opportunities"
        self.VETTED = "hive:vetted"
        self.POSITIONS = "hive:positions"
        self.SENTIMENT = "hive:sentiment"
        self.RISK_STATE = "hive:risk_state"

    # --- OPPORTUNITIES ---
    def add_opportunity(self, opp: dict):
        """Add opportunity (expires in 5 minutes)."""
        key = f"{self.OPPORTUNITIES}:{opp['condition_id']}"
        self.client.setex(key, 300, json.dumps(opp))

    def get_opportunities(self) -> list:
        """Get all active opportunities."""
        keys = self.client.keys(f"{self.OPPORTUNITIES}:*")
        return [json.loads(self.client.get(k)) for k in keys]

    # --- SENTIMENT CACHE ---
    def set_sentiment(self, topic: str, sentiment: dict):
        """Cache pre-digested sentiment (expires in 10 minutes)."""
        key = f"{self.SENTIMENT}:{topic}"
        self.client.setex(key, 600, json.dumps(sentiment))

    def get_sentiment(self, topic: str) -> Optional[dict]:
        """Instant sentiment lookup (no API call needed)."""
        key = f"{self.SENTIMENT}:{topic}"
        data = self.client.get(key)
        return json.loads(data) if data else None

    # --- RISK STATE ---
    def set_risk_state(self, state: str):
        self.client.set(self.RISK_STATE, state)

    def get_risk_state(self) -> str:
        return self.client.get(self.RISK_STATE) or "HEALTHY"

    # --- ATOMIC OPERATIONS ---
    def atomic_add_position(self, position: dict) -> bool:
        """Add position atomically (prevents double-execution)."""
        key = f"{self.POSITIONS}:{position['condition_id']}"
        # SETNX = Set if Not Exists (atomic)
        return self.client.setnx(key, json.dumps(position))
```

**Implementation Tasks**:
- [ ] Create `core/redis_state.py`
- [ ] Install Redis on AWS (`sudo yum install redis`)
- [ ] Migrate hot state to Redis
- [ ] Keep JSON for audit trail / cold storage

### L3. Parallel Sentiment Stream (Pre-Vetting)

**Current**: Analyst waits for Scout, then searches news (slow)
**Target**: Analyst continuously pre-caches sentiment for trending topics

```python
# sovereign_hive/agents/sentiment_streamer.py

import asyncio
from core.news_client import NewsClient
from core.llm_analyst import LLMAnalyst
from core.redis_state import RedisState

class SentimentStreamer:
    """
    Background process that continuously pre-digests news.
    When Scout finds anomaly, sentiment is already cached.
    """

    def __init__(self):
        self.news = NewsClient()
        self.llm = LLMAnalyst()
        self.state = RedisState()

        # Topics to monitor (updated by Scout findings)
        self.hot_topics = set()

    async def stream_sentiment(self):
        """Continuous sentiment pre-caching loop."""
        while True:
            # Get trending topics from recent opportunities
            opps = self.state.get_opportunities()
            for opp in opps:
                topic = self._extract_topic(opp['question'])
                self.hot_topics.add(topic)

            # Pre-digest sentiment for each topic
            for topic in list(self.hot_topics)[:20]:  # Limit to 20
                cached = self.state.get_sentiment(topic)
                if not cached:
                    # Fetch and analyze
                    news = self.news.search(topic, hours_back=6)
                    if news:
                        sentiment = self.llm.quick_sentiment(topic, news)
                        self.state.set_sentiment(topic, sentiment)
                        print(f"[SENTIMENT] Cached: {topic} -> {sentiment['direction']}")

            await asyncio.sleep(30)  # Update every 30 seconds

    def _extract_topic(self, question: str) -> str:
        """Extract key topic from market question."""
        # Simple extraction - upgrade to NER later
        words = question.lower().split()
        # Remove common words
        stopwords = {'will', 'the', 'be', 'a', 'an', 'in', 'on', 'by', 'to'}
        key_words = [w for w in words if w not in stopwords][:3]
        return ' '.join(key_words)
```

**The Magic**: When Scout finds "Japan PM Takaichi" anomaly:
- **Before**: 5-10 second LLM call to analyze news
- **After**: 100ms Redis lookup (sentiment already cached)

**Implementation Tasks**:
- [ ] Create `agents/sentiment_streamer.py`
- [ ] Implement topic extraction (basic → NER)
- [ ] Run as separate background process
- [ ] Track cache hit rate

### L4. Co-Location (Proximity)

**Physics is the final boss of latency.**

| Your Location | Polymarket (us-east-1) | Round-Trip Latency |
|---------------|------------------------|-------------------|
| London | Virginia | ~140ms |
| California | Virginia | ~80ms |
| **Virginia** | **Virginia** | **<5ms** |

**Implementation Tasks**:
- [ ] Confirm Polymarket API region (likely us-east-1)
- [ ] Deploy to AWS us-east-1
- [ ] Use t3.small or c6i.large for low-latency networking

### L5. Guardian Heartbeat Monitor

**Risk**: Event-driven systems can go "blind" if WebSocket drops.

```python
# In omega_guardian.py

async def heartbeat_monitor(self, ws_listener, interval=5):
    """Ensure WebSocket is alive. Force reconnect if dead."""
    while True:
        is_healthy = await ws_listener.health_check()

        if not is_healthy:
            self.alerts.append("⚠️ WebSocket disconnected!")
            self.state.set_risk_state("WARNING")

            # Force reconnect
            await ws_listener.reconnect()

            # If still dead after 3 attempts, halt trading
            for attempt in range(3):
                await asyncio.sleep(2)
                if await ws_listener.health_check():
                    self.state.set_risk_state("HEALTHY")
                    break
            else:
                self.state.set_risk_state("HALTED")
                self._send_alert("🚨 WebSocket DEAD - Trading HALTED")

        await asyncio.sleep(interval)
```

---

## Latency Budget

| Component | Current | Target | Method |
|-----------|---------|--------|--------|
| Market Data | 10,000ms (polling) | <10ms | WebSocket |
| State Read/Write | 50-200ms (file) | <5ms | Redis |
| Sentiment Lookup | 5,000-10,000ms (LLM) | <100ms | Pre-cache |
| Order Submission | 200-500ms | 100-200ms | Co-location |
| **Total Cycle** | **15,000-20,000ms** | **<500ms** |

---

## Current State (Completed)

| Component | Status | Location |
|-----------|--------|----------|
| Blackboard Schema | ✅ Done | `blackboard.json` |
| Alpha Scout | ✅ Done | `agents/alpha_scout.py` |
| Beta Analyst | ✅ Done | `agents/beta_analyst.py` |
| Gamma Sniper | ✅ Done | `agents/gamma_sniper.py` |
| Omega Guardian | ✅ Done | `agents/omega_guardian.py` |
| Orchestrator | ✅ Done | `run_hive.py` |

---

## Phase 0: Async Architecture Upgrade (Week 0-1)

### Goal
Transform from polling to event-driven before building on a slow foundation.

### 0.1 Install Redis

```bash
# Local (Mac)
brew install redis
brew services start redis

# AWS (Amazon Linux)
sudo yum install redis6 -y
sudo systemctl start redis6
sudo systemctl enable redis6
```

### 0.2 Implement Core Components

| Component | File | Priority |
|-----------|------|----------|
| Redis State | `core/redis_state.py` | P0 |
| WebSocket Listener | `core/ws_listener.py` | P0 |
| Sentiment Streamer | `agents/sentiment_streamer.py` | P1 |
| Guardian Heartbeat | Update `omega_guardian.py` | P1 |

### 0.3 Refactor Agents for Async

```python
# All agents must become async-compatible

# BEFORE (blocking)
def run_scan():
    markets = fetch_markets()  # Blocks for 2 seconds
    ...

# AFTER (non-blocking)
async def run_scan():
    markets = await asyncio.to_thread(fetch_markets)
    # Or better: receive from WebSocket
    ...
```

### Phase 0 Deliverables

| Deliverable | Success Criteria |
|-------------|------------------|
| Redis Running | `redis-cli ping` returns PONG |
| WebSocket Connected | Receives price updates in <10ms |
| Full Cycle Latency | <500ms end-to-end |

---

## Phase 1: The Nervous System (Week 1-2)

### Goal
Harden the foundation with atomic operations and local simulation.

### 1.1 Blackboard Hardening (Cold Storage)

**Note**: With Redis handling hot state, `blackboard.json` becomes audit trail only.

**Problem**: File lock issues when multiple agents read/write simultaneously.

**Solution**: Implement atomic file operations with retry logic (for cold storage only).

```python
# sovereign_hive/core/blackboard.py

import json
import fcntl
import time
from pathlib import Path

class Blackboard:
    def __init__(self, path: Path):
        self.path = path
        self.max_retries = 5
        self.retry_delay = 0.1

    def read(self) -> dict:
        """Atomic read with file locking."""
        for attempt in range(self.max_retries):
            try:
                with open(self.path, 'r') as f:
                    fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                    data = json.load(f)
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                    return data
            except (IOError, json.JSONDecodeError):
                time.sleep(self.retry_delay * (attempt + 1))
        return {}

    def write(self, data: dict):
        """Atomic write with file locking."""
        for attempt in range(self.max_retries):
            try:
                with open(self.path, 'w') as f:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    json.dump(data, f, indent=2)
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                    return True
            except IOError:
                time.sleep(self.retry_delay * (attempt + 1))
        return False

    def update(self, key: str, value: any):
        """Atomic update of a single key."""
        data = self.read()
        data[key] = value
        return self.write(data)
```

**Tasks**:
- [ ] Create `core/blackboard.py` with atomic operations
- [ ] Refactor all agents to use `Blackboard` class
- [ ] Add write timestamps for conflict detection
- [ ] Implement backup/recovery for corrupted state

### 1.2 Local Mock API

**Purpose**: Test the full pipeline without hitting real Polymarket APIs.

```python
# sovereign_hive/testing/mock_api.py

from flask import Flask, jsonify
import random

app = Flask(__name__)

MOCK_MARKETS = [
    {
        "conditionId": "0xMOCK001",
        "question": "Mock Market: Will X happen?",
        "bestBid": 0.45,
        "bestAsk": 0.46,
        "volume24hr": 500000,
        "oneDayPriceChange": -0.15,
        "liquidityNum": 100000
    },
    # ... more mock markets
]

@app.route('/markets')
def get_markets():
    # Randomly fluctuate prices
    for m in MOCK_MARKETS:
        m['bestBid'] += random.uniform(-0.02, 0.02)
        m['bestAsk'] = m['bestBid'] + random.uniform(0.005, 0.02)
    return jsonify(MOCK_MARKETS)

@app.route('/order', methods=['POST'])
def post_order():
    return jsonify({
        "success": True,
        "orderID": f"MOCK_{random.randint(1000, 9999)}",
        "status": "live"
    })
```

**Tasks**:
- [ ] Create `testing/mock_api.py` Flask server
- [ ] Add configurable market scenarios (arbitrage, crash, spike)
- [ ] Implement mock order matching engine
- [ ] Create `--mock` flag for all agents

### 1.3 Structured Logging

**Purpose**: Every decision must be traceable.

```python
# sovereign_hive/core/logger.py

import logging
from datetime import datetime
from pathlib import Path

def setup_agent_logger(agent_name: str) -> logging.Logger:
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)

    logger = logging.getLogger(agent_name)
    logger.setLevel(logging.DEBUG)

    # File handler (detailed)
    fh = logging.FileHandler(
        log_dir / f"{agent_name}_{datetime.now().strftime('%Y%m%d')}.log"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        '%(asctime)s | %(levelname)s | %(message)s'
    ))

    # Console handler (summary)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(
        '[%(name)s] %(message)s'
    ))

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger
```

**Tasks**:
- [ ] Create `core/logger.py`
- [ ] Add structured JSON logging for audit trail
- [ ] Implement log rotation (keep 7 days)
- [ ] Create `logs/` directory with gitignore

### Phase 1 Deliverables

| Deliverable | Success Criteria |
|-------------|------------------|
| Atomic Blackboard | 100 concurrent reads/writes without corruption |
| Mock API | Full cycle runs without real API calls |
| Logging | Every decision logged with reasoning |

---

## Phase 2: Semantic Awareness (Week 3-4)

### Goal
Move Beta from rule-based analysis to real-world intelligence.

### 2.1 News API Integration

**Options Evaluated**:

| Provider | Cost | Latency | Quality |
|----------|------|---------|---------|
| Tavily | $50/mo | ~2s | High |
| Perplexity | $20/mo | ~3s | High |
| NewsAPI | $0 (dev) | ~1s | Medium |
| Google News RSS | Free | ~5s | Low |

**Recommended**: Start with **NewsAPI** (free tier), upgrade to **Tavily** for production.

```python
# sovereign_hive/core/news_client.py

import os
import requests
from datetime import datetime, timedelta

class NewsClient:
    def __init__(self):
        self.api_key = os.getenv("NEWS_API_KEY")
        self.base_url = "https://newsapi.org/v2"

    def search(self, query: str, hours_back: int = 24) -> list:
        """Search for recent news articles."""
        from_date = (datetime.utcnow() - timedelta(hours=hours_back)).isoformat()

        resp = requests.get(
            f"{self.base_url}/everything",
            params={
                "q": query,
                "from": from_date,
                "sortBy": "relevancy",
                "apiKey": self.api_key
            },
            timeout=10
        )

        if resp.status_code == 200:
            articles = resp.json().get("articles", [])
            return [
                {
                    "title": a["title"],
                    "source": a["source"]["name"],
                    "published": a["publishedAt"],
                    "description": a.get("description", "")
                }
                for a in articles[:5]
            ]
        return []
```

**Tasks**:
- [ ] Create `core/news_client.py`
- [ ] Implement query extraction from market questions
- [ ] Add caching (same query within 5 min = cached response)
- [ ] Handle rate limits gracefully

### 2.2 LLM Integration for Analysis

**Purpose**: Replace rule-based analysis with semantic understanding.

```python
# sovereign_hive/core/llm_analyst.py

import os
from anthropic import Anthropic

class LLMAnalyst:
    def __init__(self):
        self.client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model = "claude-3-haiku-20240307"  # Fast & cheap

    def analyze_opportunity(
        self,
        market_question: str,
        price: float,
        price_change: float,
        news_context: list
    ) -> dict:
        """Use LLM to analyze if opportunity is legitimate."""

        news_text = "\n".join([
            f"- {n['title']} ({n['source']})"
            for n in news_context
        ]) or "No recent news found."

        prompt = f"""You are a prediction market analyst. Analyze this opportunity:

MARKET: {market_question}
CURRENT PRICE: ${price:.3f}
24H CHANGE: {price_change:+.1f}%

RECENT NEWS:
{news_text}

Determine if this is:
1. VETTED - Safe to trade (price reflects reality or is undervalued)
2. REJECTED - Trap/noise (price is justified or manipulated)
3. PENDING - Need more information

Respond in JSON format:
{{"verdict": "VETTED|REJECTED|PENDING", "confidence": 0.0-1.0, "reasoning": "brief explanation"}}
"""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )

        # Parse JSON response
        import json
        try:
            return json.loads(response.content[0].text)
        except:
            return {"verdict": "PENDING", "confidence": 0.5, "reasoning": "Parse error"}
```

**Tasks**:
- [ ] Create `core/llm_analyst.py`
- [ ] Add fallback to rule-based if LLM fails
- [ ] Implement cost tracking (tokens used)
- [ ] Cache identical analyses

### 2.3 Cross-Verification System

**Problem**: Single news source could be wrong/satirical.

**Solution**: Require 2+ sources to agree before high-confidence verdict.

```python
def cross_verify(market_question: str, news_client: NewsClient) -> dict:
    """Verify with multiple sources."""

    # Extract key terms
    key_terms = extract_entities(market_question)  # "Japan", "PM", "Takaichi"

    # Search multiple angles
    sources = []
    for term in key_terms[:3]:
        articles = news_client.search(term)
        sources.extend(articles)

    # Dedupe by title similarity
    unique_sources = dedupe_articles(sources)

    # Count supporting vs contradicting
    # (This is where LLM helps interpret sentiment)

    return {
        "source_count": len(unique_sources),
        "sources": unique_sources,
        "cross_verified": len(unique_sources) >= 2
    }
```

**Tasks**:
- [ ] Implement entity extraction from market questions
- [ ] Add source diversity scoring
- [ ] Create "cross_verified" flag in blackboard
- [ ] Beta only gives 95%+ confidence if cross-verified

### 2.4 Confidence Score Calibration

**Purpose**: Map internal confidence to actual win rate.

```
Confidence Score Tiers:
├── 0.95-1.00: ARBITRAGE (near-certain, price > $0.98)
├── 0.80-0.95: HIGH (news-confirmed, cross-verified)
├── 0.60-0.80: MEDIUM (single source, plausible)
├── 0.40-0.60: LOW (conflicting signals)
└── 0.00-0.40: REJECT (likely trap)
```

**Tasks**:
- [ ] Implement confidence calibration in Beta
- [ ] Track predicted vs actual outcomes
- [ ] Adjust confidence weights based on history

### Phase 2 Deliverables

| Deliverable | Success Criteria |
|-------------|------------------|
| News Integration | 90% of markets have relevant news |
| LLM Analysis | Responses in < 3 seconds |
| Cross-Verification | Reduce false positives by 50% |

---

## Phase 3: Execution Engine (Week 5-6)

### Goal
Deploy to AWS with production-grade execution and risk controls.

### 3.1 Sniper Order Optimization

**Current**: Simple limit order at bid.

**Improved**: Smart order routing based on urgency.

```python
# sovereign_hive/core/order_router.py

class OrderRouter:
    def __init__(self, client):
        self.client = client

    def route_order(
        self,
        token_id: str,
        side: str,
        size: float,
        urgency: str  # "LOW", "MEDIUM", "HIGH"
    ) -> dict:
        """Route order based on urgency level."""

        book = self.client.get_order_book(token_id)
        best_bid = float(book.bids[0].price) if book.bids else 0
        best_ask = float(book.asks[0].price) if book.asks else 1
        spread = best_ask - best_bid

        if urgency == "HIGH":
            # Taker: Hit the ask immediately
            price = best_ask
            order_type = "IOC"  # Immediate or Cancel

        elif urgency == "MEDIUM":
            # Aggressive maker: Join ask minus 1 tick
            price = round(best_ask - 0.001, 3)
            order_type = "GTC"  # Good Till Cancel

        else:  # LOW
            # Passive maker: Join bid
            price = best_bid
            order_type = "GTC"

        return self.client.create_and_post_order(
            OrderArgs(
                price=price,
                size=size,
                side=side,
                token_id=token_id
            )
        )
```

**Tasks**:
- [ ] Create `core/order_router.py`
- [ ] Implement urgency classification (ARBITRAGE=HIGH, DIP=LOW)
- [ ] Add order status tracking
- [ ] Implement partial fill handling

### 3.2 The Kill Switch

**Purpose**: Automatic shutdown if things go wrong.

```python
# sovereign_hive/core/kill_switch.py

import os
from pathlib import Path

class KillSwitch:
    def __init__(self, blackboard):
        self.blackboard = blackboard
        self.max_drawdown_pct = 20.0
        self.max_single_loss = 10.0
        self.daily_loss_limit = 25.0

    def check_and_kill(self, current_pnl: float, daily_pnl: float) -> bool:
        """Check if we should halt trading."""

        reasons = []

        if current_pnl < -self.max_drawdown_pct:
            reasons.append(f"Max drawdown exceeded: {current_pnl:.1f}%")

        if daily_pnl < -self.daily_loss_limit:
            reasons.append(f"Daily loss limit hit: ${daily_pnl:.2f}")

        if reasons:
            self._execute_kill(reasons)
            return True

        return False

    def _execute_kill(self, reasons: list):
        """Emergency shutdown procedure."""

        # 1. Set blackboard to HALTED
        self.blackboard.update("risk_state", "HALTED")
        self.blackboard.update("halt_reasons", reasons)

        # 2. Cancel all open orders
        # (Gamma will read HALTED state and cancel)

        # 3. Revoke API credentials (rotate keys)
        # This is the nuclear option - requires manual re-auth

        # 4. Send alert
        self._send_alert(f"🚨 KILL SWITCH ACTIVATED\n" + "\n".join(reasons))

    def _send_alert(self, message: str):
        """Send Discord/Telegram alert."""
        webhook_url = os.getenv("ALERT_WEBHOOK_URL")
        if webhook_url:
            import requests
            requests.post(webhook_url, json={"content": message})
```

**Tasks**:
- [ ] Create `core/kill_switch.py`
- [ ] Integrate with Omega Guardian
- [ ] Add Discord/Telegram alerting
- [ ] Implement manual override (resume command)

### 3.3 Vulture Logic Enhancement

**Purpose**: Maximize arbitrage capture rate.

```python
def vulture_scan(markets: list) -> list:
    """Find near-certain outcomes for arbitrage."""

    vultures = []

    for m in markets:
        best_ask = float(m.get("bestAsk", 0))
        spread_pct = float(m.get("spread", 1)) * 100
        volume = float(m.get("volume24hr", 0))

        # Vulture criteria
        if best_ask >= 0.98 and best_ask < 0.999:
            # Calculate expected profit
            profit_per_share = 1.0 - best_ask
            fee_estimate = best_ask * 0.002  # 0.2% taker fee
            net_profit = profit_per_share - fee_estimate

            if net_profit > 0 and spread_pct < 1.0:
                vultures.append({
                    "condition_id": m["conditionId"],
                    "question": m["question"],
                    "price": best_ask,
                    "net_profit_pct": net_profit / best_ask * 100,
                    "urgency": "HIGH",
                    "strategy": "VULTURE"
                })

    # Sort by profit potential
    vultures.sort(key=lambda x: x["net_profit_pct"], reverse=True)
    return vultures
```

**Tasks**:
- [ ] Enhance Alpha Scout with vulture_scan
- [ ] Calculate net profit after fees
- [ ] Prioritize vultures over other strategies
- [ ] Track vulture success rate

### 3.4 AWS Deployment

**Architecture**:

```
┌─────────────────────────────────────────────────────┐
│                    AWS EC2 (t3.small)               │
├─────────────────────────────────────────────────────┤
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │
│  │  ALPHA   │ │   BETA   │ │  GAMMA   │ │ OMEGA  │ │
│  │ (Screen) │ │ (Screen) │ │ (Screen) │ │(Screen)│ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └───┬────┘ │
│       │            │            │            │      │
│       └────────────┼────────────┼────────────┘      │
│                    ▼                                 │
│            ┌──────────────┐                         │
│            │  blackboard  │                         │
│            │    .json     │                         │
│            └──────────────┘                         │
│                    │                                 │
│                    ▼                                 │
│            ┌──────────────┐                         │
│            │   CloudWatch │ ──▶ Alerts              │
│            │    Metrics   │                         │
│            └──────────────┘                         │
└─────────────────────────────────────────────────────┘
```

**Deployment Script**:

```bash
#!/bin/bash
# deploy_hive.sh

REMOTE="ec2-user@<IP>"
KEY="path/to/key.pem"

# Sync code
rsync -avz -e "ssh -i $KEY" \
  --exclude '.git' \
  --exclude 'logs/*' \
  --exclude '__pycache__' \
  sovereign_hive/ $REMOTE:/app/sovereign_hive/

# Start agents in screen sessions
ssh -i $KEY $REMOTE << 'EOF'
cd /app/sovereign_hive

# Kill existing
pkill -f "alpha_scout.py" || true
pkill -f "beta_analyst.py" || true
pkill -f "gamma_sniper.py" || true
pkill -f "omega_guardian.py" || true

# Start fresh
screen -dmS alpha python agents/alpha_scout.py
screen -dmS beta python agents/beta_analyst.py
screen -dmS gamma python agents/gamma_sniper.py --live
screen -dmS omega python agents/omega_guardian.py

echo "Hive deployed. Use 'screen -ls' to see sessions."
EOF
```

**Tasks**:
- [ ] Create `deploy_hive.sh`
- [ ] Set up CloudWatch metrics
- [ ] Configure auto-restart on crash
- [ ] Implement health check endpoint

### Phase 3 Deliverables

| Deliverable | Success Criteria |
|-------------|------------------|
| Order Router | 95% fill rate on vulture plays |
| Kill Switch | Triggers within 1 second of threshold |
| AWS Deploy | 99.9% uptime over 1 week |

---

## Phase 4: Self-Optimization (Week 7-8)

### Goal
The system learns from its own performance.

### 4.1 Post-Mortem Analysis

**Purpose**: After every resolved trade, evaluate if the analysis was correct.

```python
# sovereign_hive/core/post_mortem.py

class PostMortem:
    def __init__(self, blackboard):
        self.blackboard = blackboard
        self.history_path = Path("data/trade_history.json")

    def analyze_resolved(self, position: dict, resolution: str) -> dict:
        """Analyze a resolved position."""

        entry_price = position["entry_price"]
        exit_value = 1.0 if resolution == "YES" else 0.0
        pnl = (exit_value - entry_price) * position["size"]
        pnl_pct = (exit_value - entry_price) / entry_price * 100

        # Compare to analyst prediction
        analyst_confidence = position.get("analyst_confidence", 0.5)
        was_correct = (resolution == "YES" and entry_price < 0.5) or \
                      (resolution == "NO" and entry_price > 0.5)

        result = {
            "condition_id": position["condition_id"],
            "question": position["question"],
            "entry_price": entry_price,
            "resolution": resolution,
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "analyst_confidence": analyst_confidence,
            "was_correct": was_correct,
            "resolved_at": datetime.now(timezone.utc).isoformat()
        }

        # Save to history
        self._save_to_history(result)

        # Update calibration
        self._update_calibration(analyst_confidence, was_correct)

        return result

    def _update_calibration(self, confidence: float, correct: bool):
        """Update confidence calibration based on outcome."""
        # Track: when we say 90% confident, are we right 90% of the time?
        # Adjust future confidence scores accordingly
        pass

    def get_performance_stats(self) -> dict:
        """Calculate overall performance metrics."""
        history = self._load_history()

        total_trades = len(history)
        wins = sum(1 for h in history if h["pnl"] > 0)
        total_pnl = sum(h["pnl"] for h in history)

        return {
            "total_trades": total_trades,
            "win_rate": wins / total_trades if total_trades > 0 else 0,
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(total_pnl / total_trades, 2) if total_trades > 0 else 0
        }
```

**Tasks**:
- [ ] Create `core/post_mortem.py`
- [ ] Track all resolved trades
- [ ] Calculate win rate by strategy type
- [ ] Generate weekly performance reports

### 4.2 Strategy Performance Tracking

**Purpose**: Know which strategies actually work.

```
Strategy Performance Dashboard:

VULTURE (Arbitrage)
├── Trades: 47
├── Win Rate: 100%
├── Avg Profit: +0.4%
└── Total PnL: +$18.80

DIP_BUY
├── Trades: 12
├── Win Rate: 58%
├── Avg Profit: +12.3%
└── Total PnL: +$44.16

VOLUME_SPIKE
├── Trades: 8
├── Win Rate: 37%
├── Avg Profit: -5.2%
└── Total PnL: -$12.48
```

**Tasks**:
- [ ] Create strategy performance tracker
- [ ] Disable strategies with < 50% win rate
- [ ] Auto-adjust position sizing based on strategy confidence

### 4.3 Micro-Agent Specialization

**Purpose**: Spawn specialized agents for specific niches.

```python
# Future: Micro-agent factory

class MicroAgentFactory:
    def spawn_specialist(self, niche: str) -> Agent:
        """Create a specialist agent for a niche."""

        if niche == "esports":
            return ESportsScout(
                keywords=["LoL", "CS2", "Dota", "Valorant"],
                api_sources=["liquipedia", "hltv"],
                min_confidence=0.80
            )

        elif niche == "politics":
            return PoliticsScout(
                keywords=["election", "president", "vote"],
                api_sources=["politico", "538"],
                min_confidence=0.70
            )

        elif niche == "crypto":
            return CryptoScout(
                keywords=["bitcoin", "ethereum", "SEC"],
                api_sources=["coindesk", "decrypt"],
                min_confidence=0.60  # Lower due to volatility
            )
```

**Tasks**:
- [ ] Define niche categories
- [ ] Create specialized news sources per niche
- [ ] Implement A/B testing between generalist and specialist
- [ ] Track niche-specific performance

### Phase 4 Deliverables

| Deliverable | Success Criteria |
|-------------|------------------|
| Post-Mortem | 100% of trades analyzed within 24h of resolution |
| Strategy Tracking | Dashboard shows win rate by strategy |
| Confidence Calibration | Predicted confidence within 10% of actual |

---

## Risk Mitigation Matrix

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| File lock corruption | HIGH | MEDIUM | Atomic operations + backups |
| Latency (miss arb) | MEDIUM | HIGH | Parallel execution + urgency routing |
| LLM hallucination | HIGH | LOW | Cross-verification + confidence caps |
| API rate limits | MEDIUM | MEDIUM | Caching + exponential backoff |
| Flash crash | HIGH | LOW | Kill switch + position limits |
| News source wrong | MEDIUM | MEDIUM | 2+ source requirement |

---

## Budget Estimate

| Item | Monthly Cost |
|------|--------------|
| AWS EC2 (t3.small) | $15 |
| Redis (ElastiCache) | $0 (local) / $15 (prod) |
| NewsAPI (Basic) | $0 (dev) / $50 (prod) |
| Claude API (Haiku) | ~$5 (estimated 10k calls) |
| Polygon RPC | $0 (public) / $50 (dedicated) |
| **Total (Dev)** | **$20** |
| **Total (Prod)** | **$135** |

---

## Timeline Summary

| Phase | Duration | Key Milestone |
|-------|----------|---------------|
| **Phase 0** | **Week 0-1** | **Async architecture, Redis, WebSocket** |
| Phase 1 | Week 1-2 | Cold storage hardened, mock testing works |
| Phase 2 | Week 3-4 | LLM analysis live, cross-verification |
| Phase 3 | Week 5-6 | AWS deployed (us-east-1), kill switch active |
| Phase 4 | Week 7-8 | Self-optimization running |

---

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Win Rate | > 60% | Trades with positive PnL |
| Vulture Success | > 95% | Arbitrage plays that settle in profit |
| False Positive Rate | < 20% | Rejected trades that would have won |
| Uptime | > 99% | Bot running and responsive |
| Latency (Alpha) | < 5s | Time from API call to blackboard write |
| Latency (Full Cycle) | < 30s | Alpha → Beta → Gamma complete |

---

## Next Immediate Actions

1. **Today**: Review and approve this roadmap
2. **Tomorrow**: Begin Phase 1.1 (Blackboard hardening)
3. **This Week**: Complete Phase 1 foundation
4. **Next Week**: Start Phase 2 (semantic awareness)

---

*Document Version: 1.0*
*Last Updated: February 8, 2026*
*Author: Sovereign Hive Architecture Team*
