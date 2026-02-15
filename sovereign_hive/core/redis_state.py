#!/usr/bin/env python3
"""
REDIS STATE - In-Memory Hot Storage with Persistence
=====================================================
Real-time state management with JSON file persistence for recovery.
"""

import json
from pathlib import Path
from typing import Optional, List
from datetime import datetime, timezone

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

# Default persistence file
DEFAULT_BLACKBOARD = Path(__file__).parent.parent / "blackboard.json"


class RedisState:
    """
    In-memory state for real-time trading.
    Falls back to dict if Redis unavailable.
    """

    # Key prefixes
    OPPORTUNITIES = "hive:opp"
    VETTED = "hive:vetted"
    POSITIONS = "hive:pos"
    SENTIMENT = "hive:sent"
    RISK_STATE = "hive:risk"
    METRICS = "hive:metrics"

    def __init__(self, host='localhost', port=6379, fallback=True, persistence_file: Path = None):
        self.fallback = fallback
        self._memory = {}  # Fallback dict
        self.client = None
        self.connected = False
        self._persistence_file = persistence_file or DEFAULT_BLACKBOARD
        self._auto_persist = True

        # Load persisted state on startup
        self._load_from_disk()

        if not REDIS_AVAILABLE:
            if fallback:
                print("[REDIS] Using in-memory fallback (redis package not installed)")
            else:
                raise ConnectionError("Redis package not installed")
            return

        try:
            self.client = redis.Redis(
                host=host, port=port,
                decode_responses=True,
                socket_connect_timeout=2
            )
            self.client.ping()
            self.connected = True
            print("[REDIS] Connected to Redis")
        except:
            self.client = None
            self.connected = False
            if fallback:
                print("[REDIS] Using in-memory fallback (no Redis server)")
            else:
                raise ConnectionError("Redis not available")

    # === GENERIC OPS ===
    def _set(self, key: str, value: str, ttl: int = None):
        if self.connected:
            if ttl:
                self.client.setex(key, ttl, value)
            else:
                self.client.set(key, value)
        else:
            self._memory[key] = value

    def _get(self, key: str) -> Optional[str]:
        if self.connected:
            return self.client.get(key)
        return self._memory.get(key)

    def _keys(self, pattern: str) -> List[str]:
        if self.connected:
            return self.client.keys(pattern)
        return [k for k in self._memory.keys() if pattern.replace('*', '') in k]

    def _delete(self, key: str):
        if self.connected:
            self.client.delete(key)
        elif key in self._memory:
            del self._memory[key]

    # === OPPORTUNITIES ===
    def add_opportunity(self, opp: dict, ttl: int = 300):
        """Add opportunity (expires in 5 minutes by default)."""
        key = f"{self.OPPORTUNITIES}:{opp['condition_id']}"
        self._set(key, json.dumps(opp), ttl)

    def get_opportunities(self) -> List[dict]:
        """Get all active opportunities."""
        keys = self._keys(f"{self.OPPORTUNITIES}:*")
        opps = []
        for k in keys:
            data = self._get(k)
            if data:
                opps.append(json.loads(data))
        return opps

    def get_opportunity(self, condition_id: str) -> Optional[dict]:
        key = f"{self.OPPORTUNITIES}:{condition_id}"
        data = self._get(key)
        return json.loads(data) if data else None

    # === VETTED TRADES ===
    def add_vetted(self, trade: dict, ttl: int = 600):
        """Add vetted trade (expires in 10 minutes)."""
        key = f"{self.VETTED}:{trade['condition_id']}"
        self._set(key, json.dumps(trade), ttl)

    def get_vetted(self) -> List[dict]:
        keys = self._keys(f"{self.VETTED}:*")
        return [json.loads(self._get(k)) for k in keys if self._get(k)]

    def remove_vetted(self, condition_id: str):
        self._delete(f"{self.VETTED}:{condition_id}")

    # === POSITIONS ===
    def add_position(self, pos: dict) -> bool:
        """Add position atomically (returns False if already exists)."""
        key = f"{self.POSITIONS}:{pos['condition_id']}"
        if self.connected:
            added = bool(self.client.setnx(key, json.dumps(pos)))
        elif key in self._memory:
            return False
        else:
            self._memory[key] = json.dumps(pos)
            added = True

        if added and self._auto_persist:
            self.persist()
        return added

    def get_positions(self) -> List[dict]:
        keys = self._keys(f"{self.POSITIONS}:*")
        return [json.loads(self._get(k)) for k in keys if self._get(k)]

    def remove_position(self, condition_id: str):
        self._delete(f"{self.POSITIONS}:{condition_id}")
        if self._auto_persist:
            self.persist()

    # === SENTIMENT CACHE ===
    def set_sentiment(self, topic: str, sentiment: dict, ttl: int = 600):
        """Cache pre-digested sentiment."""
        key = f"{self.SENTIMENT}:{topic.lower().replace(' ', '_')}"
        self._set(key, json.dumps(sentiment), ttl)

    def get_sentiment(self, topic: str) -> Optional[dict]:
        """Instant sentiment lookup."""
        key = f"{self.SENTIMENT}:{topic.lower().replace(' ', '_')}"
        data = self._get(key)
        return json.loads(data) if data else None

    # === RISK STATE ===
    def set_risk_state(self, state: str):
        self._set(self.RISK_STATE, state)

    def get_risk_state(self) -> str:
        return self._get(self.RISK_STATE) or "HEALTHY"

    # === METRICS ===
    def incr_metric(self, name: str, amount: int = 1):
        key = f"{self.METRICS}:{name}"
        if self.connected:
            self.client.incrby(key, amount)
        else:
            self._memory[key] = self._memory.get(key, 0) + amount

    def get_metric(self, name: str) -> int:
        key = f"{self.METRICS}:{name}"
        val = self._get(key)
        return int(val) if val else 0

    # === PUBSUB (Event-Driven) ===
    def publish(self, channel: str, message: dict):
        """Publish event to channel."""
        if self.connected:
            self.client.publish(channel, json.dumps(message))

    def subscribe(self, channel: str):
        """Subscribe to channel (returns pubsub object)."""
        if self.connected:
            ps = self.client.pubsub()
            ps.subscribe(channel)
            return ps
        return None

    # === PERSISTENCE ===
    def _load_from_disk(self):
        """Load persisted state from JSON file on startup."""
        if not self._persistence_file.exists():
            print(f"[STATE] No persistence file found, starting fresh")
            return

        try:
            with open(self._persistence_file) as f:
                data = json.load(f)

            # Restore positions (critical - must survive restart)
            for pos in data.get("positions", []):
                key = f"{self.POSITIONS}:{pos['condition_id']}"
                self._memory[key] = json.dumps(pos)

            # Restore risk state
            if data.get("risk_state"):
                self._memory[self.RISK_STATE] = data["risk_state"]

            # Restore metrics
            for name, value in data.get("metrics", {}).items():
                self._memory[f"{self.METRICS}:{name}"] = value

            print(f"[STATE] Loaded {len(data.get('positions', []))} positions from disk")

        except Exception as e:
            print(f"[STATE] Error loading persistence file: {e}")

    def persist(self):
        """Save current state to JSON file."""
        try:
            data = {
                "positions": self.get_positions(),
                "vetted": self.get_vetted(),
                "risk_state": self.get_risk_state(),
                "metrics": self._get_all_metrics(),
                "last_updated": datetime.now(timezone.utc).isoformat()
            }

            # Atomic write (write to temp, then rename)
            temp_file = self._persistence_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)

            temp_file.rename(self._persistence_file)

        except Exception as e:
            print(f"[STATE] Persist error: {e}")

    def _get_all_metrics(self) -> dict:
        """Get all metrics as dict."""
        metrics = {}
        prefix = f"{self.METRICS}:"
        for key in self._memory:
            if key.startswith(prefix):
                name = key[len(prefix):]
                metrics[name] = self._memory[key]
        return metrics

    def update_position(self, condition_id: str, updates: dict):
        """Update an existing position."""
        key = f"{self.POSITIONS}:{condition_id}"
        data = self._get(key)
        if data:
            pos = json.loads(data)
            pos.update(updates)
            self._set(key, json.dumps(pos))
            if self._auto_persist:
                self.persist()
            return True
        return False


# Singleton instance
_state = None

def get_state() -> RedisState:
    global _state
    if _state is None:
        _state = RedisState()
    return _state
