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


def test_each_chain_publishes_its_native_coin_decimals():
    # Problem O6: TRX was published with 18 decimals; it has 6.
    from app import config
    from app.tron_client import SUN_PER_TRX

    published = {key: chain.to_dict()["assets"][0] for key, chain in config.CHAINS.items()}
    assert published["tron"] == {"symbol": "TRX", "address": None, "decimals": 6, "native": True}
    assert 10 ** published["tron"]["decimals"] == SUN_PER_TRX
    for key in ("ethereum", "bsc", "polygon", "arbitrum"):
        assert published[key]["decimals"] == 18, key


# Tron (r2-g2-documented-claims-vs-code-7-7): the TRC-20 parser used to guess
# 6 when token_info had no decimals, use the raw integer when the figure was
# negative (5 USDT read as 5,000,000), and take a stated 18 over the
# configured 6 (5 USDT read as 5e-12).
USDT_TRON = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"


def _trc20(info):
    return {"transaction_id": "t1", "type": "Transfer", "from": "TSFFxCbDLh6nP1x4BcyqkbEFJyx3zSGY2r",
            "to": "TD5gsCnXYaDzd6CwT1aT6XsPX5q8tBfTbY", "value": "5000000",
            "block_timestamp": 1_700_000_000_000, "token_info": info}


def _tron(decimals=6):
    from app.tron_client import TronClient
    return TronClient(api_key="k", contract_address=USDT_TRON, asset_symbol="USDT", token_decimals=decimals)


def test_tron_token_without_decimals_uses_the_configured_precision():
    assert _tron()._token_transfer(_trc20({"address": USDT_TRON})).value_native == 5.0


def test_tron_negative_decimals_fall_back_to_config_not_raw_units():
    assert _tron()._token_transfer(_trc20({"address": USDT_TRON, "decimals": -1})).value_native == 5.0


def test_tron_record_disagreeing_with_config_is_dropped():
    assert _tron()._token_transfer(_trc20({"address": USDT_TRON, "decimals": 18})) is None
    assert _tron()._token_transfer(_trc20({"address": USDT_TRON, "decimals": 6})).value_native == 5.0


def test_tron_token_with_no_known_decimals_is_dropped():
    assert _tron(decimals=None)._token_transfer(_trc20({"address": USDT_TRON})) is None


def test_open_source_gives_tron_the_configured_decimals():
    from app import config
    from app.chain_data import open_source

    with open_source(config.CHAINS["tron"], "USDT") as client:
        assert client.token_decimals == 6
