"""Sign a guarded transaction. Cannot broadcast one.

THE BROADCAST PATH DOES NOT EXIST IN THIS VERSION, AND THAT IS DELIBERATE.

`rpc.py::READ_METHODS` has no `sendTransaction` in it, so there is no code path in this
package that puts bytes on the network -- not behind a flag, not behind the three gates, not
behind an accident. With every gate open, the most this package does is produce a signed
transaction, verify the signature locally, simulate it with `sigVerify: true` against live
chain state, write the ledger rows, and print the bytes. Adding the send is a deliberate
edit to a method allowlist, visible in a diff, made by someone who has read this file.

That is a stronger guarantee than a dry-run flag and it costs the desk nothing right now:
the acceptance test is a dry run, the operator's review happens before any send, and the
landing policy (`studies/RESULT_execution_landing.md` §8: sign once, rebroadcast identical
bytes every ~400ms until `lastValidBlockHeight`, never re-sign inside the window, poll
`getSignatureStatuses`) is a second body of work with its own failure modes -- an unresolved
signature is a manual-intervention event, not a retry -- and shipping it half-built next to
a live key is how a desk gets a double fill.

`sign_guarded` therefore exists to make the signing path testable and reviewable before it
is reachable. Note what it will not do: it signs a `GuardedTransaction`, and there is no way
to construct one of those except by passing `guard.guard_transaction`.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from solders.keypair import Keypair
from solders.message import to_bytes_versioned
from solders.transaction import VersionedTransaction

from .guard import GuardedTransaction, TransactionRefused


@dataclass(frozen=True, slots=True)
class SignedTransaction:
    encoded: str
    signature: str
    signers: tuple[str, ...]


def sign_guarded(guarded: GuardedTransaction, *signers: Keypair) -> SignedTransaction:
    """Sign in the message's own signer order and verify locally before returning.

    Signers are matched to `account_keys` positionally rather than trusted to arrive in the
    right order, because a mis-ordered signature list produces a transaction that verifies
    against the wrong key and fails at the validator, which is a far worse place to find out.
    """
    message = guarded.transaction.message
    required = message.header.num_required_signatures
    available = {str(keypair.pubkey()): keypair for keypair in signers}
    payload = to_bytes_versioned(message)

    ordered: list[Keypair] = []
    for index in range(required):
        key = str(message.account_keys[index])
        keypair = available.get(key)
        if keypair is None:
            raise TransactionRefused(f"no key available for required signer {key}")
        ordered.append(keypair)

    signatures = [keypair.sign_message(payload) for keypair in ordered]
    signed = VersionedTransaction.populate(message, signatures)
    if signed.verify_with_results() != [True] * required:
        raise TransactionRefused("locally signed transaction did not verify")
    return SignedTransaction(
        encoded=base64.b64encode(bytes(signed)).decode("ascii"),
        signature=str(signed.signatures[0]),
        signers=tuple(str(keypair.pubkey()) for keypair in ordered),
    )
