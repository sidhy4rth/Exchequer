"""Tests for the OFAC SDN parser.

This parser decides what goes into a file that accuses named parties, so the
cases that matter are the ones where it must *not* write an entry: a Bitcoin
address filed under Ethereum, or a chain Exchequer does not trace, would each
produce a label that can only ever mislead.

The fixture is a cut-down copy of the real document's structure, so no network
call is needed to test the logic that reads it.
"""
from __future__ import annotations

import textwrap

import pytest

from scripts.import_ofac_addresses import parse
from app.risk_matcher import MIXER, SANCTIONED

from conftest import addr

TORNADO = addr("7047")
LAZARUS = addr("1a2a")
TRON_ADDR = "TKrEigqhGgTKDTL6Wm4mUAAWFEbHqsdMhu"


# Dedented once, at import, so substituting multi-line entries later cannot
# disturb the leading `<?xml` declaration -- which XML requires at byte zero.
_DOCUMENT = textwrap.dedent("""\
    <?xml version="1.0" standalone="yes"?>
    <sdnList xmlns="https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/XML">
      <publshInformation>
        <Publish_Date>01/15/2026</Publish_Date>
        <Record_Count>3</Record_Count>
      </publshInformation>
    __ENTRIES__
    </sdnList>
    """)

_ENTRY = textwrap.dedent("""\
      <sdnEntry>
        <uid>1</uid>
        <lastName>__NAME__</lastName>
        <sdnType>Entity</sdnType>
        <programList><program>__PROGRAM__</program></programList>
        <idList>
          <id>
            <uid>2</uid>
            <idType>__ID_TYPE__</idType>
            <idNumber>__ADDRESS__</idNumber>
          </id>
        </idList>
      </sdnEntry>
    """)


def sdn_document(entries: str) -> str:
    return _DOCUMENT.replace("__ENTRIES__", entries)


def an_entry(name: str, program: str, id_type: str, address: str) -> str:
    return (
        _ENTRY.replace("__NAME__", name)
        .replace("__PROGRAM__", program)
        .replace("__ID_TYPE__", id_type)
        .replace("__ADDRESS__", address)
    )


@pytest.fixture
def sdn_file(tmp_path):
    def write(entries: str):
        path = tmp_path / "sdn.xml"
        path.write_text(sdn_document(entries))
        return path
    return write


def test_reads_the_publication_date(sdn_file):
    path = sdn_file(an_entry("LAZARUS GROUP", "DPRK3", "Digital Currency Address - ETH", LAZARUS))
    _, _, published = parse(path)
    assert published == "01/15/2026"


def test_files_an_eth_address_under_ethereum(sdn_file):
    path = sdn_file(an_entry("LAZARUS GROUP", "DPRK3", "Digital Currency Address - ETH", LAZARUS))
    by_chain, _, _ = parse(path)

    assert set(by_chain) == {"ethereum"}
    entry = by_chain["ethereum"][LAZARUS]
    assert entry["category"] == SANCTIONED
    assert entry["entity"] == "LAZARUS GROUP"
    assert entry["ofac_programs"] == ["DPRK3"]
    assert entry["ofac_id_type"] == "Digital Currency Address - ETH"
    assert "01/15/2026" in entry["source"]


def test_files_a_trx_address_under_tron(sdn_file):
    path = sdn_file(an_entry("SOME ENTITY", "CYBER2", "Digital Currency Address - TRX", TRON_ADDR))
    by_chain, _, _ = parse(path)
    assert TRON_ADDR in by_chain["tron"]


def test_classifies_a_tumbler_as_a_mixer(sdn_file):
    """The split is editorial, but it is what stops a trace."""
    path = sdn_file(an_entry("TORNADO CASH", "CYBER2", "Digital Currency Address - ETH", TORNADO))
    by_chain, _, _ = parse(path)
    assert by_chain["ethereum"][TORNADO]["category"] == MIXER


def test_a_bitcoin_address_is_skipped_not_misfiled(sdn_file):
    """An XBT address in an Ethereum label file could only mislead."""
    path = sdn_file(
        an_entry("SOME ENTITY", "CYBER2", "Digital Currency Address - XBT",
                 "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2")
    )
    by_chain, skipped, _ = parse(path)

    assert by_chain == {}
    assert skipped == {"XBT": 1}


def test_a_chain_we_do_not_trace_is_skipped(sdn_file):
    path = sdn_file(an_entry("SOME ENTITY", "CYBER2", "Digital Currency Address - XMR", "4Aabc"))
    by_chain, skipped, _ = parse(path)

    assert by_chain == {}
    assert skipped == {"XMR": 1}


def test_a_token_designation_is_resolved_by_address_format(sdn_file):
    """USDT names a token, not a ledger; the address format is the discriminator."""
    path = sdn_file(
        an_entry("A", "CYBER2", "Digital Currency Address - USDT", TRON_ADDR)
        + an_entry("B", "CYBER2", "Digital Currency Address - USDT", LAZARUS)
    )
    by_chain, _, _ = parse(path)

    assert TRON_ADDR in by_chain["tron"]
    assert LAZARUS in by_chain["ethereum"]
    # The original idType is preserved so the assumption stays visible.
    assert by_chain["ethereum"][LAZARUS]["ofac_id_type"] == "Digital Currency Address - USDT"


def test_an_eth_address_is_not_copied_onto_bsc(sdn_file):
    """The Tornado Cash pools are contracts; the same address on BSC is not them."""
    path = sdn_file(an_entry("TORNADO CASH", "CYBER2", "Digital Currency Address - ETH", TORNADO))
    by_chain, _, _ = parse(path)
    assert "bsc" not in by_chain


def test_a_malformed_address_is_skipped(sdn_file):
    path = sdn_file(an_entry("A", "CYBER2", "Digital Currency Address - ETH", "0xnothex"))
    by_chain, skipped, _ = parse(path)

    assert by_chain == {}
    assert skipped == {"ETH": 1}


def test_entries_without_a_crypto_address_are_ignored(sdn_file):
    """Almost every SDN entry is a person or company with no wallet at all."""
    path = sdn_file(an_entry("SOMEONE", "SDGT", "Passport", "X1234567"))
    by_chain, skipped, _ = parse(path)

    assert by_chain == {}
    assert skipped == {}
