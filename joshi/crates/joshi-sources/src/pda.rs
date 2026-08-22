//! Program-derived address arithmetic, and exactly what binding it buys.
//!
//! An account address that arrives from a provider index, a frontend list, or an operator's
//! clipboard is a *candidate*. Owner and discriminator checks prove what an account **is**; they do
//! not prove **which mint it belongs to**. For a `PumpSwap` pool that gap closes itself, because the
//! pool account states its own base mint. For a Pump bonding curve it does not: the account carries
//! reserves, a completion flag, and a creator, and never names the mint whose curve it is.
//!
//! This module closes that gap with the derivation the deployed programs themselves use. A
//! bonding curve lives at `PDA(["bonding-curve", mint], pump_program)`, so recomputing the address
//! from a mint and comparing it to the account under inspection binds the two with bytes rather
//! than with a provider's say-so.
//!
//! **What this does not prove.** Solana's canonical derivation is `find_program_address`, which
//! walks the bump downward and takes the first result that is *not* a valid ed25519 point. Deciding
//! whether 32 bytes decompress to a curve point needs field arithmetic over `2^255 - 19` that this
//! crate does not carry, and would not carry lightly. So [`derivation_bump`] proves the weaker,
//! still useful statement: *this address is the program-derived address of these seeds under this
//! program at bump `b`*. It does not prove `b` is the canonical bump. Nothing downstream depends on
//! canonicity, because every account is additionally required to be owned by the program and to
//! carry the recomputed Anchor discriminator, and a deployed program only ever writes at the bump
//! its own `find_program_address` returned.
//!
//! Nothing here reads the network, and nothing here is an economic action.

use sha2::{Digest, Sha256};

/// The literal suffix Solana's `create_program_address` hashes after the program id.
pub const PROGRAM_DERIVED_ADDRESS_MARKER: &[u8] = b"ProgramDerivedAddress";
/// Longest single seed the runtime accepts.
pub const MAX_SEED_LEN: usize = 32;
/// Most seeds the runtime accepts, before the bump seed.
pub const MAX_SEEDS: usize = 16;

/// Decodes a base58 address into the exact 32 bytes it denotes.
///
/// Returns `None` for anything that is not 32 bytes, so a truncated or padded address can never be
/// silently zero-extended into a different key.
#[must_use]
pub fn decode_address(address: &str) -> Option<[u8; 32]> {
    let mut bytes = [0_u8; 32];
    let written = bs58::decode(address).onto(&mut bytes[..]).ok()?;
    (written == 32).then_some(bytes)
}

/// The address `seeds` derive to under `program_id` at one stated bump.
///
/// Returns `None` when the program id is not a 32-byte address, when a seed is longer than the
/// runtime allows, or when there are more seeds than the runtime allows — the same inputs the
/// runtime itself would reject, refused here rather than hashed anyway.
#[must_use]
pub fn derive_program_address(seeds: &[&[u8]], program_id: &str, bump: u8) -> Option<String> {
    if seeds.len() > MAX_SEEDS || seeds.iter().any(|seed| seed.len() > MAX_SEED_LEN) {
        return None;
    }
    let program = decode_address(program_id)?;
    let mut hasher = Sha256::new();
    for seed in seeds {
        hasher.update(seed);
    }
    hasher.update([bump]);
    hasher.update(program);
    hasher.update(PROGRAM_DERIVED_ADDRESS_MARKER);
    Some(bs58::encode(hasher.finalize()).into_string())
}

/// The bump at which `address` is the program-derived address of `seeds` under `program_id`.
///
/// At most one bump can match, because two bumps hash to two different digests. A `Some` is
/// therefore an exact statement about these bytes and not a probabilistic one. A `None` is the
/// honest answer that this address is not derived from these seeds at any bump — which is what
/// makes it usable as a refusal.
///
/// Read the module documentation for what a match does and does not establish.
#[must_use]
pub fn derivation_bump(address: &str, seeds: &[&[u8]], program_id: &str) -> Option<u8> {
    let target = decode_address(address)?;
    (0..=u8::MAX).rev().find(|bump| {
        derive_program_address(seeds, program_id, *bump)
            .and_then(|candidate| decode_address(&candidate))
            .is_some_and(|candidate| candidate == target)
    })
}

/// The highest `count` bumps' derived addresses, highest bump first.
///
/// This exists because the canonical bump cannot be identified offline without ed25519 curve
/// arithmetic. A caller that wants to *find* an account rather than verify one asks the provider
/// about several candidates in a single batched read and keeps whichever one exists, is owned by
/// the program, and carries the right discriminator. That is a strictly stronger test than
/// deriving one address and trusting it, and it costs slots in a request that was going to be made
/// anyway.
///
/// Returns an empty vector for the same inputs [`derive_program_address`] refuses.
#[must_use]
pub fn descending_bump_candidates(
    seeds: &[&[u8]],
    program_id: &str,
    count: u8,
) -> Vec<(u8, String)> {
    (0..count)
        .filter_map(|step| {
            let bump = u8::MAX.checked_sub(step)?;
            Some((bump, derive_program_address(seeds, program_id, bump)?))
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Mainnet addresses whose derivation was confirmed against the live accounts on 2026-08-22.
    const PUMP_PROGRAM: &str = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P";
    const CURVE_MINT: &str = "BKdJofyhtW3sBgC8PGuXaawKHmrPjTdzxqaJfSpupump";
    const CURVE: &str = "wrXaYnT8PBRSqigbLL3fTfHN2iYcGHCNfMwaGUKijeW";
    const GLOBAL: &str = "4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4Jjaxnjf";

    #[test]
    fn a_live_bonding_curve_is_the_derived_address_of_its_own_mint() {
        let mint = decode_address(CURVE_MINT).expect("mint is 32 bytes");
        let bump = derivation_bump(CURVE, &[b"bonding-curve", &mint], PUMP_PROGRAM)
            .expect("the live curve derives from its mint");
        assert_eq!(bump, 255);
        assert_eq!(
            derive_program_address(&[b"bonding-curve", &mint], PUMP_PROGRAM, bump).as_deref(),
            Some(CURVE)
        );
    }

    #[test]
    fn a_curve_does_not_derive_from_a_mint_that_is_not_its_own() {
        let other = decode_address("gV5pNNAfxLfJ1fX4kKzJGhENMgE9o12H5aUHUgipump").expect("32");
        assert_eq!(
            derivation_bump(CURVE, &[b"bonding-curve", &other], PUMP_PROGRAM),
            None
        );
    }

    #[test]
    fn the_global_account_derives_from_its_own_single_seed() {
        assert_eq!(
            derivation_bump(GLOBAL, &[b"global"], PUMP_PROGRAM),
            Some(255)
        );
    }

    #[test]
    fn descending_candidates_start_at_the_highest_bump_and_are_all_distinct() {
        let mint = decode_address(CURVE_MINT).expect("32");
        let candidates = descending_bump_candidates(&[b"bonding-curve", &mint], PUMP_PROGRAM, 4);
        assert_eq!(candidates.len(), 4);
        assert_eq!(candidates[0], (255, CURVE.to_owned()));
        assert_eq!(candidates[3].0, 252);
        let mut addresses: Vec<&str> = candidates.iter().map(|(_, a)| a.as_str()).collect();
        addresses.sort_unstable();
        addresses.dedup();
        assert_eq!(addresses.len(), 4);
    }

    #[test]
    fn an_address_that_is_not_thirty_two_bytes_is_refused_rather_than_extended() {
        assert_eq!(decode_address(""), None);
        assert_eq!(decode_address("1111"), None);
        assert_eq!(decode_address("not base58 at all !!"), None);
        assert_eq!(derivation_bump("1111", &[b"global"], PUMP_PROGRAM), None);
    }

    #[test]
    fn seeds_the_runtime_would_reject_are_refused_rather_than_hashed() {
        let long = [0_u8; MAX_SEED_LEN + 1];
        assert_eq!(derive_program_address(&[&long], PUMP_PROGRAM, 255), None);
        let many: Vec<&[u8]> = vec![b"x"; MAX_SEEDS + 1];
        assert_eq!(derive_program_address(&many, PUMP_PROGRAM, 255), None);
        assert!(descending_bump_candidates(&[&long], PUMP_PROGRAM, 4).is_empty());
    }
}
