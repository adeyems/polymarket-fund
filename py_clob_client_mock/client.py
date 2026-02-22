import asyncio
import time

class MockOrderBook:
    def __init__(self):
        # Create some fake bids/asks
        self.bids = [type('obj', (object,), {'price': 0.50, 'size': 100})]
        self.asks = [type('obj', (object,), {'price': 0.51, 'size': 100})]

class ClobClient:
    def __init__(self, host, key, chain_id, creds):
        self.host = host
        self.key = key
        self.chain_id = chain_id
        
    def get_address(self):
        return "0xMOCK_USER_ADDRESS"
        
    def get_collateral_address(self):
        return "0xMOCK_USDC_ADDRESS"
        
    def get_fee_rate_bps(self, token_id):
        return 0
        
    def get_order_book(self, token_id):
        # Simulate network latency
        time.sleep(0.1) 
        return MockOrderBook()
        
    def post_orders(self, orders):
        return {"status": "mock_success", "orders": len(orders)}
        
    def cancel_all(self):
        print("[MOCK CLOB] All orders cancelled.")
