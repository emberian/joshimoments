//! Follow a sibling-written catalog: new immutable scenes, never a mutated one.
//!
//! `live-surface-inspect` derives one scene and serves it byte-for-byte forever. A keeper daemon
//! now keeps the source catalog advancing, so this module makes the served surface follow it
//! without giving V1 the mutable current-scene pointer it deliberately refuses: liveness here is
//! NEW scenes appearing in a feed, plus the operator choosing to advance. A scene, once derived,
//! is never re-derived into different bytes and never swapped under an act.
//!
//! # Generations
//!
//! An operator act is only accepted when the catalog it commits into can re-check the scene it
//! names: `commit_operator_v1` re-reads every evidence row and watermark. A scene derived from a
//! newer source cutoff therefore cannot bind an act inside an overlay copied at an older cutoff,
//! and the source's history cannot be merged into a diverged overlay without fabricating
//! provenance. So the follow mount keeps *generations*: each advance re-runs the existing
//! SQLite-backup overlay pattern into a fresh directory, the newest generation receives every new
//! act (its copied history is a superset of every earlier cutoff, so old scenes bind there too),
//! and an older generation is retained exactly as long as it holds acts nothing else retains.
//! Pairing state lives in its own small catalog so following never logs the operator out.
//!
//! What is honest about this shape: every scene is re-derivable, byte-for-byte, from the newest
//! generation at its recorded cutoff, because the source is append-only and a backup copies its
//! commit history verbatim. Restart re-derives and *verifies* rather than trusting the sidecar.
//!
//! # A scene appears only when the source actually observed something
//!
//! Every derivation is cut at the source's `delivered_through` — the highest commit that carries
//! an observation from the followed source — never at the catalog's max commit. Scene identity is
//! a deterministic function of that cutoff and the observation identities beneath it, so a commit
//! that carries no new observation (an operator act, a journal write, another source's traffic)
//! can never mint a scene: the tick backs the catalog up, sees the watermark unchanged, discards
//! the copy and reports `unchanged`. Without this rule, a client following "act on the newest
//! scene" would chase its own tail — each act re-rendering a "new" scene over unchanged evidence,
//! which invites another look, which invites another act. The feed carries the cutoff on every
//! row precisely so a client advances on new *evidence*, not on a new scene identity.

use crate::{
    live_gesture::{LiveGestureError, copy_blob_tree, source_catalog_config},
    live_surface::{
        LiveSurfaceError, LiveSurfaceOptions, MAX_LIVE_OBSERVATIONS, derive_live_surface_with,
        source_identity,
    },
    service::operator_capture,
};
use joshi_domain::{CommitSeq, SceneId, SourceId, StableString, UtcTimestamp};
use joshi_operator::{CommandReceiptV1, ValidatedGlassViewV1, ValidatedOperatorCommandV1};
use joshi_store::{SqliteStore, StoreConfig, StoreMode, StoredOperatorCommandV1};
use serde::{Deserialize, Serialize};
use std::{
    fs,
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
    time::Duration,
};
use thiserror::Error;

/// Where a follow mount keeps everything it writes: generations, pairing, and its scene ledger.
#[must_use]
pub fn follow_root(state: &Path) -> PathBuf {
    state.join("live-follow")
}

fn state_file(root: &Path) -> PathBuf {
    root.join("follow-state.json")
}

/// Store configuration for one generation: a consistent backup of the source catalog.
fn generation_catalog_config(dir: &Path) -> Result<StoreConfig, FollowError> {
    Ok(StoreConfig {
        catalog_path: dir.join("catalog.sqlite"),
        blob_root: dir.join("blobs"),
        export_root: dir.join("exports"),
        inline_blob_max_bytes: 64 * 1024,
        busy_timeout: Duration::from_secs(2),
        catalog_id: StableString::new("joshi-live-follow-generation")?,
        max_observations_per_batch: 256,
        max_raw_bytes_per_batch: 4 * 1024 * 1024,
    })
}

/// Store configuration for the pairing catalog a follow mount keeps beside its generations.
///
/// Pairing epochs and session occurrences are writes of this process, not of the source, and a
/// generation is replaced whenever the source advances. Keeping pairing in its own catalog means
/// following never invalidates the operator's session.
///
/// # Errors
///
/// Fails when the catalog identity is not a valid wire string.
pub fn pairing_catalog_config(state: &Path) -> Result<StoreConfig, FollowError> {
    let root = follow_root(state).join("pairing");
    Ok(StoreConfig {
        catalog_path: root.join("catalog.sqlite"),
        blob_root: root.join("blobs"),
        export_root: root.join("exports"),
        inline_blob_max_bytes: 64 * 1024,
        busy_timeout: Duration::from_secs(2),
        catalog_id: StableString::new("joshi-live-follow-pairing")?,
        max_observations_per_batch: 256,
        max_raw_bytes_per_batch: 4 * 1024 * 1024,
    })
}

/// Opens (creating if absent) the pairing catalog for a follow mount, migrated to head.
///
/// # Errors
///
/// Fails on store open or migration failure.
pub fn open_pairing_store(state: &Path) -> Result<SqliteStore, FollowError> {
    let mut store = SqliteStore::open(pairing_catalog_config(state)?, StoreMode::SingleWriter)?;
    store.migrate(now()?)?;
    Ok(store)
}

/// One derived immutable scene: the exact facts the feed states about it, plus its bytes.
struct SceneRecord {
    view: Arc<ValidatedGlassViewV1>,
    fact: SceneFact,
}

/// The durable, restart-surviving facts about one derived scene.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SceneFact {
    scene_id: String,
    /// The exact commit the derivation was cut at: the source's `delivered_through` at that poll.
    cutoff_commit_seq: String,
    /// Wall clock of the derivation itself. This is the scene's age; it is never data freshness.
    derived_at: String,
    subject_count: String,
    observation_count: String,
    view_digest: String,
}

struct Generation {
    basis: u64,
    dir: PathBuf,
    store: SqliteStore,
    has_acts: bool,
}

/// The last time this process actually looked at the source catalog, and what it found.
///
/// This is deliberately separate from the scene list. The scenes are facts this process already
/// holds and can always state; whether the source catalog could be reached just now is a different
/// claim, and an unreachable catalog must never be rendered as an empty feed.
#[derive(Clone, Debug, Eq, PartialEq)]
enum CatalogContact {
    /// The initial mount read the source and derived the first scene.
    Mounted { at: String },
    /// Remounted from retained state; the source has not been polled since this process started.
    NotYetPolled,
    /// A poll found new source commits and a new scene was derived.
    Advanced { at: String },
    /// A poll found nothing new for the followed source.
    Unchanged { at: String },
    /// The source catalog could not be read. The scenes already derived remain served.
    Unreachable { at: String, detail: String },
}

struct FollowState {
    generations: Vec<Generation>,
    /// Oldest first; the feed serves them reversed.
    scenes: Vec<SceneRecord>,
    contact: CatalogContact,
    /// Highest source commit already inspected and found to carry nothing new for the followed
    /// source. Skips re-copying a catalog whose advance was other traffic; in-memory only, so a
    /// restart re-checks from scratch.
    futile_through: u64,
}

/// What one poll of the source catalog concluded.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TickOutcome {
    /// A new scene was derived at this cutoff and appended to the feed.
    Advanced { scene_id: String },
    /// The source delivered nothing new for the followed source.
    Unchanged,
    /// The source catalog could not be read; the reason is recorded and stated by the feed.
    Unreachable { detail: String },
}

/// Sidecar ledger persisted under the follow root. Every scene entry is *verified* by exact
/// re-derivation or digest-checked durable readback at remount, never trusted.
#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PersistedFollowState {
    contract: String,
    schema_version: u16,
    source_id: String,
    scenes: Vec<SceneFact>,
    generations: Vec<PersistedGeneration>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PersistedGeneration {
    basis_commit_seq: String,
    dir_name: String,
    has_acts: bool,
}

/// A mounted follow surface: the scene registry, its generations, and the poll loop's target.
pub struct FollowRuntime {
    catalog: PathBuf,
    root: PathBuf,
    source: SourceId,
    options: LiveSurfaceOptions,
    state: Mutex<FollowState>,
}

impl FollowRuntime {
    /// Mounts a follow surface over one source catalog, fresh or from retained state.
    ///
    /// A fresh mount backs the source up into the first generation and derives the first scene at
    /// the source's delivered-through cutoff. A remount reopens every retained generation, replays
    /// nothing, and re-verifies every recorded scene byte-for-byte before serving it again.
    ///
    /// # Errors
    ///
    /// Refuses an unreadable source, an unusable follow root, retained state that no longer
    /// re-derives to its recorded bytes, or any derivation refusal.
    pub fn mount(
        catalog: &Path,
        state: &Path,
        source_id: &str,
        options: &LiveSurfaceOptions,
    ) -> Result<Arc<Self>, FollowError> {
        let root = follow_root(state);
        let source = source_identity(source_id)?;
        if state_file(&root).is_file() {
            Self::remount(catalog, &root, source, options)
        } else {
            Self::fresh_mount(catalog, &root, source, options)
        }
    }

    fn fresh_mount(
        catalog: &Path,
        root: &Path,
        source: SourceId,
        options: &LiveSurfaceOptions,
    ) -> Result<Arc<Self>, FollowError> {
        fs::create_dir_all(root).map_err(|error| FollowError::Io(error.to_string()))?;
        // A crash between creating a generation and writing the ledger leaves directories no
        // ledger names. No act can exist in them (acts imply a mounted runtime, which implies a
        // written ledger), so they are stale copies and are removed rather than guessed about.
        for entry in fs::read_dir(root).map_err(|error| FollowError::Io(error.to_string()))? {
            let entry = entry.map_err(|error| FollowError::Io(error.to_string()))?;
            let name = entry.file_name().to_string_lossy().into_owned();
            if name.starts_with("gen-") || name.starts_with("pending-") {
                fs::remove_dir_all(entry.path())
                    .map_err(|error| FollowError::Io(error.to_string()))?;
            }
        }
        let mounted_at = now()?.to_string();
        let source_store = SqliteStore::open(
            source_catalog_config(catalog).map_err(Box::new)?,
            StoreMode::ReadOnly,
        )?;
        let generation = build_generation(catalog, &source_store, root)?;
        drop(source_store);
        let runtime = Self {
            catalog: catalog.to_owned(),
            root: root.to_owned(),
            source,
            options: options.clone(),
            state: Mutex::new(FollowState {
                generations: Vec::new(),
                scenes: Vec::new(),
                contact: CatalogContact::Mounted { at: mounted_at },
                futile_through: 0,
            }),
        };
        let (generation, scene) = runtime.derive_from(generation)?;
        {
            let mut state = runtime.lock()?;
            state.generations.push(generation);
            state.scenes.push(scene);
            runtime.persist(&state)?;
        }
        Ok(Arc::new(runtime))
    }

    fn remount(
        catalog: &Path,
        root: &Path,
        source: SourceId,
        options: &LiveSurfaceOptions,
    ) -> Result<Arc<Self>, FollowError> {
        let bytes =
            fs::read(state_file(root)).map_err(|error| FollowError::Io(error.to_string()))?;
        let persisted: PersistedFollowState = serde_json::from_slice(&bytes)?;
        if persisted.contract != "joshi.core.live_follow_state" || persisted.schema_version != 1 {
            return Err(FollowError::State(
                "retained follow ledger has an unknown contract".to_owned(),
            ));
        }
        if persisted.source_id != source.as_str() {
            return Err(FollowError::State(format!(
                "retained follow ledger follows source {}, not {}",
                persisted.source_id, source
            )));
        }
        let mut generations = Vec::with_capacity(persisted.generations.len());
        for entry in &persisted.generations {
            let dir = root.join(&entry.dir_name);
            if !dir.is_dir() {
                return Err(FollowError::State(format!(
                    "retained follow ledger names generation {} but the directory is gone",
                    entry.dir_name
                )));
            }
            let mut store =
                SqliteStore::open(generation_catalog_config(&dir)?, StoreMode::SingleWriter)?;
            store.migrate(now()?)?;
            generations.push(Generation {
                basis: entry.basis_commit_seq.parse().map_err(|_| {
                    FollowError::State("generation basis is not a commit".to_owned())
                })?,
                dir,
                store,
                has_acts: entry.has_acts,
            });
        }
        let Some(current) = generations.last() else {
            return Err(FollowError::State(
                "retained follow ledger names no generation".to_owned(),
            ));
        };
        // Re-verify every recorded scene: durable bytes where an act retained them, exact
        // re-derivation from the newest generation everywhere else. A mismatch is corruption of
        // this mount's own state and is refused loudly rather than served quietly.
        let mut scenes = Vec::with_capacity(persisted.scenes.len());
        for fact in persisted.scenes {
            let scene_id = SceneId::new(fact.scene_id.clone())?;
            let durable = generations
                .iter()
                .rev()
                .find_map(|generation| generation.store.load_scene(&scene_id).ok());
            let view = if let Some(stored) = durable {
                ValidatedGlassViewV1::parse_exact(&stored.view_bytes, Some(&fact.view_digest))
                    .map_err(|error| {
                        FollowError::State(format!(
                            "retained scene {} no longer matches its recorded digest: {error}",
                            fact.scene_id
                        ))
                    })?
            } else {
                let cutoff = fact
                    .cutoff_commit_seq
                    .parse()
                    .map_err(|_| FollowError::State("scene cutoff is not a commit".to_owned()))?;
                let derived = derive_live_surface_with(
                    &current.store,
                    &source,
                    Some(CommitSeq::new(cutoff)),
                    options,
                )?;
                if derived.report.scene_id != fact.scene_id
                    || derived.report.view_digest != fact.view_digest
                {
                    return Err(FollowError::State(format!(
                        "scene {} does not re-derive to its recorded identity at commit {}",
                        fact.scene_id, fact.cutoff_commit_seq
                    )));
                }
                derived.view
            };
            scenes.push(SceneRecord {
                view: Arc::new(view),
                fact,
            });
        }
        Ok(Arc::new(Self {
            catalog: catalog.to_owned(),
            root: root.to_owned(),
            source,
            options: options.clone(),
            state: Mutex::new(FollowState {
                generations,
                scenes,
                contact: CatalogContact::NotYetPolled,
                futile_through: 0,
            }),
        }))
    }

    /// Derive one scene from a freshly built generation at the source's delivered-through cutoff.
    fn derive_from(
        &self,
        generation: Generation,
    ) -> Result<(Generation, SceneRecord), FollowError> {
        let durable = generation
            .store
            .source_observations_as_known(&self.source, None, MAX_LIVE_OBSERVATIONS)?
            .ok_or_else(|| FollowError::NoObservations(self.source.to_string()))?;
        let cutoff = durable.delivered_through;
        let derived =
            derive_live_surface_with(&generation.store, &self.source, Some(cutoff), &self.options)?;
        let fact = SceneFact {
            scene_id: derived.report.scene_id.clone(),
            cutoff_commit_seq: cutoff.get().to_string(),
            derived_at: now()?.to_string(),
            subject_count: derived.report.candidate_count.to_string(),
            observation_count: derived.report.observation_count.to_string(),
            view_digest: derived.report.view_digest.clone(),
        };
        Ok((
            generation,
            SceneRecord {
                view: Arc::new(derived.view),
                fact,
            },
        ))
    }

    /// Poll the source catalog once; derive and install a new scene when it advanced.
    ///
    /// The expensive work (backup, derivation) happens without holding the state lock, so the
    /// routes keep serving while a new generation is being built.
    ///
    /// # Errors
    ///
    /// Fails only on this mount's own filesystem or lock failures. A source catalog that cannot
    /// be read is not an error here: it is recorded and stated by the feed as `unreachable`.
    pub fn tick(&self) -> Result<TickOutcome, FollowError> {
        let at = now()?.to_string();
        let (already_inspected, last_cutoff) = {
            let state = self.lock()?;
            let basis = state
                .generations
                .last()
                .map_or(0, |generation| generation.basis);
            let cutoff = state
                .scenes
                .last()
                .and_then(|scene| scene.fact.cutoff_commit_seq.parse::<u64>().ok())
                .unwrap_or(0);
            (basis.max(state.futile_through), cutoff)
        };
        let probe = SqliteStore::open(
            source_catalog_config(&self.catalog).map_err(Box::new)?,
            StoreMode::ReadOnly,
        )
        .and_then(|store| {
            store
                .source_observations_as_known(&self.source, None, 1)
                .map(|durable| (store, durable))
        });
        let (source_store, durable) = match probe {
            Ok(value) => value,
            Err(error) => {
                let detail = error.to_string();
                self.record_contact(CatalogContact::Unreachable {
                    at,
                    detail: detail.clone(),
                })?;
                return Ok(TickOutcome::Unreachable { detail });
            }
        };
        let Some(durable) = durable else {
            // Reachable, but the followed source has delivered nothing: nothing advanced.
            self.record_contact(CatalogContact::Unchanged { at })?;
            return Ok(TickOutcome::Unchanged);
        };
        if durable.through_commit_seq.get() <= already_inspected {
            self.record_contact(CatalogContact::Unchanged { at })?;
            return Ok(TickOutcome::Unchanged);
        }
        let generation = build_generation(&self.catalog, &source_store, &self.root)?;
        drop(source_store);
        let advanced = generation
            .store
            .source_observations_as_known(&self.source, None, MAX_LIVE_OBSERVATIONS)?
            .is_some_and(|copied| copied.delivered_through.get() > last_cutoff);
        if !advanced {
            // The catalog advanced, but not for the followed source. Deriving here would mint a
            // new scene identity over identical observations, which is noise, not liveness. The
            // inspected watermark is remembered so quiet other-source traffic is not re-copied
            // on every poll.
            let inspected = generation.basis;
            let dir = generation.dir.clone();
            drop(generation);
            fs::remove_dir_all(dir).map_err(|error| FollowError::Io(error.to_string()))?;
            let mut state = self.lock()?;
            state.futile_through = state.futile_through.max(inspected);
            state.contact = CatalogContact::Unchanged { at };
            return Ok(TickOutcome::Unchanged);
        }
        let (generation, scene) = self.derive_from(generation)?;
        let scene_id = scene.fact.scene_id.clone();
        {
            let mut state = self.lock()?;
            // Prune the superseded generation only when it retains no acts. Its scenes stay
            // re-derivable from the new generation, because a backup carries the whole history.
            if let Some(previous) = state.generations.pop() {
                if previous.has_acts {
                    state.generations.push(previous);
                } else {
                    let dir = previous.dir.clone();
                    drop(previous);
                    fs::remove_dir_all(dir).map_err(|error| FollowError::Io(error.to_string()))?;
                }
            }
            state.generations.push(generation);
            state.scenes.push(scene);
            state.contact = CatalogContact::Advanced { at };
            self.persist(&state)?;
        }
        Ok(TickOutcome::Advanced { scene_id })
    }

    /// The newest derived scene identity, for the launcher to print.
    ///
    /// # Errors
    ///
    /// Fails only when the state lock is poisoned.
    pub fn newest_scene_id(&self) -> Result<String, FollowError> {
        let state = self.lock()?;
        state
            .scenes
            .last()
            .map(|scene| scene.fact.scene_id.clone())
            .ok_or(FollowError::Invariant(
                "a follow mount holds at least one scene",
            ))
    }

    /// Exact bytes and mode for one scene this mount serves, durable bytes preferred.
    ///
    /// # Errors
    ///
    /// Fails only when the state lock is poisoned; an unknown scene is `Ok(None)`.
    pub(crate) fn scene_bytes(
        &self,
        scene_id: &SceneId,
    ) -> Result<Option<(Vec<u8>, &'static str)>, FollowError> {
        let state = self.lock()?;
        for generation in state.generations.iter().rev() {
            if let Ok(stored) = generation.store.load_scene(scene_id) {
                return Ok(Some((
                    stored.view_bytes,
                    super::service::mode_name(stored.mode),
                )));
            }
        }
        Ok(state
            .scenes
            .iter()
            .find(|record| record.view.scene_id() == scene_id)
            .map(|record| {
                (
                    record.view.canonical_bytes().to_vec(),
                    super::service::glass_mode_name(&record.view),
                )
            }))
    }

    /// Commit one operator act into the generation that can re-check the scene it names.
    ///
    /// A new act always lands in the newest generation, whose copied history is a superset of
    /// every derived cutoff. An exact retry of an act an older retained generation already holds
    /// is routed back to that generation, so the retry returns the original durable closure.
    ///
    /// # Errors
    ///
    /// Fails when the named scene cannot be re-checked or the store refuses the act.
    pub(crate) fn commit_act(
        &self,
        command: &ValidatedOperatorCommandV1,
        committed_at: UtcTimestamp,
        committed_mono_ns: u64,
        writer_clock_id: &str,
    ) -> Result<CommandReceiptV1, FollowError> {
        let mut state = self.lock()?;
        let count = state.generations.len();
        if count == 0 {
            return Err(FollowError::Invariant("a follow mount holds a generation"));
        }
        let capture = |mounting: bool| {
            operator_capture(mounting, writer_clock_id)
                .map_err(|error| FollowError::State(error.to_string()))
        };
        for index in 0..count - 1 {
            let held = state.generations[index]
                .store
                .operator_commands_for_scene_v1(command.scene_id())?
                .iter()
                .any(|stored| stored.command_id.as_str() == command.command_id().as_str());
            if held {
                let receipt = state.generations[index].store.commit_operator_v1(
                    command,
                    None,
                    &capture(false)?,
                    committed_at,
                    StableString::new(writer_clock_id)?,
                    committed_mono_ns,
                    StableString::new(env!("CARGO_PKG_VERSION"))?,
                )?;
                return Ok(receipt);
            }
        }
        let mounted = state
            .scenes
            .iter()
            .find(|record| record.view.scene_id() == command.scene_id())
            .map(|record| record.view.clone())
            .filter(|view| {
                state.generations[count - 1]
                    .store
                    .load_scene(view.scene_id())
                    .is_err()
            });
        let receipt = state.generations[count - 1].store.commit_operator_v1(
            command,
            mounted.as_deref(),
            &capture(mounted.is_some())?,
            committed_at,
            StableString::new(writer_clock_id)?,
            committed_mono_ns,
            StableString::new(env!("CARGO_PKG_VERSION"))?,
        )?;
        if !state.generations[count - 1].has_acts {
            state.generations[count - 1].has_acts = true;
            self.persist(&state)?;
        }
        Ok(receipt)
    }

    /// Every durable act bound to one scene, across every retained generation, oldest catalog
    /// first. Also states whether the scene itself is durable anywhere or still served-only.
    pub(crate) fn readback(
        &self,
        scene_id: &SceneId,
    ) -> Result<Option<(&'static str, Vec<StoredOperatorCommandV1>)>, FollowError> {
        let state = self.lock()?;
        let mut durable = false;
        let mut commands = Vec::new();
        for generation in &state.generations {
            if generation.store.load_scene(scene_id).is_ok() {
                durable = true;
            }
            commands.extend(generation.store.operator_commands_for_scene_v1(scene_id)?);
        }
        if durable {
            return Ok(Some(("durable", commands)));
        }
        let served = state
            .scenes
            .iter()
            .any(|record| record.view.scene_id() == scene_id);
        if served {
            return Ok(Some(("served_not_yet_durable", commands)));
        }
        Ok(None)
    }

    /// The scene feed: every derived scene newest-first, plus the last actual catalog contact.
    ///
    /// # Errors
    ///
    /// Fails only when the state lock is poisoned.
    pub fn feed_wire(&self) -> Result<SceneFeedWire, FollowError> {
        let state = self.lock()?;
        let scenes = state
            .scenes
            .iter()
            .rev()
            .map(|record| {
                let durable = state
                    .generations
                    .iter()
                    .any(|generation| generation.store.load_scene(record.view.scene_id()).is_ok());
                SceneFeedEntryWire {
                    scene_id: record.fact.scene_id.clone(),
                    derived_at: record.fact.derived_at.clone(),
                    cutoff_commit_seq: record.fact.cutoff_commit_seq.clone(),
                    subject_count: record.fact.subject_count.clone(),
                    observation_count: record.fact.observation_count.clone(),
                    view_digest: record.fact.view_digest.clone(),
                    scene_retention: if durable {
                        "durable"
                    } else {
                        "served_not_yet_durable"
                    },
                }
            })
            .collect();
        let (outcome, last_contact_at, detail) = match &state.contact {
            CatalogContact::Mounted { at } => ("mounted", Some(at.clone()), None),
            CatalogContact::NotYetPolled => ("not_yet_polled_since_restart", None, None),
            CatalogContact::Advanced { at } => ("advanced", Some(at.clone()), None),
            CatalogContact::Unchanged { at } => ("unchanged", Some(at.clone()), None),
            CatalogContact::Unreachable { at, detail } => {
                ("unreachable", Some(at.clone()), Some(detail.clone()))
            }
        };
        Ok(SceneFeedWire {
            contract: "joshi.core.scene_feed",
            schema_version: 1,
            authority: "read_only_no_execution",
            source_id: self.source.to_string(),
            scenes,
            catalog: CatalogContactWire {
                outcome,
                last_contact_at,
                detail,
                basis_commit_seq: state
                    .generations
                    .last()
                    .map_or_else(|| "0".to_owned(), |generation| generation.basis.to_string()),
            },
        })
    }

    fn record_contact(&self, contact: CatalogContact) -> Result<(), FollowError> {
        let mut state = self.lock()?;
        state.contact = contact;
        Ok(())
    }

    fn lock(&self) -> Result<std::sync::MutexGuard<'_, FollowState>, FollowError> {
        self.state.lock().map_err(|_| FollowError::LockPoisoned)
    }

    fn persist(&self, state: &FollowState) -> Result<(), FollowError> {
        let persisted = PersistedFollowState {
            contract: "joshi.core.live_follow_state".to_owned(),
            schema_version: 1,
            source_id: self.source.to_string(),
            scenes: state
                .scenes
                .iter()
                .map(|record| record.fact.clone())
                .collect(),
            generations: state
                .generations
                .iter()
                .map(|generation| PersistedGeneration {
                    basis_commit_seq: generation.basis.to_string(),
                    dir_name: generation
                        .dir
                        .file_name()
                        .map(|name| name.to_string_lossy().into_owned())
                        .unwrap_or_default(),
                    has_acts: generation.has_acts,
                })
                .collect(),
        };
        let bytes = serde_json::to_vec_pretty(&persisted)?;
        let target = state_file(&self.root);
        let temporary = self.root.join("follow-state.json.tmp");
        fs::write(&temporary, bytes).map_err(|error| FollowError::Io(error.to_string()))?;
        fs::rename(&temporary, target).map_err(|error| FollowError::Io(error.to_string()))
    }
}

/// Back the source catalog up into a fresh generation directory named by its basis commit.
///
/// The source is only ever read through the consistent `SQLite` backup API, so the sibling writer
/// is never disturbed and the copy is a transactionally consistent prefix of its history.
fn build_generation(
    catalog: &Path,
    source_store: &SqliteStore,
    root: &Path,
) -> Result<Generation, FollowError> {
    let pending = root.join(format!("pending-{}", std::process::id()));
    if pending.exists() {
        fs::remove_dir_all(&pending).map_err(|error| FollowError::Io(error.to_string()))?;
    }
    fs::create_dir_all(&pending).map_err(|error| FollowError::Io(error.to_string()))?;
    let manifest = source_store.backup_to(&pending.join("catalog.sqlite"))?;
    copy_blob_tree(&catalog.join("blobs"), &pending.join("blobs")).map_err(Box::new)?;
    let basis = manifest.max_commit_seq.get();
    let dir = root.join(format!("gen-{basis}"));
    if dir.exists() {
        // A same-basis generation can only be a stale leftover; the fresh copy replaces it.
        fs::remove_dir_all(&dir).map_err(|error| FollowError::Io(error.to_string()))?;
    }
    fs::rename(&pending, &dir).map_err(|error| FollowError::Io(error.to_string()))?;
    let mut store = SqliteStore::open(generation_catalog_config(&dir)?, StoreMode::SingleWriter)?;
    store.migrate(now()?)?;
    Ok(Generation {
        basis,
        dir,
        store,
        has_acts: false,
    })
}

fn now() -> Result<UtcTimestamp, FollowError> {
    crate::live_gesture::now().map_err(|_| FollowError::Clock)
}

/// The feed a client polls to learn that newer scenes exist. A list of immutable facts, not a
/// mutable pointer: nothing here ever changes which scene a client is bound to.
#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SceneFeedWire {
    pub contract: &'static str,
    pub schema_version: u16,
    pub authority: &'static str,
    pub source_id: String,
    /// Newest first.
    pub scenes: Vec<SceneFeedEntryWire>,
    pub catalog: CatalogContactWire,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SceneFeedEntryWire {
    pub scene_id: String,
    /// When this process derived the scene. The scene's age; never the data's freshness.
    pub derived_at: String,
    /// The evidence watermark this scene was cut at: the highest source commit carrying an
    /// observation from the followed source. Two rows differ here only when the source actually
    /// delivered something new, so a client advances on this value, never on a new scene id.
    pub cutoff_commit_seq: String,
    pub subject_count: String,
    pub observation_count: String,
    pub view_digest: String,
    pub scene_retention: &'static str,
}

/// Whether the source catalog could actually be looked at, stated separately from the scene
/// list so an unreachable catalog is never mistaken for an empty one.
#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CatalogContactWire {
    pub outcome: &'static str,
    pub last_contact_at: Option<String>,
    pub detail: Option<String>,
    pub basis_commit_seq: String,
}

#[derive(Debug, Error)]
pub enum FollowError {
    #[error(transparent)]
    Store(#[from] joshi_store::StoreError),
    #[error(transparent)]
    Surface(#[from] LiveSurfaceError),
    #[error(transparent)]
    Gesture(#[from] Box<LiveGestureError>),
    #[error(transparent)]
    Wire(#[from] joshi_domain::WireStringError),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error("live follow filesystem failure: {0}")]
    Io(String),
    #[error("retained follow state is unusable: {0}")]
    State(String),
    #[error("catalog holds no durable observation for source {0}")]
    NoObservations(String),
    #[error("follow state lock is poisoned")]
    LockPoisoned,
    #[error("clock is unavailable")]
    Clock,
    #[error("live follow invariant failed: {0}")]
    Invariant(&'static str),
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        live_gesture::{
            authorized, exchange,
            live_fixture::{
                FIXTURE_MINT, FIXTURE_SOURCE, commit_bystander_frame, extend_catalog, seed_catalog,
            },
            mark_command_bytes, qualified_digest, response_bytes, send,
        },
        service::{CoreService, PairingCapability},
    };
    use axum::{Router, body::Body, http::StatusCode};
    use joshi_pairing::{PairingConfig, PairingOrigin, PairingScope};

    const ORIGIN: &str = "http://127.0.0.1:4173";

    async fn paired_app(runtime: Arc<FollowRuntime>, state: &Path) -> (Router, String) {
        let pairing_store = open_pairing_store(state).expect("pairing store");
        let (core, launcher) = CoreService::with_sqlite_pairing_following(
            pairing_store,
            PairingCapability::generate_os_random().expect("capability"),
            PairingOrigin::new(ORIGIN.to_owned()).expect("origin"),
            PairingConfig::default(),
            runtime,
            None,
        )
        .expect("paired follow service");
        let issued = launcher
            .issue_code(vec![
                PairingScope::CockpitRead,
                PairingScope::OperatorEvidenceWrite,
            ])
            .expect("one-time code");
        let app = core.router();
        let session = exchange(&app, ORIGIN, issued.code.as_str())
            .await
            .expect("pairing exchange");
        (app, session.capability)
    }

    async fn get_bytes(app: &Router, capability: &str, uri: &str) -> (StatusCode, Vec<u8>) {
        let response = send(
            app,
            authorized(ORIGIN, "GET", uri, capability, Body::empty()).expect("request"),
        )
        .await;
        let status = response.status();
        let bytes = response_bytes(response).await.expect("response bytes");
        (status, bytes)
    }

    async fn get_json(
        app: &Router,
        capability: &str,
        uri: &str,
    ) -> (StatusCode, serde_json::Value) {
        let (status, bytes) = get_bytes(app, capability, uri).await;
        (status, serde_json::from_slice(&bytes).expect("JSON body"))
    }

    fn scene_ids(feed: &serde_json::Value) -> Vec<String> {
        feed["scenes"]
            .as_array()
            .expect("feed scenes")
            .iter()
            .map(|scene| scene["sceneId"].as_str().unwrap_or_default().to_owned())
            .collect()
    }

    /// The whole living loop, headless: serve, the keeper commits, the feed grows a second
    /// immutable scene, the operator chooses to advance and holds a coin on it, and a restart
    /// still serves both scenes byte-for-byte with the act durable at its original commit.
    #[tokio::test]
    #[allow(clippy::too_many_lines)] // The ordered walk is clearer as one visible sequence.
    async fn the_feed_grows_a_scene_the_operator_advances_and_the_act_survives_restart() {
        let root = tempfile::tempdir().expect("temporary follow root");
        let catalog = root.path().join("catalog");
        let state = root.path().join("state");
        seed_catalog(&catalog).expect("seeded fixture catalog");

        let runtime = FollowRuntime::mount(
            &catalog,
            &state,
            FIXTURE_SOURCE,
            &LiveSurfaceOptions::default(),
        )
        .expect("fresh follow mount");
        let scene1 = runtime.newest_scene_id().expect("initial scene");
        let (app, capability) = paired_app(runtime.clone(), &state).await;

        let (status, feed) = get_json(&app, &capability, "/api/v1/glass/scenes").await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(feed["contract"], "joshi.core.scene_feed");
        assert_eq!(scene_ids(&feed), vec![scene1.clone()]);
        assert_eq!(
            feed["scenes"][0]["sceneRetention"],
            "served_not_yet_durable"
        );
        assert_eq!(feed["catalog"]["outcome"], "mounted");

        let snapshot_uri =
            |scene: &str| format!("/api/v1/glass/snapshot?mode=witnessed&basisSceneId={scene}");
        let (status, scene1_bytes) = get_bytes(&app, &capability, &snapshot_uri(&scene1)).await;
        assert_eq!(status, StatusCode::OK);

        // An unchanged source derives nothing.
        assert_eq!(runtime.tick().expect("idle tick"), TickOutcome::Unchanged);
        // Neither does a catalog advance carrying no observation for the followed source: a new
        // commit_seq alone is not new evidence, so no scene is minted over unchanged bytes.
        commit_bystander_frame(&catalog, 7).expect("bystander commit");
        assert_eq!(
            runtime.tick().expect("bystander tick"),
            TickOutcome::Unchanged
        );
        let (_, feed) = get_json(&app, &capability, "/api/v1/glass/scenes").await;
        assert_eq!(scene_ids(&feed).len(), 1);
        assert_eq!(feed["catalog"]["outcome"], "unchanged");

        // The keeper delivers a real observation: the feed grows a second scene, newest first,
        // and the first scene keeps serving the exact bytes it always served.
        extend_catalog(&catalog, 2..3, "batch-live-follow-extension").expect("keeper commit");
        let TickOutcome::Advanced { scene_id: scene2 } = runtime.tick().expect("advance tick")
        else {
            panic!("a new observation must derive a new scene");
        };
        assert_ne!(scene2, scene1);
        let (_, feed) = get_json(&app, &capability, "/api/v1/glass/scenes").await;
        assert_eq!(scene_ids(&feed), vec![scene2.clone(), scene1.clone()]);
        let newest_cutoff: u64 = feed["scenes"][0]["cutoffCommitSeq"]
            .as_str()
            .unwrap_or_default()
            .parse()
            .expect("cutoff");
        let older_cutoff: u64 = feed["scenes"][1]["cutoffCommitSeq"]
            .as_str()
            .unwrap_or_default()
            .parse()
            .expect("cutoff");
        assert!(newest_cutoff > older_cutoff, "advance means new evidence");
        let scene2_derived_at = feed["scenes"][0]["derivedAt"]
            .as_str()
            .expect("derivedAt")
            .to_owned();
        let (status, scene1_again) = get_bytes(&app, &capability, &snapshot_uri(&scene1)).await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(scene1_again, scene1_bytes, "an old scene never changes");
        let (status, scene2_bytes) = get_bytes(&app, &capability, &snapshot_uri(&scene2)).await;
        assert_eq!(status, StatusCode::OK);

        // The operator advances (a client act, not a server swap) and holds a coin on the new
        // scene through the ordinary operator route.
        let view_bytes = runtime
            .scene_bytes(&SceneId::new(scene2.clone()).expect("scene id"))
            .expect("lock")
            .expect("scene served")
            .0;
        let view_digest = qualified_digest(&view_bytes);
        let issued_at = crate::live_gesture::now().expect("clock");
        let command_bytes = mark_command_bytes(
            "command-follow-hold-1",
            &scene2,
            &view_digest,
            FIXTURE_MINT,
            issued_at,
        );
        let accepted = send(
            &app,
            authorized(
                ORIGIN,
                "POST",
                "/api/v1/operator/commands",
                &capability,
                Body::from(command_bytes.clone()),
            )
            .expect("request"),
        )
        .await;
        assert_eq!(accepted.status(), StatusCode::ACCEPTED);
        let receipt: serde_json::Value =
            serde_json::from_slice(&response_bytes(accepted).await.expect("receipt"))
                .expect("receipt JSON");
        let commit_seq = receipt["commitSeq"].as_str().expect("commitSeq").to_owned();

        // An exact retry returns the original durable closure, not a second commit.
        let retried = send(
            &app,
            authorized(
                ORIGIN,
                "POST",
                "/api/v1/operator/commands",
                &capability,
                Body::from(command_bytes.clone()),
            )
            .expect("request"),
        )
        .await;
        assert_eq!(retried.status(), StatusCode::OK);
        let retry: serde_json::Value =
            serde_json::from_slice(&response_bytes(retried).await.expect("retry"))
                .expect("retry JSON");
        assert_eq!(retry["commitSeq"].as_str(), Some(commit_seq.as_str()));

        let (status, readback) = get_json(
            &app,
            &capability,
            &format!("/api/v1/operator/commands?sceneId={scene2}"),
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(readback["sceneRetention"], "durable");
        assert_eq!(readback["commands"].as_array().map(Vec::len), Some(1));
        assert_eq!(
            readback["commands"][0]["commandId"],
            "command-follow-hold-1"
        );
        let (_, feed) = get_json(&app, &capability, "/api/v1/glass/scenes").await;
        assert_eq!(feed["scenes"][0]["sceneRetention"], "durable");

        // Restart: everything above dies; the retained state re-verifies and serves again.
        drop(app);
        drop(runtime);
        let runtime = FollowRuntime::mount(
            &catalog,
            &state,
            FIXTURE_SOURCE,
            &LiveSurfaceOptions::default(),
        )
        .expect("remount from retained state");
        let (app, capability) = paired_app(runtime.clone(), &state).await;
        let (_, feed) = get_json(&app, &capability, "/api/v1/glass/scenes").await;
        assert_eq!(scene_ids(&feed), vec![scene2.clone(), scene1.clone()]);
        assert_eq!(
            feed["scenes"][0]["derivedAt"].as_str(),
            Some(scene2_derived_at.as_str()),
            "a restart re-verifies a scene; it does not re-age it"
        );
        assert_eq!(feed["scenes"][0]["sceneRetention"], "durable");
        assert_eq!(
            feed["scenes"][1]["sceneRetention"],
            "served_not_yet_durable"
        );
        assert_eq!(feed["catalog"]["outcome"], "not_yet_polled_since_restart");
        let (status, scene1_after) = get_bytes(&app, &capability, &snapshot_uri(&scene1)).await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(scene1_after, scene1_bytes);
        let (status, scene2_after) = get_bytes(&app, &capability, &snapshot_uri(&scene2)).await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(scene2_after, scene2_bytes);
        let (status, readback) = get_json(
            &app,
            &capability,
            &format!("/api/v1/operator/commands?sceneId={scene2}"),
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(
            readback["commands"][0]["commitSeq"].as_str(),
            Some(commit_seq.as_str())
        );
        assert_eq!(
            runtime.tick().expect("post-restart tick"),
            TickOutcome::Unchanged
        );
    }

    /// An unreachable catalog is stated by the feed, never rendered as an empty list.
    #[tokio::test]
    async fn an_unreachable_catalog_is_stated_and_the_derived_scenes_keep_serving() {
        let root = tempfile::tempdir().expect("temporary follow root");
        let catalog = root.path().join("catalog");
        let state = root.path().join("state");
        seed_catalog(&catalog).expect("seeded fixture catalog");
        let runtime = FollowRuntime::mount(
            &catalog,
            &state,
            FIXTURE_SOURCE,
            &LiveSurfaceOptions::default(),
        )
        .expect("fresh follow mount");
        let scene1 = runtime.newest_scene_id().expect("initial scene");

        fs::rename(&catalog, root.path().join("catalog-gone")).expect("hide the catalog");
        let outcome = runtime.tick().expect("tick over a missing catalog");
        assert!(
            matches!(outcome, TickOutcome::Unreachable { .. }),
            "{outcome:?}"
        );

        let (app, capability) = paired_app(runtime.clone(), &state).await;
        let (status, feed) = get_json(&app, &capability, "/api/v1/glass/scenes").await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(feed["catalog"]["outcome"], "unreachable");
        assert!(
            feed["catalog"]["detail"]
                .as_str()
                .is_some_and(|detail| !detail.is_empty()),
            "the reason the catalog could not be read is stated"
        );
        assert_eq!(
            scene_ids(&feed),
            vec![scene1.clone()],
            "held facts stay stated"
        );
        let (status, _) = get_bytes(
            &app,
            &capability,
            &format!("/api/v1/glass/snapshot?mode=witnessed&basisSceneId={scene1}"),
        )
        .await;
        assert_eq!(status, StatusCode::OK);
    }

    /// A core without a follow mount states that no feed exists rather than serving “no scenes”.
    #[tokio::test]
    async fn a_single_scene_core_states_that_no_feed_is_mounted() {
        let root = tempfile::tempdir().expect("temporary root");
        let catalog = root.path().join("catalog");
        let state = root.path().join("state");
        seed_catalog(&catalog).expect("seeded fixture catalog");
        let mounted = crate::live_gesture::mount_live_surface(&catalog, &state, FIXTURE_SOURCE)
            .expect("single-scene mount");
        let (core, launcher) = CoreService::with_sqlite_pairing_mounting(
            mounted.store,
            None,
            PairingCapability::generate_os_random().expect("capability"),
            PairingOrigin::new(ORIGIN.to_owned()).expect("origin"),
            PairingConfig::default(),
            Some(mounted.view),
        )
        .expect("paired service");
        let issued = launcher
            .issue_code(vec![PairingScope::CockpitRead])
            .expect("one-time code");
        let app = core.router();
        let session = exchange(&app, ORIGIN, issued.code.as_str())
            .await
            .expect("pairing exchange");
        let (status, body) = get_json(&app, &session.capability, "/api/v1/glass/scenes").await;
        assert_eq!(status, StatusCode::NOT_FOUND);
        assert_eq!(body["code"], "scene_feed_not_mounted");
    }
}
