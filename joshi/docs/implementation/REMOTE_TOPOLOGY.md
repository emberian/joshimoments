# Remote acquisition and replica topology

Status: **read-only inventory and deployment decision; no deployment authorized**  
Inventory date: 2026-08-16 (America/New_York)  
Hosts inspected: `persvati`, `hbox`  
Not inspected or purchased: Hetzner

## 1. Decision

Do **not** deploy Joshi to either machine in its present state.

Both installed Ubuntu releases are end-of-life. `persvati` is on Ubuntu 25.10, whose support ended
in July 2026, and `hbox` is on Ubuntu 24.10, whose support ended on 2025-07-10. Canonical's current
[release table](https://ubuntu.com/project/docs/release-team/list-of-releases/) lists both under
end-of-life; 26.04 LTS is the current long-lived target. An acquisition host will hold provider
credentials and consume untrusted network data, so an unsupported OS is a deployment blocker, not
merely housekeeping.

After separately authorized host maintenance and the gates in section 6:

- **`persvati` is the better zero-new-cost candidate for a bounded S0/S1 collector and primary
  unadmitted spool.** It has large CPU/RAM/disk headroom, a battery, and a five-week uptime. It is
  still a laptop with only `s2idle`; closing the lid, desktop power policy, Wi-Fi loss, and reboot
  recovery must be proven rather than inferred from current uptime.
- **`hbox` is a secondary ciphertext replica and later batch worker, not the sole archive and not
  initially the collector.** Its ZFS capacity is useful, but the pool has a single-device special
  vdev whose loss can lose the pool, native encryption is off, and the machine currently has only
  about 10--15 GiB memory available with nearly all swap allocated.
- **The Mac remains the first catalog-admission/query/glass machine.** Remote acquisition creates
  exact spool segments; it does not create catalog commit order, advance a cursor, or become a
  second SQLite writer.
- **A Hetzner host is an optional later 24/7 collector/off-site spool replica**, not a present
  prerequisite. It is considered only after the local bounded capacity experiment earns the cost
  and Ember explicitly authorizes a purchase. Use a currently supported LTS image, local durable
  SSD, private management, and the same host-agnostic spool contract. Give it provider-read
  credentials only, never wallet signing material.

The initial recommendation is therefore a staged topology, not failover theatre:

```text
provider/Pump/public source
          |
          v
persvati collector + local append-only spool       later: Hetzner may assume this role
          | exact domain-bound segments
          v
hbox ciphertext replica (extra copy, not sole backup)
          |
          | resumable inventory/closure exchange
          v
Mac catalog admission -> one local SQLite writer -> CAS/export -> glass/analysis
```

An outage at the active collector creates an explicit source-scoped coverage gap. Neither replica
is a hot failover writer. A move of acquisition responsibility is an operator-recorded generation
change with overlap/reconciliation, not two collectors racing a cursor.

## 2. What was and was not inspected

The inventory used non-interactive, read-only SSH commands with `BatchMode=yes`. It inspected only
host facts relevant to this deployment: OS/kernel/architecture, CPU and memory, block and mounted
storage, ZFS shape, uptime and suspend evidence, time sync, network-interface state, listening-port
shape, Tailscale/WireGuard state, firewall visibility, init/container/tooling availability, current
load/pressure, service-user feasibility, and backup utilities/timers. It did not use `sudo`, print
addresses or credentials, traverse personal files, inspect unrelated process arguments, install
software, alter configuration, open a port, create an account or path, or start a service.

Capacity numbers below are a point-in-time inventory. Five-week uptime and one low-load sample are
useful observations, not availability guarantees. Likewise, the absence of an accessible suspend
journal entry is not proof that a future lid close or desktop update cannot suspend a host.

## 3. Host inventory

### 3.1 Comparison

| Property | `persvati` | `hbox` | Deployment consequence |
|---|---|---|---|
| OS | Ubuntu 25.10; Linux 6.17.0-40 | Ubuntu 24.10; Linux 6.11.0-29 | Both EOL; upgrade/rebuild before credentials or service |
| Architecture | bare-metal x86_64 | bare-metal x86_64 | Normal Rust/Linux target |
| CPU | Ryzen AI 9 HX PRO 370; 24 logical / 12 reported cores | Core i9-12900; 24 logical / 16 reported cores | Either exceeds S0/S1 compute needs; hybrid-core counts are inventory, not throughput |
| RAM at sample | 83 GiB total; about 76 GiB available | 123 GiB total; about 10--15 GiB available | `persvati` has headroom; `hbox` requires a memory gate |
| Swap at sample | 15 GiB total; about 3.4 GiB used | 8 GiB total; effectively exhausted | Do not add persistent load to `hbox` yet |
| Load / PSI | load about 0.48; no current memory pressure; low I/O PSI | load about 0.06; no current memory/I/O PSI | Both were idle at one instant; this does not reserve capacity |
| Root storage | 1.9 TB ext4 NVMe; about 558 GB free (69% used) | 463 GB ext4 NVMe; about 201 GB free (54% used) | Local-fs atomic spool is feasible; enforce free-space floors |
| Additional storage | none relevant | `tank`: about 2.73 TiB, 1.85 TiB free, ONLINE | Useful replica capacity with material durability caveat below |
| At-rest encryption evidenced | none | root none; `tank` ZFS `encryption=off` | Private bytes must be application-encrypted before replication |
| Uptime | 5 weeks 2 days | 4 weeks 4 days | Encouraging observation only |
| Power/sleep | battery 77%, mains online; only `s2idle` | no battery; `deep` available | Battery is not a UPS; prove restart/suspend behavior |
| Network | Wi-Fi up, Ethernet down, Tailscale up | Wi-Fi up, Ethernet down, Tailscale up | No wired-path or link-redundancy claim |
| Service manager | systemd; user linger off | systemd; user linger on | Use a system service, not a login/user service |
| Containers | Docker/containerd active | Docker/containerd active | Available but unnecessary for the first direct binary |
| Isolation | AppArmor enabled | AppArmor enabled | Add a least-privilege systemd unit after CLI stabilizes |
| Stable Joshi identity/path | no `joshi` user; system state dirs not writable by current user | same; `/tank` also not writable by current user | One-time approved admin provisioning is required |

Both machines reported a degraded systemd state because the same already-missing, unrelated
`dregg-poa-candidate.service` is failed. This inventory did not diagnose or change it. A later Joshi
readiness check must distinguish pre-existing host failures from Joshi unit health rather than
requiring the entire host state to be green.

Neither host had an active Nix or Podman installation. `persvati` reported Docker 29.1.3, a Rust
1.98 nightly, Python 3.13.7, `uv` 0.12.3, Git 2.51 and `rsync` 3.4.1. `hbox` reported Docker 27.5.1,
a Rust 1.100 nightly, Node 20.16, Python 3.12.7, Git 2.45.2 and `rsync` 3.3.0; `uv` was absent. The
standalone `sqlite3` CLI and the surveyed restic/Borg/rclone/age tooling were absent on both. Joshi's
store embeds its pinned SQLite and the repository pins Rust 1.97.1, so ambient versions are
inventory rather than permission to compile or install. NTP reported synchronized on both hosts.

### 3.2 `persvati`

`persvati` has the cleanest capacity envelope for the no-purchase pilot. The sampled process set
does not explain material contention, NTP is synchronized, Docker and cron are available, and the
machine has remained up for more than five weeks. Rust/Cargo, Python, `uv`, Git and `rsync` are
present. Its `node` command is currently a Bun wrapper that does not answer `node --version`; the
collector must not rely on an ambient JavaScript toolchain. The repository pins Rust 1.97.1, so an
unrelated installed nightly is not the deployment toolchain contract.

Hard gates remain:

- move to a supported OS before placing any source credential on the host;
- prove a 24-hour lid/power/reboot trial with the actual service, including restart after reboot;
- decide whether full-disk encryption exists outside what the unprivileged block view could show;
- provision a dedicated non-login service identity and a local crash-durable state directory;
- correct/understand the Tailscale peer asymmetry before depending on replication; and
- measure S0 queue lag, fsync latency, daily byte growth, and interactive impact under the exact
  spool implementation.

The battery improves short-interruption behavior but does not establish a UPS runtime or graceful
shutdown. Only `s2idle` was advertised. No suspend/hibernate entry appeared in the accessible last
30 days of the journal, but that cannot certify future lid behavior.

### 3.3 `hbox`

`hbox` has valuable bulk storage and ample CPU, but current memory and storage topology make it a
poor primary recorder.

The imported `tank` pool is ONLINE and its most recently reported scrub repaired 0 bytes with 0
errors. Its normal data vdev is a two-disk mirror. However, the pool also has **one unmirrored NVMe
special vdev**. OpenZFS explains that a special vdev contains the only copy of routed metadata and
must be at least as redundant as normal vdevs; losing a single-device special vdev can lose the
pool ([OpenZFS special-vdev documentation](https://openzfs.github.io/openzfs-docs/Basic%20Concepts/Pool%20Structure/Special%20vdev.html)).
This is an existing host-storage risk, not permission to reconfigure ZFS. Joshi must never call the
pool its only backup, and a replica ACK from it must never release another copy.

ZFS native encryption is off. A private-domain Joshi segment may be stored there only as an
authenticated-encryption envelope. At the sample, ARC was about 52 GiB and almost entirely reported
as metadata; kernel unreclaimable slab was about 91 GiB, aggregate process RSS only about 1.5 GiB,
and the 8 GiB swap was effectively full. There was no current PSI stall, so this is not evidence of
active thrashing, but it is evidence that nominal 123 GiB RAM is not free capacity. Before batch
work or a replica service, require a sustained memory/ARC observation and a stop policy.

No Sanoid, Syncoid, `zfs-auto-snapshot`, restic, Borg, or rclone installation was found. A recent
scrub is integrity maintenance, not a backup. No relevant ZFS snapshot/backup timer was observed.
There are other disks with ZFS member signatures that were not imported or explored; their state
and contents are unknown and must not be incorporated into a plan.

### 3.4 Hetzner

No account, product, price, host, or network was inspected. “Hetzner” here means a provider-neutral
future remote VM with these acceptance properties:

- supported LTS OS and automatic security-update policy reviewed by Ember;
- local SSD-backed crash-durable filesystem and measured fsync behavior;
- enough space for the measured retention window with 20% plus 100 GiB reserve;
- outbound access only for sources and replication, with management over authenticated private
  transport; no public Joshi HTTP/metrics listener;
- application-encrypted private segment bytes and no decryption key on a pure replica;
- no wallet private key, seed phrase, transaction builder, signing or submission capability; and
- a hard provider spend cap consistent with the pre-September no-new-spend default.

Hetzner becomes the preferred continuous collector only if the local pilot shows that laptop
sleep/network continuity materially damages coverage or an off-site failure domain is worth its
recurring cost. It does not solve catalog semantics: the Mac still admits segments through the one
writer unless a later, separately designed catalog migration is approved.

## 4. Network and exposure findings

SSH from the development Mac reached both hosts non-interactively over private-address paths; it
was not using a Tailscale address. Tailscale itself is active, enabled, online, and configured to
restart on both hosts. No separate WireGuard interface/tooling was found.

The peer view is asymmetric: `hbox` currently knows and can ping `persvati` over a direct Tailscale
path, while `persvati` does not list `hbox` as a peer and cannot Tailscale-ping it. This may be an
account/share/ACL fact rather than packet loss. Do not “fix” it as part of deployment. A later
authorized networking change must first inspect the tailnet/admin-plane relationship, then prove
both directions and record a transfer canary. Tailscale can use direct or relayed, end-to-end
WireGuard-encrypted paths ([current connection documentation](https://tailscale.com/docs/reference/connection-types)),
but the spool's correctness and private-data protection deliberately do not depend on that
transport.

Both hosts have UFW active, but effective rules were unavailable to the unprivileged inventory.
Both already expose several wildcard listeners. The relevant observed shape was:

| Host | Wildcard TCP listeners observed | Bound/loopback observations | Consequence |
|---|---|---|---|
| `persvati` | 22, 631, 8000, 8021, 8022, 8443, 59780 | additional bound/loopback services and several wildcard UDP sockets | Do not add a Joshi listener; audit ownership/firewall only under separate authority |
| `hbox` | 22, 80, 443, 631, 4001, 8091, 8787, 47166 | additional bound/loopback services and wildcard UDP sockets | Same; especially do not assume ports 80/443 belong to Joshi |

Process ownership for unrelated listeners was intentionally not enumerated. The first replication
adapter should reuse authenticated SSH or a tailnet-only authenticated client/server after that
adapter is reviewed. It must not bind `0.0.0.0`, create public DNS, or weaken UFW. An SSH tunnel is
a transport; the segment digest, domain, generation and authenticated-private envelope remain the
protocol's authority.

## 5. Storage, protection, and replication contract

### 5.1 Local filesystem contract

Each live catalog has exactly one local writer process. Its SQLite catalog, WAL and SHM remain on
the same local crash-durable filesystem, protected by the adjacent writer lease. Neither NFS/SMB,
a shared multi-host filesystem, rsync of a live SQLite directory, nor two writers are supported.

The deployment must supply explicit absolute paths, provisioned by an administrator and owned by a
dedicated `joshi` service identity:

```text
/etc/joshi/                         root-owned non-secret configuration
/var/lib/joshi/catalogs/<catalog>/catalog.sqlite3
/var/lib/joshi/catalogs/<catalog>/blobs/
/var/lib/joshi/catalogs/<catalog>/exports/
/var/lib/joshi/spool/local/          staging/ ready/ acks/ catalog_acks/ quarantine/
/var/lib/joshi/spool/replicas/<replica>/<generation>/
                                     partial/ ready/ acks/ quarantine/
```

On `hbox`, an approved replica root may instead be `/tank/joshi/spool`, provided its temp files are
inside that same filesystem and the unmirrored-special-vdev risk is explicitly accepted. The
current user cannot create that path. Do not put the production service under a personal home,
depend on user linger, or use `/tmp` for durable rename staging.

These subdirectories are the landed `joshi-spool` library contract. The local `SpoolConfig`
requires explicit bounds for segment bytes, entries per segment, total bytes, control-record reserve
and transfer chunk bytes. A `ReplicaConfig` binds one root to an explicit replica ID and generation
plus segment, chunk and total-byte bounds. A protection domain is authenticated segment metadata,
not an invented directory partition. Local evidence admission stops before consuming the configured
control reserve so a pressure/corruption/gap record can still be appended. The replica has its own
hard total bound and must surface exhaustion rather than silently evict bytes.

External CAS and export installation is temp-write, file-fsync, atomic same-filesystem rename, then
directory-fsync. The same sequence applies to spool segments. Catalog paths and immutable artifact
roots must stay explicit; a deployment script must never infer them from `$HOME`.

### 5.2 Protection domains and keys

Spool segments contain exactly one protection domain:

- explicitly public evidence may use an integrity-only envelope;
- private/authenticated Pump responses, operator scenes/notes, and other private-domain material are
  sealed before crossing the remote boundary;
- the authenticated header/AAD binds domain, segment identity, ordered entry closure, and the inner
  plaintext digest/length;
- a replica ACK binds the exact ciphertext envelope digest and length plus replica, generation,
  domain and segment identity. It does not claim decryption or catalog admission; and
- no physical deduplication crosses protection domains.

Transport encryption and disk encryption are additional layers, not substitutes. A pure replica
(`hbox`, and possibly Hetzner) does not receive private-domain decryption keys. The active collector
receives only the key(s) required to seal its assigned domains; the Mac admission process receives
only those required to decode. Key identifiers are non-secret, but key bytes never enter Git,
fixtures, logs, process arguments, shell history, or the spool directory. Key creation, escrow,
rotation, recovery, and destruction need a separate reviewed runbook and explicit authorization.
Key destruction and ciphertext deletion are separately recorded states.

### 5.3 ACK, admission, retention, and outage semantics

A durable remote ACK says only that one replica holds exact segment bytes. It cannot:

- advance a source or catalog cursor;
- allocate catalog commit order;
- declare evidence semantically valid;
- authorize deletion of the collector copy;
- prove an artifact-inclusive catalog backup; or
- promote the replica to writer.

Resume exchanges inventories and byte closures, then retries missing segments idempotently and in
any order. Corrupt or conflicting bytes are quarantined and produce a visible transfer/integrity
problem. Deletion requires a later catalog release plus a separately authorized retention record;
until that path exists, append-only means retain every segment.

Collector death leaves the last durable local segment and remote acknowledged segments intact.
The source interval after the last proven acquisition is a gap. When another collector is assigned,
it starts a new generation with overlap/backfill where the source permits. Host wall clocks are
never used to merge two alleged writer histories.

### 5.4 Catalog backup is a separate closure

The current store can create a consistent SQLite online backup and report the immutable blob/export
paths and digests it references. Its restore hook currently verifies and restores the catalog file
only. Therefore deployment must not claim a complete restore until it can:

1. create the online catalog backup at a named cutoff;
2. snapshot/copy every referenced blob and export at or after that cutoff;
3. verify all digests, counts, protection domains, and absence of missing paths;
4. restore into a new location without overwriting the live catalog; and
5. replay/read representative evidence and compare the expected closure.

ZFS snapshots alone do not protect against `tank`'s special-vdev loss, same-site disaster, silent
application inconsistency, or missing key material. Spool replication alone does not back up an
admitted catalog. Until an off-site target exists, retain copies on the collector, `hbox`, and the
Mac where capacity permits; call that same-site redundancy, not disaster recovery.

## 6. Deployment gates

All of the following must pass before starting a persistent service.

| Gate | `persvati` collector | `hbox` replica/batch | Hetzner later |
|---|---|---|---|
| Supported OS | upgrade/rebuild to supported LTS | upgrade/rebuild to supported LTS | provision supported LTS |
| Dedicated identity | create locked `joshi` system user/group | same | same |
| Local data path | root-owned creation of `/var/lib/joshi`; local FS | root-owned `/tank/joshi` only after risk acceptance, or root FS for small pilot | explicit local volume |
| Private storage | verify disk posture; app AEAD mandatory remotely | app AEAD mandatory; no private keys on replica | app AEAD mandatory; key only if collector |
| Power/restart | 24 h lid/mains/reboot/service-restart trial | reboot/service-restart trial; document no UPS | provider reboot/rebuild trial |
| Connectivity | both-direction authenticated transfer canary | same | private management + both-direction canary |
| Capacity | S0 soak within section 7 thresholds | sustained available-memory and swap gate | measured fsync/network/disk envelope |
| Firewall | effective rules reviewed; no new public listener | same | default deny; no public Joshi listener |
| Backup | second exact segment copy; no auto-deletion | never sole copy; ZFS risk acknowledged | separate failure domain and tested retrieval |
| Secrets | provider-read refs only; no wallet key | no provider or wallet key for pure replica | provider-read refs only if collector |
| Software contract | pinned release artifact and config schema | matching spool reader/writer protocol | matching protocol; staged rollout |

The `hbox` memory gate is: observe at least 24 hours including existing work; require at least 16 GiB
available under the intended service load, no sustained memory PSI, and swap use that is stable and
under an explicitly accepted threshold. If adding the service raises PSI, pushes available memory
below 8 GiB for five minutes, or grows swap materially, stop it and keep `hbox` as cold/manual
storage only. Do not tune ARC or swap without separate host-maintenance authorization.

The `persvati` continuity gate is: keep a canary collector alive for 24 hours across lid-close and
display-idle scenarios Ember actually uses, then one authorized reboot. Prove automatic restart,
fresh source acquisition, fsync, segment inventory, and replay; record every downtime interval as a
gap. A desktop setting screenshot or long pre-test uptime is insufficient.

## 7. Smallest capacity and continuity experiment

This is the first deployable experiment after the gates, with no paid service and no economic
authority:

1. Run fixture/replay validation locally, then a **24-hour S0 canary on `persvati`**: launches,
   migrations, one chosen board surface, at most five hot mints, and at most ten verified followed
   wallets. Use explicit source caps from engineering lane 22.
2. Seal private-domain segments locally. Retain every segment on `persvati`; transfer an exact copy
   to `hbox` if the authenticated path is available. Never delete on remote ACK.
3. Disconnect replication for 30 minutes, reconnect, exchange inventories, and prove idempotent
   out-of-order recovery. Corrupt a disposable fixture segment—not production evidence—and prove it
   is quarantined rather than ACKed.
4. Admit a copied set on the Mac through the sole catalog writer. Prove replica ACK and catalog ACK
   are distinct and that no source cursor advances before catalog admission.
5. Reboot/suspend only under the separately approved host-maintenance step, then prove service
   restart, segment closure, and explicit gap boundaries.

Accept `persvati` for S0/S1 only if, during the measured run:

- no unclassified loss or silent cursor advance occurs;
- p99 acquisition-to-local-durable lag stays below 2 seconds normally and every excursion is
  represented by pressure/coverage evidence;
- replica lag returns below 5 minutes after recovery and an alert is raised after 15 minutes;
- spool growth remains inside the declared 0.1--1 GB/day S0 envelope or the difference is explained;
- free space remains above both 20% and 100 GiB, whichever reserves more space;
- collector average stays within one logical CPU and 2 GiB RSS, with no sustained host PSI; and
- interactive use remains acceptable to Ember.

Crossing a threshold does not automatically buy Hetzner or broaden collection. First reduce payload,
sampling or hot-scope breadth while retaining coverage truth. Consider Hetzner when continuity—not
feature ambition—is the measured blocker. Consider managed streaming only at the separate S1/S2
gates in lane 22.

## 8. Monitoring and graceful degradation

Monitoring should be readable locally or polled over the already authenticated management path.
Do not add a public Prometheus, HTTP, dashboard, or debug listener. Logs are diagnostics, never
evidence, and must redact URLs/query strings, headers, source payloads, credentials, key paths, and
operator/private text.

Required finite-cardinality signals:

- per-source last attempted/received/durable time and declared coverage frontier;
- queue depth/bytes, oldest-item age, dropped/rejected counts and reason;
- open segment age/bytes, fsync/rename failures, local durable watermark;
- per-replica segment/byte lag, last successful canary, retry state, corrupt/quarantined count;
- catalog-admission lag separately from remote durability;
- free bytes/inodes and measured growth by protection domain/retention class;
- process RSS/CPU/file descriptors/restarts; host available memory, swap and PSI;
- NTP sync, boot ID/uptime and detected suspend interval;
- ZFS pool state, errors, scrub age and special-vdev health on `hbox`; and
- source quota/native-unit spend against hard caps, with no automatic overage.

Graceful degradation is ordered: stop media/blob enrichment, slow social polling, reduce hot-lane
TTL/count, retain the launch/migration denominator, then stop collection cleanly before disk or
memory exhaustion. Every scope reduction or queue shed becomes explicit control-plane/coverage
evidence. Never preserve an attractive UI by silently discarding the denominator.

Initial operator thresholds:

- warn at replica lag 5 minutes; page/display critical at 15 minutes;
- warn at 25% disk free, stop new collection before the stricter of 20% or 100 GiB free;
- warn on any pool degradation, checksum/write/read error, or private-envelope verification failure;
- restart on process failure with bounded backoff, but after a restart loop stop and expose the gap;
- on key unavailability, retain source attempts/gap evidence where safe but never downgrade private
  material to public integrity-only bytes; and
- on catalog unavailability, continue bounded remote spooling within disk policy; never mint a fake
  catalog ACK.

## 9. Exact authorization boundary

The authorization used for this document covered only read-only non-interactive inventory and
writing repository documentation/scaffolding. It did **not** authorize any host mutation.

Each of the following needs a new, explicit approval with named hosts and paths:

- upgrading/reinstalling an OS, rebooting, changing suspend/lid/power policy, or tuning ZFS/ARC/swap;
- creating the `joshi` user/group, directories, ownership, quotas, mounts, datasets or snapshots;
- installing a binary/package/container, writing `/etc/joshi`, installing/enabling/starting a
  systemd unit or timer, or scheduling cron;
- changing UFW, router, DNS, SSH, Tailscale membership/ACLs/tags/Tailnet Lock, WireGuard or ports;
- creating, copying, rotating, escrowing or destroying an encryption/provider credential;
- activating a provider API probe that consumes quota or SOL, purchasing Hetzner or any managed
  service, or increasing a spend limit;
- deleting/retaining/migrating an existing spool, catalog, ZFS dataset, snapshot or backup; and
- any transaction construction, wallet read/write, signing, submission, liquidity change or trade.

Approval to deploy a read-only collector never includes wallet authority. Approval to create a
replica never includes decryption keys. Approval to receive a durable segment never includes
permission to delete its source copy. Approval to repair `tank` never follows from Joshi deployment
and requires its own backup-aware storage plan.

## 10. Deployment artifact posture

[`deploy/README.md`](../../deploy/README.md) records the host-agnostic path, privilege, listener,
credential and preflight contract. An executable systemd unit is intentionally deferred until the
spool/acquisition binary exposes a stable CLI and graceful-shutdown/health contract. Shipping an
invented `ExecStart` now would be less reproducible than the explicit requirements.

When that CLI exists, generate a reviewed unit from the contract rather than hand-editing a host:

- system `User=joshi`, `Group=joshi`, `UMask=0077`;
- no capabilities, privilege escalation, writable home, device access or wallet material;
- write access only to the one explicit state/spool root;
- outbound/source and authenticated-replication address families only;
- bounded file descriptors/memory/restart loop and graceful stop long enough to seal a segment;
- credentials delivered by path/runtime credential facility, never environment value or argument;
- no listener unless a later adapter names its address, authentication and firewall contract; and
- a preflight that rejects unsupported OS, non-local state FS, wrong ownership/mode, low disk,
  missing key, duplicate writer lease, protocol mismatch or failed transfer canary.
