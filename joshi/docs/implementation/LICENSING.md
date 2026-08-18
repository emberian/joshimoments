# Licensing and release posture

Status: active implementation policy  
Audit date: 2026-08-16  
Project license: `AGPL-3.0-or-later`

This document is an engineering compliance policy, not legal advice. It records the repository's
chosen license, the present dependency audit, and the checks required before source publication,
binary distribution, extension distribution, or operation of a modified network service.

## 1. Project licensing decision

Unless a file or provenance record says otherwise, original Joshi source code and original project
documentation are licensed under the **GNU Affero General Public License, version 3 or any later
version**, using the SPDX identifier `AGPL-3.0-or-later`.

Canonical metadata:

| Surface | Required value |
|---|---|
| Repository license file | Root `LICENSE`, unmodified GNU AGPL version 3 text |
| SPDX expression | `AGPL-3.0-or-later` |
| Rust workspace | `[workspace.package] license = "AGPL-3.0-or-later"`; member crates inherit it |
| npm packages | `"license": "AGPL-3.0-or-later"` even while `private: true` |
| Python package | PEP 621 `license = "AGPL-3.0-or-later"` |
| Copyright notice | `Copyright (C) 2026 Joshi contributors` unless a file has a more specific accurate notice |

The SPDX “or later” choice is intentional. Do not shorten it to `AGPL-3.0`, use the deprecated
ambiguous `AGPL-3.0`, or replace it with `AGPL-3.0-only` in a subpackage.

The root `LICENSE` is the canonical legal text. The Python build context contains a byte-identical
`analysis/LICENSE` so wheel/sdist metadata can carry the license without reaching outside its
package root; release checks must reject drift between the two. Package manifests and source
headers identify the license; they do not paraphrase or modify it. The official text and
identifiers are available from the
[GNU license page](https://www.gnu.org/licenses/agpl-3.0.html), [plain-text
license](https://www.gnu.org/licenses/agpl-3.0.txt), and [SPDX
record](https://spdx.org/licenses/AGPL-3.0-or-later.html). Cargo accepts SPDX expressions in its
[`license` field](https://doc.rust-lang.org/cargo/reference/manifest.html#the-license-and-license-file-fields);
the Python and npm equivalents are described by the [Python packaging
guide](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#license-and-license-files)
and [npm package metadata](https://docs.npmjs.com/cli/v11/configuring-npm/package-json#license).

## 2. What the project license does and does not cover

The project license covers copyrightable first-party source and documentation contributed under
that license. It does not erase or replace:

- dependency licenses, notices, trademarks, or attribution conditions;
- provider terms of service or API agreements;
- copyright, database rights, privacy interests, or publicity rights in captured material;
- fixture provenance and redistribution restrictions;
- secret, wallet, authenticated, personal, or user-supplied data classifications; or
- license requirements of generated code or vendored schemas derived from another project.

Do not add “all files are AGPL” language to fixture directories. A project-authored synthetic
fixture may state `AGPL-3.0-or-later` in its manifest when that claim is known to be accurate.
Captured/provider-derived bytes retain their own provenance and may need to remain private or be
excluded from a release. Code that reads a dataset and data emitted by a program are not
automatically the same licensing question.

## 3. AGPL network and distribution posture

AGPL section 13 adds an obligation for a modified version that users interact with remotely over a
network: the modified program must prominently offer those users the Corresponding Source through
a standard or customary means, at no charge. The safest product posture is a persistent **Source**
link in every remotely served modified UI, pointing to the exact deployed revision or a source
archive for it—not merely to an unrelated upstream branch.

Object-code distribution also requires one of the source-access methods permitted by the license.
An app bundle, browser extension package, container image, downloadable binary, or hosted modified
service must therefore be paired with the correct source and notices for that exact build.

“Corresponding Source” is broader than the hand-written Rust/TypeScript/Python files. For Joshi it
normally includes the exact source revision, schemas and migrations, build scripts, interface
definitions, package manifests and lockfiles, patches, configuration needed to build/install/run,
and any other non-System-Library material required to generate and operate the work. It does not
mean publishing private user data, credentials, wallet secrets, or captured evidence. Those must be
excluded from source archives and supplied through documented safe configuration mechanisms.

No contributor, agent, or release job may publish or deploy merely because this policy exists.
Publication, hosting, store submission, and external account creation remain separate user-authorized
actions.

## 4. Current dependency compatibility audit

The audit inspected the resolved local lockfiles and installed metadata on 2026-08-16. It is a
point-in-time gate, not approval of future versions.

### Rust workspace

The post-scaffold `cargo metadata --locked` snapshot reports 251 package records, including nine
first-party workspace crates, and **zero missing license expressions**.
The current dependency paths offer MIT, MIT-0, Apache-2.0, ISC, BSD-2-Clause, BSD-3-Clause, Zlib,
Unicode-3.0, CDLA-Permissive-2.0, CC0-1.0, Unlicense, or other permissive alternatives. Conjunctive
expressions such as `Apache-2.0 AND ISC` are also permissive. The two `r-efi` generations offer
`MIT OR Apache-2.0 OR LGPL-2.1-or-later`; Joshi relies on the MIT/Apache permission, not the LGPL
alternative. `ryu-js` offers Apache-2.0 instead of needing its BSL alternative.

No resolved Rust dependency is GPL-2.0-only, proprietary, source-available-only, or otherwise known
to conflict with an AGPLv3 combined work. Apache License 2.0 is compatible with GPLv3-family terms;
see the [Apache Software Foundation compatibility
explanation](https://www.apache.org/licenses/GPL-compatibility.html) and the [GNU license
list](https://www.gnu.org/licenses/license-list.html).

Caveats:

- metadata compatibility does not replace review of bundled files, notices, build scripts, unsafe
  code, patents, or export controls;
- slash-form expressions such as `MIT/Apache-2.0` are legacy metadata and should be normalized by
  upstream, but currently provide a permissive route;
- release notice generation must choose and retain an allowed license path for dual-licensed
  packages instead of deleting upstream texts; and
- optional protocol packages are not approved merely because their transitive crates are
  compatible.

### TypeScript applications

The exact npm lockfiles contain 170 package entries for `apps/glass` and 223 for the companion.
All current third-party runtime dependency paths are MIT, ISC, or Apache-2.0 **except**
`backslash` 0.2.2, whose npm manifest has no license field. Its upstream repository supplies an MIT
license; this is recorded as a manual exception in
[`THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md).

MPL-2.0 appears in current dev/build tooling (`axe-core` and the `lightningcss` package family), not
as an application runtime library. Retain the MPL source/license obligations whenever those
packages themselves are redistributed. Do not copy their source into Joshi and relabel it AGPL.
MPL 2.0's secondary-license rules are described in the [Mozilla MPL
FAQ](https://www.mozilla.org/en-US/MPL/2.0/FAQ/); any package or source file marked “Incompatible
With Secondary Licenses” needs individual review before combining source rather than invoking the
secondary-license route. Using a separately licensed build tool to produce Joshi output does not
relicense the tool.

`lightweight-charts` 5.2.1 is Apache-2.0 and imposes a specific TradingView attribution/link
requirement. The UI must keep its attribution logo enabled or provide an equivalent visible notice
and link. A disabled logo without an alternative is a release blocker.

### Python analysis package

The locked environment currently resolves nine distributions. PyArrow is Apache-2.0; DuckDB's
installed metadata exposes an MIT classifier rather than a modern SPDX expression; the remaining
runtime/dev packages expose MIT, Apache-2.0, or BSD-2-Clause paths. No present Python dependency is
a known AGPL compatibility conflict. Binary wheels may bundle additional third-party components,
so a distributable analysis environment must retain the license/notice files from the exact wheels
rather than treating top-level PyPI metadata as exhaustive.

### Result

The current first-party code can be licensed `AGPL-3.0-or-later` without a known dependency-license
conflict. This is a **conditional pass**: correct notices, TradingView attribution, the manual
`backslash` exception, fixture provenance, and release-time lockfile audits remain mandatory.

## 5. Optional protocol SDK policy

Protocol SDKs and generated IDLs are high-risk because “official,” public, or available on GitHub
does not itself grant redistribution rights.

A protocol SDK may enter a production dependency graph only when all of the following are recorded:

1. exact registry version and checksum or immutable source revision;
2. declared SPDX expression and the actual license text in the artifact/repository;
3. copyright holder and the scope covered by that license;
4. any generated-code, IDL, trademark, attribution, patent, or data-use terms;
5. an AGPL compatibility determination for how Joshi links, copies, modifies, or distributes it;
6. complete transitive license/notice inventory; and
7. a private adapter boundary plus conformance fixtures, so rejection remains cheap.

If license metadata is missing or the repository/license scope is ambiguous:

- do not copy code, generated files, or formulas whose copyright status is unclear;
- do not add the package to production, release, or vendored source trees;
- a separate, unshipped research probe may inspect behavior without becoming a product dependency;
- retain only independently obtained facts, clean-room specifications, and fixtures whose
  redistribution rights are known; and
- request clarification from the rights holder before changing the gate.

This keeps the current Meteora Rust repository probe blocked for production because the relevant
Rust package/repository lacks clear license metadata. Its ISC TypeScript package may serve only in
the separately bounded role already documented. Pump's published Rust package declares MIT, but it
still requires exact tarball/checksum provenance and adapter quarantine; permissive licensing does
not resolve its broad Anchor/Solana graph or execution-capability risks.

## 6. Fixture and generated-artifact rules

Every retained or distributed fixture/artifact manifest must identify, where applicable:

- creator/source/provider and retrieval or generation date;
- whether it is synthetic, observed, transformed, or exact-byte retained;
- source URL/API/document and immutable revision/version;
- exact digest and transformation/generator version;
- copyright/license or redistribution permission, including required attribution;
- privacy/protection domain and whether public release is allowed;
- presence of personal data, wallet addresses, authentication material, or secrets; and
- dependencies or schemas embedded in generated output.

Rules:

- Unknown license or redistribution permission means **do not publish**; it does not mean AGPL.
- Never include secrets, authenticated URLs, signing material, private wallet state, or private
  captured responses in a source offer or public fixture bundle.
- Generated source retains generator/input provenance. Do not remove an upstream header or replace
  it with a Joshi copyright notice.
- Compiled/minified bundles must preserve applicable license banners and be accompanied by the
  complete generated notice set.
- Research output manifests state their input rights and release classification. Running an AGPL
  program over data does not by itself settle the output data's copyright or disclosure status.
- Golden fixtures copied from another repository or provider remain separately attributed; edits
  must record the transformation rather than implying original authorship.

## 7. Source-publication and release checklist

Run this checklist for each exact tag/build. A prior release's result cannot approve a new lockfile.

### Rights and provenance

- [ ] Root `LICENSE` matches the canonical GNU AGPLv3 text; manifests say
  `AGPL-3.0-or-later`.
- [ ] Contributor and imported-code provenance is known; no prior-repository code was copied under
  an incompatible or absent license.
- [ ] Every fixture/export is classified public, private, excluded, or separately licensed.
- [ ] Optional SDKs and generated IDLs meet §5; unclear-license probes are absent.
- [ ] Trademarks and required product attributions, including TradingView, are visible and correct.

### Exact dependency inventory

- [ ] Rust: `cargo metadata --locked`, `cargo tree --workspace --target all --duplicates`, `cargo deny`,
  `cargo audit`, and generated license notices pass against the committed lock.
- [ ] npm: both package locks are unchanged by clean install, production and dev license inventories
  are reviewed, and allowed install scripts remain explicit.
- [ ] Python: `uv sync --locked` is clean; wheel/sdist licenses and bundled third-party notices are
  collected from the artifacts actually distributed.
- [ ] Every missing/custom/deprecated license expression has a documented manual decision; no
  automatic “unknown = allowed” rule exists.
- [ ] SBOM and notice bundle correspond to the exact shipped artifacts and architectures.

### Corresponding Source

- [ ] The source archive/repository points to the exact deployed/distributed commit and includes
  build/install scripts, schemas, migrations, interface definitions, manifests, lockfiles, and
  necessary patches/configuration templates.
- [ ] A clean machine can build the object artifacts from that source without private files.
- [ ] License, copyright, warranty, and third-party notices survive source and object packaging.
- [ ] Downloaded binaries/extensions/containers use a source-access method permitted by the AGPL.
- [ ] Every remotely usable modified UI prominently offers no-charge Corresponding Source for its
  exact running version through a stable **Source** link.

### Privacy and release safety

- [ ] Secret/path/authenticated-URL scans pass for repository, history, build output, source archive,
  logs, maps, fixtures, and SBOM.
- [ ] Source maps and debug artifacts contain no private paths or captured values.
- [ ] Public release archives exclude operational databases, CAS data, research run outputs, browser
  profiles, credentials, wallets, and private evidence.
- [ ] The user has separately authorized the particular publication, deployment, store upload, or
  release action.

## 8. Audit commands

These commands are inventory inputs, not legal conclusions:

```sh
cargo metadata --format-version 1 --locked
cargo tree --workspace --target all --duplicates
cargo audit
cargo deny check

npm --prefix apps/glass install --ignore-scripts --package-lock-only
npm --prefix extensions/pump-companion install --ignore-scripts --package-lock-only

uv --directory analysis sync --locked
```

Release automation should additionally generate full third-party notices and an SBOM from the
resolved artifacts. Keep hand-reviewed exceptions in `THIRD_PARTY_NOTICES.md`; never overwrite that
file with a generator.
