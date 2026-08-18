# Reusable graph, field, and modeling toolbox

Status: dependency and modeling boundary; no packages added  
Survey date: 2026-08-16  
Target platforms: Apple arm64 development; Linux arm64/x86-64 batch execution  
Project license: `AGPL-3.0-or-later`

## 1. Decision

Joshi should begin with one conservative Python scientific stack and a handful of explicit,
testable mathematical constructions—not a second analytics platform in Rust and not a graph or
probabilistic framework embedded in the recorder.

The recommended center is:

- existing DuckDB and PyArrow for frozen input/output;
- NumPy and SciPy for arrays, sparse matrices, linear algebra, optimization, distributions, and
  numerical integration;
- NetworkX for inspectable typed graph snapshots;
- statsmodels for classical state-space, duration, and statistical diagnostics;
- scikit-learn for preprocessing, simple baselines, metrics, and calibration;
- Matplotlib for deterministic static research figures; and
- small Joshi-owned implementations where coverage, orientation, censoring, replay, or evidence
  meaning is the algorithm.

Rust stays responsible for exact facts, bounded reduction, online safety, and export contracts.
`petgraph`, `nalgebra`, `sprs`/`faer`, `num-dual`, or an optimizer enter Rust only after a named
online or promoted-model workload proves that Python artifacts are insufficient. No modeling
dependency belongs in acquisition, evidence, accounting, storage, or protocol crates.

Specialized Hawkes, survival, GraphBLAS, simplicial, topological, autodiff, and probabilistic
libraries are useful as differential or performance probes. They do not own Joshi's temporal risk
sets, coverage semantics, graph ontology, field orientation, or claims.

## 2. Decision vocabulary

| State | Meaning |
|---|---|
| **Adopt** | Approved when the first named experiment uses it; add to a bounded analysis group and lock exact artifacts. |
| **Probe** | Compare against an explicit baseline on frozen fixtures; no durable artifact may require it yet. |
| **Defer** | Plausible only after a scale, model-family, or deployment threshold is demonstrated. |
| **Reject** | Do not introduce in the current architecture; the dependency or abstraction is actively misleading or redundant. |

“Adopt” is not permission to put every approved package in the next lockfile. The smallest valid
environment is still the environment needed by the current registered experiment.

## 3. Live estate and compatibility constraints

At survey time:

- `analysis` supports Python `>=3.12,<3.15` and locks only DuckDB 1.5.5, PyArrow 25.0.1, pytest,
  Ruff, and packaging/build support;
- the Rust lock contains exact accounting integers/rationals, `ruint`, Rusqlite, transport and
  evidence primitives, but no graph, ndarray, BLAS, optimization, autodiff, or ML framework;
- the glass uses React, Lightweight Charts, and no graph-layout package; and
- Rust Arrow/Parquet 59.2 is an approved export dependency but had not entered the live lock.

This clean separation is an asset. Python and Rust package version numbers do not have to match to
exchange standards-compliant Parquet or Arrow IPC. They do have to agree on a conservative schema,
units, null meaning, identities, event/known clocks, snapshot manifest, and logical digest.

The dependency estate was changing concurrently during the survey. Version numbers below are
current registry releases, not root-manifest instructions. Re-resolve and repeat license/wheel/tree
checks when a package is actually introduced.

## 4. Executive matrix

### 4.1 Python research layer

| Area | State | Package/current line | Joshi role | Boundary or concern |
|---|---:|---|---|---|
| Dense arrays | Adopt | NumPy 2.5.2, BSD-family | Numeric feature arrays, simulation, vectorized explicit estimators | Never coerce exact monetary/protocol truth into float before export. |
| Sparse/linalg/optimization | Adopt | SciPy 1.18.0, BSD-3-Clause | CSR/CSC, sparse solves, `optimize`, distributions, integration | Native wheel and BLAS runtime; preserve bundled notices and cap threads. |
| Tabular model adapters | Adopt only as needed | pandas 3.0.5, BSD-3-Clause | Compatibility edge for statsmodels/sklearn, never snapshot authority | Keep DuckDB/Arrow as cohort and interchange truth. |
| Small graph snapshots | Adopt | NetworkX 3.6.1, BSD-3-Clause | Typed directed multigraph exploration and reference algorithms | Python objects are derived and ephemeral; never pickle as evidence. |
| Classical inference | Adopt | statsmodels 0.14.6, BSD-3-Clause | State-space/Kalman, GLM, duration/PH baselines, diagnostics | Design matrices and time/risk sets remain manifested Joshi artifacts. |
| Baselines/calibration | Adopt | scikit-learn 1.9.0, BSD-3-Clause | Pipelines, simple models, Brier/log loss, isotonic/sigmoid calibration | Custom temporal/group splits; default IID CV is forbidden. |
| Static research figures | Adopt at report consumer | Matplotlib 3.11.1, PSF-compatible | Versioned PNG/SVG/PDF report figures | Native/font notice bundle; figures are renderings, not evidence. |
| Survival ergonomics | Probe | lifelines 0.30.3, MIT | Aalen–Johansen, Cox/time-varying exploratory oracle | Pins pandas `<3`; autograd/formula stack; do not make it the only estimator. |
| Hawkes oracle | Probe | `tick` 0.8.0.2, BSD-3-Clause | Differential fit/simulation for supported kernels | Large C++/NumPy/SciPy/sklearn stack; PyPI metadata lacks project URLs despite a current upstream tag. |
| Hawkes oracle | Probe | HawkesPyLib 0.3.0, MIT | Small simulation/fit cross-check | Numba/native-JIT graph and narrow model family; never source of coverage semantics. |
| Faster graph algorithms | Probe | rustworkx 0.18.1, Apache-2.0 | Performance comparison for immutable snapshots | Native Rust wheel; index semantics must not escape into project IDs. |
| Sparse graph algebra | Probe | python-graphblas 2025.2.0 + SuiteSparse GraphBLAS 10.4.1, Apache-2.0 | Semirings, large adjacency/incidence algebra | Native SuiteSparse/OpenMP-like thread budget and a second sparse API. |
| Simplicial/cell oracle | Probe | TopoNetX 0.4.0, MIT | Boundary/Hodge differential tests | Heavy `pandas/pyarrow/trimesh/requests` graph; no network use in canonical jobs. |
| Hypergraph oracle | Probe | XGI 0.10.2, BSD-3-Clause | Higher-order relation representation comparison | Broad plotting/pandas stack; typed Joshi bundle/simplex rows remain authority. |
| Persistent topology | Defer | GUDHI 3.13.0, MIT | A named filtration/persistence hypothesis only | Native C++ wheels; powerful answer to a question not yet established. |
| Conformal methods | Probe | MAPIE 1.5.0, BSD-3-Clause | Rolling/block conformal comparison | Default exchangeability assumptions do not hold for adaptive market time. Avoid large extras. |
| Autodiff/probabilistic | Defer to isolated group | JAX/JAXlib 0.11.0, Apache-2.0 | Custom differentiable likelihood after explicit baseline | XLA native runtime, compilation cache, device-specific numerics, large resolver surface. |
| Bayesian inference | Defer to one-family bakeoff | NumPyro 0.21.0, Apache-2.0 **or** PyMC 6.3.1, Apache-2.0 | Hierarchical uncertainty when data/support justify it | Pick one, not both; retain sampler diagnostics and exact likelihood inputs. |
| State-space framework | Defer | DynaMax 1.0.2, MIT | Nonlinear/HMM/SSM after statsmodels limit | Pulls JAX, `tfp-nightly`, Optax and sklearn; nightly dependency is a reproducibility warning. |
| Convex modeling | Defer | CVXPY 1.9.2, Apache-2.0 | A declared convex allocation/fit problem | Solver matrix adds native packages and differing licenses; SciPy first. |
| GPL/native survival | Defer | scikit-survival 0.28.0, GPL-3.0-or-later | Survival forests/SVM only after simpler models fail | AGPL-compatible but non-permissive, compiled, and pulls OSQP/ECOS/sklearn. |
| Temporal graph DB | Reject now | Raphtory 0.18.5, GPL-3.0 | None in canonical pipeline | Duplicates temporal truth and query semantics; large native runtime and non-permissive license. |
| Legacy Hawkes package | Reject | `hawkeslib` 0.2.2, MIT | None | Last release 2019, CPython 3.6 wheel, Python 2-era metadata. |
| Second dataframe engine | Reject now | Polars 1.43.2, MIT | None | DuckDB/PyArrow already own the batch boundary; adds another Arrow/Rust engine and semantics. |

### 4.2 Rust online/promoted layer

| Area | State | Crate/current line | Feature policy and role |
|---|---:|---|---|
| Derived graph snapshot | Probe | `petgraph` 0.8.3, MIT/Apache-2.0 | Defaults off; `std,stable_graph` only if needed. Store Joshi IDs as weights; indices never persist. |
| Small fixed-state algebra | Probe | `nalgebra` 0.35.0, Apache-2.0 | Default `std,macros` is acceptable for a named Kalman/filter module; do not make it an ambient domain type. |
| Sparse assembly | Defer/probe | `sprs` 0.11.5, MIT/Apache-2.0 | Defaults off to avoid legacy `alga` and automatic Rayon; CSR/CSC only after a Rust Hodge/graph consumer exists. |
| Sparse factorization | Defer/probe | `faer` 0.24.4, MIT | Defaults off; select `std,linalg,sparse-linalg`; measure compile size, SIMD and Rayon oversubscription. Do not carry both `sprs` and `faer` without a conversion gate. |
| Low-dimensional derivatives | Probe | `num-dual` 0.15.0, MIT/Apache-2.0 | Defaults off to avoid `nalgebra`; scalar dual/hyperdual derivative oracle for explicit likelihoods. No Python/PyO3 feature. |
| Generic optimizer | Defer | `argmin` 0.11.0, MIT/Apache-2.0 | Defaults off; only after a promoted Rust likelihood names its objective, gradient and stop rule. |
| Conic optimizer | Defer | `clarabel` 0.11.1, Apache-2.0 | Pure-Rust default path; no BLAS/MKL features. Named convex problem and SciPy comparison required. |
| Distribution functions | Defer/probe | `statrs` 0.19.1, MIT | Defaults off, `std` only; use for a named online tail/CDF calculation, not research statistics. |
| N-dimensional arrays | Defer | `ndarray` 0.17.2, MIT/Apache-2.0 | No `blas`; only if a Rust batch consumer proves Arrow arrays/purpose-built loops insufficient. |
| LAPACK binding | Reject | `ndarray-linalg` 0.18.1, MIT/Apache-2.0 | Forces BLAS/LAPACK backend selection and duplicate native-runtime risk for work Python already owns. |
| QP FFI | Reject now | `osqp` 1.0.1, Apache-2.0 | C FFI/build surface and stale docs link; Clarabel/SciPy are cleaner candidates if a QP appears. |
| Rust ML frameworks | Reject now | Linfa 0.8.1; Burn 0.22 pre; Candle 0.11 | Duplicate the Python research ecology and pull ndarray/BLAS/tensor backends without a serving contract. |
| Rust GraphBLAS/topology search results | Reject | assorted FFI/young crates | No established need; current Hodge semantics are safer as explicit SciPy matrices and goldens. |
| Arrow implementation | Adopt at exporter | official `arrow`/`parquet` 59.2 family, Apache-2.0 | Exact family pin; Parquet durable, Arrow record batches transient. |
| Alternate Arrow | Reject | archived `arrow2` 0.18.0, Apache-2.0 | Upstream archived in 2024; do not create a second Arrow type universe. |

### 4.3 Glass and visualization

| State | Package/current line | Use |
|---:|---|---|
| Adopt incrementally | `d3-array` 3.2.4, `d3-scale` 4.0.2, `d3-shape` 3.2.0; ISC | Individual deterministic scales, bins, and SVG paths. Do not add the full D3 bundle by habit. |
| Probe | Cytoscape.js 3.34.1, MIT | Bounded typed wallet/identity/territory neighborhood with keyboard-accessible companion table. |
| Defer | Graphology 0.26.0 + Sigma 3.0.3, MIT | WebGL graph only if Cytoscape/canvas measurement fails at a declared node/edge budget. |
| Defer | Observable Plot 0.6.17, ISC; Vega-Lite 6.4.3, BSD-3-Clause | Reproducible exploratory specs, not a second glass rendering framework. |
| Keep | Lightweight Charts 5.2.1, Apache-2.0 | Time series, kernel overlays, transition/event markers; retain required TradingView attribution. |

React wrappers around graph/chart engines are not preferred. The current thin imperative
`MarketChart` boundary is easier to pin, test, dispose, and make accessible than an extra wrapper
whose release cadence can lag React and the underlying renderer.

## 5. Temporal and marked point processes

### 5.1 The model object

A point-process row is not merely `(timestamp, kind)`. A canonical experiment needs:

```text
process/subject ID
event time and known/acquired time
event kind and mark schema/version
source, coverage interval, gap/recovery state
entity/coin/wallet relation evidence IDs
risk-set and censoring boundaries
snapshot/feature version
```

Marks may include side, amount, venue, wallet-role claim, territory, creator/community transition,
operator action, or exact derived state. Unknown and missing marks stay distinct. Same-slot events
retain a deterministic partial-order/tie representation; do not add random epsilon time to make a
library happy.

### 5.2 What remains explicit project code

The first Hawkes/response-kernel implementation should be a small Python reference over
NumPy/SciPy for one exponential or fixed-basis kernel. Joshi owns:

- which events enter each process and which are merely observation artifacts;
- integration over observed exposure windows rather than pretending gaps contain zero events;
- left/right censoring and source-specific coverage;
- tie policy and event/known-time mode;
- mark encoding, exogenous baseline/covariates, and unit normalization;
- stability checks, including multivariate branching/spectral-radius diagnostics;
- likelihood, integral term, gradient or finite-difference cross-check, and stop conditions;
- time-rescaling residuals, simulations, and held-out log score; and
- fixture provenance and parameter/non-identifiability reporting.

For exponential kernels the recursive sufficient statistics are small enough to audit. A generic
package saves fewer meaningful lines than it appears to, because none of the packages knows Joshi's
coverage or as-known semantics.

### 5.3 Package roles

SciPy supplies bounded optimization, quadrature, sparse algebra and distributions. `tick` and
HawkesPyLib are differential or simulation oracles only. The current `tick` project is active again
and publishes Apple-arm64/Linux wheels through 0.8.0.2, but its PyPI record omits project URLs; pin
the exact wheel hash and cross-check the upstream tag `v0.8.0.2` at commit
`a40d19f868c22469be90c1e6c50bc3dab26ff070`. Its C++ stack also pulls pandas, matplotlib and
scikit-learn. HawkesPyLib 0.3.0 is smaller but brings Numba and supports a narrower family.

Do not treat self-excitation as causal influence. Common unobserved attention, launch clocks,
market-wide flow, collector latency, and selection can all generate apparent excitation. Always
compare against time-of-day/coin-age/regime baselines, shifted/blocked nulls, and held-out periods.

### 5.4 Survival and competing transitions

Build risk sets and time-varying covariates in DuckDB under both event-time and available-time
cutoffs. Use statsmodels first for transparent proportional-hazard/duration baselines. Probe
lifelines for Aalen–Johansen and time-varying Cox ergonomics, but keep a tiny independent
cumulative-incidence/Aalen–Johansen implementation for golden fixtures.

Relevant transitions are competing and recurrent:

- surfaced → opened/ignored/expired;
- watched wallet trade → operator open/arm/reject;
- provisional territory → corroborated/split/merged/abandoned;
- community/creator state → claim/share/CTO/quiet/deletion;
- position → partial exit/flat-watching/re-entry/zap; and
- source scope → healthy/gapped/recovered/retired.

No package may collapse those into one “time to success.” Left truncation, recurrent episodes,
wallet/coin/community clustering, informative disappearance, and source gaps must be visible.
scikit-survival is deferred because its forest/SVM value does not yet justify GPL/native/solver
surface; GPLv3 is compatible with the AGPL project, but permissive simpler tools are available.

Primary sources: [SciPy optimize](https://docs.scipy.org/doc/scipy/reference/optimize.html),
[`tick` Hawkes guide](https://x-datainitiative.github.io/tick/modules/hawkes.html),
[HawkesPyLib](https://simbold.github.io/HawkesPyLib/),
[statsmodels duration models](https://www.statsmodels.org/stable/duration.html), and
[lifelines documentation](https://lifelines.readthedocs.io/).

## 6. Graph, multigraph, and dynamic storage

### 6.1 One ontology, several projections

Do not build one graph whose edges all mean “related.” Canonical tables retain typed node and edge
identities, relation kind, direction, event/valid/known intervals, evidence, confidence/assertion
status, and source coverage. Examples include:

- profile ↔ platform identity claims;
- profile wallet, observed trade signer, funder, fee recipient, creator and operator wallet roles;
- wallet → coin signed buys/sells/transfers;
- coin ↔ territory membership proposals;
- post/reply/mention/follow/callout relations;
- same-transaction or same-launch bundles; and
- operator attention and episode relations.

The Rust ecology reducer should emit canonical Arrow-facing node, edge, oriented-incidence,
same-transaction bundle/simplex, and cohort rows. SQLite/Parquet remain temporal truth. A Python job
materializes a named as-known snapshot into NetworkX or a sparse matrix. Mutating a NetworkX graph
does not mutate evidence and `pickle` is never an interchange format.

NetworkX `MultiDiGraph` is the reference engine because it is inspectable and supports directed
parallel edges. Node/edge keys are Joshi stable IDs, not array indices. Algorithms that require a
simple graph must name the aggregation/projection that removed direction, edge types, multiplicity,
time, or confidence.

### 6.2 Scaling decision

Stay with NetworkX until a frozen representative snapshot fails a stated budget. Then compare:

1. rustworkx for faster conventional algorithms;
2. SciPy sparse matrices for explicit algebra; and
3. python-graphblas/SuiteSparse only for semiring or scale advantages.

The bakeoff must match exact component membership, path/reachability semantics, multiplicities,
weights, and missing/unknown handling—not merely wall time. Rustworkx indices and GraphBLAS matrix
coordinates remain ephemeral; stable project IDs live in side tables/manifests.

Do not add a graph database. Dynamic truth already needs bitemporal/evidence-aware edge tables,
coverage, replay, and immutable snapshots. Neo4j/Kùzu/Raphtory-style storage would create a second
commit/query/backup/schema authority without removing the hard ontology work. Raphtory is
interesting temporal-graph research and current, but its GPLv3/native database/runtime surface is
the wrong boundary for V1/V2 evidence.

Primary sources: [NetworkX `MultiDiGraph`](https://networkx.org/documentation/stable/reference/classes/multidigraph.html),
[rustworkx API](https://www.rustworkx.org/),
[python-graphblas](https://python-graphblas.readthedocs.io/),
[SuiteSparse GraphBLAS](https://github.com/DrTimothyAldenDavis/GraphBLAS), and
[`petgraph::stable_graph`](https://docs.rs/petgraph/0.8.3/petgraph/stable_graph/).

## 7. Simplicial, Hodge, and “field” operations

### 7.1 Make the metaphor executable

An exotic field is useful only after its carrier, orientation, units and clocks are explicit:

| Object | Possible Joshi meaning | Required representation |
|---|---|---|
| Scalar/node 0-cochain | attention, hazard, net position, activity, credibility assertion | `(snapshot, node_id, value, unit, known_cutoff)` |
| Directed edge 1-cochain | wallet capital flow, follow/callout flow, pairwise preference | oriented typed edge plus signed value |
| Hyperedge/simplex | same transaction, coordinated wallet bundle, shared post/thread/community episode | stable member list and explicit orientation/order |
| Time-varying field | response after launch/callout/trade/gesture | frozen windows with coverage and event/known clocks |

Do not infer a simplex merely because three nodes form a triangle in a projected pairwise graph.
A simplex represents one witnessed higher-order relation; a clique is a different claim.

### 7.2 Small explicit Hodge layer

Build oriented boundary/incidence matrices from canonical rows using SciPy sparse:

```text
B1: vertices × directed edges
B2: directed edges × oriented 2-simplices
L0 = B1 B1ᵀ
L1 = B1ᵀ B1 + B2 B2ᵀ
```

The first non-negotiable golden is `B1 @ B2 == 0`. Additional goldens cover orientation reversal,
parallel typed edges, disconnected components, gauge/null-space choices, missing faces, weights,
and permutation invariance after mapping back to stable IDs. Hodge decomposition of an edge flow
into gradient/curl/harmonic components is a derived lens, not proof of coordination, identity, or
causality.

Probe TopoNetX against these goldens for simplicial/cell Laplacians and XGI for hypergraph
representations. Neither package owns the canonical orientation. TopoNetX's runtime graph is much
broader than its noun suggests; XGI also pulls a plotting/dataframe stack. HyperNetX 2.4.3 is
deferred: its repository carries a BSD-style license, but current PyPI metadata classifies it as
“Other/Proprietary” and it pulls `igraph`; resolve metadata and transitive licensing before use.

GUDHI is a maintained MIT native toolkit with Apple/Linux wheels. Defer it until a registered
filtration/persistent-homology question survives simpler component/cycle/null tests. Reject the
current crop of tiny Rust “Hodge”/simplicial crates: search results are young and do not justify
putting ontology-critical orientation into an unaudited niche dependency.

Primary sources: [TopoNetX documentation](https://pyt-team.github.io/toponetx/),
[XGI documentation](https://xgi.readthedocs.io/),
[HyperNetX repository](https://github.com/pnnl/HyperNetX), and
[GUDHI Python documentation](https://gudhi.inria.fr/python/latest/).

## 8. Linear algebra, optimization, and automatic differentiation

### 8.1 One native numerical stack per process

Python NumPy/SciPy is the primary numerical process. Current wheels exist for CPython 3.14 on Apple
arm64 and Linux arm64/x86-64. SciPy wheels may bundle OpenBLAS/LAPACK and GCC runtime libraries;
their licenses/notices are part of the distributed artifact. Record `numpy.show_config()`, SciPy,
threadpool and CPU information in every benchmark/run manifest.

Avoid simultaneous OpenBLAS, MKL, Accelerate, SuiteSparse and multiple OpenMP runtimes in one
process unless a bakeoff requires them. Symptoms include oversubscription, nondeterministic timing,
symbol conflicts and numerical drift. Set explicit BLAS/OpenMP/Rayon thread budgets in jobs; the
96-GiB Mac makes accidental parallelism less visible, not less real.

Rust should prefer ordinary loops or a single pure-Rust algebra crate for small promoted online
work. `nalgebra` fits fixed, low-dimensional state vectors. `sprs` fits transparent CSR/CSC
assembly. `faer` supplies modern dense/sparse factorization without an external BLAS, but its
defaults add Rayon, random, NPY and sparse-linalg features; select features explicitly and measure
compile/runtime costs. Do not add `ndarray-linalg` to bridge to BLAS that already lives in Python.

### 8.2 Optimization

Use SciPy first with explicit objective, domain transform/bounds, gradients, initialization,
convergence tolerances, restarts, and synthetic recovery. Save the full optimization trace and
Hessian/curvature diagnostics where feasible. “Optimizer converged” is not model identification.

For a later Rust-promoted likelihood, `argmin` is a candidate generic solver. `clarabel` is the
candidate for an explicitly convex conic/QP problem and can remain on a pure-Rust non-BLAS path.
OSQP and CVXPY are deferred because their C/native solver graphs and solver-specific licensing are
not justified by an unnamed allocation problem.

### 8.3 Automatic differentiation

Prefer analytic recursions plus finite differences for the first response kernels. Probe
`num-dual` with defaults disabled for low-dimensional first/second derivatives in Rust; it is far
smaller and more inspectable than a tensor framework.

JAX becomes reasonable only when a named custom likelihood is too complex for analytic derivatives
and the explicit NumPy/SciPy reference already exists. Keep it in a separate locked environment:

- CPU is the portable Apple/Linux baseline;
- Linux CUDA is a different artifact/environment;
- compilation cache, device, precision mode and JAX/XLA versions enter the run manifest;
- compare value and gradient against NumPy/finite-difference goldens; and
- never import JAX into acquisition/core or make a JIT trace the only description of a model.

Burn, Candle and Linfa are rejected for now. Rust training does not reduce architecture complexity
when every data/diagnostic/modeling comparison already lives in Python.

Primary sources: [SciPy sparse arrays](https://docs.scipy.org/doc/scipy/reference/sparse.html),
[Faer](https://faer-rs.github.io/), [Nalgebra](https://nalgebra.rs/),
[`num-dual`](https://github.com/itt-ustutt/num-dual),
[Clarabel](https://clarabel.org/), and
[JAX installation/platform matrix](https://docs.jax.dev/en/latest/installation.html).

## 9. State-space, uncertainty, and calibration

### 9.1 State-space progression

Use an honest ladder:

1. deterministic rolling summaries/EWMA and explicit change diagnostics;
2. small linear Gaussian state-space/Kalman model in statsmodels;
3. hidden Markov or nonlinear model only after transition/emission identifiability checks;
4. DynaMax/JAX only after statsmodels cannot express the registered model.

Relevant latent states might summarize market-wide activity, observation quality, coin lifecycle,
or wallet behavior, but they are model states—not a claim that the market possesses those regimes.
Late/backfilled events require an as-known filter and a separate retrospective smoother. Do not
silently smooth future data into a witnessed scene.

If a tiny filter must run online in Rust, write the transition/observation equations explicitly over
`nalgebra`, record the prior and update version, and differentially replay it against statsmodels.
Do not adopt a niche Kalman crate simply to hide ten equations.

Primary sources: [statsmodels state-space models](https://www.statsmodels.org/stable/statespace.html)
and [DynaMax](https://probml.github.io/dynamax/).

### 9.2 Uncertainty is an output contract

Every model report should distinguish:

- sampling/model uncertainty;
- market-path irreducibility;
- label/outcome censoring;
- missing source coverage;
- selection/support uncertainty;
- calibration error under temporal shift; and
- sensitivity to fees, fills, horizons, clustering and regime definitions.

Use scikit-learn for Brier score, log loss, reliability diagrams and simple calibration. Fit the
calibrator on a temporally later calibration split distinct from training and final evaluation;
group by coin/family/wallet/community/episode as the estimand requires. Never use random row CV.

Probe MAPIE only with rolling/block or explicitly weighted conformal designs. Vanilla conformal
coverage relies on exchangeability that adaptive, autocorrelated memecoin scenes do not possess.
Report marginal coverage by time, liquidity, lifecycle, source health and operator-attention slice;
one aggregate “90% interval” is inadequate.

Bayesian inference is deferred until the likelihood and priors answer a concrete hierarchical
question. If reached, choose NumPyro **or** PyMC by a common bakeoff; do not maintain both. Persist
chains or sufficient diagnostics, divergences, effective sample sizes, R-hat, posterior predictive
checks, seeds/device and exact data/likelihood code. ArviZ may then be added for diagnostics, not
before.

Primary sources: [scikit-learn probability calibration](https://scikit-learn.org/stable/modules/calibration.html),
[MAPIE](https://mapie.readthedocs.io/), [NumPyro](https://num.pyro.ai/), and
[PyMC](https://www.pymc.io/).

## 10. Visualization and glass contract

### 10.1 Research figures

Matplotlib is the first report renderer because it is scriptable, offline, mature and easy to bind
to run manifests. Use explicit styles, dimensions, fonts, limits, colors, seed, timezone and
renderer version. Seaborn is optional syntactic sugar, not required baseline. Plotly/Altair are
deferred; interactive HTML can become a large opaque artifact and a second browser runtime.

Figures must expose denominators, missing/gap intervals, uncertainty definition, as-known cutoff,
and cohort/snapshot ID. A smooth kernel line across an unobserved interval is misleading unless the
gap is visibly masked.

### 10.2 Glass views

- Keep Lightweight Charts for price/time overlays and event/kernel markers.
- Add individual D3 modules for scales, bins, curves and SVG geometry—not full `d3` by default.
- Probe Cytoscape.js for a selected node's bounded typed neighborhood, not the whole market graph.
- Defer Sigma/Graphology until a measured WebGL-scale requirement exists.

Every force/spectral layout is a derived model artifact. Record algorithm, parameters, seed,
package version and final coordinates so witnessed replay does not reshuffle. Position does not
mean similarity or importance unless the legend says exactly how it was computed.

Canvas/WebGL/SVG network views require an accessible table/tree/text equivalent, keyboard traversal,
focus/selection synchronization, non-color edge labels, reduced motion, and an edge/provenance
drawer. The browser consumes bounded nodes/edges/coordinates and model overlays; it does not run
community detection, Hodge decomposition, or graph identity resolution.

Primary sources: [D3 modules](https://d3js.org/),
[Cytoscape.js](https://js.cytoscape.org/),
[Graphology](https://graphology.github.io/), and [Sigma.js](https://www.sigmajs.org/).

## 11. Arrow and sparse/graph interoperability

Parquet is the durable analytical boundary. Arrow record batches and IPC are transient/versioned
batch boundaries. The canonical interchange uses conservative primitive/list/struct types and
manifested schemas; no Python pickle, NetworkX pickle, NumPy `.npy`, framework tensor checkpoint,
or Rust memory layout is a durable contract.

Recommended table families:

```text
node(snapshot_id, node_id, node_kind, attributes..., known_cutoff)
edge(snapshot_id, edge_id, src_id, dst_id, relation_kind,
     orientation, value/unit, valid/known bounds, evidence_ids...)
incidence(snapshot_id, cell_id, boundary_id, dimension,
          orientation_sign, weight, evidence_ids...)
bundle_member(snapshot_id, bundle_id, member_id, member_role, ordinal...)
field_value(snapshot_id, field_id, carrier_kind, carrier_id,
            value/unit, model_run_id, availability...)
```

For sparse matrices, prefer coordinate/incidence rows in Parquet plus an ordering manifest. CSR
arrays (`indptr`, `indices`, `data`) may be stored as a derived optimization only with shape,
dtype, ordering, index base, duplicate policy, sortedness and stable-ID maps. SciPy/GraphBLAS/Rust
can then reconstruct without adopting a custom Arrow extension type.

PyArrow 25 and Rust Arrow 59 use different release numbering but implement the Arrow/Parquet
formats. Cross-language acceptance is value/schema based, not crate-version equality. Test nulls,
dictionary encoding, timestamp unit/timezone, large integer strings, list ordering, NaN/Inf policy,
and extension metadata through Rust → Parquet → PyArrow/DuckDB and back to manifested rows.

Do not use PyO3, a Rust Python extension, Arrow C Data FFI, or shared memory merely to avoid a
Parquet file. The [Arrow C Data Interface](https://arrow.apache.org/docs/format/CDataInterface.html)
is appropriate only after profiling proves same-process zero-copy is material and lifetime/panic/GIL
boundaries receive their own test campaign. Official sources: [PyArrow](https://arrow.apache.org/docs/python/),
[Arrow Rust](https://arrow.apache.org/rust/), and
[Parquet](https://parquet.apache.org/).

## 12. Native build, licensing, and supply-chain rules

### 12.1 License posture

The adopt/probe recommendations are permissively licensed and compatible with Joshi's AGPL. Keep
their license and notice texts in release inventories. Special cases:

- scikit-survival and Raphtory are GPL-3.0-family. They are legally composable with an AGPLv3 work
  under the GPL/AGPL compatibility mechanism, but are deferred/rejected because a permissive,
  smaller route exists and their native/runtime surfaces are substantial;
- HyperNetX has a BSD-style repository license but inconsistent PyPI classification; no lock until
  artifact and transitive license review resolves it;
- SciPy/Matplotlib/native wheels bundle third-party libraries/fonts with additional notices;
- optional solver backends may differ radically in license even when the wrapper is permissive; and
- public package metadata is inventory evidence, not a substitute for inspecting the exact wheel,
  sdist, source revision and bundled notices.

No unclear-license protocol SDK, captured provider data, or fixture becomes safe to publish merely
because a model package is permissive. The repository-wide `LICENSING.md` policy still governs.

### 12.2 Environment shape

Use bounded `uv` dependency groups rather than one permanent “everything” environment:

```text
model-core: NumPy, SciPy, pandas, NetworkX, statsmodels, scikit-learn, Matplotlib
point-process-probe: exact tick and/or HawkesPyLib artifact
topology-probe: one of TopoNetX, XGI, python-graphblas, GUDHI
autodiff-probe: JAX/JAXlib plus exactly one of NumPyro/DynaMax as required
```

Do not activate every group in canonical CI. Each registered run records Python, OS/arch, lock
digest, exact wheels/hashes, NumPy/SciPy configuration, CPU/thread environment and package list.
Prefer registry wheels for Apple arm64 and Linux arm64/x86-64; a source/Fortran/C++ build is a
separate reproducibility task and must not happen silently on a remote host.

Rust packages use exact feature review and `cargo tree -e features -d`. Never enable `full`, BLAS,
MKL, Rayon, random, serialization, Python, CUDA or plotting features by convenience. Treat model
artifacts as untrusted inputs: bounded size/dimensions, schema/version/digest checks, no pickle or
arbitrary object deserialization.

### 12.3 Duplicate-runtime budget

Before accepting a native candidate, record:

- BLAS/LAPACK/GraphBLAS implementation and integer ABI (LP64/ILP64);
- OpenMP/GCC/LLVM runtime and thread controls;
- CPU dispatch/architecture floor and Linux glibc baseline;
- Apple Accelerate/OpenBLAS choice;
- Rust Rayon/Tokio and Python BLAS oversubscription;
- CUDA/ROCm/Metal/XLA variants if any;
- wheel availability for Python 3.12–3.14 and both deployment architectures; and
- binary size, cold import/JIT/compile time, peak RSS and license notices.

The default answer to two BLAS implementations in one process is “remove one,” not “hope symbols
do not collide.” Separate processes joined by manifested Arrow/Parquet are an acceptable boundary.

## 13. Workload-to-tool map

| Joshi question | First tool | Probe only after baseline | Explicit semantics retained by Joshi |
|---|---|---|---|
| Do watched-wallet events change near-term coin activity? | DuckDB risk sets + NumPy/SciPy response histograms | tick/HawkesPyLib | coverage, ties, marks, baseline, censoring, null shifts |
| Which transitions follow community/creator events? | statsmodels duration/GLM | lifelines; later scikit-survival | competing states, time-varying covariates, as-known cutoff |
| Are wallet/coin territories coherent? | NetworkX typed `MultiDiGraph` + matched nulls | rustworkx/GraphBLAS | edge ontology, temporal snapshot, multiplicity, evidence |
| Is there higher-order coordination beyond pairwise overlap? | explicit bundle/simplex rows + SciPy incidence | TopoNetX/XGI | witnessed hyperedge, orientation, `B1 @ B2 == 0` |
| Does a wallet-flow field contain gradient/curl/harmonic structure? | SciPy sparse Hodge golden | TopoNetX/GraphBLAS/GUDHI | carrier, units, weights, gauge, null space, interpretation |
| Is a latent activity/regime model useful? | statsmodels state-space | DynaMax/JAX | as-known filter vs retrospective smoother, state meaning |
| Are predictions honest? | sklearn Brier/log loss/calibration | MAPIE; NumPyro/PyMC | temporal/group split, support, coverage, sensitivity |
| Can a model be promoted online? | replayed Python artifact first | nalgebra/petgraph/num-dual/argmin Rust port | frozen preprocessing, bounded inputs, fail-closed version |
| How should it appear in glass? | Lightweight Charts + D3; tabular evidence | Cytoscape; later Sigma | stored coordinates, provenance, accessibility, no causal color |

## 14. Common bakeoff specification

No specialized package advances based on a notebook demo. Use one manifested, synthetic-plus-real
fixture suite:

### 14.1 Point process and survival

- simulated exponential Hawkes processes with known parameters, stable/near-unstable cases,
  simultaneous events, marks, exogenous baseline, left/right censoring and inserted coverage gaps;
- exact explicit likelihood/gradient/integral versus SciPy finite differences and package oracle;
- time-rescaling and held-out log score;
- a multi-state competing-risk fixture with left truncation, recurrent episode, time-varying
  covariate and informative disappearance;
- perturb event time versus known time and prove witnessed outputs do not change from future data.

### 14.2 Graph and topology

- typed directed multigraph with parallel edges, self-loops, disconnected components, repeated
  wallets, an ambiguous identity assertion and a same-transaction triple;
- exact algorithms/results through NetworkX and each performance candidate;
- oriented triangle/cycle/tetrahedron incidence goldens, orientation reversal and `B1 @ B2 == 0`;
- shuffled stable IDs/order produce identical mapped results;
- benchmark 100k, 1m and 10m edge synthetic snapshots where memory permits, with peak RSS/import
  time/build time as well as algorithm time.

### 14.3 State, optimization and calibration

- linear Gaussian fixture with known filtered/smoothed states and missing observation interval;
- non-identifiable/flat likelihood and boundary optimum cases;
- analytic/dual/finite-difference gradient agreement;
- rolling temporally shifted probability fixture demonstrating that random CV lies;
- calibration and interval coverage by regime/source-health subgroup, not only aggregate.

### 14.4 Interchange and glass

- Arrow/Parquet round trip for node/edge/incidence/field rows through Rust, PyArrow and DuckDB;
- exact logical digest after reconstruction into each graph/sparse engine;
- deterministic recorded layout replay;
- keyboard/screen-reader/table fallback and reduced-motion check for graph rendering;
- no package object/pickle or executable model format in the bundle.

A candidate wins only if it produces the same semantics, has an explained dependency/license/native
graph, runs on Apple arm64 and target Linux, and materially improves correctness, capability or the
measured resource budget. Saving twenty lines is not sufficient.

## 15. Introduction order and stop rules

1. Add NumPy/SciPy only when the first explicit response/sparse experiment lands.
2. Add NetworkX with the first canonical typed graph snapshot and null comparison.
3. Add statsmodels/sklearn only with named duration/state/calibration baselines.
4. Add Matplotlib when canonical reports are produced.
5. Probe one specialized package at a time in a named dependency group; never introduce two
   competing graph, Hawkes, Bayesian, or tensor ecosystems simultaneously.
6. Port a model to Rust only after a frozen Python artifact passes prospective replay and an online
   latency/availability requirement exists.

Stop or shelve the higher-order toolbox when:

- source coverage cannot distinguish silence from missing acquisition;
- wallet/identity/territory edges remain mostly ambiguous assertions;
- higher-order results collapse under typed-edge, time-shift or degree-preserving nulls;
- Hodge/topological output is unstable to orientation, window or weight choices;
- point-process excitation disappears under coin-age/market baseline and gap sensitivity;
- prediction calibration fails out-of-time or the attended slice has no support in the census;
- a native dependency cannot reproduce on Apple and Linux from locked artifacts; or
- the visualization is impressive but does not improve a recorded operator decision or audit.

Shelving a model never discards the event tape, coverage, typed graph rows, incidence rows,
snapshots, or operator observations. Those reusable facts are the point of building the toolbox
around explicit seams.

