//! Shared ingest bounds for every path that turns a source response into durable local bytes.
//!
//! Nothing here performs I/O, admits a request, or grants authority. [`physical_size`] derives the
//! worst-case physical byte cost of carrying one HTTP response entity body all the way to a local
//! spool segment, so a caller can refuse a read it could not durably retain *before* opening a
//! socket. The derivation is a property of the encoders in the chain, not of any one source.
//!
//! The ceiling for every artifact produced here is [`crate::AUTHORITY_CEILING`].

pub mod physical_size;
