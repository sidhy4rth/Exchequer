"""The one word filter both exchange importers read a tag through.

An exchange match ends a trace and names where the funds were cashed out, so
a tag that names something the exchange runs but that is not where customers
cash out -- a contract (proxy, factory, executor, forwarder, implementation,
router, aggregator, relayer, swap, bridge, multisig, token), the wallets that
deploy contracts or fund deposit addresses' gas, a batch sender, another
firm's treasury -- must never become an exchange wallet. import_eth_labels
and import_exchange_labels kept two lists that drifted apart ('Binance:
Proxy' passed one, r1-scripts-0), so both read this one, on the tag cleaned
the same way: app.tron_tags.clean_tag (NFKC, invisible and format characters
removed), then casefolded, so 'OKX: Rout​er 2' or a full-width
'Ｐｒｏｘｙ' cannot hide a word.

A name filter will always miss a contract named some new way: refusing an
address that holds bytecode is the stronger check (port_evm_labels does it).
"""
from __future__ import annotations

import re
from typing import Any

from app.tron_tags import clean_tag

NOT_CASH_OUT = re.compile(
    # Contracts an exchange runs.
    r"proxy|upgradeab|factory|executor|forwarder|implementation|router|aggregat|relayer|paymaster|swap|bridge|multisig|"
    r"contract|token|batch|dispers|distributor|airdrop|minter|wrapper|escrow|registry|operator|launchpad|"
    # Its own wallets that are not where customers cash out.
    r"deployer|funder|depositor|supplier|treasury|vesting|staking|"
    # Not an exchange at all.
    r"exploit|charity|^bitget wallet|\bdex\b(?!-trade)",
    re.IGNORECASE,
)


def cleaned(tag: Any) -> str:
    """A tag as the filter reads it."""
    return clean_tag(tag).casefold()


def names_infrastructure(tag: Any) -> bool:
    """Whether `tag` names something that is not a cash-out wallet."""
    return NOT_CASH_OUT.search(cleaned(tag)) is not None
