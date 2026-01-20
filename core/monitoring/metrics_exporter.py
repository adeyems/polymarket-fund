# =============================================================================
# QuesQuant HFT - CloudWatch Metrics Exporter
# =============================================================================
"""
Professional-grade metrics export to AWS CloudWatch.
Pushes trading metrics every 60 seconds for SRE monitoring.
"""

import boto3
import threading
import time
import logging
from dataclasses import dataclass
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class TradingMetrics:
    """Container for trading metrics snapshot."""
    tick_to_trade_latency_ms: float = 0.0
    pnl_session: float = 0.0
    inventory_imbalance: int = 0
    order_count: int = 0
    fill_rate: float = 0.0
    heartbeat: int = 1  # 1 = alive, 0 = dead


class MetricsExporter:
    """
    Exports trading metrics to AWS CloudWatch.
    
    Usage:
        exporter = MetricsExporter(namespace="QuesQuant/HFT")
        exporter.start()
        
        # Update metrics from trading loop
        exporter.update(
            tick_to_trade_latency_ms=150.5,
            pnl_session=1250.00,
            inventory_imbalance=15
        )
    """
    
    NAMESPACE = "QuesQuant/HFT"
    PUSH_INTERVAL_SECONDS = 60
    
    def __init__(
        self,
        namespace: str = None,
        region: str = "us-east-1",
        environment: str = "prod"
    ):
        """
        Initialize the metrics exporter.
        
        Args:
            namespace: CloudWatch namespace (default: QuesQuant/HFT)
            region: AWS region
            environment: Environment tag (prod, staging, dev)
        """
        self.namespace = namespace or self.NAMESPACE
        self.region = region
        self.environment = environment
        
        # Thread-safe metrics storage
        self._metrics = TradingMetrics()
        self._lock = threading.Lock()
        
        # Background thread
        self._thread: Optional[threading.Thread] = None
        self._running = False
        
        # CloudWatch client (lazy init for IAM role)
        self._cloudwatch: Optional[boto3.client] = None
        
        logger.info(f"[METRICS] Initialized exporter: {self.namespace}")
    
    @property
    def cloudwatch(self):
        """Lazy-init CloudWatch client."""
        if self._cloudwatch is None:
            self._cloudwatch = boto3.client(
                'cloudwatch',
                region_name=self.region
            )
        return self._cloudwatch
    
    def update(
        self,
        tick_to_trade_latency_ms: float = None,
        pnl_session: float = None,
        inventory_imbalance: int = None,
        order_count: int = None,
        fill_rate: float = None
    ):
        """
        Update metrics (thread-safe).
        Call this from the trading loop.
        """
        with self._lock:
            if tick_to_trade_latency_ms is not None:
                self._metrics.tick_to_trade_latency_ms = tick_to_trade_latency_ms
            if pnl_session is not None:
                self._metrics.pnl_session = pnl_session
            if inventory_imbalance is not None:
                self._metrics.inventory_imbalance = inventory_imbalance
            if order_count is not None:
                self._metrics.order_count = order_count
            if fill_rate is not None:
                self._metrics.fill_rate = fill_rate
            # Always update heartbeat
            self._metrics.heartbeat = 1
    
    def push_heartbeat(self):
        """Dedicated method to pulse the heartbeat and ensure the background loop stays alive."""
        with self._lock:
            self._metrics.heartbeat = 1
    
    def _get_snapshot(self) -> TradingMetrics:
        """Get a thread-safe copy of current metrics."""
        with self._lock:
            return TradingMetrics(
                tick_to_trade_latency_ms=self._metrics.tick_to_trade_latency_ms,
                pnl_session=self._metrics.pnl_session,
                inventory_imbalance=self._metrics.inventory_imbalance,
                order_count=self._metrics.order_count,
                fill_rate=self._metrics.fill_rate,
                heartbeat=self._metrics.heartbeat
            )
    
    def _push_metrics(self):
        """Push current metrics to CloudWatch."""
        snapshot = self._get_snapshot()
        
        dimensions = [
            {'Name': 'Environment', 'Value': self.environment}
        ]
        
        metric_data = [
            {
                'MetricName': 'TickToTradeLatency',
                'Value': snapshot.tick_to_trade_latency_ms,
                'Unit': 'Milliseconds',
                'Dimensions': dimensions
            },
            {
                'MetricName': 'PnL_Session',
                'Value': snapshot.pnl_session,
                'Unit': 'None',
                'Dimensions': dimensions
            },
            {
                'MetricName': 'InventoryImbalance',
                'Value': float(snapshot.inventory_imbalance),
                'Unit': 'Count',
                'Dimensions': dimensions
            },
            {
                'MetricName': 'OrderCount',
                'Value': float(snapshot.order_count),
                'Unit': 'Count',
                'Dimensions': dimensions
            },
            {
                'MetricName': 'FillRate',
                'Value': snapshot.fill_rate * 100,  # Percentage
                'Unit': 'Percent',
                'Dimensions': dimensions
            },
            {
                'MetricName': 'Heartbeat',
                'Value': float(snapshot.heartbeat),
                'Unit': 'Count',
                'Dimensions': dimensions
            }
        ]
        
        try:
            self.cloudwatch.put_metric_data(
                Namespace=self.namespace,
                MetricData=metric_data
            )
            logger.debug(f"[METRICS] Pushed {len(metric_data)} metrics to CloudWatch")
        except Exception as e:
            logger.error(f"[METRICS] Failed to push: {e}")
    
    def _run_loop(self):
        """Background loop that pushes metrics every PUSH_INTERVAL_SECONDS."""
        logger.info(f"[METRICS] Background exporter started (interval: {self.PUSH_INTERVAL_SECONDS}s)")
        
        while self._running:
            try:
                self._push_metrics()
            except Exception as e:
                logger.error(f"[METRICS] Loop error: {e}")
            
            # Sleep in chunks to allow quick shutdown
            for _ in range(self.PUSH_INTERVAL_SECONDS):
                if not self._running:
                    break
                time.sleep(1)
        
        logger.info("[METRICS] Background exporter stopped")
    
    def start(self):
        """Start the background metrics export thread."""
        if self._running:
            logger.warning("[METRICS] Exporter already running")
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("[METRICS] Exporter started")
    
    def stop(self):
        """Stop the background metrics export thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("[METRICS] Exporter stopped")
    
    def push_now(self):
        """Force an immediate push (for testing or shutdown)."""
        self._push_metrics()


# -----------------------------------------------------------------------------
# Convenience Function for Market Maker Integration
# -----------------------------------------------------------------------------
_global_exporter: Optional[MetricsExporter] = None


def get_metrics_exporter() -> MetricsExporter:
    """Get or create the global metrics exporter."""
    global _global_exporter
    if _global_exporter is None:
        _global_exporter = MetricsExporter()
    return _global_exporter


def export_tick_metrics(latency_ms: float, pnl: float, inventory: int):
    """Quick helper to export metrics from trading loop."""
    exporter = get_metrics_exporter()
    exporter.update(
        tick_to_trade_latency_ms=latency_ms,
        pnl_session=pnl,
        inventory_imbalance=inventory
    )
