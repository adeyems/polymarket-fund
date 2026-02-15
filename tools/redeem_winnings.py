#!/usr/bin/env python3
"""
Redeem winning Polymarket positions on-chain.
"""
import os
import sys
from dotenv import load_dotenv
from web3 import Web3

load_dotenv()

# Config
WALLET = '0xb22028EA4E841CA321eb917C706C931a94b564AB'
PRIVATE_KEY = os.getenv('POLYMARKET_PRIVATE_KEY')

# Contracts
CONDITIONAL_TOKENS = '0x4D97DCd97eC945f40cF65F87097ACe5EA0476045'
USDC_E = '0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174'

# Winning positions to redeem
POSITIONS = [
    {
        'name': 'Gov Shutdown 4+ Days - YES',
        'conditionId': '0x90d15ca9a35a0cef4d67b2e4ec79a77dc98621536af438bccc6f016a59eb0f39',
        'tokenId': 65725371253697761962782192914659497151911283155170584494749509449973630951716,
        'outcomeIndex': 0,  # YES = 0
    },
    {
        'name': 'Netflix Warner Bros - YES', 
        'conditionId': '0x3afaa6c9c9487ab0eff39abb4e93be2647afcb4069e1ce8e6af5cca37de14438',
        'tokenId': 9150172187999749270028515736853734790361197935118480975845332252523455886710,
        'outcomeIndex': 0,  # YES = 0
    },
]

# Conditional Tokens ABI (minimal for redemption)
CT_ABI = [
    {
        'constant': True,
        'inputs': [{'name': 'account', 'type': 'address'}, {'name': 'id', 'type': 'uint256'}],
        'name': 'balanceOf',
        'outputs': [{'name': '', 'type': 'uint256'}],
        'type': 'function'
    },
    {
        'constant': False,
        'inputs': [
            {'name': 'collateralToken', 'type': 'address'},
            {'name': 'parentCollectionId', 'type': 'bytes32'},
            {'name': 'conditionId', 'type': 'bytes32'},
            {'name': 'indexSets', 'type': 'uint256[]'}
        ],
        'name': 'redeemPositions',
        'outputs': [],
        'type': 'function'
    },
    {
        'constant': True,
        'inputs': [{'name': 'conditionId', 'type': 'bytes32'}],
        'name': 'payoutDenominator',
        'outputs': [{'name': '', 'type': 'uint256'}],
        'type': 'function'
    },
]

def main():
    print('=' * 60)
    print('POLYMARKET WINNINGS REDEMPTION')
    print('=' * 60)
    
    # Connect
    w3 = Web3(Web3.HTTPProvider('https://polygon-bor-rpc.publicnode.com'))
    if not w3.is_connected():
        print('ERROR: Cannot connect to Polygon RPC')
        sys.exit(1)
    
    print(f'Connected to Polygon (Chain ID: {w3.eth.chain_id})')
    
    account = w3.eth.account.from_key(PRIVATE_KEY)
    print(f'Wallet: {account.address}')
    
    # Check POL balance for gas
    pol_balance = w3.eth.get_balance(account.address)
    print(f'POL Balance: {pol_balance/1e18:.4f}')
    
    if pol_balance < w3.to_wei('0.1', 'ether'):
        print('WARNING: Low POL balance for gas!')
    
    # Contract
    ct = w3.eth.contract(
        address=Web3.to_checksum_address(CONDITIONAL_TOKENS),
        abi=CT_ABI
    )
    
    # Check USDC.e balance before
    usdc_abi = [{'constant':True,'inputs':[{'name':'account','type':'address'}],'name':'balanceOf','outputs':[{'name':'','type':'uint256'}],'type':'function'}]
    usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC_E), abi=usdc_abi)
    usdc_before = usdc.functions.balanceOf(account.address).call()
    print(f'\nUSDC.e Before: ${usdc_before/1e6:.2f}')
    
    # Process each position
    for pos in POSITIONS:
        print(f'\n--- {pos["name"]} ---')
        
        # Check token balance
        balance = ct.functions.balanceOf(account.address, pos['tokenId']).call()
        print(f'Token Balance: {balance/1e6:.2f} shares')
        
        if balance == 0:
            print('No tokens to redeem, skipping...')
            continue
        
        # Check if condition is resolved (payoutDenominator > 0)
        try:
            payout_denom = ct.functions.payoutDenominator(pos['conditionId']).call()
            print(f'Payout Denominator: {payout_denom}')
            if payout_denom == 0:
                print('Market not resolved yet, skipping...')
                continue
        except Exception as e:
            print(f'Could not check payout: {e}')
        
        # Build redemption transaction
        # indexSets: [1] for YES (outcome 0), [2] for NO (outcome 1)
        # For binary markets: YES=1 (2^0), NO=2 (2^1)
        index_set = 1 << pos['outcomeIndex']  # 1 for YES, 2 for NO
        
        print(f'Redeeming with indexSet: [{index_set}]')
        
        try:
            # Get current gas price
            gas_price = w3.eth.gas_price
            boosted_gas = int(gas_price * 1.5)
            print(f'Gas Price: {boosted_gas/1e9:.2f} gwei')
            
            # Build transaction
            nonce = w3.eth.get_transaction_count(account.address, 'pending')
            
            txn = ct.functions.redeemPositions(
                Web3.to_checksum_address(USDC_E),  # collateralToken
                bytes(32),  # parentCollectionId (0x0 for root)
                pos['conditionId'],  # conditionId
                [index_set]  # indexSets
            ).build_transaction({
                'from': account.address,
                'nonce': nonce,
                'gas': 200000,
                'gasPrice': boosted_gas,
                'chainId': 137
            })
            
            # Sign and send
            signed = account.sign_transaction(txn)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            print(f'TX Sent: {tx_hash.hex()}')
            
            # Wait for confirmation
            print('Waiting for confirmation...')
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            
            if receipt['status'] == 1:
                print(f'✅ SUCCESS! Block: {receipt["blockNumber"]}')
            else:
                print(f'❌ FAILED! Check transaction on Polygonscan')
                
        except Exception as e:
            print(f'ERROR: {e}')
    
    # Check USDC.e balance after
    usdc_after = usdc.functions.balanceOf(account.address).call()
    print(f'\n{"=" * 60}')
    print(f'USDC.e Before: ${usdc_before/1e6:.2f}')
    print(f'USDC.e After:  ${usdc_after/1e6:.2f}')
    print(f'Redeemed:      ${(usdc_after - usdc_before)/1e6:.2f}')
    print('=' * 60)

if __name__ == '__main__':
    main()
