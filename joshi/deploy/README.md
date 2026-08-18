# Joshi deployment scaffold

Status: **inert contract only**. Nothing in this directory installs, configures, starts, exposes,
or purchases anything.

The current remote-host decision and inventory are in
[`docs/implementation/REMOTE_TOPOLOGY.md`](../docs/implementation/REMOTE_TOPOLOGY.md). Both
inventoried hosts are currently deployment-blocked by end-of-life operating systems. Do not turn
this scaffold into commands until Ember separately authorizes the named host mutations.

## Host-agnostic variables

A future deployment renderer must require these values explicitly; it must not infer them from a
login home, ambient working directory, remote mount, or hostname convention.

| Value | Contract |
|---|---|
| `service_user` / `service_group` | dedicated locked system identity; normally `joshi` |
| `state_root` | absolute local crash-durable filesystem root; normally `/var/lib/joshi` |
| `catalog_id` | stable catalog identity, not a hostname |
| `catalog_path` | exact SQLite path; WAL/SHM/writer lock remain adjacent |
| `blob_root` | explicit immutable CAS root on a local filesystem |
| `export_root` | explicit immutable export root on a local filesystem |
| `local_spool_root` | exact append-only origin root; fixed subdirectories below |
| `replica_root` | exact root for one replica ID and generation; fixed subdirectories below |
| `replica_id` / `generation` | protocol identities, never inferred from an IP |
| `protection_domain` | one declared domain per segment; no cross-domain physical dedup |
| `credential_paths` | root-provisioned references or runtime credentials; never secret values |
| `resource_limits` | measured memory, file-descriptor and queue bounds |
| `spool_bounds` | max segment bytes, entries/segment, total bytes, control reserve, transfer chunk bytes |
| `replica_bounds` | max segment, chunk and total bytes |
| `source_caps` | explicit request/message/native-unit/no-overage limits |

Suggested path shape, subject to host-specific approval:

```text
/etc/joshi/                         # root-owned non-secret config only
/var/lib/joshi/catalogs/<catalog>/catalog.sqlite3
/var/lib/joshi/catalogs/<catalog>/blobs/
/var/lib/joshi/catalogs/<catalog>/exports/
/var/lib/joshi/spool/local/          staging/ ready/ acks/ catalog_acks/ quarantine/
/var/lib/joshi/spool/replicas/<replica>/<generation>/
                                     partial/ ready/ acks/ quarantine/
```

`hbox` may later substitute an explicitly approved `/tank/joshi/...` replica root. That is not an
authorization or a durability claim; its current pool has an unmirrored special vdev and no native
encryption.

Those subdirectory names and bound fields match the transport-neutral `joshi-spool` library.
Protection domain is authenticated in each segment envelope; it is not inferred from a path. The
library currently provides synchronous filesystem primitives, not a daemon, listener, transport,
configuration parser or service CLI.

## Required renderer outputs

Once the runtime CLI is stable, a deployment renderer may produce, for review:

1. root-owned closed-schema configuration with absolute paths and non-secret key identifiers;
2. a least-privilege systemd **system** unit using the dedicated identity and `UMask=0077`;
3. an optional bounded timer only for a pull/verify operation whose idempotency is tested;
4. a preflight report that prints no addresses, tokens, key paths or source payloads; and
5. uninstall/rollback instructions that stop the unit but preserve data by default.

The unit must have no ambient/capability bounding set, no writable home, no arbitrary device or
kernel access, and write access only to the selected state root. It must use bounded restart/backoff
and a graceful shutdown long enough to seal/fsync the current segment. It must not bind a public
listener. A listener template is allowed only after an adapter specifies its exact loopback or
tailnet bind, mutual authentication, request bounds, replay protection, firewall rule and coverage
failure semantics.

An executable unit is intentionally absent today: the acquisition/spool binary does not yet expose
a stable operator CLI, health command, config schema, or shutdown interface. An `ExecStart` guessed
in advance would be an unsafe deployment artifact rather than scaffolding.

## Preflight must fail closed

Before any start, the eventual preflight must reject:

- unsupported/EOL OS or an unreviewed upgrade state;
- missing/wrong service identity, ownership, modes, or absolute paths;
- NFS/SMB/shared storage for SQLite or spool temp/rename across filesystems;
- a held catalog writer lease or a request for more than one catalog writer;
- less free space than both the configured bound and the topology stop floor;
- unavailable private-domain sealing key or an attempted private-to-public downgrade;
- unknown protocol/config version, replica ID, generation or protection domain;
- failed authenticated transfer canary where replication is required; and
- an absent source quota/spend cap.

Remote durability ACK, catalog admission ACK, retention authorization and deletion evidence are
distinct protocol objects. No script may translate one into another or remove a segment merely
because a copy command returned zero.

## Mutation checklist

Every future deployment change should be presented as a dry-run diff naming:

- host and supported OS version;
- users/groups and exact paths/modes/owners to create;
- packages/artifacts and verified digests;
- unit/config files to write and their non-secret diff;
- credentials by purpose and reference, never value;
- listeners/firewall/Tailscale changes (normally none);
- source calls and worst-case quota/native-unit/currency effect;
- start/restart/reboot actions;
- rollback that preserves evidence; and
- any deletion, key destruction or storage repair as a separate destructive action.

Only the items Ember explicitly approves may be applied. Read-only collection authority never
implies wallet, signing, transaction, liquidity, trade, purchase, or overage authority.

## Wave 4 dry-run packet

[`wave4/README.md`](wave4/README.md) indexes the W4-09 review artifacts. They are intentionally
inert: the host inventory is read-only, mutation packets are data rather than installers, and the
service/config render is explicitly blocked while `joshi-collector` has no live `run` contract.
No file in that directory contacts, mutates, repairs, provisions, starts, or purchases a host.
