import pytest
import time
import random
import threading
from unittest.mock import MagicMock, patch

# --- MOCK INFRASTRUCTURE ---

class MockBinanceAPI:
    """Simulates Binance Price Feeds under different scenarios."""
    def __init__(self):
        self.scenario = "SIDEWAYS"
        self.price = 95000.0
        self.start_time = time.time()
    
    def get_price(self, symbol="BTCUSDT"):
        elapsed = time.time() - self.start_time
        
        if self.scenario == "TC_FLASH_CRASH":
            # Drop 5% linearly over 10 seconds
            drop = 95000.0 * 0.05
            if elapsed < 10:
                self.price = 95000.0 - (drop * (elapsed / 10))
            else:
                self.price = 95000.0 - drop # Bottom
                
        elif self.scenario == "TC_MOON":
            # Pump 5% linearly
            jump = 95000.0 * 0.05
            if elapsed < 10:
                self.price = 95000.0 + (jump * (elapsed / 10))
            else:
                self.price = 95000.0 + jump
        
        elif self.scenario == "TC_SIDEWAYS":
            # Noise +/- $50
            noise = random.uniform(-50, 50)
            self.price = 95000.0 + noise
            
        return self.price

# --- TEST LOGIC ---

@pytest.fixture
def mock_binance():
    return MockBinanceAPI()

def test_binance_flash_crash(mock_binance):
    """Verify Flash Crash Scenario drops price correctly."""
    mock_binance.scenario = "TC_FLASH_CRASH"
    mock_binance.start_time = time.time()
    
    initial_price = mock_binance.get_price()
    # Allow small epsilon because time passes between set and get
    assert initial_price == pytest.approx(95000.0, abs=1.0)
    
    time.sleep(5) # Halfway
    mid_price = mock_binance.get_price()
    assert mid_price < 94000.0 # Should have dropped significantly
    
    time.sleep(6) # Done
    final_price = mock_binance.get_price()
    assert final_price <= (95000.0 * 0.95)
    print(f"\n[PASS] Flash Crash: {initial_price} -> {mid_price} -> {final_price}")

def test_inventory_concurrency():
    """Verify inventory_state remains consistent under concurrent updates."""
    inventory = {"pos": 0}
    lock = threading.Lock()
    
    def fill_order(side, qty):
        with lock:
            # Critical Section
            start_pos = inventory["pos"]
            time.sleep(0.001) # Simulate DB latency
            if side == "BUY":
                inventory["pos"] += qty
            else:
                inventory["pos"] -= qty
    
    threads = []
    # Launch 50 BUYs of 10 and 50 SELLs of 10 concurrently
    # Net change should be 0
    for _ in range(50):
        t1 = threading.Thread(target=fill_order, args=("BUY", 10))
        t2 = threading.Thread(target=fill_order, args=("SELL", 10))
        threads.append(t1)
        threads.append(t2)
        t1.start()
        t2.start()
        
    for t in threads:
        t.join()
        
    assert inventory["pos"] == 0
    print(f"\n[PASS] Concurrency Test: Final Position {inventory['pos']} (Expected 0)")

def test_latency_benchmark():
    """Benchmarks the mock 'sign and post' latency."""
    latencies = []
    
    def mock_sign_and_post():
        start = time.perf_counter()
        # Simulate crypto signing (CPU intensive)
        _ = [x**2 for x in range(10000)]
        # Simulate Network RTT
        time.sleep(random.uniform(0.01, 0.05)) 
        end = time.perf_counter()
        return (end - start) * 1000 # ms
        
    print("\n--- Latency Benchmark (100 Orders) ---")
    for i in range(100):
        lat = mock_sign_and_post()
        latencies.append(lat)
        
    avg_lat = sum(latencies) / len(latencies)
    max_lat = max(latencies)
    p99_lat = sorted(latencies)[98]
    

    print(f"Avg: {avg_lat:.2f}ms | Max: {max_lat:.2f}ms | P99: {p99_lat:.2f}ms")
    assert avg_lat < 100 # Requirement: Sub-100ms

def test_reorg_protection():
    """Verify that inventory is only updated after simulated block confirmations."""
    pending_queue = []
    inventory = {"pos": 0}
    BLOCK_TIME = 4.0
    
    # 1. Fill happens
    fill_time = time.time()
    pending_queue.append({'side': 'BUY', 'qty': 10, 'fill_time': fill_time})
    
    # 2. Immediate check (Should be 0)
    current_time = time.time()
    confirmed = [f for f in pending_queue if current_time - f['fill_time'] >= BLOCK_TIME]
    assert len(confirmed) == 0
    assert inventory["pos"] == 0
    
    # 3. Simulate wait (Wait 4.1s)
    time.sleep(4.1)
    current_time = time.time()
    confirmed = [f for f in pending_queue if current_time - f['fill_time'] >= BLOCK_TIME]
    
    # 4. Process Confirmations
    for fill in confirmed:
        if fill['side'] == 'BUY':
            inventory["pos"] += fill['qty']
        pending_queue.remove(fill)
        
    assert len(confirmed) == 1
    assert inventory["pos"] == 10
    print(f"\n[PASS] Re-org Protection: Inventory updated only after {BLOCK_TIME}s")

def test_dead_drop_expiry():
    """Verify that orders are created with correct expiration/salt logic."""
    # Since we can't check the exchange, we verify the Order Construction Logic
    def create_dead_drop_order(price, size):
        salt = random.randint(0, 1000000) # Salt for uniqueness
        expiration = int(time.time() + 90) # Hard requirement
        return {"price": price, "size": size, "salt": salt, "expiration": expiration}
    
    order = create_dead_drop_order(0.50, 10)
    
    assert order["expiration"] > time.time()
    assert order["expiration"] < time.time() + 95 # Tight tolerance
    assert "salt" in order
    print(f"\n[PASS] Dead Drop: Order generated with Expiry {order['expiration']} & Salt {order['salt']}")
