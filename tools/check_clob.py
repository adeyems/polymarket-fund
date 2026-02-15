
import sys
import py_clob_client
print(f"Location: {py_clob_client.__file__}")
from py_clob_client.client import ClobClient
print(f"Client: {ClobClient}")
print(f"Has get_positions: {hasattr(ClobClient, 'get_positions')}")
