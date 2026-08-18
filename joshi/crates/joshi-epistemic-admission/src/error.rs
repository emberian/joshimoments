use joshi_epistemic_book::BookError;
use thiserror::Error;

/// Fail-closed error from the epistemic admission boundary.
#[derive(Debug, Error)]
pub enum EpistemicAdmissionError {
    /// The book's strict semantic contract rejected caller-owned data.
    #[error(transparent)]
    Book(#[from] BookError),
    /// A public operation attempted to claim durability unavailable at this boundary.
    #[error("durable epistemic admission requires private store-resolved receipts")]
    MissingPrivateReceipt,
    /// First-round data exposed a peer forecast or ensemble before its own sealed commit.
    #[error("first-round submission is not mutually blind")]
    FirstRoundNotBlind,
    /// A private adapter attempted to bind distinct exact objects.
    #[error("store-resolved receipt does not bind the exact epistemic artifact")]
    ReceiptBinding,
    /// A private adapter attempted to use a later clock or an invalid B0 relation.
    #[error("store-resolved receipt violates the exact B0 clock")]
    Clock,
    /// A reveal occurred before all eligible first-round components were sealed.
    #[error("reveal precedes the sealed eligible first-round set")]
    RevealBeforeSeal,
    /// A score/ensemble attempted to consume support that is current or future at the occurrence.
    #[error("support lineage is not strictly earlier than the consuming occurrence cutoff")]
    FutureSupport,
}

/// Result specialized to the receipt-gated epistemic-admission boundary.
pub type Result<T> = std::result::Result<T, EpistemicAdmissionError>;
