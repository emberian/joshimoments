# Canary, rollback, and recovery packet

Status: **procedures only; no host action authorized**  
Procedure date: 2026-08-17

The present executable surface can prove offline durability and recovery. It cannot prove an
always-on collector, provider recovery, or remote resilience because live `run` and replica
transport do not exist. Every procedure below preserves evidence by default.

## Gate order

The order is strict. A later approval does not retroactively approve an earlier mutation.

1. **Fresh read-only inventory.** Run the reviewed preflight locally on the target; do not use
   `sudo`. Archive stdout on the Mac as private operational evidence.
2. **Action-time OS decision.** Archive Canonical's release table, its retrieval time and SHA-256;
   bind one supported LTS `ID:VERSION_ID` to a separate repair/rebuild packet. The repair packet
   must contain backup, boot-media, rollback and reboot consequences. W4-09 supplies no OS command.
3. **Post-repair read-only inventory.** Require the approved OS identity, NTP synchronization,
   local filesystem, free-space floor, no new Joshi listener, and no unexplained regression.
4. **Identity/path packet.** Ember may approve only the exact `groupadd`, `useradd`, and `install
   -d` lines in the target YAML. Existing identities or paths must match; do not `chown -R` or
   rewrite an overlapping tree.
5. **Release closure.** Require an immutable source revision, binary, SPDX JSON SBOM, notices,
   license, adjacent Corresponding Source/source offer, and exact SHA-256/length closure. The
   current unborn repository and absent binaries fail this gate.
6. **Offline fake-provider canary.** Separately approve the exact fixture, release, root and hours.
   No source credential is placed and no provider socket is opened.
7. **Live collector canary.** Blocked until W4-01 freezes `run`, config, credentials, health exit
   semantics, signal handling and stop deadline and W4-09 rerenders an actual unit.
8. **Replica canary.** Blocked until the transport and replica CLI/service exist, Tailscale/SSH
   reachability is approved and proven, and `hbox` passes OS/ZFS/memory gates.

## Offline `persvati` canary after approvals

The exact intended command is:

```text
/usr/local/libexec/joshi/joshi-collector fake-provider \
  --root /var/lib/joshi/collector \
  --fixture /usr/local/share/joshi/canary/fake-provider.json \
  --hours 24 \
  --realtime
```

It is not currently runnable: there is no release artifact or installed fixture. When separately
approved, invoke it as the locked `joshi` identity through the approved system-session mechanism;
do not give the identity a login shell or run the process from a personal home.

Before and after the run, capture:

```text
/usr/local/libexec/joshi/joshi-collector health --root /var/lib/joshi/collector
/usr/local/libexec/joshi/joshi-collector replay --root /var/lib/joshi/collector
```

The 24-hour fake run passes only if:

- every attempt is reserved before fake I/O and every injected crash interval becomes a gap;
- no payload is released before local fsync/rename ACK;
- queue caps remain at 4,096 records and 64 MiB and no control record loses its reserve;
- outer segments stay at or below 32 MiB and total growth stays at or below 1 GiB/day;
- normal acquisition-to-local-durable p99 stays under two seconds;
- average process use stays at or below one logical CPU and 2 GiB RSS;
- free storage stays above the greater of 20% and 100 GiB plus the configured spool cap;
- a kill/restart preserves exact occurrence identity, repeats without skips, and quarantines a
  deliberately corrupted **disposable fixture** segment; and
- health/replay print no source bodies, URLs, credentials, key paths, wallet material or private
  operator text.

Lid close, suspend, power-policy change and reboot are different host actions. They require a
named approval after the offline run. Each interruption must preserve the last fsynced segment,
restart under the same generation only when that is true, and append explicit downtime bounds.

## Replica canary after approvals

Do not use a generic successful `rsync` as `RemoteDurabilityAck`. The future adapter must exchange
segment inventory and closure, resume bounded chunks, fsync the destination, atomically rename,
verify the exact authenticated-private outer envelope, and then create the protocol ACK.

The approved test sequence will be:

1. copy one disposable authenticated-private fixture segment while retaining the origin;
2. verify replica ID `hbox-ciphertext-01`, generation `s0-canary-001`, domain, digest and length;
3. interrupt transport for 30 minutes, accumulate bounded origin backlog, restore transport, and
   recover below five minutes; surface critical lag at fifteen minutes;
4. retry completed and out-of-order chunks and prove idempotency;
5. corrupt a replica **fixture copy**, not production evidence, and require quarantine/no ACK;
6. stop on the configured total bound; never evict or reinterpret a remote ACK as deletion; and
7. observe `hbox` for 24 hours with at least 16 GiB available, no sustained memory PSI and stable
   accepted swap use. Stop if available memory stays below 8 GiB for five minutes.

No pure replica receives a decryption key, provider credential, catalog handle, retention release,
or source cursor.

## Rollback

Rollback is forward-preserving:

- **Before mutation:** nothing to undo; retain the reviewed packet and failed gate result.
- **OS repair:** use only the separately reviewed host-repair rollback. Joshi installation is not
  an excuse to erase or repartition a host, change ZFS topology, or tune ARC/swap.
- **Identity/path creation:** leave the empty locked identity and paths in place until Ember
  separately approves removal. Never recursively delete `/var/lib/joshi`, `/tank/joshi`, a home,
  mount, pool, or dataset.
- **Bad artifact before start:** do not install it. Quarantine the release bundle by digest outside
  live paths and record the failed verification.
- **Bad artifact after a future start:** stop and disable only the named Joshi unit under a new
  approval, preserve its state root unchanged, reinstall the last verified artifact by exact
  digest, run offline health/replay, and start only after the original failure is classified.
- **Bad config:** no runtime config exists today. A future rollback must restore the prior complete
  immutable config artifact, never hand-edit a secret or path on-host.
- **Network:** this packet makes no network change, so there is no network rollback. A future ACL,
  UFW, Tailscale or SSH change owns its exact independent reversal.

Stopping a collector creates a source gap. Rollback success therefore includes explicit downtime,
not merely a green process.

## Recovery rules

- **Collector crash:** reopen the same root, verify identity/journal/ready closures, quarantine
  conflicts, and retry exact bytes. Never infer success from a log line.
- **Collector loss/reassignment:** start a new explicit generation and overlap/backfill where the
  source permits. Do not merge by wall clock or run two writers against one source cursor.
- **Mac/catalog offline:** continue bounded local spooling; do not mint catalog ACKs. Stop before
  control reserve or disk floor.
- **Replica offline:** retain every origin segment and mark replica durability unavailable. The
  catalog may continue independently.
- **Replica corrupt:** quarantine exact bytes and invalidate the durability claim for that replica
  generation; the origin remains retained.
- **Key unavailable:** stop private payload capture or retain only safe attempt/gap control
  evidence; never downgrade it to public integrity-only storage.
- **Disk or memory pressure:** degrade in the fixed order—media/enrichment, social cadence, hot
  scopes, then clean stop while retaining the launch/migration denominator as long as safe.
- **ZFS fault:** stop replication, retain other copies, and hand the host to a separately approved
  backup-aware storage plan. A scrub or `ONLINE` state is not a restore.
- **Evidence restoration:** restore into a new path, verify segment/CAS/catalog closures, then
  compare representative replay. Never overwrite the live catalog or call spool replication a
  catalog backup.

`qualified_remote_resilient` remains impossible until both supported-host canaries and the root
Wave 4 witness pass. A remote-absent deployment can still become a
`qualified_local_operational` **candidate**, but only the root witness may assert that enum value.
Before that witness, the exact diagnostic is
`qualified_local_operational_candidate_subject_to_root_witness`; the packet does not invent a
parallel truth vocabulary.
