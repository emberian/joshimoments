# Release closure packet

Status: **required layout; no release exists and no install is authorized**  
Packet date: 2026-08-17

A future reviewed bundle has exactly this shape, where `<release-id>` is immutable and appears in
`RELEASE_MANIFEST.yaml`:

```text
<release-id>/
  bin/
    joshi-collector                 # or the separately frozen replica executable
  source/
    joshi-source-<release-id>.tar.zst
  LICENSE
  THIRD_PARTY_NOTICES.md
  SOURCE_OFFER.txt
  dependency-licenses.json
  sbom.spdx.json
  RELEASE_MANIFEST.yaml
  SHA256SUMS
```

The source archive is Corresponding Source for the exact binary: immutable release revision,
`Cargo.toml`, locked `Cargo.lock`, `rust-toolchain.toml`, build/install instructions, schemas,
migrations, and only those fixtures whose publication provenance permits distribution. It excludes
credentials, private evidence, provider session material, operator-private text, and authenticated
response bodies. `SOURCE_OFFER.txt` names the adjacent archive and its digest or an equally exact,
immutable public revision. It may not point at a branch.

The release builder must generate an SPDX 2.3 JSON SBOM for the locked target, a dependency-license
inventory, third-party notices, audit reports, and the complete digest manifest. The release
manifest binds their paths, byte lengths, SHA-256 values, target triple, compiler, lockfile, build
command, source revision, and verification reports. Signing may be added only after a key custody
policy is separately approved; an unsigned bundle must not pretend a digest is provenance.

## Offline verification order

Run these from the reviewed extracted bundle as an unprivileged reviewer, before any copy to a host
install path:

```text
/usr/bin/sha256sum --check SHA256SUMS
/usr/bin/test -f RELEASE_MANIFEST.yaml
/usr/bin/test -f sbom.spdx.json
/usr/bin/test -f dependency-licenses.json
/usr/bin/test -f THIRD_PARTY_NOTICES.md
/usr/bin/test -f LICENSE
/usr/bin/test -f SOURCE_OFFER.txt
/usr/bin/test -f source/joshi-source-<release-id>.tar.zst
```

The literal `<release-id>` must be replaced by the manifest value in the final reviewed packet; no
shell interpolation or glob belongs in an approved host command. A reviewer then checks that every
manifest length/digest matches, the SBOM and license inventory match the exact `Cargo.lock` and
target, the source archive reconstructs the release, and all `false`/`UNRESOLVED` fields in
`RELEASE_MANIFEST.required.yaml` are closed. Failure quarantines the bundle outside live paths by
digest; it never triggers an install.

The current repository has an unborn `HEAD`, and no collector/replica release binary exists. That
is an intentional hard stop, not a value to fill with a working-tree hash.
