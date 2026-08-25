//! Sign-In-With-Solana session for Ember's own pump.fun account, obtained under one hard rule.
//!
//! # HARD BOUNDARY — read this before touching anything here
//!
//! The wallet key this module loads SIGNS EXACTLY ONE THING, EVER: the login timestamp of a
//! pump.fun Sign-In-With-Solana challenge. The signed bytes are the constant-shaped string
//! `Sign in to pump.fun: {millis}` and nothing else is ever handed to the signer. This is
//! AUTHENTICATION — proving the account is Ember's — and it is NOT AUTHORIZATION TO SPEND. The
//! resulting session reads READ-ONLY routes only. This module, and any caller of it, must never
//! construct, sign, or submit a Solana transaction, and must never reach a create/trade/send
//! route even to measure it. If a gated route worth reading has a mutating sibling, the sibling
//! is off-limits; there is no code path here that could reach it.
//!
//! # Credential discipline
//!
//! Two secrets pass through this module: the wallet secret key and the `auth_token` the login
//! returns. Both are wrapped so their `Debug` is redacted, are never serialized into an
//! acquisition, a fixture, a receipt, a request fingerprint, or a log line, and are read from
//! files that must be mode 0600. A retained acquisition through an authenticated route stores the
//! provider's RESPONSE bytes; it never stores the token or the key. The login exchange itself is
//! the only place the token is in memory in the clear, and it is moved straight into a
//! [`secrecy::SecretString`].

use std::fmt;
use std::fs;
use std::path::{Path, PathBuf};

use ed25519_dalek::{Signer, SigningKey};
use secrecy::{ExposeSecret, SecretString};

use crate::auth::{SessionError, SessionMaterial, SessionProvider};
use crate::catalog::RouteSpec;

/// The exact challenge pump.fun's SIWS login verifies. The colon-space is load-bearing: the bare
/// timestamp is rejected `401 Invalid signature`, measured 2026-08-23.
const LOGIN_PREFIX: &str = "Sign in to pump.fun: ";
/// The Origin the login endpoint expects. The gated GETs do not require it; the login POST does.
const PUMP_ORIGIN: &str = "https://pump.fun";
const LOGIN_URL: &str = "https://frontend-api-v3.pump.fun/auth/login";

/// Errors from loading a wallet, signing the login challenge, or exchanging it for a session.
#[derive(Debug)]
pub enum SiwsError {
    /// The wallet file was missing, unreadable, or not a regular file.
    WalletRead(PathBuf),
    /// The wallet file's permissions allow group or other access.
    WalletPermissions,
    /// The wallet file did not decode to a 64-byte base58 Solana secret key.
    WalletShape,
    /// The login request could not be sent.
    Transport(String),
    /// The provider answered the login with a non-success status. The body is deliberately not
    /// captured here, because a failed auth body can echo the submitted material.
    LoginRejected(u16),
    /// The login succeeded but returned no `auth_token`.
    NoToken,
}

impl fmt::Display for SiwsError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::WalletRead(path) => {
                write!(formatter, "unable to read wallet at {}", path.display())
            }
            Self::WalletPermissions => formatter
                .write_str("wallet file permissions must exclude group/other access (0600)"),
            Self::WalletShape => {
                formatter.write_str("wallet file is not a 64-byte base58 Solana secret key")
            }
            Self::Transport(detail) => write!(formatter, "login transport failed: {detail}"),
            Self::LoginRejected(status) => write!(formatter, "login rejected with status {status}"),
            Self::NoToken => formatter.write_str("login succeeded but carried no auth_token"),
        }
    }
}

impl std::error::Error for SiwsError {}

/// A loaded wallet that can sign the login challenge and nothing else.
///
/// The signing key is private and never leaves this type. The only method that touches it,
/// [`WalletSigner::sign_login_challenge`], accepts a timestamp and produces a signature over the
/// fixed challenge string; there is no method that signs caller-supplied bytes.
pub struct WalletSigner {
    signing_key: SigningKey,
    address: String,
}

impl fmt::Debug for WalletSigner {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("WalletSigner")
            .field("signing_key", &"[REDACTED]")
            .field("address", &self.address)
            .finish()
    }
}

impl WalletSigner {
    /// Load a base58 64-byte Solana secret key (32-byte seed followed by its 32-byte public key)
    /// from a mode-0600 file.
    ///
    /// # Errors
    ///
    /// Returns [`SiwsError`] when the file is missing, world/group-readable, or does not decode to
    /// a 64-byte key whose trailing 32 bytes are the seed's public key.
    pub fn from_file(path: impl AsRef<Path>) -> Result<Self, SiwsError> {
        let (signing_key, address) = load_solana_signing_key(path.as_ref())?;
        Ok(Self {
            signing_key,
            address,
        })
    }

    /// The base58 public address this wallet authenticates as. Not a secret.
    #[must_use]
    pub fn address(&self) -> &str {
        &self.address
    }

    /// Sign the SIWS login challenge for a millisecond timestamp. This is the ONLY signing this
    /// type performs; it composes the challenge internally so no caller can substitute the bytes.
    fn sign_login_challenge(&self, timestamp_millis: i64) -> String {
        let message = format!("{LOGIN_PREFIX}{timestamp_millis}");
        let signature = self.signing_key.sign(message.as_bytes());
        bs58::encode(signature.to_bytes()).into_string()
    }
}

/// A wallet-file load failure, mapped by each session module into its own error type.
///
/// The 0600/base58/64-byte/trailing-pubkey checks are identical for the pump SIWS wallet and the
/// coin-communities wallet — the same key file, in fact — so they live in one place
/// ([`load_solana_signing_key`]) and this small enum carries the outcome back to whichever module
/// asked, which restates it in its own vocabulary.
#[derive(Debug)]
pub(crate) enum WalletKeyError {
    /// The wallet file was missing, unreadable, or not a regular file.
    Read(PathBuf),
    /// The wallet file's permissions allow group or other access.
    Permissions,
    /// The wallet file did not decode to a 64-byte base58 Solana secret key.
    Shape,
}

impl From<WalletKeyError> for SiwsError {
    fn from(error: WalletKeyError) -> Self {
        match error {
            WalletKeyError::Read(path) => Self::WalletRead(path),
            WalletKeyError::Permissions => Self::WalletPermissions,
            WalletKeyError::Shape => Self::WalletShape,
        }
    }
}

/// Load a base58 64-byte Solana secret key (32-byte seed followed by its 32-byte public key) from a
/// mode-0600 file, returning the ed25519 signing key and its base58 address.
///
/// This is the single loader behind both [`WalletSigner`] and the coin-communities signer, so the
/// permission and shape checks — the guarantees that a group-readable or truncated key is refused
/// rather than signing under a surprise identity — exist in exactly one auditable place. The
/// signing key it returns is handed straight into the caller's private field and never rendered.
///
/// # Errors
///
/// Returns [`WalletKeyError`] when the file is missing, world/group-readable, or does not decode to
/// a 64-byte key whose trailing 32 bytes are the seed's public key.
pub(crate) fn load_solana_signing_key(path: &Path) -> Result<(SigningKey, String), WalletKeyError> {
    let metadata = fs::metadata(path).map_err(|_| WalletKeyError::Read(path.to_path_buf()))?;
    if !metadata.is_file() {
        return Err(WalletKeyError::Read(path.to_path_buf()));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt as _;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err(WalletKeyError::Permissions);
        }
    }
    let text = fs::read_to_string(path).map_err(|_| WalletKeyError::Read(path.to_path_buf()))?;
    let decoded = bs58::decode(text.trim())
        .into_vec()
        .map_err(|_| WalletKeyError::Shape)?;
    if decoded.len() != 64 {
        return Err(WalletKeyError::Shape);
    }
    let seed: [u8; 32] = decoded[..32]
        .try_into()
        .map_err(|_| WalletKeyError::Shape)?;
    let signing_key = SigningKey::from_bytes(&seed);
    // The trailing 32 bytes of a Solana secret key are the public key; require they match the seed
    // so a malformed or truncated file is rejected rather than signing under a surprise identity.
    if signing_key.verifying_key().to_bytes() != decoded[32..] {
        return Err(WalletKeyError::Shape);
    }
    let address = bs58::encode(signing_key.verifying_key().to_bytes()).into_string();
    Ok((signing_key, address))
}

/// A live pump.fun session token with the instant it expires.
pub struct SiwsSession {
    cookie: SecretString,
    expires_at: time::OffsetDateTime,
    label: String,
}

impl fmt::Debug for SiwsSession {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("SiwsSession")
            .field("cookie", &"[REDACTED]")
            .field("expires_at", &self.expires_at)
            .field("label", &self.label)
            .finish()
    }
}

impl SiwsSession {
    /// Sign the current wall-clock timestamp and exchange it for an `auth_token` session.
    ///
    /// The wallet signs only the login challenge here. On success the token is moved directly into
    /// a secret and the plaintext is not returned to the caller.
    ///
    /// # Errors
    ///
    /// Returns [`SiwsError`] on a transport failure, a non-success login status, or a success that
    /// carried no token.
    pub async fn login(signer: &WalletSigner) -> Result<Self, SiwsError> {
        let timestamp_millis =
            i64::try_from(time::OffsetDateTime::now_utc().unix_timestamp_nanos() / 1_000_000)
                .map_err(|_| {
                    SiwsError::Transport("clock is implausibly far from the epoch".to_owned())
                })?;
        let signature = signer.sign_login_challenge(timestamp_millis);
        let http = reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|error| SiwsError::Transport(error.to_string()))?;
        let body = serde_json::to_vec(&serde_json::json!({
            "address": signer.address(),
            "signature": signature,
            "timestamp": timestamp_millis,
        }))
        .map_err(|error| SiwsError::Transport(error.to_string()))?;
        let response = http
            .post(LOGIN_URL)
            .header(reqwest::header::ORIGIN, PUMP_ORIGIN)
            .header(reqwest::header::CONTENT_TYPE, "application/json")
            .body(body)
            .send()
            .await
            .map_err(|error| SiwsError::Transport(error.to_string()))?;
        let status = response.status();
        let set_cookies: Vec<String> = response
            .headers()
            .get_all(reqwest::header::SET_COOKIE)
            .iter()
            .filter_map(|value| value.to_str().ok().map(str::to_owned))
            .collect();
        let text = response
            .text()
            .await
            .map_err(|error| SiwsError::Transport(error.to_string()))?;
        if !status.is_success() {
            return Err(SiwsError::LoginRejected(status.as_u16()));
        }
        let token = token_from_cookies(&set_cookies)
            .or_else(|| token_from_body(&text))
            .ok_or(SiwsError::NoToken)?;
        let expires_at = jwt_expiry(&token)
            .unwrap_or_else(|| time::OffsetDateTime::now_utc() + time::Duration::days(1));
        Ok(Self {
            cookie: SecretString::from(format!("auth_token={token}")),
            expires_at,
            label: format!("siws:pump-callout:{}", &signer.address()[..8]),
        })
    }

    /// Whether the session is still valid at the current instant.
    #[must_use]
    pub fn is_live(&self) -> bool {
        self.expires_at > time::OffsetDateTime::now_utc()
    }

    /// The instant this session expires. Not a secret.
    #[must_use]
    pub fn expires_at(&self) -> time::OffsetDateTime {
        self.expires_at
    }
}

/// A [`SessionProvider`] backed by one already-obtained SIWS session.
///
/// The login network exchange happens once, in [`SiwsSession::login`], before this provider is
/// built. `session_for` is the synchronous trait method the client calls immediately before an
/// authenticated GET, so it only clones the cached cookie into fresh [`SessionMaterial`]; it
/// performs no I/O and holds the wallet key nowhere.
#[derive(Debug)]
pub struct SiwsSessionProvider {
    session: SiwsSession,
}

impl SiwsSessionProvider {
    #[must_use]
    pub fn new(session: SiwsSession) -> Self {
        Self { session }
    }
}

impl SessionProvider for SiwsSessionProvider {
    fn session_for(&self, _route: RouteSpec) -> Result<SessionMaterial, SessionError> {
        if !self.session.is_live() {
            return Err(SessionError::Expired);
        }
        Ok(SessionMaterial::cookie_only(
            self.session.cookie.expose_secret(),
            &self.session.label,
        ))
    }
}

/// Pull the `auth_token` value out of any `Set-Cookie` header line.
fn token_from_cookies(set_cookies: &[String]) -> Option<String> {
    for line in set_cookies {
        for part in line.split(';') {
            if let Some(value) = part.trim().strip_prefix("auth_token=")
                && !value.is_empty()
            {
                return Some(value.to_owned());
            }
        }
    }
    None
}

/// Fall back to an `auth_token` / `token` field in a JSON login body.
fn token_from_body(text: &str) -> Option<String> {
    let value: serde_json::Value = serde_json::from_str(text).ok()?;
    for key in ["auth_token", "authToken", "token", "access_token"] {
        if let Some(token) = value.get(key).and_then(serde_json::Value::as_str)
            && !token.is_empty()
        {
            return Some(token.to_owned());
        }
    }
    None
}

/// Read the `exp` claim from a JWT without verifying it. Used only to set a local expiry so a dead
/// token is refused before it is sent, never as a trust decision.
///
/// Shared with [`crate::community_session`] so both wallet-auth sessions parse token expiry through
/// one implementation rather than each hand-rolling a second, subtly different one.
pub(crate) fn jwt_expiry(token: &str) -> Option<time::OffsetDateTime> {
    use base64::Engine as _;
    let payload = token.split('.').nth(1)?;
    let decoded = base64::engine::general_purpose::URL_SAFE_NO_PAD
        .decode(payload)
        .ok()?;
    let value: serde_json::Value = serde_json::from_slice(&decoded).ok()?;
    let exp = value.get("exp")?.as_i64()?;
    time::OffsetDateTime::from_unix_timestamp(exp).ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn challenge_is_prefix_plus_timestamp() {
        use ed25519_dalek::{Signature, Verifier};
        // A fixed 32-byte seed so the signature is deterministic and never a real key.
        let signer = WalletSigner {
            signing_key: SigningKey::from_bytes(&[7u8; 32]),
            address: "test".to_owned(),
        };
        let signature = signer.sign_login_challenge(1_700_000_000_000);
        let bytes = bs58::decode(&signature).into_vec().expect("valid base58");
        assert_eq!(bytes.len(), 64, "an ed25519 signature is 64 bytes");
        // The signer verifies against the exact challenge string, and against nothing else.
        let parsed = Signature::from_slice(&bytes).expect("signature parses");
        let message = format!("{LOGIN_PREFIX}{}", 1_700_000_000_000i64);
        signer
            .signing_key
            .verifying_key()
            .verify(message.as_bytes(), &parsed)
            .expect("challenge verifies");
        assert!(
            signer
                .signing_key
                .verifying_key()
                .verify(b"1700000000000", &parsed)
                .is_err(),
            "the bare timestamp must NOT verify — the colon-space prefix is load-bearing",
        );
    }

    #[test]
    fn token_parsed_from_set_cookie() {
        let cookies = vec![
            "other=1; Path=/".to_owned(),
            "auth_token=abc.def.ghi; HttpOnly; Path=/; Max-Age=2592000".to_owned(),
        ];
        assert_eq!(token_from_cookies(&cookies), Some("abc.def.ghi".to_owned()));
    }

    #[test]
    fn token_parsed_from_body_fallback() {
        assert_eq!(
            token_from_body(r#"{"authToken":"xyz"}"#),
            Some("xyz".to_owned())
        );
        assert_eq!(token_from_body(r#"{"nope":1}"#), None);
    }

    #[test]
    fn jwt_expiry_reads_exp() {
        // header.payload.signature with payload {"exp":1700000000}
        use base64::Engine as _;
        let payload =
            base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(br#"{"exp":1700000000}"#);
        let token = format!("h.{payload}.s");
        let expiry = jwt_expiry(&token).expect("exp present");
        assert_eq!(expiry.unix_timestamp(), 1_700_000_000);
    }
}
