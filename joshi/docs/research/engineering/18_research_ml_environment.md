# Engineering lane 18: research and learning environment

Status: design proposal only. It does not authorize implementation, cloud purchase, model-driven
trading, signing, submission, or production scoring.

## Recommendation

Start with a **local, Python-first, manifest-driven research environment** that treats the evidence
substrate as read-only. Use DuckDB SQL over immutable Parquet snapshots, PyArrow as the typed
in-memory/interchange boundary, ordinary Python modules for reusable logic, and notebooks only as
thin exploratory clients of those modules.

Do not begin with a feature store, workflow orchestrator, model-serving platform, vector database,
distributed lakehouse, online learner, or cross-language FFI layer. The first environment needs to
do five things exceptionally well:

1. Build an immutable, point-in-time-correct scene/episode snapshot from named evidence.
2. Run a study from a locked environment and declarative config.
3. Preserve row-level predictions, retrieved analogs, metrics, and failures in a self-describing run
   bundle.
4. Reproduce the run without reading whatever the live market happens to contain later.
5. Prevent an exploratory artifact from silently entering the cockpit or influencing a trade.

This small spine can grow into survival and competing-risk studies, multimodal chart/social models,
LLM interpretation, prequential/continual estimation, program synthesis, and nonlinear hybrid-system
abduction. Those are consumers of the evidence contract, not reasons to turn the evidence store into
an ML platform now.

The design in one picture is:

```text
append-only evidence substrate (read-only to research)
                         |
                snapshot construction job
                         |
            immutable dataset + split manifest
                         |
       reproducible job ---------------- exploratory notebook
                         |                       |
                         +----------+------------+
                                    |
                    immutable run/evaluation bundle
                                    |
                         candidate registry entry
                                    |
                    shadow/advisory promotion review
                                    |
                         separate product consumer
```

No arrow in this diagram points back into raw evidence. No candidate model is a production decision
rule merely because it appears in a registry.

## 1. Load-bearing separation

### 1.1 Evidence, derivation, experiment, and decision are different authorities

The event-tape lane distinguishes raw observations, versioned assertions, and derivations. The
research environment adds two more layers:

- **Dataset snapshot:** a frozen selection of point-in-time assertions/derivations for one declared
  question.
- **Experiment/run:** code and configuration applied to that snapshot, producing artifacts and
  claims.

Production or operator-visible decisions remain outside all five layers. A useful authority model
is:

```text
raw observation          source said these bytes at this receive time
typed assertion          parser vN made this bounded claim
derived interpretation   transform/model vN computed this annotation
dataset snapshot         study vN froze these rows under this knowledge cutoff
experiment result        job vN produced this estimate on this split
product decision         separately reviewed consumer chose to display or act
```

The research process may append a derivation that points to evidence; it may never mutate the
evidence to agree with a model. Corrections create new assertions or snapshots. LLM outputs,
embeddings, inferred regimes, and synthesized predicates are always recomputable annotations.

### 1.2 Physical isolation, not merely convention

The research runtime should receive:

- read-only access to approved evidence and immutable snapshot objects;
- write access only to scratch space, derived artifacts, and the experiment registry;
- no wallet secret, signer, transaction submission endpoint, browser credential, or production
  configuration secret; and
- for cloud jobs, no route back to a live wallet or mutable local evidence database.

An accidental `UPDATE`, notebook cleanup command, compromised model artifact, or dependency should
therefore be unable to alter the source record or move money. Repository policy is not an adequate
substitute for this capability boundary.

### 1.3 Evaluation visibility is itself a treatment

Candidate scores and analog outcomes remain hidden from Ember during a confirmatory evaluation
unless displaying them is the explicitly registered intervention. Once a score changes what Ember
looks at, it has changed the attention policy and the resulting episodes belong to a new policy
epoch. Similarly, an interviewer who reveals future outcomes or machine interpretations before
elicitation has changed the label-generating process.

Every product-visible model output therefore records:

- model/run identifier and exact output;
- display and viewport time;
- source evidence and freshness;
- UI treatment/experiment identifier and propensity, if system-randomized; and
- whether it was visible before the operator gesture or interview response.

## 2. Language and runtime decision

### 2.1 Python is the initial research spine

Python should own snapshot construction, study orchestration, conventional statistics, retrieval,
survival baselines, LLM annotation jobs, and initial multimodal work. The reason is integration
economics, not a claim that Python is the best language for every eventual method:

- DuckDB and PyArrow have first-class Python clients.
- The statistical, scientific, survival, embedding, and deep-learning ecosystems are reachable
  without cross-process conversion.
- PyTorch has CPU, CUDA, and macOS MPS paths, allowing one job shape to start locally and move only
  when measured compute requires it. The current PyTorch MPS backend maps tensor operations onto
  Metal Performance Shaders on supported macOS systems. [PyTorch MPS documentation](https://docs.pytorch.org/docs/stable/notes/mps.html)
- A locked `pyproject.toml`/`uv.lock` environment is small enough for the first lane. `uv run
  --locked` refuses to update a stale lock rather than silently resolving a new environment, and
  exact sync removes undeclared packages. [uv locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/)

The initial dependency surface should remain narrow: DuckDB, PyArrow, numerical/statistical basics,
a plotting layer, and a notebook kernel. Survival or PyTorch dependencies enter separate optional
groups only when a named study uses them. Provider-specific LLM SDKs should sit behind a tiny job
adapter rather than leak into every analysis module.

Python's convenience is also a risk: notebooks can pickle arbitrary state, dataframe joins make
leakage easy, and dependencies update quickly. The controls in this document—not the language—make
the result reproducible.

### 2.2 Julia is an opt-in scientific sidecar, not a second platform

Julia becomes attractive if a concrete hybrid-system, differential-equation, probabilistic,
optimization, or circuit-abduction study is materially clearer or faster there. It should consume
the same frozen snapshot and emit the same run-manifest contract as Python.

Current interoperability is adequate for a batch sidecar:

- Julia's `Project.toml` plus `Manifest.toml` can instantiate the recorded dependency graph; the
  manifest records exact direct and transitive package state. [Julia Pkg manifest documentation](https://pkgdocs.julialang.org/v1/toml-files/)
- Arrow.jl supports Arrow IPC streams/files and record batches, although its current documentation
  does not claim Flight RPC or the Arrow C Data Interface. [Arrow.jl documentation](https://arrow.apache.org/julia/)
- DuckDB has a Julia client, but DuckDB currently classifies Julia among tertiary clients with no
  support guarantees. [DuckDB client support tiers](https://duckdb.org/docs/current/clients/tertiary_clients/overview)

Therefore prefer versioned Arrow IPC exports or Parquet queried through a pinned job environment;
do not build Python↔Julia object bridges, shared-memory FFI, or a Julia online service initially.
Add Julia only when one registered experiment states what Python cannot reasonably provide.

### 2.3 OCaml belongs at typed synthesis/verification boundaries, if needed

OCaml may later be valuable for a typed policy DSL, trace checker, counterexample-guided synthesis,
or a mechanically small verified safety kernel. It should not become the general feature or model
training environment.

Apache Arrow's current official implementation list includes Python, Julia, and .NET but not OCaml.
[Apache Arrow implementations](https://arrow.apache.org/docs/implementations.html) That does not
prove no third-party OCaml package exists; it means this design must not assume an officially
supported native Arrow boundary. A future OCaml study should consume a deliberately small typed
export—canonical JSON/CBOR, a generated schema, or a subprocess query result—and return a proof,
program AST, counterexample set, or scored trace with content hashes.

Do not write an OCaml Parquet stack or bind the entire Python process merely to run a synthesizer.
The language boundary should make the synthesized object's inputs inspectable.

### 2.4 C# is a possible product/inference consumer, not a duplicate research stack

If the cockpit or services ultimately use .NET, C# can consume typed Arrow IPC and, for compatible
models, ONNX artifacts. Arrow maintains an official .NET implementation, and ONNX Runtime provides
a C# inference API. [Arrow implementation status](https://arrow.apache.org/docs/status.html),
[ONNX Runtime C# API](https://onnxruntime.ai/docs/get-started/with-csharp.html)

DuckDB currently classifies C# as a secondary client while Python is primary. [DuckDB client
overview](https://duckdb.org/docs/stable/clients/overview) That is sufficient for tooling but not a
reason to reimplement research in C#. ML.NET can train models in .NET, but maintaining two training
stacks would add divergence before there is a deployment need.

If a model eventually crosses into a C# product:

1. export only after the research artifact passes promotion;
2. freeze the input schema and preprocessing contract;
3. compare C# inference row-for-row with the originating Python artifact;
4. characterize unsupported operators and numerical drift; and
5. keep the Python run bundle as the source of the model claim.

ONNX is not a universal answer—retrieval pipelines, LLM calls, arbitrary Python transforms, and
program synthesizers may not export. A narrow scoring service or precomputed advisory artifact is a
valid alternative. No deployment boundary is needed in the first environment.

### 2.5 Summary

| Runtime | Initial role | Later justified role | Boundary | Do not do now |
|---|---|---|---|---|
| Python | all research jobs and snapshots | ML, survival, retrieval, LLM orchestration | DuckDB + PyArrow | mutable notebook pipelines |
| Julia | none | nonlinear/hybrid inference or optimization with a named advantage | frozen Arrow/Parquet snapshot + run manifest | shared-memory FFI or second live stack |
| OCaml | none | typed DSL, synthesis, trace checker, safety proof | small canonical typed exports | general analytics or custom Parquet reader |
| C# | none in research | promoted inference/product consumer | Arrow IPC, ONNX, or narrow service | duplicate model training and feature logic |

## 3. Data boundaries: Arrow, Parquet, DuckDB, and blobs

### 3.1 Parquet is the durable analytical table boundary

Use immutable Parquet files for sizeable, columnar snapshot tables and run predictions. DuckDB and
PyArrow can scan them without loading every column or row; DuckDB's reader pushes projections and
filters into Parquet scans. [DuckDB Parquet documentation](https://duckdb.org/docs/stable/data/parquet/overview)

Parquet is not the raw evidence envelope and not a database of mutable truth. Each snapshot names
exact physical files, schema version, row counts, partitions, min/max clocks, and hashes. Rewriting a
partition creates a new snapshot. Partition for the study's actual access pattern after measuring
it; do not preemptively create millions of tiny `mint/date/hour` files.

Exact quantities remain integer or decimal with explicit units and token decimals. Do not turn
lamports, raw token quantities, slots, fee basis points, or reserve values into floats because a
model library prefers them.

### 3.2 Arrow is the typed in-memory and IPC boundary

Use Arrow tables/record batches between DuckDB, Python, Julia, and a future .NET consumer, and Arrow
IPC for short-lived or versioned batch exchange. Arrow schemas are immutable objects and carry field
types; the IPC format supports record-batch streams and files. [PyArrow data model](https://arrow.apache.org/docs/python/data.html),
[Arrow IPC API](https://arrow.apache.org/docs/python/api/ipc.html)

Arrow is a format contract, not the domain schema registry. Store the domain schema identifier,
units, null/missing semantics, and time authority in the snapshot manifest even where Arrow custom
metadata is also present. The official implementation matrix shows that language support differs
for some extension types and interfaces, so the first cross-language schemas should use a
conservative common subset. [Arrow implementation status](https://arrow.apache.org/docs/status.html)

### 3.3 DuckDB is a reproducible query engine and disposable cache

Use pinned DuckDB SQL to:

- build scene/episode cohorts;
- perform explicit temporal and risk-set joins;
- scan Parquet locally;
- export deterministic analytical tables; and
- audit row counts, missingness, and leakage invariants.

DuckDB supports ASOF joins for selecting a time-varying value as of an entity timestamp.
[DuckDB ASOF join](https://duckdb.org/docs/current/guides/sql_features/asof_join) That primitive is
useful but not sufficient for Joshi: a correct feature must satisfy both its **event-time** window
and its **available-time** cutoff. A late backfill with an old event time is still future information
for as-known replay.

A `.duckdb` file may cache a snapshot or host a scratch catalog. It is not the canonical artifact;
the manifest plus immutable Parquet/blob objects are. Jobs should create explicit connections rather
than depend on DuckDB's module-global Python connection, which the current client documentation warns
can create thread-safety problems. [DuckDB Python client](https://duckdb.org/docs/stable/clients/python/overview)

### 3.4 Non-tabular objects remain content-addressed blobs

Keep raw images, chart scene renders, audio, transcripts, model weights, prompt payloads where
retention permits, and large tensor artifacts outside Parquet. Tables contain typed references:

```text
blob_hash, media_type, byte_length, encoding, shape/axes if relevant,
retention_class, encryption class, source evidence id
```

Fixed-size embedding vectors may be stored in Arrow/Parquet when that is convenient. Large or
variable tensors should remain a named model artifact. Never store only an embedding when the raw
input is legally and operationally retainable; future encoders need the original evidence.

### 3.5 Physical and logical hashes

Each object receives a physical cryptographic hash. Dataset snapshots additionally receive a
logical digest over canonical schema, keys, ordering, and values. Parquet byte layout and metadata
can change across writer versions even when the logical table is equivalent; both identities are
useful:

- physical hash: these exact bytes;
- logical digest: this ordered typed relation;
- snapshot ID: this specification, input manifest, transformation, and split assignment.

## 4. Minimal project and execution shape

The conceptual repository boundary is:

```text
research environment
  pyproject.toml + uv.lock       locked Python/runtime intent
  src/                           reusable snapshot, feature, metric, and study code
  sql/                           versioned cohort/point-in-time queries
  specs/                         dataset, feature, label, split, and experiment specs
  notebooks/                     exploratory views; never authoritative jobs
  tests/                         temporal, accounting, schema, and known-effect controls

derived artifact root (not Git)
  snapshots/<snapshot_id>/       immutable manifest + tables/blob references
  runs/<run_id>/                 config, logs, predictions, metrics, model, report
  registry/                      append-only candidate/promotion records
  scratch/                       disposable and excluded from evidence
```

This is a data contract, not a mandated directory implementation. The load-bearing properties are
immutability, content addressing, declared inputs, and read-only evidence.

Every canonical operation is a non-interactive job with explicit inputs:

```text
build-snapshot   DatasetSpec -> SnapshotManifest
derive-features FeatureSpec + SnapshotManifest -> FeatureArtifact
train           ExperimentSpec + split -> ModelRun
evaluate        frozen ModelRun + frozen split -> EvaluationRun
annotate        AnnotationSpec + evidence refs -> VersionedDerivations
render-report   RunManifest -> human-readable report
```

Jobs write to a temporary directory, validate, then atomically publish a completed manifest. A
failed job never leaves an apparently valid half-snapshot.

## 5. Notebooks versus reproducible jobs

### Notebooks are appropriate for

- inspecting a frozen snapshot;
- drawing distributions and episode timelines;
- interactively checking joins and missingness;
- viewing retrieved analogs and annotation disagreements;
- developing a hypothesis or feature; and
- writing an exploratory narrative.

### Notebooks are not appropriate for

- writing or correcting evidence;
- defining the only copy of a feature or label;
- producing a confirmatory cohort through hidden cell state;
- training the only copy of a model;
- mutating a registry or promoting a candidate; or
- querying a live mutable database while claiming a frozen result.

Reusable logic moves into versioned modules/SQL. A notebook records the snapshot ID and run IDs it
views, has a clean-run test when retained, and is rendered to a static artifact. Clearing outputs is
not enough: execution order, kernel environment, parameters, and external input manifests must be
captured.

For a confirmatory result, the canonical artifact is the job's run bundle and generated report.
The notebook may explain it, but cannot be the only way to reproduce it.

## 6. Deterministic dataset snapshots and point-in-time correctness

### 6.1 Snapshot specification

A `DatasetSpec` should declare at least:

```text
question/hypothesis id
population and inclusion/exclusion rules
anchor event and entity/episode keys
as-known or retrospective knowledge mode
event-time interval
maximum evidence available_at cutoff
census/hot-lane coverage requirements
source/assertion/derivation versions permitted
feature set versions
label definition versions
quote size, route, fees, and terminal-value convention
missingness/censoring policy
entity, episode, narrative-family, and temporal grouping
train/calibration/test split definition
```

The resulting manifest freezes:

- the fully resolved spec;
- sorted input object/assertion IDs and hashes;
- transformation code commit and dirty-patch hash;
- SQL/config hashes and engine/library versions;
- schema and logical-table digests;
- row counts and key uniqueness checks;
- coverage/gap summaries;
- exact split assignments; and
- build logs and validation results.

The live evidence store can continue appending while a snapshot remains unchanged.

### 6.2 Four clocks are required in research rows

At minimum preserve:

- `event_time`: when the source says the thing happened;
- `observed_at`: when Joshi received it;
- `available_at`: when the parsed/validated value could enter a view or policy; and
- `produced_at`: when a derived feature/model output was computed.

For a decision anchored at \(t\), an as-known feature row is eligible only when its evidence and
the feature itself were available by \(t\). Event time alone is insufficient. A creator identity
resolved tomorrow, engagement count reread next week, or LLM label completed 40 seconds after the
gesture cannot appear in today's decision vector.

The snapshot builder should assert, per example:

```text
max(input.available_at) <= example.decision_available_at
feature.lookback_end <= example.event_time
label.window_start >= example.anchor_time
```

Known future-only sentinel columns should be included in test fixtures and required to fail the
builder. Point-in-time-correct retrieval is a known feature-store responsibility—Feast, for example,
defines historical retrieval by scanning backward from each entity timestamp within a TTL—but the
first Joshi environment does not need a feature-store service to implement a small number of
auditable joins. [Feast point-in-time joins](https://docs.feast.dev/getting-started/concepts/point-in-time-joins)

### 6.3 Splits are immutable artifacts

Splitting code is not enough. Persist the exact example-to-split mapping, including exclusion
reason. Split chronologically first, then enforce grouping needed by the claim:

- mint and operator episode;
- represented person/narrative and duplicate-coin family;
- overlapping market-time risk sets; and
- wallet/community entity where leakage is plausible.

Exploration and feature construction may use the training block. Calibration chooses thresholds.
The test block is opened once for the registered claim. UI-visible prospective data belongs to a
new policy epoch and must not be merged into a prior holdout.

Deterministic ordering, explicit seeds, and stable group keys make the split reproducible. A seed
does not repair an invalid random split across time or related entities.

## 7. Feature and label versioning

### 7.1 A feature is a temporal claim, not a column name

Each feature definition needs:

```text
feature_id and immutable semantic version
entity/scene key and value type/unit
input assertion/derivation kinds and versions
event-time window and boundary semantics
available-time rule
missing/unknown/stale behavior
normalization reference population
transformation code/config/model/prompt identity
produced_at and lineage
online-computability declaration and expected latency
```

Changing `volume_5m` from event time to ingest time, treating missing replies as zero, replacing a
chart encoder, or changing an identity resolver creates a new version. A model's input contract
names exact feature versions; it never requests “latest.”

Normalization is fitted on the training block and stored as an artifact. A market-wide percentile
that uses the evaluation period is a future-dependent feature even if every individual row is old.

### 7.2 Labels are executable outcome specifications

Each label definition names:

- anchor and eligible population;
- action or fixed evaluation policy;
- size and route;
- fees, landing/slippage model, and quote freshness;
- horizon and terminal liquidation rule;
- partial-exit/runner or competing-event semantics;
- whether the label is realized, shadow replay, censored, unquotable, or unresolved;
- data coverage required to call it observed; and
- code/config version.

`return_5m` is not a label specification. “Net executable liquidation value of an actual 0.1 SOL
entry five minutes after landing, using the route and dynamic fees available then, with explicit
unquotable state” is much closer.

Features and labels materialize separately and join only through frozen example IDs. This makes it
harder for a retrospective label transform to leak into the as-known feature view.

### 7.3 Version external and nondeterministic derivations

For LLM labels and embeddings preserve provider/model identifier, endpoint parameters, prompt or
encoder version, tokenizer if exposed, exact input manifest, request/response time, exact output,
usage/cost, error/retry path, and whether caching was used. A marketing model alias is not a durable
version; where the provider exposes no immutable model revision, record that limitation and keep the
returned artifact.

## 8. Chart drawings as structured supervision

Chart drawings are unusually valuable because they externalize spatial/temporal predicates without
forcing Ember to name them first. Do not reduce them to screenshots.

### 8.1 Preserve the gesture and coordinate transform

For every drawing or edit retain:

```text
drawing_id, scene_id, episode_id
created/edited/deleted times and gesture sequence
tool type and tool-version
raw pointer/sample path in viewport pixels
chart transform: x-domain, y-domain, linear/log, price/mcap/unit
vertices/curve in event-time × economic-value coordinates
visible candle/trade range and source watermarks
snap behavior and inferred anchors
free text/voice fragment and explicit unknown
created by operator, suggested by model, or edited from suggestion
outcome visibility state at creation
supersedes/retracts links
```

Keeping pixels allows faithful replay; keeping data coordinates allows comparison across zoom and
screen size. The full chart transform is what relates them. Preserve raw gesture points before
simplifying a polyline or snapping it to candles.

### 8.2 Derived supervision remains plural

One drawing may later yield several versioned targets:

- time/price region Ember considered salient;
- pairwise chart-scene similarity;
- support/resistance, channel, acceleration, exhaustion, or transition hypotheses;
- expected action window or invalidation boundary;
- a segmentation/ranking target for a chart encoder; or
- a counterexample to a synthesized predicate.

A line is not automatically a factual support level, a trade instruction, or a positive outcome
label. Its semantic reading may remain `unknown`. Model-suggested drawings and Ember's edits are
especially useful, but must never be mistaken for independent human labels.

### 8.3 Evaluation uses temporal and operator-aware splits

If a chart model is trained from drawings, split by later episodes and related coin/narrative
families. Rasterized screenshots must be generated from the as-known chart domain, without outcome
bars or UI badges. Compare models using raw event sequences, rendered images, and their fusion;
do not assume visual representation is superior because the supervision was drawn visually.

## 9. Interviews as structured but non-oracular supervision

Immediate fragments and post-resolution interviews observe different cognitive objects. Store both;
never merge them into one cleaned explanation.

With Ember's explicit consent, an interview bundle may contain:

- prompt protocol/version and interviewer identity;
- audio hash and retention class;
- transcript with word/segment timing and correction history;
- scene/episode/action references visible during each answer;
- whether outcomes, machine interpretations, or prior notes were visible;
- exact utterance plus optional operator edits;
- marked spans linked to cues, dispositions, comparisons, expected transitions, invalidations,
  counterfactuals, and uncertainties;
- epistemic mode: observed then, inferred then, felt but inarticulable, remembered later, learned
  later, normative preference, or unknown;
- LLM-extracted structured proposals with extractor version and confidence; and
- confirm/reject/revise events without requiring review of every extraction.

Useful learning objects include:

- pairwise “this scene is more like that one” judgments;
- positive and negative analog relevance;
- missing-predicate counterexamples;
- action/disposition transitions;
- cue spans grounded in chart, post, author, or flow evidence; and
- explicit uncertainty or inability to articulate.

Retrospective explanation is evidence about how Ember now organizes the episode, not ground truth
about the original policy or market causation. An LLM can propose structure, summarize, or retrieve
similar passages; it may not overwrite the utterance or silently turn a polished post-hoc story into
a contemporaneous label.

## 10. Growth path by method family

### 10.1 Stage A: episode and scene retrieval

Begin with inspectable retrieval, not a predictor:

- exact filters and temporal nearest neighbors over structured market context;
- simple normalized chart-path distances;
- text/image embeddings computed as versioned annotations;
- late fusion rather than one opaque universal embedding; and
- a result card showing why each analog matched, coverage differences, and heterogeneous outcomes.

Evaluation records past-only recall, operator relevance/irrelevance, diversity, latency, missing
modality behavior, and outcome-blindness. Retrieval outcomes are hidden while Ember judges analogy.
The first learned object can simply rerank candidates using accumulated pairwise relevance.

Do not start with a vector database. At pilot scale, flat files plus an in-process index are easier
to snapshot and audit. Adopt a persistent vector service only after the corpus and latency require
it and after its version/filter semantics can reproduce a historical query.

### 10.2 Stage B: survival and competing risks

Start with empirical transition tables and nonparametric cumulative-incidence estimates before
complex hazard models. The current scikit-survival API includes a nonparametric cumulative-incidence
estimator for multiple competing event codes. [scikit-survival competing-risk API](https://scikit-survival.readthedocs.io/en/stable/api/generated/sksurv.nonparametric.cumulative_incidence_competing_risks.html)

Then add cause-specific or multi-state models only when the event definitions, delayed entry,
recurrent episodes, time-varying covariates, and censoring processes are defensible. Evaluate
cumulative-incidence calibration, time-dependent Brier/error measures, and event-specific coverage,
not only concordance. A model of claim, endorsement, fragmentation, migration, collapse, and loss of
quote must not treat the other events as ordinary independent censoring.

### 10.3 Stage C: multimodal chart and social models

Progress in this order:

1. strong structured/tabular and retrieval baselines;
2. frozen pretrained encoders as versioned features;
3. late fusion with modality-missingness indicators;
4. task-specific fine-tuning only after adequate supervision and chronological evaluation; and
5. representation learning from operator analogy/drawing data if it improves a declared task.

Keep raw chart events and rendered views. Keep raw social threads, images, authorship, and graph
context. Measure whether a multimodal branch adds held-out value beyond lifecycle, liquidity, flow,
and the current scene; architecture novelty is not an estimand.

### 10.4 Stage D: LLM text and social-transition analysis

LLMs should first run asynchronously as annotators over frozen raw evidence:

- entity/reference resolution proposals;
- stance and participation cues;
- claims of creator awareness versus verified acts;
- community themes, disagreements, and narrative migration;
- interview span extraction; and
- human-readable analog summaries grounded in source IDs.

Use task-specific schemas and allow abstention/multiple hypotheses. Evaluate extraction against
operator-reviewed spans and known chain/social events, including prompt-injection and adversarial
coin text. Record latency and cost as outcome dimensions. A fluent explanation without evidence
links is not a valid derived signal.

Realtime LLM use comes later and must respect available time: its feature becomes usable when the
response completes, not when the post was authored. External submission of text/media is a data
egress decision requiring provider/retention review.

### 10.5 Stage E: online and continual estimation

“Continual” should initially mean scheduled, reviewable candidate updates—not a production model
that rewrites itself after every episode.

Use prequential semantics:

1. score the new scene with a frozen checkpoint;
2. append the score before the outcome;
3. wait for the declared delayed label or competing event;
4. evaluate the frozen score;
5. optionally update a **candidate** checkpoint; and
6. compare it with the unchanged advisory/champion on later events.

Every checkpoint names its training window, parent, state, optimizer if relevant, RNG state, and
feature versions. Drift detectors may open a review or abstention gate; they do not promote a model.
Maintain rolling, expanding, and regime-conditioned estimates side by side. Because displaying a
model changes operator attention, model/UI epochs are part of the context and policy, not nuisance
metadata.

### 10.6 Stage F: program synthesis from partial specifications

Export a compact typed trace containing:

- observed scene predicates and their provenance;
- gesture/action transitions;
- positive constraints and explicit counterexamples;
- unknown/unobserved predicates;
- temporal relations;
- safety invariants; and
- retrieved interview/drawing spans that motivated each candidate predicate.

The synthesizer returns a typed AST, complexity, satisfied/violated constraints, counterexamples,
and abstention domain. It never writes a production rule directly. Evaluate behavioral agreement
separately from economic value and safety. Skips are not automatic negative examples, and later
interview explanations are not contemporaneous inputs unless they can be reconstructed from earlier
evidence.

OCaml may be justified here for a typed DSL/checker; Python remains the experiment orchestrator and
snapshot authority.

### 10.7 Stage G: nonlinear hybrid-system and circuit abduction

Represent continuous state, discrete modes, topology changes, observations, operator controls, and
exogenous social inputs explicitly. A study bundle should distinguish:

- hypothesized latent modes and transition guards;
- observed variables and sensor availability;
- parameter priors/constraints;
- alternative observationally equivalent explanations;
- interventions or natural experiments that discriminate them;
- posterior/predicted traces and residuals; and
- falsifying episodes.

Julia may become worthwhile for nonlinear inference or optimization; OCaml may check the discrete
transition system; Python still binds the evidence and evaluation. Abduced circuits remain
hypotheses. They are promoted only insofar as they predict held-out transitions, explain
counterexamples better than simpler baselines, and retain calibration under regime change.

## 11. Run manifests, experiment tracking, and model registry

### 11.1 Start with a transparent run bundle

Every job publishes a `RunManifest` conceptually containing:

```text
run_id, parent_run_ids
exploratory/confirmatory designation and hypothesis id
snapshot, feature, label, and split ids
code commit + dirty patch hash
Python/Julia lock hash and runtime version
DuckDB/Arrow/model-library versions
resolved config and all seeds
OS, architecture, CPU/GPU/backend, driver/runtime details
start/end time, status, warnings, data-quality gates
row-level predictions/retrievals and example ids
aggregate metrics with uncertainty
model/checkpoint and preprocessing artifacts
plots/report/error cases
cost/latency/resource summaries
```

Store row-level outputs, not only a winning metric. Later error analysis, matched comparisons, and
metric corrections require the prediction-to-example relation.

### 11.2 A registry records evidence state, not truth

Initial registry states should be simple append-only records:

```text
exploratory -> reproduced -> candidate -> shadow -> advisory -> retired
```

There is deliberately no automatic `production` transition. Each transition names reviewer,
evidence bundle, approved use, expiry/review date, known regimes, exclusions, and rollback target.
A model can be advisory for analog retrieval while forbidden for ranking or execution.

MLflow is a reasonable later replacement for homegrown run browsing: current MLflow Tracking logs
parameters, code versions, metrics, artifacts, and dataset metadata, while its Registry manages
named model versions and aliases. [MLflow Tracking](https://mlflow.org/docs/latest/ml/tracking/),
[MLflow Model Registry](https://mlflow.org/docs/latest/ml/model-registry/tutorial/)

Do not deploy MLflow initially. It would not remove the need for Joshi's evidence IDs,
available-time rules, immutable split manifest, executable label specification, or promotion
authority. Adopt it when run volume or multiple researchers make its comparison UI and APIs worth
operating.

## 12. Evaluation contract by research family

Every evaluation includes a simple baseline, chronological/entity-aware split, coverage and
missingness, row-level outputs, uncertainty at the correct dependence level, economically
executable outcomes where relevant, known-zero and planted-effect controls, and an explicit search
budget.

Additional family-specific requirements:

| Family | Minimum evaluation |
|---|---|
| Analog retrieval | past-only index; operator relevance before outcomes; recall/rank, diversity, coverage, latency; failed analogs preserved |
| Candidate ranking | top-\(k\) uplift and scale-decay curves under a common policy; matched risk sets; capacity and turnover |
| Survival/competing risk | cumulative-incidence calibration by event; Brier/time-dependent error; delayed entry and censoring audit |
| Multimodal | structured baseline, modality ablations, missing-modality strata, family/time holdout, representation version |
| LLM annotation | source-grounded span/event accuracy, calibration/abstention, prompt-injection set, latency/cost, model/prompt drift |
| Online/continual | test-then-update order, delayed-label accounting, frozen champion, checkpoint lineage, rolling/regime results |
| Program synthesis | trace agreement, counterexamples, unknown-domain behavior, complexity, holdout economic value, invariant checks |
| Hybrid abduction | alternatives/equivalence class, held-out transition prediction, residuals, intervention discriminability, falsifiers |

For GPU experiments, record and control RNGs and deterministic algorithms where available, then
repeat enough seeds to expose instability. PyTorch explicitly warns that complete reproducibility
is not guaranteed across releases, platforms, or CPU versus GPU, even with identical seeds.
[PyTorch reproducibility note](https://docs.pytorch.org/docs/stable/notes/randomness) A seed is
provenance, not proof of determinism.

## 13. Local, GPU, and cloud pathways

### 13.1 Local CPU first

DuckDB cohort construction, tabular baselines, nonparametric survival, small retrieval indexes,
interview processing, and API-based LLM annotations should start locally. This shortens the loop and
keeps raw evidence within the reviewed retention boundary.

### 13.2 Local GPU when a measured job benefits

Use Apple MPS or another available local accelerator only after profiling the named workload.
Record the backend and run a smaller CPU parity case. Unsupported/fallback operations, memory
limits, and cross-device numeric changes are part of the run record. Do not select a model family
merely to justify available hardware.

### 13.3 Cloud only through immutable job packages

A cloud job receives:

- an immutable, minimal approved snapshot or feature artifact;
- code/container digest and locked dependency environment;
- resolved config and run ID;
- least-privilege write target for its result bundle; and
- no live evidence credentials, wallet material, browser session, or transaction authority.

Before upload, classify raw social content, media, transcripts, and wallet linkage for retention and
provider terms. Encrypt transport/storage, set deletion/retention policy, and hash returned
artifacts. Record instance/GPU, driver, CUDA/runtime, region, duration, and cost. Interactive cloud
notebooks do not become a hidden second environment; heavy work remains a submitted reproducible
job.

Do not add Ray, Kubernetes, a scheduler, or a cloud data lake until a local job is demonstrably too
large or slow and its snapshot contract is stable. “Might train multimodal models later” is not a
current scaling requirement.

## 14. Promotion gates

### 14.1 Exploratory result to registered candidate

Require:

- immutable snapshot/split and complete run manifest;
- point-in-time and entity-grouping checks pass;
- clean rerun from the lockfile produces logically equivalent outputs within declared tolerance;
- simple and known-zero controls behave correctly;
- row-level errors and missingness are inspectable;
- chronological held-out result is reported with all tried configurations;
- intended use and forbidden uses are explicit; and
- no evidence or label provenance is unresolved at the scale of the claimed effect.

### 14.2 Candidate to shadow

Require:

- inference can be computed from genuinely available live inputs at the measured latency;
- offline/online preprocessing parity tests pass;
- output is logged before outcome and cannot move money;
- coverage, abstention, staleness, and drift are visible;
- costs and failure modes fit the cockpit; and
- the shadow period and evaluation are preregistered.

### 14.3 Shadow to operator-visible advisory

Require:

- prospective performance and calibration across the named regimes;
- evidence links and uncertainty appropriate to the task;
- UI treatment is recorded, including its effect on attention;
- a simple rollback/disable path and expiry date;
- no material degradation of natural use or scene capture; and
- explicit human review of false positives, false negatives, and abstentions.

### 14.4 Advisory to any automated financial decision

This is outside the current project phase. It requires a separate authorization and safety review,
execution envelope, loss and exposure limits, signer separation, simulation/shadow evidence,
incident controls, and narrowly stated permitted actions. No model registry alias, benchmark result,
or successful advisory period can authorize it automatically.

## 15. What must not be built yet

- A general online/offline feature store such as Feast. Borrow its point-in-time discipline; do not
  operate its service before repeated features and a live scoring consumer exist.
- Kafka/Flink-style streaming feature computation or event-driven online retraining.
- Delta/Iceberg/lakehouse catalogs, distributed SQL, or a mutable “single source of truth” warehouse.
- Airflow, Dagster, Kubeflow, Ray clusters, Kubernetes, or a bespoke workflow engine.
- A vector database for the pilot retrieval corpus.
- A central MLflow server/model registry before filesystem run manifests become painful.
- Separate Julia, OCaml, and C# research implementations of the same features.
- Python↔Julia or Python↔OCaml in-process FFI.
- ONNX export and production scoring wrappers without a promoted model and consumer.
- Deep end-to-end chart/social architectures before strong structured and frozen-encoder baselines.
- Fine-tuning an LLM on interviews or private operator traces before consent, corpus quality, and a
  task-specific evaluation exist.
- An agent that autonomously rewrites labels, dispositions, episode boundaries, or production
  prompts.
- Self-promoting continual learning, reinforcement learning on live capital, or an automated bandit.
- A bespoke market simulator used as ground truth before quote/execution replay is validated.
- A universal ontology that turns drawings and interviews into one “correct” label.

## 16. Smallest useful environment experiment

Build nothing in this lane yet; first approve a bounded design spike whose intended output is a
reproducibility report.

Use a small frozen corpus containing:

- a handful of complete prospective scenes/episodes from the first cockpit slice;
- at least one partial exit/runner transition;
- at least one flat-watching/re-entry sequence if naturally observed;
- contemporaneous choice-set alternatives;
- one chart drawing and one immediate/retrospective interview pair; and
- explicit gap, late-arrival, and unquotable examples.

Define one simple task: retrieve analogous prior scenes without showing outcomes. Run it once from
a Python job and inspect it in a notebook. Rebuild the snapshot after new evidence has arrived and
verify that the original snapshot and run remain unchanged. Deliberately introduce:

- a late backfill with an old event time;
- a future identity resolution;
- a duplicate mint/episode row;
- a changed feature definition under the old name; and
- a missing blob.

The environment design passes only if it rejects or versions every fault, reconstructs the exact
example/split/run inputs, renders the drawing/interview supervision without flattening provenance,
and produces no path by which the exploratory score enters the cockpit.

After that, add the next dependency only for the next named study—nonparametric competing risks is a
plausible first one. The correct initial achievement is not “we have an ML platform.” It is “a
later model can learn from this episode without changing what the episode was.”

## 17. Current primary-source notes

The following implementation facts were checked against current project documentation on
2026-08-16 and should be rechecked before engineering:

- DuckDB reads/writes Parquet with filter/projection pushdown and provides ASOF joins.
  [Parquet](https://duckdb.org/docs/stable/data/parquet/overview),
  [ASOF](https://duckdb.org/docs/current/guides/sql_features/asof_join)
- Arrow currently maintains official Python, Julia, and .NET implementations; capabilities differ
  by language and interface. [Implementations](https://arrow.apache.org/docs/implementations.html),
  [status matrix](https://arrow.apache.org/docs/status.html)
- Arrow's format is stable across the 1.x format line, while the project cautions that IPC is not
  optimized as a long-term archival format in the way compressed Parquet often is.
  [Arrow format stability](https://arrow.apache.org/docs/format/Versioning.html),
  [Arrow FAQ](https://arrow.apache.org/faq/)
- Julia Pkg manifests record exact package graphs; Arrow.jl supports IPC but currently lacks Flight
  and the C Data Interface. [Julia Pkg](https://pkgdocs.julialang.org/v1/toml-files/),
  [Arrow.jl](https://arrow.apache.org/julia/)
- PyTorch warns that full reproducibility is not guaranteed across software releases or hardware
  platforms. [PyTorch reproducibility](https://docs.pytorch.org/docs/stable/notes/randomness)
- MLflow offers run/artifact/dataset tracking and model-registry functions, but those do not encode
  Joshi's evidence and temporal semantics by themselves. [MLflow Tracking](https://mlflow.org/docs/latest/ml/tracking/)

## 18. Unresolved decisions

1. What is the reviewed local artifact root and retention policy for raw media/audio versus derived
   transcripts and embeddings?
2. Which exact Python versions/platforms must the initial lock support: Ember's macOS machine only,
   or macOS plus a Linux execution target?
3. Which snapshot tables need cross-language Arrow compatibility, and which can remain
   Python/DuckDB-internal?
4. What tolerance defines logical reproduction for floating-point statistics and GPU embeddings?
5. Which operator-visible retrieval output is useful enough to justify becoming the first advisory
   treatment?
6. What is the first competing-risk event vocabulary stable enough to freeze as labels?
7. Will chart drawing arrive through a native Joshi chart, a permitted Padre/Pump companion capture,
   or both, and can the exact chart transform be recovered?
8. What interview media may leave the local machine for external transcription or LLM analysis?
9. What evidence volume or collaboration pain would justify MLflow, a vector database, or a feature
   store rather than merely make them fashionable?
10. Which future product language, if any, creates a real C#/OCaml deployment boundary?

The recommended principle is simple: **a research environment may become more powerful without
becoming more authoritative. Evidence stays immutable, evaluation stays prospective and
point-in-time correct, and promotion remains a deliberate human act.**
