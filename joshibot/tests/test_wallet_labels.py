"""The wallet-label file's own invariants, as tests rather than as a comment.

``wallet_labels.yaml`` carries operator-attested ground truth, and it closes with an
invariant written out as a shell one-liner in a comment: every live address is on the
ed25519 curve. That comment caught two fabricated addresses when somebody remembered to
run it. On 2026-08-15 nobody did, and two new entries were appended past the end of the
``external:`` list — landing inside ``address_poisoning:``, where a sequence item cannot
follow mapping keys. The file was committed **unparseable** and stayed that way until an
unrelated reader tried to load it.

So the lesson is not "run the one-liner". It is that a check nobody can forget has to be a
test. These are cheap, they need no network, and they fail loudly the moment an edit to
that file breaks it.

Why on-curve matters, restated because it is the whole point: an address off the ed25519
curve has no private key. It cannot sign and it cannot be paid at. Whatever a label claims,
such an entry is not a wallet — it is a truncated display completed with a fabricated tail,
which is exactly how two of this file's three inherited addresses were wrong.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
pubkey_mod = pytest.importorskip("solders.pubkey")
Pubkey = pubkey_mod.Pubkey

LABELS_PATH = Path(__file__).resolve().parent.parent / "wallet_labels.yaml"

#: Sections whose entries name a live address we might act on.
LIVE_SECTIONS = ("own_wallets", "external")


@pytest.fixture(scope="module")
def labels() -> dict:
    return yaml.safe_load(LABELS_PATH.read_text(encoding="utf-8"))


def test_file_parses() -> None:
    """The failure that motivated this module: the file did not parse at all."""

    loaded = yaml.safe_load(LABELS_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    for section in LIVE_SECTIONS:
        assert isinstance(loaded.get(section), list), f"{section} must be a list"


def test_every_live_address_is_on_curve(labels: dict) -> None:
    """The footer invariant. An off-curve address has no keypair and is not a wallet."""

    offenders: list[tuple[str, str]] = []
    for section in LIVE_SECTIONS:
        for entry in labels.get(section) or []:
            address = entry.get("address")
            if address is None:
                continue  # deliberately unresolved; `resolution` records what was searched
            if not Pubkey.from_string(address).is_on_curve():
                offenders.append((str(entry.get("label")), address))
    assert not offenders, f"off-curve addresses in use: {offenders}"


def test_superseded_addresses_are_quarantined_not_live(labels: dict) -> None:
    """A corrected address stays as `superseded_address` so a lookalike is never re-adopted."""

    live = {
        entry["address"]
        for section in LIVE_SECTIONS
        for entry in labels.get(section) or []
        if entry.get("address")
    }
    for section in LIVE_SECTIONS:
        for entry in labels.get(section) or []:
            superseded = entry.get("superseded_address")
            if superseded is not None:
                assert superseded not in live, (
                    f"{entry.get('label')}: superseded address {superseded} is also live"
                )


def test_addresses_are_unique_across_live_sections(labels: dict) -> None:
    """One address, one label. Two labels on one key means one of them is wrong."""

    seen: dict[str, str] = {}
    for section in LIVE_SECTIONS:
        for entry in labels.get(section) or []:
            address = entry.get("address")
            if address is None:
                continue
            label = str(entry.get("label"))
            if address in seen and seen[address] != label:
                pytest.fail(f"{address} carries two labels: {seen[address]!r} and {label!r}")
            seen[address] = label


def test_entries_carry_a_confidence_outside_own_wallets(labels: dict) -> None:
    """`attested` / `probable` / `inferred` — an unlabelled confidence is an unusable label."""

    allowed = {"attested", "probable", "inferred"}
    for entry in labels.get("external") or []:
        assert entry.get("confidence") in allowed, (
            f"{entry.get('label')}: confidence {entry.get('confidence')!r} not in {sorted(allowed)}"
        )


def test_the_watched_caller_and_its_homoglyph_are_distinct_and_labelled(labels: dict) -> None:
    """The operator watches one of these and must never act on the other.

    Pinned by address on purpose: the whole hazard is that the two handles are one
    homoglyph apart, so a test keyed on the *name* would pass while the addresses were
    swapped.
    """

    by_address = {
        entry["address"]: entry
        for entry in labels.get("external") or []
        if entry.get("address")
    }
    real = by_address.get("BAr5csYtpWoNpwhUjixX7ZPHXkUciFZzjBp9uNxZXJPh")
    imposter = by_address.get("9T8QKsR28boKJL3x3td39rX8dk1xsd5zwWaF2nFzijvP")

    assert real is not None, "the watched caller jackduvalcalls is missing"
    assert imposter is not None, "the jackduvalcalls homoglyph is missing"
    assert real["label"] == "jackduvalcalls"
    assert real["kind"] == "watched_caller"
    assert imposter["kind"] == "adversary", "the homoglyph must never be labelled benign"
    assert real["address"] != imposter["address"]
