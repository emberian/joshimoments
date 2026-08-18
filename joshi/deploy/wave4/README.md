# Wave 4 deployment dry run

Status: **rendered review packet; zero host authority**  
Packet date: 2026-08-17  
Contract: `joshi.wave4.deployment_packet/v1`

This directory turns W4-09 into reviewable artifacts without pretending that either inventoried
host is deployable. It does not contain an installer or an active service unit.

## Current disposition

| Target | Intended role | Current result | Hard blockers |
|---|---|---|---|
| `persvati` | first S0 collector canary | `blocked_eol_and_runtime_absent` | Ubuntu 25.10 EOL; no authorized OS repair; no live collector `run`/config/shutdown contract; lid/reboot continuity unproved; Tailscale asymmetry unresolved |
| `hbox` | ciphertext-only replica | `blocked_eol_storage_memory_and_runtime_absent` | Ubuntu 24.10 EOL; unmirrored ZFS special vdev; ZFS encryption off; memory/swap gate failed at inventory; no replica daemon/CLI; Tailscale asymmetry unresolved |
| optional Hetzner | later supported-LTS collector or off-site replica | `not_inspected_not_purchased` | no account/product/price/host inspection; $0 pre-September budget; purchase and network authority absent |

No approval is inferred from these files. In particular, approval to repair an OS is not approval
to install Joshi; approval to install a collector is not approval to place credentials or start it;
approval to copy ciphertext is not approval to decrypt or delete its source.

## Frozen collector seam

The W4-01 owner supplied this provisional interface and asked W4-09 not to render a service until a
live runtime exists:

```text
executable: joshi-collector

joshi-collector replay \
  --root <collector-root> \
  [--private-key-file <owner-only-path>]

joshi-collector fake-provider \
  --root <collector-root> \
  --fixture <path> \
  --hours <n> \
  [--realtime]

joshi-collector health \
  --root <collector-root>
```

All commands are offline. `health` reads a durable JSON snapshot; it is not an HTTP endpoint.
There is no live `run`, no readiness socket, no runtime config schema, and no stable graceful-stop
deadline. The exact collector root chosen for a future approved `persvati` canary is:

```text
/var/lib/joshi/collector/
  identity/
  journal/
  spool/
    staging/
    ready/
    acks/
    catalog_acks/
    quarantine/
  health/
```

Consequences:

- `rendered/collector.service.blocked` is the exact service-render result. It is not a unit.
- No file is proposed for `/etc/joshi/collector.*`; the binary does not accept one.
- The offline commands may be used only in a separately approved fake-provider canary. They do not
  justify an always-on service.
- A future W4-01 change must freeze `run`, config version, key/credential ingestion, exit codes,
  signal behavior, maximum graceful-stop time, and release artifact before this packet is rerendered.

## Files

| Artifact | Purpose |
|---|---|
| [`preflight-readonly.sh`](preflight-readonly.sh) | local-on-target, stdout-only inventory; no SSH, sudo, network, writes, addresses, process arguments, or secret paths |
| [`packets/persvati-collector-s0.yaml`](packets/persvati-collector-s0.yaml) | exact proposed identities, paths, modes, bounds, resource envelope, zero-change network policy, and staged mutation boundary |
| [`packets/hbox-replica-s0.yaml`](packets/hbox-replica-s0.yaml) | ciphertext-only replica packet with ZFS/memory blockers left red |
| [`packets/hetzner-optional.yaml`](packets/hetzner-optional.yaml) | non-purchase acceptance packet; no product or price assumption |
| [`rendered/collector.service.blocked`](rendered/collector.service.blocked) | exact reason no collector unit may be installed |
| [`rendered/collector.config.blocked`](rendered/collector.config.blocked) | exact reason no host runtime config may be written |
| [`rendered/replica.service.blocked`](rendered/replica.service.blocked) | exact reason no replica unit may be installed |
| [`release/RELEASE_MANIFEST.required.yaml`](release/RELEASE_MANIFEST.required.yaml) | mandatory binary/SBOM/digest/license/source fields; not a claim that an artifact exists |
| [`release/README.md`](release/README.md) | exact future release-bundle layout and offline verification order |
| [`CANARY_ROLLBACK_RECOVERY.md`](CANARY_ROLLBACK_RECOVERY.md) | separately authorized canary, conservative rollback, and evidence-preserving recovery |

## Read-only inventory invocation

The script intentionally has no remote orchestration. If Ember separately authorizes a fresh
read-only inventory, an operator copies or pipes the reviewed exact script to the named host and
runs one of:

```text
bash preflight-readonly.sh --expected-host persvati --role collector
bash preflight-readonly.sh --expected-host hbox --role replica
```

The output is line-oriented `key=value` with a fixed contract header. It does not decide OS
support from a stale embedded calendar. The operator must also archive an action-time copy of
Canonical's official release table, record its SHA-256, and bind the approved `ID:VERSION_ID` to
the mutation approval. The current expected repair target is Ubuntu 26.04 LTS, but the action-time
official table—not this repository sentence—is authoritative.

## Network default

The render is intentionally empty:

```yaml
listeners: []
firewall_changes: []
tailscale_changes: []
dns_changes: []
public_endpoints: []
```

Health is polled through the offline CLI over a separately authenticated management session. The
first replica transport may reuse reviewed SSH, but no copy command is rendered because the
replica transport/CLI and the asymmetric Tailscale membership have not passed conformance. No
packet opens UFW, binds wildcard or loopback HTTP, changes an ACL/tag, creates DNS, or assumes that
ports 80/443 belong to Joshi.

## Ciphertext rule

`hbox` and any pure-replica Hetzner role accept only exact segment envelopes already marked
`authenticated_private`; they receive no provider credential and no decryption key. Current public
integrity-only segments are not silently re-encrypted because that would change their exact bytes
and ACK identity. Until an explicit domain-preserving repack protocol exists, such segments stay
on their origin/Mac or use a separately designed public replica. Remote ACK never authorizes local
deletion.

## Qualification vocabulary

These packets emit diagnostics, not root witness truth. A host with no approved remote replica may
still be a `qualified_local_operational` candidate. Only the root Wave 4 witness may assert
`qualified_local_operational` or `qualified_remote_resilient`; until then, packet diagnostics use
the explicit suffix `_candidate_subject_to_root_witness`.
