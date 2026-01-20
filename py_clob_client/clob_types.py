from pydantic import BaseModel

class ApiCreds:
    def __init__(self, api_key, api_secret, api_passphrase):
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_passphrase = api_passphrase

class OrderArgs(BaseModel):
    price: float
    size: float
    side: str
    token_id: str
    expiration: str = "0"
    fee_rate_bps: int = 0
