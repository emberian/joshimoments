//! Exact, evidence-only Glass scene and operator-command admission.
//!
//! Validation consumes canonical bytes, not a permissive in-memory approximation. Successful
//! values have private fields, so persistence can accept them as capabilities without exposing a
//! second unchecked scene or command path.

mod command;
mod error;
mod glass;

pub use command::{
    AssertedChoiceSetV1, AssertedChoiceSubjectV1, CommandReceiptV1, OperatorCommandKind,
    OperatorCommandStatus, OperatorSubject, ValidatedOperatorCommandV1,
};
pub use error::{OperatorAdmissionError, Result};
pub use glass::{
    GlassChoiceIndex, GlassEvidenceIndex, GlassMode, GlassProjectionIndex, GlassSourceIndex,
    ValidatedGlassViewV1,
};
