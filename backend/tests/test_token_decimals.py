"""A token amount is only as right as the precision it is divided by.

USDT is 6 decimals on Ethereum. A record that arrived without its decimals
used to be read as 18, which shrank every such transfer by a factor of a
trillion without anything failing. These tests pin the fallback order:
the record's own figure, then the traced token's confirmed figure, then
drop the record -- never guess.
"""

from app.etherscan_client import Transaction, resolve_decimals
from app.nodereal_client import NoderealClient

USDT_ETH = "0xdac17f958d2ee523a2206206994597c13d831ec7"
SENDER = "0x" + "1" * 40
RECEIVER = "0x" + "2" * 40


def _tokentx(**overrides):
    raw = {
        "hash": "0xabc", "from": SENDER, "to": RECEIVER,
        "value": "2500000000",  # 2,500 USDT at 6 decimals
        "timeStamp": "1700000000", "blockNumber": "18000000",
        "tokenSymbol": "USDT", "contractAddress": USDT_ETH, "tokenDecimal": "6",
    }
    raw.update(overrides)
    return raw


def test_the_record_s_own_decimals_win():
    tx = Transaction.from_token_api(_tokentx(), fallback_decimals=18)
    assert tx.value_native == 2500


def test_a_missing_decimal_falls_back_to_the_traced_token():
    tx = Transaction.from_token_api(_tokentx(tokenDecimal=""), fallback_decimals=6)
    assert tx.value_native == 2500


def test_a_missing_decimal_with_nothing_to_fall_back_on_is_dropped():
    assert Transaction.from_token_api(_tokentx(tokenDecimal=None)) is None


def test_a_garbled_or_negative_decimal_is_treated_as_missing():
    assert resolve_decimals("-3", 6) == 6
    assert resolve_decimals("six", 6) == 6
    assert resolve_decimals("0", 6) == 0  # a real zero-decimal token stays zero


def _nodereal_record(**overrides):
    raw = {
        "hash": "0xabc", "from": SENDER, "to": RECEIVER,
        "value": hex(2_500_000_000), "blockNum": "0x10", "blockTimeStamp": 1700000000,
        "asset": "USDT", "contractAddress": USDT_ETH, "decimal": 6,
    }
    raw.update(overrides)
    return raw


def test_nodereal_token_without_decimal_uses_the_traced_token():
    client = NoderealClient(api_key="k", contract_addresses=[USDT_ETH], token_decimals=6)
    tx = client._to_transaction(_nodereal_record(decimal=None))
    assert tx.value_native == 2500


def test_nodereal_token_without_any_known_decimal_is_dropped():
    client = NoderealClient(api_key="k", contract_addresses=[USDT_ETH])
    assert client._to_transaction(_nodereal_record(decimal=None)) is None


def test_nodereal_native_coin_is_still_18_decimals():
    client = NoderealClient(api_key="k")
    raw = _nodereal_record(value=hex(3 * 10**18), decimal=None, contractAddress=None, asset="BNB")
    assert client._to_transaction(raw).value_native == 3
