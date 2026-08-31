# Wallet placeholders

Every operator-owned Solana address that once appeared in this repository has been replaced with a
synthetic placeholder — in the working tree **and throughout the git history**, including commit
messages. The real addresses are not recoverable from anything published here.

## The placeholders

| label | placeholder address |
|---|---|
| `shitcoims` | `Sh1WNJ8g68rXJGyDjVPcfxWN1WbMrLsgdXmSb6cccuE` |
| `tha_funds` | `Funv3QdbBA1ZUC53t2ZoWa9zubAz15w9oCyajDPoRaMQ` |
| `pumpfun_main` | `PmpDh2BQCMMseKYPxseWTSoX3aAouHE4sWyFWTdkqYE` |
| `ember_dev` | `Dev2GmPW2Jv28KW8D7DLqh7TM9hRf8adTDF5p6Jk3CHc` |
| `og_shitcoims` | `PrvpTgcuAzN337qSmmKizTMSmhpLPJmZ5Vt8WKCzagf` |
| `coinbase_receiving` | `Cbx3NneVa8dKpFbWJeVGARH9pmx4ZttdAfWVqm3HP3Eh` |
| `payroll` | `PayDyNeCPqJBp34JMWWjP7DbDbneF2mHHFjPNrEbuv6` |
| `payroll_superseded` | `PsupYUmZCrn9YdBwkxNoxhYnDBCYe2cCPmetKtRbEB6` |

Each placeholder is a genuine, well-formed Solana public key: valid base58, decoding to exactly 32
bytes, so every parser and validator in this codebase accepts it. Each one is also **off the
ed25519 curve**, which means no private key can exist for it. They are structurally real and
provably nobody's wallet — they cannot receive funds and no one can sign for them. Do not send
anything to them, and do not expect to find them on a block explorer.

Each begins with a short readable tag (`Sh1`, `Fun`, `Pmp`, `Dev`, `Prv`, `Cbx`, `Pay`, `Psu`) so a
placeholder is recognizable as one at a glance, and so the eight remain distinguishable wherever the
research refers to them by an abbreviated prefix.

## Address-poisoning lookalikes

`wallet_labels.yaml` documents an address-poisoning campaign whose whole method is generating
addresses that match a target's leading *and* trailing characters. Those lookalikes were therefore
partial copies of the real addresses, and they have been replaced too — with synthetic mimics that
reproduce the placeholders' heads and tails instead, keeping each lookalike's own distinctive middle.
The demonstration of the attack is intact; the reconstruction hazard is not.

## What this does and does not accomplish

It removes the literal addresses. It is **not** anonymization: the studies still report exact SOL
amounts, timestamps, counterparty structure, and program interactions, all of which are unchanged
and all of which remain on a public ledger. A determined chain analyst could re-identify these
wallets from the behavioral record. That was a deliberate tradeoff — scrubbing the analysis itself
would have destroyed the work this repository exists to share.

Nothing in the findings depends on the identifiers. Substituting one opaque handle for another
leaves every measurement, null result, and correction exactly as it was.
