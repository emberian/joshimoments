# Wave 6 store-resolved operator-evidence input

Status: **useful partial**. V22 closes one exact W5 discovery census, headed Cockpit V2 scene,
durable gapped operator act, and separate later browser-reported mount into one sole-store-built
Wave 6 input. It is not a human-viewing, recognition, replay-result, operator-model, product, or
live claim.

## Exact boundary

Migration `0022_wave6_operator_evidence_input.sql` adds the append-only
`wave6_operator_evidence_input_v1` row. The public commit method accepts only five identities and a
batch/build label. The store independently reloads and revalidates:

- the exact W6 fixture program and its V20 store-resolved input census;
- the source occurrence, headed immutable Cockpit V2 publication, and both semantic and physical
  publication/head digests;
- the exact W5 `operator_act` bytes, queue generation, session, subject, committed-scene binding,
  catalog cutoff, and original typed `not_mounted` presentation gap; and
- the later exact browser claim, claim bytes/digests, paired session lineage, rendered-subject set,
  publication/source binding, and store commit.

The bridge requires one subject shared by the eligible source denominator, durable act, and later
claim. It requires strict publication -> head -> act -> presentation commit order. It retains the
full typed act and claim inside the store-built document, then reparses and independently rebuilds
that document from all priors after commit and read-only restart. Exact retry returns the original
identity and commit. An episode cannot substitute for the act; a missing/foreign presentation
cannot substitute for the selected claim.

Core embeds both that exact store-built document and the full store-reloaded V20 census in its JSON
report. The locked Python `wave6_operator_model.store_input` validator preserves Rust field order,
recomputes the physical operator document, memory occurrence, browser claim, and claim-material
digests, then reuses the strict V20 census validator to rederive its source receipt, denominator,
hot/cold partition, coverage, omissions, binding, and document digest. It cross-closes both embedded
documents against the same program, source occurrence, and commit lineage. Duplicate/reordered JSON
and re-signed census-relabelling, subject, gap, or qualification substitutions refuse.

The later browser report does **not** rewrite or repair the act. The two session identifiers remain
in their distinct memory and pairing domains, with no equivalence claim. The document fixes:

```text
actPresentationGapRetained    true
presentationRepairsActGap     false
sessionEquivalenceClaimed     false
humanViewingVerified          false
recognitionObserved           false
operatorModelResolved         false
```

## Offline witness

Run the bounded command directly:

```bash
cargo run --locked --offline -q -p joshi-core -- \
  wave6-operator-evidence-input \
  --state /tmp/joshi-wave6-operator-input.manual/catalog
```

Or run the complete focused gate:

```bash
./scripts/wave6-operator-evidence-input-readiness
```

The command creates the W5 G0 prefix and its distinct browser-evidence overlay when absent, runs
the in-process scripted browser-format claim path without opening a network socket, commits the W6
program and V20 census, commits/retries V22, and reopens it read-only. A whole-command retry selects
the original V22 input rather than minting another presentation. The focused gate then feeds both
reports through the locked Python validator and requires identical binding, document, and commit
coordinates with the explicit non-admission receipt.

## Hard ceiling

The store contract's exact ceiling is `store_resolved_operator_evidence_input_only`, with claim
scope
`store_resolved_act_gap_and_later_browser_report_not_human_recognition_or_operator_model`.

The Core witness separately labels `scriptedPresentationPath=true`. That path proves protocol,
pairing, durable-report, and restart closure only. No connected browser was observed; the claim is
not pixel verification or evidence that Ember saw, understood, recognized, or responded to the
scene. The bridge does not instantiate the Python Wave 6 operator-model protocol and supplies no
recognition response, ontology label truth, economic effect, outcome, provider I/O, external
mutation, product qualification, or live qualification.

The Python receipt's ceiling is
`cross_runtime_store_input_validated_not_model_admitted`. It does not construct `SceneBinding`,
`ReplayMaterialReceipt`, `RecognitionResponse`, or any model output.
