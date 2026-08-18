# Lane 21 — Wave 4 deployment dry run

Status: rendered and locally validated on 2026-08-17; **no host is qualified and no mutation is
authorized**  
Owned artifacts: `deploy/wave4/`  
Planning item: W4-09

## Result

W4-09 now has a reviewable deployment packet without an installer. It names the proposed locked
identity, exact paths/modes, future resource ceilings, ciphertext-replica boundary, release closure,
canary, rollback, recovery, and every presently withheld authority. Its most important render is an
explicit absence: there is no installable service or runtime config because the collector is an
offline CLI and the replica executable/transport do not exist.

This is not a paper deployment. The packet preserves all known red gates:

| Target | Packet disposition | What remains red |
|---|---|---|
| `persvati` | `blocked_eol_and_runtime_absent` | inventoried Ubuntu 25.10 is EOL; OS repair is unauthorized; live `run`, config and stop contract are absent; lid/suspend/restart and Tailscale continuity are unproved |
| `hbox` | `blocked_eol_storage_memory_and_runtime_absent` | inventoried Ubuntu 24.10 is EOL; unmirrored ZFS special-vdev, native encryption-off and memory/swap risks remain; replica executable/transport and Tailscale conformance are absent |
| Hetzner | `not_inspected_not_purchased` | no product, account, quote, host, purchase, recurring spend, network or service authority exists |

Remote absence does not disqualify a successful first local episode. It can at most become a
`qualified_local_operational` candidate. Only the root witness owns the authoritative enum;
deployment packets use `qualified_local_operational_candidate_subject_to_root_witness` and never
assert `qualified_local_operational` or `qualified_remote_resilient` themselves.

## Frozen runtime seam

The W4-01 vertical-slice owner supplied and W4-09 froze this provisional surface:

```text
joshi-collector replay --root <collector-root> [--private-key-file <owner-only-path>]
joshi-collector fake-provider --root <collector-root> --fixture <path> --hours <n> [--realtime]
joshi-collector health --root <collector-root>
```

These operations are offline. `health` reads a durable JSON snapshot. There is no `run`, daemon
listener, readiness endpoint, runtime config parser, released executable, stable shutdown deadline,
or supervisor contract. Therefore the exact service and config renders are zero-byte/blocked
records, not `.service` or config files. An actual unit must be rerendered after W4-01 freezes the
live command, credentials, exit/health semantics, signals, deadline and artifact path.

The proposed local root is `/var/lib/joshi/collector`, with `identity/`, `journal/`, `health/`, and
`spool/{staging,ready,acks,catalog_acks,quarantine}`. The exact pure-replica generation root is
`/tank/joshi/spool/replicas/hbox-ciphertext-01/s0-canary-001`, with
`partial/`, `ready/`, `acks/`, and `quarantine/`.

## Artifact index

| Artifact | Review meaning |
|---|---|
| `deploy/wave4/preflight-readonly.sh` | local-on-target, stdout-only inventory; no SSH, sudo, network call or write |
| `deploy/wave4/packets/persvati-collector-s0.yaml` | exact proposed `joshi:joshi` identity, local layout, S0 bounds, resource target, credential purposes, empty network diff, and staged authority |
| `deploy/wave4/packets/hbox-replica-s0.yaml` | exact pure-ciphertext generation, ZFS/memory gates, paths, resource target and no-key/no-delete authority |
| `deploy/wave4/packets/hetzner-optional.yaml` | zero-spend unselected-host acceptance criteria; no provider or purchase action |
| `deploy/wave4/rendered/collector.service.blocked` | exact reason the collector unit render is empty |
| `deploy/wave4/rendered/collector.config.blocked` | exact reason the runtime config render is empty |
| `deploy/wave4/rendered/replica.service.blocked` | exact reason the replica unit render is empty |
| `deploy/wave4/release/RELEASE_MANIFEST.required.yaml` | required source/toolchain/binary/SBOM/license/digest/test closure; all current unknowns remain visible |
| `deploy/wave4/release/README.md` | future bundle shape and offline verification order |
| `deploy/wave4/CANARY_ROLLBACK_RECOVERY.md` | approval-ordered fake/live/replica canaries, forward-preserving rollback and failure recovery |

## Read-only preflight and OS support

W4-09 did not contact a host. After Ember separately authorizes inventory, the reviewed script is
run locally on exactly one intended target without `sudo`:

```text
bash preflight-readonly.sh --expected-host persvati --role collector
bash preflight-readonly.sh --expected-host hbox --role replica
```

It emits a bounded `key=value` report: hostname, OS/kernel/architecture, NTP, identity and path
facts, filesystem/mount options, byte/inode reserve, memory/swap/PSI, systemd state, wildcard TCP
listener **ports only**, Tailscale/UFW unit state, and on `hbox` only ZFS health/capacity/encryption.
It runs no peer canary, prints no IP address or process argument, and deliberately does not read
firewall rules without a distinct authority.

OS support is never inferred from the packet date. At action time, archive Canonical's official
release table, retrieval clock and SHA-256, bind the exact supported LTS `ID:VERSION_ID` to a
separate repair packet, then inventory again after repair. Ubuntu 26.04 LTS is only the expected
target. W4-09 contains no repair, package, reboot, boot-media, partition, encryption or ZFS command.

## Identity, paths, resources and network

Both host packets propose a system-allocated `joshi` user/group, `/nonexistent` home, no home
creation and `/usr/sbin/nologin`. Parents are root-owned `0750`/`0755`; state and every spool
directory are `joshi:joshi 0700`; future staged secrets are `root:root 0400`. The YAML holds the
exact `groupadd`, `useradd`, and `install -d` commands, but labels them unapplied. Existing objects
must match exactly; recursive ownership repair is forbidden.

The collector target is average one logical CPU and 2 GiB RSS; a future unit envelope proposes
`CPUQuota=100%`, `MemoryHigh=2G`, `MemoryMax=3G`, `TasksMax=128`, `LimitNOFILE=8192`, `UMask=0077`
and write access only to its collector root. The replica target proposes `CPUQuota=50%`,
`MemoryHigh=512M`, `MemoryMax=1G`, `MemorySwapMax=0`, `TasksMax=64`, `LimitNOFILE=4096`,
`UMask=0077` and write access only to the exact generation root. Both envelopes remove ambient and
bounding capabilities and are review targets, not units. Unfrozen total/root/control/chunk bounds
and graceful-stop deadlines remain blockers.

All rendered network mutations are empty: no listener, public endpoint, firewall/UFW rule,
Tailscale ACL/tag/member, DNS record, or assumption about ports 80/443. Health remains a local CLI
invoked over a separately authenticated management session. A future replica transport must earn
its own reviewed reachability and authenticated bidirectional canary; a convenient `rsync` result
is not a protocol remote durability ACK.

## Ciphertext and authority boundary

`hbox` and any pure-replica Hetzner role accept only exact outer envelopes already labeled
`authenticated_private`. Replica identity and generation are part of the ACK. A pure replica gets
no private-domain decryption key, source/provider credential, wallet material, catalog handle,
semantic or cursor authority, retention release, or deletion/key-destruction authority. It is not
the sole copy or a catalog backup. Public-integrity segments are not silently repacked because that
would change exact bytes and identity; they require a separately designed public-replica or
domain-preserving repack contract.

The collector may eventually receive a purpose-specific provider-read token and origin sealing key
through systemd credentials only after distinct approval. Pump session material, wallet seed/key,
challenge signature, builder and submitter capability are forbidden. Private operator text stays
local and is not an allowed replica payload unless a later private-domain policy explicitly says
otherwise.

## Release, canary, rollback and recovery

No release is installable while the repository has an unborn `HEAD` and the collector/replica
binaries are absent. A future bundle must close an immutable revision, locked toolchain and
lockfile, exact binary, SPDX 2.3 JSON SBOM, dependency-license inventory, notices, AGPL license,
Corresponding Source archive/source offer, test/audit reports, byte lengths and SHA-256 values.
Credentials, private evidence and unauthorizable fixtures are excluded. Verification occurs before
any host install; a failed bundle is quarantined by digest outside live paths.

The first allowable runtime exercise is a separately approved 24-hour offline fake-provider
canary. It must prove reservation-before-I/O, crash gaps, fsync/rename ACK ordering, the 4,096-record
and 64-MiB queue caps, 32-MiB outer segments, 1-GiB/day growth, under-two-second p99 durability,
resource/disk floors, restart identity, quarantine and redaction. Lid/suspend/reboot are separate
host actions. A live collector canary waits for the live contract.

The replica canary additionally waits for OS/ZFS risk disposition, transport and replica CLI. It
must verify exact ciphertext closure, bounded resume and idempotency, quarantine without ACK,
five-minute catch-up with critical lag at fifteen minutes, and 24 hours with at least 16 GiB
available, no sustained memory PSI and stable accepted swap. Stop if memory stays below 8 GiB for
five minutes. This lane authorizes no ARC/swap or ZFS tuning.

Rollback preserves evidence: stop only the named future unit under new authority, retain state,
restore the last verified artifact/config by digest, and record the resulting source gap. No
recursive deletion, pool/dataset repair, network rollback fiction, catalog overwrite or remote-ACK
deletion is allowed. Recovery distinguishes collector, Mac/catalog, replica, key, disk/memory and
ZFS failures; it restores into a new path and verifies closure before any comparison.

## Authorization ledger

| Action | W4-09 authority |
|---|---|
| read local repository; render/validate packet | allowed and completed |
| run reviewed read-only preflight on either host | not run; requires Ember's host-specific approval |
| repair OS, reboot, change lid/power policy | absent; separate destructive packet required |
| repair/tune ZFS, ARC, memory or swap | absent |
| create users/groups/datasets/paths | exact future lines rendered; not authorized or applied |
| build/copy/install artifact | blocked by release closure; not authorized |
| place credentials or keys | absent |
| install/enable/start/stop a service | absent; service render is blocked |
| provider call or live source capture | absent |
| listener/firewall/Tailscale/DNS change | no-change default; absent |
| copy ciphertext or delete/release an origin | absent |
| access wallet material or construct/sign/submit a transaction | forbidden |
| inspect/buy/configure Hetzner | absent; recurring spend cap is zero |

## Validation and handoff

Local validation covers shell syntax, YAML parsing, exact blocked render contents, path consistency,
no service-unit suffix in the artifact tree, and absence of accidental secrets or mutation scripts.
It proves packet coherence only. No host inventory, OS-support retrieval, provider access, release
build, service render, canary, recovery or remote-resilience claim was performed.

W4-01 must later freeze the live collector/replica runtime and remaining spool bounds. W4-11 must
record remote as explicitly unavailable/stopped when absent rather than omit it. That disposition
can coexist with a root-owned `qualified_local_operational` result, but never with
`qualified_remote_resilient`.
