use crate::{CatalogError, CatalogSnapshot, CommitReceipt, EvidenceDraft, InMemoryCatalog};
use thiserror::Error;
use tokio::sync::{mpsc, oneshot};

/// Explicit bounds for the in-process evidence ingress.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct IngestLimits {
    /// Maximum queued commands awaiting the one writer.
    pub queue_capacity: usize,
    /// Maximum exact payload bytes in one observation.
    pub max_payload_bytes: u64,
}

impl IngestLimits {
    /// Creates non-zero ingress limits.
    ///
    /// # Errors
    ///
    /// Returns an error when either limit is zero.
    pub fn new(queue_capacity: usize, max_payload_bytes: u64) -> Result<Self, IngestError> {
        if queue_capacity == 0 {
            return Err(IngestError::ZeroQueueCapacity);
        }
        if max_payload_bytes == 0 {
            return Err(IngestError::ZeroPayloadLimit);
        }
        Ok(Self {
            queue_capacity,
            max_payload_bytes,
        })
    }
}

/// Creates a bounded command handle and its single-writer worker.
#[must_use = "the worker must be run for append acknowledgements to make progress"]
pub fn bounded_ingest(limits: IngestLimits) -> (BoundedIngestHandle, BoundedIngestWorker) {
    let (sender, receiver) = mpsc::channel(limits.queue_capacity);
    (
        BoundedIngestHandle { sender },
        BoundedIngestWorker {
            receiver,
            catalog: InMemoryCatalog::new(limits.max_payload_bytes),
        },
    )
}

/// Cloneable ingress/control handle. It has no direct access to writer state.
#[derive(Clone, Debug)]
pub struct BoundedIngestHandle {
    sender: mpsc::Sender<Command>,
}

impl BoundedIngestHandle {
    /// Waits for queue capacity, then waits for the one writer's commit result.
    ///
    /// # Errors
    ///
    /// Returns an explicit queue, writer, or catalog error.
    pub async fn append(&self, draft: EvidenceDraft) -> Result<CommitReceipt, IngestError> {
        let pending = self.enqueue(draft).await?;
        pending.wait().await
    }

    /// Waits only for queue capacity and returns a separate commit acknowledgement.
    ///
    /// # Errors
    ///
    /// Returns an error if the writer queue is closed.
    pub async fn enqueue(&self, draft: EvidenceDraft) -> Result<PendingAppend, IngestError> {
        let (reply, receiver) = oneshot::channel();
        self.sender
            .send(Command::Append {
                draft: Box::new(draft),
                reply,
            })
            .await
            .map_err(|_| IngestError::QueueClosed)?;
        Ok(PendingAppend { receiver })
    }

    /// Does not wait for capacity. A full queue is explicit rather than silently lossy.
    ///
    /// # Errors
    ///
    /// Returns [`IngestError::QueueFull`] or [`IngestError::QueueClosed`] without silently
    /// dropping a record.
    pub fn try_enqueue(&self, draft: EvidenceDraft) -> Result<PendingAppend, IngestError> {
        let (reply, receiver) = oneshot::channel();
        self.sender
            .try_send(Command::Append {
                draft: Box::new(draft),
                reply,
            })
            .map_err(|error| match error {
                mpsc::error::TrySendError::Full(_) => IngestError::QueueFull,
                mpsc::error::TrySendError::Closed(_) => IngestError::QueueClosed,
            })?;
        Ok(PendingAppend { receiver })
    }

    /// Obtains a stable commit-ordered catalog snapshot from the writer.
    ///
    /// # Errors
    ///
    /// Returns an error when the writer is closed or stops before replying.
    pub async fn snapshot(&self) -> Result<CatalogSnapshot, IngestError> {
        let (reply, receiver) = oneshot::channel();
        self.sender
            .send(Command::Snapshot { reply })
            .await
            .map_err(|_| IngestError::QueueClosed)?;
        receiver.await.map_err(|_| IngestError::WriterStopped)
    }

    /// Requests an orderly writer stop and returns its final snapshot.
    ///
    /// # Errors
    ///
    /// Returns an error when the writer is closed or stops before replying.
    pub async fn shutdown(&self) -> Result<CatalogSnapshot, IngestError> {
        let (reply, receiver) = oneshot::channel();
        self.sender
            .send(Command::Shutdown { reply })
            .await
            .map_err(|_| IngestError::QueueClosed)?;
        receiver.await.map_err(|_| IngestError::WriterStopped)
    }
}

/// Commit acknowledgement for a command already admitted to the bounded queue.
#[derive(Debug)]
pub struct PendingAppend {
    receiver: oneshot::Receiver<Result<CommitReceipt, CatalogError>>,
}

impl PendingAppend {
    /// Waits for commit or explicit rejection by the one writer.
    ///
    /// # Errors
    ///
    /// Returns an explicit writer or catalog error.
    pub async fn wait(self) -> Result<CommitReceipt, IngestError> {
        self.receiver
            .await
            .map_err(|_| IngestError::WriterStopped)?
            .map_err(IngestError::Catalog)
    }
}

/// Owns the mutable catalog and serializes all append commands.
#[derive(Debug)]
pub struct BoundedIngestWorker {
    receiver: mpsc::Receiver<Command>,
    catalog: InMemoryCatalog,
}

impl BoundedIngestWorker {
    /// Runs until shutdown is requested or every sender is dropped.
    pub async fn run(mut self) -> CatalogSnapshot {
        while let Some(command) = self.receiver.recv().await {
            match command {
                Command::Append { draft, reply } => {
                    let _result_ignored_if_caller_cancelled =
                        reply.send(self.catalog.append(*draft));
                }
                Command::Snapshot { reply } => {
                    let _result_ignored_if_caller_cancelled = reply.send(self.catalog.snapshot());
                }
                Command::Shutdown { reply } => {
                    let snapshot = self.catalog.snapshot();
                    let _result_ignored_if_caller_cancelled = reply.send(snapshot.clone());
                    return snapshot;
                }
            }
        }
        self.catalog.snapshot()
    }
}

#[derive(Debug)]
enum Command {
    Append {
        draft: Box<EvidenceDraft>,
        reply: oneshot::Sender<Result<CommitReceipt, CatalogError>>,
    },
    Snapshot {
        reply: oneshot::Sender<CatalogSnapshot>,
    },
    Shutdown {
        reply: oneshot::Sender<CatalogSnapshot>,
    },
}

/// Explicit queue/control failure from bounded ingress.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum IngestError {
    /// A non-blocking producer reached the configured bound.
    #[error("evidence ingress queue is full")]
    QueueFull,
    /// The writer is no longer accepting commands.
    #[error("evidence ingress queue is closed")]
    QueueClosed,
    /// The writer ended before acknowledging a command.
    #[error("evidence writer stopped before replying")]
    WriterStopped,
    /// The immutable catalog rejected the record.
    #[error(transparent)]
    Catalog(#[from] CatalogError),
    /// A zero-capacity queue would panic rather than provide backpressure.
    #[error("queue capacity must be greater than zero")]
    ZeroQueueCapacity,
    /// A zero payload bound cannot retain any observation.
    #[error("maximum payload bytes must be greater than zero")]
    ZeroPayloadLimit,
}

#[cfg(test)]
mod tests {
    use super::{IngestError, IngestLimits, bounded_ingest};
    use crate::{
        AcquisitionRecord, EvidenceDraft, MonotonicReading, ObservationDraft, ObservationEventTime,
        ObservationMetadata, ObservationTiming,
    };
    use joshi_domain::{
        AcquisitionClocks, AcquisitionId, ObservationId, OpenVariant, RequestFingerprint, SourceId,
        StableString, UtcTimestamp, WireU64,
    };

    fn draft(observation_id: &str) -> EvidenceDraft {
        let timestamp = "2026-08-16T12:00:00.000000Z"
            .parse::<UtcTimestamp>()
            .unwrap_or_else(|_| unreachable!());
        EvidenceDraft::Observation(ObservationDraft {
            acquisition: AcquisitionRecord {
                acquisition_id: AcquisitionId::new(format!("acq-{observation_id}"))
                    .unwrap_or_else(|_| unreachable!()),
                source_id: SourceId::new("fixture").unwrap_or_else(|_| unreachable!()),
                acquisition_kind: OpenVariant::known("fixture").unwrap_or_else(|_| unreachable!()),
                transport_kind: OpenVariant::known("fixture").unwrap_or_else(|_| unreachable!()),
                parent_acquisition_id: None,
                request_fingerprint: RequestFingerprint::new(format!("sha256:{}", "0".repeat(64)))
                    .unwrap_or_else(|_| unreachable!()),
                contract_version: StableString::new("v1").unwrap_or_else(|_| unreachable!()),
                started_at: timestamp,
                started_monotonic: Some(MonotonicReading {
                    clock_id: StableString::new("fixture-clock").unwrap_or_else(|_| unreachable!()),
                    nanoseconds: WireU64::new(0),
                }),
                source_locator: None,
                source_cursor: None,
                clocks: AcquisitionClocks {
                    requested_at: None,
                    received_at: timestamp,
                    persisted_at: timestamp,
                    monotonic_elapsed_ns: None,
                    monotonic_domain: None,
                },
            },
            observation: ObservationMetadata {
                observation_id: ObservationId::new(observation_id)
                    .unwrap_or_else(|_| unreachable!()),
                acquisition_ordinal: WireU64::new(0),
                observation_kind: OpenVariant::known("fixture").unwrap_or_else(|_| unreachable!()),
                source_events: Vec::new(),
                source_variant: OpenVariant::known("fixture").unwrap_or_else(|_| unreachable!()),
                event_time: ObservationEventTime {
                    status: OpenVariant::known("not_applicable").unwrap_or_else(|_| unreachable!()),
                    lower: None,
                    upper: None,
                    precision_us: None,
                },
                chain: None,
                source_cursor: None,
                timing: ObservationTiming {
                    received_at: timestamp,
                    received_monotonic: MonotonicReading {
                        clock_id: StableString::new("fixture-clock")
                            .unwrap_or_else(|_| unreachable!()),
                        nanoseconds: WireU64::new(1),
                    },
                    persisted_at: timestamp,
                    available_at: timestamp,
                },
                parse_disposition: OpenVariant::known("opaque").unwrap_or_else(|_| unreachable!()),
                quality_code: None,
                media_type: StableString::new("application/json")
                    .unwrap_or_else(|_| unreachable!()),
            },
            payload: b"{}".to_vec(),
        })
    }

    #[test]
    fn limits_reject_zeroes() {
        assert_eq!(IngestLimits::new(0, 1), Err(IngestError::ZeroQueueCapacity));
        assert_eq!(IngestLimits::new(1, 0), Err(IngestError::ZeroPayloadLimit));
    }

    #[tokio::test]
    async fn a_full_queue_is_visible_to_nonblocking_producers() {
        let limits = IngestLimits::new(1, 1024).unwrap_or_else(|_| unreachable!());
        let (handle, _worker) = bounded_ingest(limits);
        let first = handle.try_enqueue(draft("obs-1"));
        let second = handle.try_enqueue(draft("obs-2"));
        assert!(first.is_ok());
        assert!(matches!(second, Err(IngestError::QueueFull)));
    }

    #[tokio::test]
    async fn worker_serializes_append_and_snapshot() {
        let limits = IngestLimits::new(2, 1024).unwrap_or_else(|_| unreachable!());
        let (handle, worker) = bounded_ingest(limits);
        let task = tokio::spawn(worker.run());
        assert!(handle.append(draft("obs-1")).await.is_ok());
        let snapshot = handle.snapshot().await;
        assert!(snapshot.is_ok());
        if let Ok(snapshot) = snapshot {
            assert_eq!(snapshot.observations.len(), 1);
        }
        assert!(handle.shutdown().await.is_ok());
        assert!(task.await.is_ok());
    }
}
