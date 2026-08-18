# Third-party notices

This repository contains or depends on third-party software. Those components remain under their
own licenses; Joshi's `AGPL-3.0-or-later` license does not replace their notices or terms.

This file records hand-reviewed exceptions and attribution requirements. It is **not** the complete
machine-generated notice bundle required for a release. Release artifacts must generate and retain
the full license/notice inventory from the exact Rust, npm, and Python lockfiles as described in
[`docs/implementation/LICENSING.md`](docs/implementation/LICENSING.md).

## TradingView Lightweight Charts

`apps/glass` uses `lightweight-charts` 5.2.1 under the Apache License 2.0. Its upstream notice is:

> TradingView Lightweight Charts™  
> Copyright (с) 2025 TradingView, Inc. <https://www.tradingview.com/>

The upstream package requires an attribution notice and link to TradingView in the user-visible
application. Joshi keeps the library's `attributionLogo` enabled. A replacement chart or custom
layout must preserve an equivalent visible attribution and link while this dependency is present.
The package also identifies incorporated `tslib` portions under the BSD Zero Clause License.

Sources: [package repository](https://github.com/tradingview/lightweight-charts/tree/v5.2.1),
[license and attribution instructions](https://github.com/tradingview/lightweight-charts/blob/v5.2.1/README.md#license),
and [upstream notice](https://github.com/tradingview/lightweight-charts/blob/v5.2.1/NOTICE).

## `backslash`

Both npm lockfiles resolve `backslash` 0.2.2. The npm manifest omits its `license` field, but the
upstream repository includes an MIT license and identifies copyright (c) 2015 JD Ballard. Treat
this as a manual license exception until the package is removed or replaced; preserve the upstream
MIT text in any distribution containing the package.

Sources: [upstream license](https://github.com/Qix-/node-backslash/blob/master/LICENSE) and
[repository](https://github.com/Qix-/node-backslash).

## Evidence, fixtures, and provider material

Some fixtures are synthetic and some retain shapes or observations originating outside Joshi.
Their source and fidelity are described in:

- [`fixtures/sources/README.md`](fixtures/sources/README.md);
- [`fixtures/accounting/README.md`](fixtures/accounting/README.md);
- [`fixtures/tape/README.md`](fixtures/tape/README.md); and
- per-snapshot and per-export manifests.

No blanket ownership or relicensing claim is made for third-party, provider-derived, captured, or
user-supplied content. Public availability is not a license. A public release must exclude any
artifact whose provenance, redistribution permission, privacy class, or required attribution is
unknown.
