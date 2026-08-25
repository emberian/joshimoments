//! Wallet-auth session for Ember's own coin-communities (`api.coin-communities.xyz`) account, the
//! second authentication surface, obtained under the SAME hard rule as the pump SIWS session next
//! door in [`crate::auth_session`].
//!
//! # HARD BOUNDARY — read this before touching anything here
//!
//! The wallet key this module loads signs EXACTLY ONE CLASS OF THING: a SERVER-ISSUED
//! AUTHENTICATION CHALLENGE — the plain text string the service returns from its `wallet/challenge`
//! endpoint — handed to the wallet's message-signing primitive and nothing else. This mirrors what
//! the pump.fun app itself does: it takes the challenge `message`, `TextEncoder().encode`s it, and
//! calls `signSolanaMessage` (categorically distinct from `sendSolanaTransaction`). This is
//! AUTHENTICATION — proving the account is Ember's — and it is NOT AUTHORIZATION TO SPEND. This
//! module, and any caller of it, must never construct, serialize, sign, or submit a Solana
//! transaction. The one place the wallet signs, [`CommunityWalletSigner::sign_authentication_challenge`],
//! GUARDS the challenge to printable authentication text before a single byte reaches the signer,
//! so a hostile or buggy server cannot smuggle transaction-shaped bytes through the message signer
//! the way a raw `signMessage` over attacker-chosen bytes otherwise could. If a challenge is not
//! authentication-shaped text, it is refused, not signed.
//!
//! Standing authorization (recorded in the session goal): signing a server-issued authentication
//! challenge through the message-sign primitive is pre-approved for this handshake and the pump
//! SIWS one alike. The line that does not move: nothing transaction-shaped is ever built here.
//!
//! # Credential discipline
//!
//! Three secrets pass through this module: the wallet secret key, the `accessToken` (bearer) and
//! the `refreshToken`. A fourth value, the shared `x-api-key` product key, is not a secret of
//! Ember's — the app ships the same one to every visitor — but it is still wrapped and never
//! rendered. All are held in [`secrecy::SecretString`] with redacted `Debug`, are never serialized
//! into an acquisition, a fixture, a receipt, a request fingerprint, or a log line, and the wallet
//! is read from a file that must be mode 0600 (enforced by the shared loader in
//! [`crate::auth_session`]). The token exchange is the only place a token is in memory in the
//! clear, and it is moved straight into a secret. Refresh rotates BOTH tokens atomically — the old
//! pair survives a failed refresh, and a `4xx` clears the session so a full handshake is required,
//! exactly as the app behaves.

use std::fmt;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use ed25519_dalek::{Signer, SigningKey};
use secrecy::{ExposeSecret, SecretString};

use crate::auth::{SessionError, SessionMaterial, SessionProvider};
use crate::auth_session::{WalletKeyError, jwt_expiry, load_solana_signing_key};
use crate::catalog::RouteSpec;

/// The coin-communities origin. The wallet-auth POSTs below and every gated GET are on this host.
const ORIGIN: &str = "https://api.coin-communities.xyz";
/// Step one: ask for a challenge to sign. Security in the service's `OpenAPI` SDK is `x-api-key`
/// only — the handshake bootstraps from the shared product key, needing no bearer to start.
const CHALLENGE_URL: &str = "https://api.coin-communities.xyz/api/v1/users/auth/wallet/challenge";
/// Step two: hand back the signed challenge and receive the `{accessToken, refreshToken}` pair.
/// Security `x-api-key` only.
const VERIFY_URL: &str = "https://api.coin-communities.xyz/api/v1/users/auth/wallet/verify";
/// Refresh: exchange the stored refresh token for a rotated pair. Security `x-api-key` only.
const REFRESH_URL: &str = "https://api.coin-communities.xyz/api/v1/users/token/refresh";
/// The websocket origin the per-community social push channel lives on. The ticket mint below is
/// the ONLY bearer-carrying POST besides the auth handshake, and it mints a READ-ONLY subscription
/// ticket (`docs/reference/PUMP_API_MAP.md` §4.6/§4.7): nothing about it posts, likes, moderates,
/// or otherwise mutates community state.
const WS_ORIGIN: &str = "wss://api.coin-communities.xyz";
/// The chain discriminator the app sends on the challenge and verify bodies.
const CHAIN_TYPE: &str = "svm";
/// The shared product-key header name the handshake POSTs carry (same header the gated GETs use).
const API_KEY_HEADER: &str = "x-api-key";
/// The browser `Origin` the app requests from. Sent so the handshake looks like the real client.
const BROWSER_ORIGIN: &str = "https://pump.fun";
/// A sane upper bound on an authentication challenge. A nonce-plus-wording challenge is short; this
/// is a floor under the printable-text guard, not a wire limit the service imposes.
const CHALLENGE_MAX_BYTES: usize = 4096;
/// If a returned access token carries no readable `exp`, treat it as short-lived so it is refreshed
/// eagerly rather than trusted for a day. Most tokens carry `exp`; this is only the fallback.
const FALLBACK_SESSION_TTL: time::Duration = time::Duration::minutes(5);

/// Errors from loading the wallet, signing the challenge, or exchanging it for a session.
#[derive(Debug)]
pub enum CommunityAuthError {
    /// The wallet file was missing, unreadable, or not a regular file.
    WalletRead(PathBuf),
    /// The wallet file's permissions allow group or other access.
    WalletPermissions,
    /// The wallet file did not decode to a 64-byte base58 Solana secret key.
    WalletShape,
    /// The server-issued challenge was not authentication-shaped text and was refused unsigned.
    /// This is the boundary firing: the wallet does not sign anything that is not a plain-text
    /// authentication challenge.
    UntrustedChallenge,
    /// A handshake request could not be sent.
    Transport(String),
    /// The challenge request returned a non-success status.
    ChallengeRejected(u16),
    /// The challenge succeeded but carried no `message` to sign.
    NoChallenge,
    /// The verify request returned a non-success status. The body is deliberately not captured,
    /// because a failed auth body can echo the submitted material.
    VerifyRejected(u16),
    /// The exchange succeeded but carried no `accessToken`/`refreshToken` pair.
    NoTokens,
    /// Refresh returned a non-4xx, non-success status; the stored pair is left intact to retry.
    RefreshRejected(u16),
    /// Refresh returned a `4xx`: the refresh token is dead and the session has been cleared. The
    /// caller must run a full handshake again — the app's own behavior.
    SessionCleared,
    /// Session material was requested from a session that is not live.
    NotLive,
    /// A websocket-ticket subject was not shaped like a public token address and was refused
    /// before any request was built. The subject is interpolated into a URL path, so anything
    /// that is not plainly a base58 mint is rejected rather than encoded around.
    UnsafeSubject,
    /// The ticket mint returned a non-success status. `429` here is the shared ~1 rps product
    /// bucket's ordinary weather, not a refusal; other `4xx` are refusals. The body is not
    /// captured: a failed mint body may echo request material.
    TicketRejected(u16),
    /// The ticket mint succeeded but carried no non-empty `ticket` string.
    NoTicket,
}

impl From<WalletKeyError> for CommunityAuthError {
    fn from(error: WalletKeyError) -> Self {
        match error {
            WalletKeyError::Read(path) => Self::WalletRead(path),
            WalletKeyError::Permissions => Self::WalletPermissions,
            WalletKeyError::Shape => Self::WalletShape,
        }
    }
}

impl fmt::Display for CommunityAuthError {
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
            Self::UntrustedChallenge => formatter
                .write_str("server challenge is not authentication-shaped text; refused unsigned"),
            Self::Transport(detail) => write!(formatter, "handshake transport failed: {detail}"),
            Self::ChallengeRejected(status) => {
                write!(formatter, "challenge rejected with status {status}")
            }
            Self::NoChallenge => formatter.write_str("challenge succeeded but carried no message"),
            Self::VerifyRejected(status) => {
                write!(formatter, "verify rejected with status {status}")
            }
            Self::NoTokens => {
                formatter.write_str("verify succeeded but carried no access/refresh token pair")
            }
            Self::RefreshRejected(status) => {
                write!(formatter, "refresh rejected with status {status}")
            }
            Self::SessionCleared => {
                formatter.write_str("refresh token is dead; session cleared, re-handshake required")
            }
            Self::NotLive => formatter.write_str("session is not live"),
            Self::UnsafeSubject => formatter
                .write_str("ws-ticket subject is not shaped like a public token address; refused"),
            Self::TicketRejected(status) => {
                write!(formatter, "ws ticket mint rejected with status {status}")
            }
            Self::NoTicket => formatter.write_str("ws ticket mint succeeded but carried no ticket"),
        }
    }
}

impl std::error::Error for CommunityAuthError {}

/// A loaded wallet that can sign the coin-communities authentication challenge and nothing else.
///
/// The signing key is private and never leaves this type. The only method that touches it,
/// [`Self::sign_authentication_challenge`], guards its input to printable authentication text and
/// then produces a message signature over exactly those bytes; there is no method that signs
/// transaction-shaped or otherwise unvetted bytes.
pub struct CommunityWalletSigner {
    signing_key: SigningKey,
    address: String,
}

impl fmt::Debug for CommunityWalletSigner {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("CommunityWalletSigner")
            .field("signing_key", &"[REDACTED]")
            .field("address", &self.address)
            .finish()
    }
}

impl CommunityWalletSigner {
    /// Load the base58 64-byte Solana secret key (the same key file the pump SIWS signer loads)
    /// from a mode-0600 file.
    ///
    /// # Errors
    ///
    /// Returns [`CommunityAuthError`] when the file is missing, world/group-readable, or does not
    /// decode to a valid 64-byte key.
    pub fn from_file(path: impl AsRef<Path>) -> Result<Self, CommunityAuthError> {
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

    /// Sign a SERVER-ISSUED AUTHENTICATION CHALLENGE, and only that.
    ///
    /// The challenge is guarded to printable authentication text by [`challenge_is_authentication_text`]
    /// before a single byte reaches the signer; anything that is not is refused as
    /// [`CommunityAuthError::UntrustedChallenge`]. The signed bytes are the challenge's own UTF-8,
    /// exactly as the app's message-sign path encodes them. Nothing here constructs or signs a
    /// transaction.
    fn sign_authentication_challenge(&self, challenge: &str) -> Result<String, CommunityAuthError> {
        if !challenge_is_authentication_text(challenge) {
            return Err(CommunityAuthError::UntrustedChallenge);
        }
        let signature = self.signing_key.sign(challenge.as_bytes());
        Ok(bs58::encode(signature.to_bytes()).into_string())
    }
}

/// Whether a server-issued challenge is an authentication challenge we will sign.
///
/// A coin-communities auth challenge is human-readable text — a nonce plus descriptive wording. A
/// serialized Solana transaction is binary: 32-byte raw public keys and a 32-byte blockhash, which
/// cannot be printable text. Requiring the challenge to be non-empty printable UTF-8 within a sane
/// length is the domain separation the pump SIWS fixed prefix provides for the other session: it
/// makes it impossible for a hostile server to route transaction bytes through the message signer.
/// Ordinary whitespace (newline, carriage return, tab) is allowed because SIWS-style challenges are
/// multi-line; every other control character is refused.
fn challenge_is_authentication_text(challenge: &str) -> bool {
    !challenge.is_empty()
        && challenge.len() <= CHALLENGE_MAX_BYTES
        && challenge
            .chars()
            .all(|character| !character.is_control() || matches!(character, '\n' | '\r' | '\t'))
}

/// A rotated access/refresh token pair, moved straight into secrets.
struct Tokens {
    access: SecretString,
    refresh: SecretString,
}

/// A live coin-communities session: the bearer, the refresh token, the shared product key needed to
/// refresh, and the instant the access token expires.
pub struct CommunitySession {
    access: SecretString,
    refresh: SecretString,
    product_key: SecretString,
    access_expires_at: time::OffsetDateTime,
    label: String,
}

impl fmt::Debug for CommunitySession {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("CommunitySession")
            .field("access", &"[REDACTED]")
            .field("refresh", &"[REDACTED]")
            .field("product_key", &"[REDACTED]")
            .field("access_expires_at", &self.access_expires_at)
            .field("label", &self.label)
            .finish()
    }
}

impl CommunitySession {
    /// Run the full handshake: request a challenge, sign it (guarded), exchange it for a session.
    ///
    /// The wallet signs only the authentication challenge here. On success both tokens are moved
    /// directly into secrets and no plaintext is returned to the caller.
    ///
    /// # Errors
    ///
    /// Returns [`CommunityAuthError`] on a transport failure, a non-success status at either step,
    /// a challenge that is not authentication-shaped text, or a success carrying no tokens.
    pub async fn login(
        signer: &CommunityWalletSigner,
        product_key: &str,
    ) -> Result<Self, CommunityAuthError> {
        let http = build_http()?;
        let challenge = request_challenge(&http, signer.address(), product_key).await?;
        let signature = signer.sign_authentication_challenge(&challenge)?;
        let tokens = verify_signature(&http, signer.address(), &signature, product_key).await?;
        let access_expires_at = jwt_expiry(tokens.access.expose_secret())
            .unwrap_or_else(|| time::OffsetDateTime::now_utc() + FALLBACK_SESSION_TTL);
        let label = format!(
            "community:coin-communities:{}",
            &signer.address()[..signer.address().len().min(8)]
        );
        Ok(Self {
            access: tokens.access,
            refresh: tokens.refresh,
            product_key: SecretString::from(product_key.to_owned()),
            access_expires_at,
            label,
        })
    }

    /// Whether the access token is still valid at the current instant.
    #[must_use]
    pub fn is_live(&self) -> bool {
        self.access_expires_at > time::OffsetDateTime::now_utc()
    }

    /// The instant the access token expires. Not a secret.
    #[must_use]
    pub fn expires_at(&self) -> time::OffsetDateTime {
        self.access_expires_at
    }

    /// Current bearer material, or [`CommunityAuthError::NotLive`] if the session has expired.
    fn material(&self) -> Result<SessionMaterial, CommunityAuthError> {
        if !self.is_live() {
            return Err(CommunityAuthError::NotLive);
        }
        Ok(SessionMaterial::bearer_only(
            self.access.expose_secret(),
            &self.label,
        ))
    }

    /// Exchange the stored refresh token for a rotated pair, replacing BOTH atomically on success.
    ///
    /// The network exchange happens first; only once both new tokens are in hand are the fields
    /// assigned together, so a failed refresh leaves the previous pair intact. A `4xx` clears the
    /// session and returns [`CommunityAuthError::SessionCleared`], which the caller answers with a
    /// full [`Self::login`] — the app's own behavior.
    ///
    /// # Errors
    ///
    /// Returns [`CommunityAuthError`] on transport failure, a non-success status, or a success
    /// carrying no tokens; [`CommunityAuthError::SessionCleared`] specifically means re-handshake.
    pub async fn refresh(&mut self) -> Result<(), CommunityAuthError> {
        let http = build_http()?;
        match perform_refresh(
            &http,
            self.refresh.expose_secret(),
            self.product_key.expose_secret(),
        )
        .await
        {
            Ok(tokens) => {
                self.install_rotation(tokens);
                Ok(())
            }
            Err(CommunityAuthError::SessionCleared) => {
                self.clear();
                Err(CommunityAuthError::SessionCleared)
            }
            Err(error) => Err(error),
        }
    }

    /// Install a rotated token pair. Called only with both tokens already in hand, so the swap is
    /// atomic: no partial state is ever observable.
    fn install_rotation(&mut self, tokens: Tokens) {
        self.access_expires_at = jwt_expiry(tokens.access.expose_secret())
            .unwrap_or_else(|| time::OffsetDateTime::now_utc() + FALLBACK_SESSION_TTL);
        self.access = tokens.access;
        self.refresh = tokens.refresh;
    }

    /// Wipe the tokens and mark the session dead, so no request can reuse a cleared session.
    fn clear(&mut self) {
        self.access = SecretString::from(String::new());
        self.refresh = SecretString::from(String::new());
        self.access_expires_at = time::OffsetDateTime::UNIX_EPOCH;
    }
}

/// A [`SessionProvider`] backed by a coin-communities session, refreshed in place.
///
/// Unlike the SIWS provider, this one is refreshable: it holds the session behind a mutex so that
/// [`Self::ensure_fresh`] (the caller's proactive pre-request refresh, mirroring the app's
/// `isJwtExpired` check) and [`SessionProvider::invalidate`] (the reactive path on a 401) can both
/// update it. The mutex is never held across an `await`: the async refresh clones the secrets it
/// needs, drops the guard, performs the exchange, then re-locks to install the result.
pub struct CommunitySessionProvider {
    session: Mutex<CommunitySession>,
}

impl fmt::Debug for CommunitySessionProvider {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("CommunitySessionProvider")
            .field("session", &"[COMMUNITY SESSION]")
            .finish()
    }
}

impl CommunitySessionProvider {
    #[must_use]
    pub fn new(session: CommunitySession) -> Self {
        Self {
            session: Mutex::new(session),
        }
    }

    /// The instant the wrapped session expires. Not a secret.
    #[must_use]
    pub fn expires_at(&self) -> time::OffsetDateTime {
        self.locked().access_expires_at
    }

    /// Install a freshly handshaken session in place of the wrapped one.
    ///
    /// This is the caller's answer to [`CommunityAuthError::SessionCleared`]: a dead refresh
    /// token cannot be refreshed, the app re-runs the full handshake, and the new session then
    /// replaces the cleared one HERE so every holder of this provider sees the rotation. The
    /// swap is whole — both tokens and the expiry move together under the lock.
    pub fn replace(&self, session: CommunitySession) {
        *self.locked() = session;
    }

    /// Whether the wrapped session is live right now.
    #[must_use]
    pub fn is_live(&self) -> bool {
        self.locked().is_live()
    }

    /// Refresh the session if it is not live, mirroring the app's pre-request `isJwtExpired` check.
    ///
    /// A no-op when the session is still live. Otherwise it refreshes off the stored refresh token
    /// and installs the rotated pair. A `4xx` clears the session and surfaces
    /// [`CommunityAuthError::SessionCleared`] so the caller re-runs the full handshake. The mutex
    /// is dropped before the network exchange and re-acquired only to install the result.
    ///
    /// # Errors
    ///
    /// Returns [`CommunityAuthError`] on transport failure or a non-success refresh; specifically
    /// [`CommunityAuthError::SessionCleared`] when the refresh token is dead.
    pub async fn ensure_fresh(&self) -> Result<(), CommunityAuthError> {
        let (refresh_token, product_key) = {
            let session = self.locked();
            if session.is_live() {
                return Ok(());
            }
            (
                session.refresh.expose_secret().to_owned(),
                session.product_key.expose_secret().to_owned(),
            )
        };
        let http = build_http()?;
        match perform_refresh(&http, &refresh_token, &product_key).await {
            Ok(tokens) => {
                self.locked().install_rotation(tokens);
                Ok(())
            }
            Err(CommunityAuthError::SessionCleared) => {
                self.locked().clear();
                Err(CommunityAuthError::SessionCleared)
            }
            Err(error) => Err(error),
        }
    }

    fn locked(&self) -> std::sync::MutexGuard<'_, CommunitySession> {
        self.session
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}

impl SessionProvider for CommunitySessionProvider {
    fn session_for(&self, _route: RouteSpec) -> Result<SessionMaterial, SessionError> {
        self.locked().material().map_err(|_| SessionError::Expired)
    }

    fn invalidate(&self, _route: RouteSpec) {
        // The server rejected the bearer even though our clock may still call it live (skew, or a
        // server-side revoke). Mark it clock-dead so the next `ensure_fresh` forces a refresh — the
        // reactive path collapsing into the proactive one, exactly as the app retries a 401 by
        // refreshing. This provider never mines a fresh credential on its own; it only refreshes an
        // already-held one, and a dead refresh token then requires Ember's wallet again.
        self.locked().access_expires_at = time::OffsetDateTime::UNIX_EPOCH;
    }
}

/// A short-lived, single-use subscription ticket for the per-community social push websocket.
///
/// The ticket is a credential (whoever holds it may open the socket the bearer paid for), so it is
/// wrapped and never rendered; the ONE way it leaves this type is inside the connect URL
/// [`Self::socket_url`] builds, and that URL therefore inherits the same discipline as a keyed
/// endpoint: never logged, never retained, and connect errors are stated without quoting it.
/// Tickets are single-use — mint a fresh one for every (re)connect, never store one.
pub struct WsTicket {
    value: SecretString,
}

impl fmt::Debug for WsTicket {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("WsTicket")
            .field("value", &"[REDACTED]")
            .finish()
    }
}

impl WsTicket {
    /// The `wss://` connect URL for one community's socket, with the ticket as its query.
    ///
    /// The returned string CONTAINS THE TICKET. Treat it like a keyed endpoint: hand it to the
    /// websocket connector and nothing else; never log it, retain it, or quote a transport error
    /// that may echo it.
    ///
    /// # Errors
    ///
    /// Returns [`CommunityAuthError::UnsafeSubject`] when the token address is not shaped like a
    /// public mint, and [`CommunityAuthError::Transport`] if URL construction fails.
    pub fn socket_url(&self, token_address: &str) -> Result<String, CommunityAuthError> {
        if !token_address_is_public_mint(token_address) {
            return Err(CommunityAuthError::UnsafeSubject);
        }
        let mut url = url::Url::parse(&format!(
            "{WS_ORIGIN}/api/v1/communities/{token_address}/ws"
        ))
        .map_err(|error| CommunityAuthError::Transport(error.to_string()))?;
        url.query_pairs_mut()
            .append_pair("ticket", self.value.expose_secret());
        Ok(url.into())
    }
}

/// Whether a websocket-ticket subject is plainly a public token address: base58-alphabet
/// characters only, at a Solana-key length. The subject lands inside a URL path, so this guard
/// exists to make traversal or query smuggling structurally impossible, not to validate mints.
fn token_address_is_public_mint(token_address: &str) -> bool {
    (32..=44).contains(&token_address.len())
        && token_address
            .chars()
            .all(|character| character.is_ascii_alphanumeric())
}

/// Pull the ws `ticket` out of a mint response body, tolerating the same `data` wrapper the auth
/// bodies use. Empty is absent.
fn ticket_from_body(text: &str) -> Option<SecretString> {
    let value: serde_json::Value = serde_json::from_str(text).ok()?;
    nonempty_str(&value, "ticket").map(SecretString::from)
}

impl CommunitySessionProvider {
    /// Mint one single-use ticket for one community's websocket:
    /// `POST /api/v1/communities/{token_address}/ws/ticket`, bearer + shared `x-api-key`.
    ///
    /// This is a READ-ONLY subscription mint (the map's §4.7 note): it grants a push
    /// subscription and mutates no community state. The service's `OpenAPI` declares no request
    /// body, so none is sent; a `400`/`411`/`415`/`422` first answer is retried once inside this
    /// call with an empty JSON object body in case the deployed handler differs from its SDK,
    /// and the FIRST status is reported if both are refused. The response body is parsed for the
    /// ticket and never surfaced; failed-mint bodies are dropped unread beyond status.
    ///
    /// This call spends the same shared ~1 rps GLOBAL product-key bucket as the handshake and
    /// every community GET: pace it, treat `429` as weather, and never mint in parallel.
    ///
    /// # Errors
    ///
    /// Returns [`CommunityAuthError::UnsafeSubject`] for a non-mint-shaped subject,
    /// [`CommunityAuthError::NotLive`] when the session is not live (call
    /// [`Self::ensure_fresh`] first), [`CommunityAuthError::TicketRejected`] with the status on
    /// a non-success answer, and [`CommunityAuthError::NoTicket`] when a success carries none.
    pub async fn mint_ws_ticket(
        &self,
        token_address: &str,
    ) -> Result<WsTicket, CommunityAuthError> {
        if !token_address_is_public_mint(token_address) {
            return Err(CommunityAuthError::UnsafeSubject);
        }
        let (bearer, product_key) = {
            let session = self.locked();
            if !session.is_live() {
                return Err(CommunityAuthError::NotLive);
            }
            (
                session.access.expose_secret().to_owned(),
                session.product_key.expose_secret().to_owned(),
            )
        };
        let http = build_http()?;
        let url = format!("{ORIGIN}/api/v1/communities/{token_address}/ws/ticket");
        let first = post_ticket(&http, &url, &bearer, &product_key, None).await?;
        let first_status = first.status();
        let response = if first_status.is_success() {
            first
        } else if matches!(first_status.as_u16(), 400 | 411 | 415 | 422) {
            let second = post_ticket(&http, &url, &bearer, &product_key, Some(b"{}")).await?;
            if second.status().is_success() {
                second
            } else {
                return Err(CommunityAuthError::TicketRejected(first_status.as_u16()));
            }
        } else {
            return Err(CommunityAuthError::TicketRejected(first_status.as_u16()));
        };
        let text = response
            .text()
            .await
            .map_err(|error| CommunityAuthError::Transport(error.to_string()))?;
        ticket_from_body(&text)
            .map(|value| WsTicket { value })
            .ok_or(CommunityAuthError::NoTicket)
    }
}

/// The one place the ticket POST is shaped: bearer + shared product key + browser origin, and a
/// body only when the caller names one. The bearer and key are written into headers and appear
/// nowhere else.
async fn post_ticket(
    http: &reqwest::Client,
    url: &str,
    bearer: &str,
    product_key: &str,
    body: Option<&[u8]>,
) -> Result<reqwest::Response, CommunityAuthError> {
    let mut builder = http
        .post(url)
        .header(reqwest::header::AUTHORIZATION, format!("Bearer {bearer}"))
        .header(reqwest::header::ORIGIN, BROWSER_ORIGIN)
        .header(API_KEY_HEADER, product_key);
    if let Some(body) = body {
        builder = builder
            .header(reqwest::header::CONTENT_TYPE, "application/json")
            .body(body.to_vec());
    }
    builder
        .send()
        .await
        .map_err(|error| CommunityAuthError::Transport(error.to_string()))
}

/// A redirect-refusing HTTP client for the handshake POSTs, matching the SIWS login's posture.
fn build_http() -> Result<reqwest::Client, CommunityAuthError> {
    reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|error| CommunityAuthError::Transport(error.to_string()))
}

/// POST the challenge request; return the `message` string to sign.
async fn request_challenge(
    http: &reqwest::Client,
    address: &str,
    product_key: &str,
) -> Result<String, CommunityAuthError> {
    let body = serde_json::to_vec(&serde_json::json!({
        "address": address,
        "chainType": CHAIN_TYPE,
    }))
    .map_err(|error| CommunityAuthError::Transport(error.to_string()))?;
    let response = post(http, CHALLENGE_URL, product_key, body).await?;
    let status = response.status();
    let text = response
        .text()
        .await
        .map_err(|error| CommunityAuthError::Transport(error.to_string()))?;
    if !status.is_success() {
        return Err(CommunityAuthError::ChallengeRejected(status.as_u16()));
    }
    challenge_from_body(&text).ok_or(CommunityAuthError::NoChallenge)
}

/// POST the signed challenge; return the rotated token pair.
async fn verify_signature(
    http: &reqwest::Client,
    address: &str,
    signature: &str,
    product_key: &str,
) -> Result<Tokens, CommunityAuthError> {
    let body = serde_json::to_vec(&serde_json::json!({
        "address": address,
        "chainType": CHAIN_TYPE,
        "signature": signature,
    }))
    .map_err(|error| CommunityAuthError::Transport(error.to_string()))?;
    let response = post(http, VERIFY_URL, product_key, body).await?;
    let status = response.status();
    let text = response
        .text()
        .await
        .map_err(|error| CommunityAuthError::Transport(error.to_string()))?;
    if !status.is_success() {
        return Err(CommunityAuthError::VerifyRejected(status.as_u16()));
    }
    tokens_from_body(&text).ok_or(CommunityAuthError::NoTokens)
}

/// POST the stored refresh token; return the rotated pair, or [`CommunityAuthError::SessionCleared`]
/// on a `4xx` (the refresh token is dead).
async fn perform_refresh(
    http: &reqwest::Client,
    refresh_token: &str,
    product_key: &str,
) -> Result<Tokens, CommunityAuthError> {
    let body = serde_json::to_vec(&serde_json::json!({ "refreshToken": refresh_token }))
        .map_err(|error| CommunityAuthError::Transport(error.to_string()))?;
    let response = post(http, REFRESH_URL, product_key, body).await?;
    let status = response.status();
    let text = response
        .text()
        .await
        .map_err(|error| CommunityAuthError::Transport(error.to_string()))?;
    if !status.is_success() {
        if (400..500).contains(&status.as_u16()) {
            return Err(CommunityAuthError::SessionCleared);
        }
        return Err(CommunityAuthError::RefreshRejected(status.as_u16()));
    }
    tokens_from_body(&text).ok_or(CommunityAuthError::NoTokens)
}

/// The one place the handshake POSTs are shaped: JSON body, the shared product-key header, and the
/// browser origin. The product key is written into the header value and appears nowhere else.
async fn post(
    http: &reqwest::Client,
    url: &str,
    product_key: &str,
    body: Vec<u8>,
) -> Result<reqwest::Response, CommunityAuthError> {
    http.post(url)
        .header(reqwest::header::CONTENT_TYPE, "application/json")
        .header(reqwest::header::ORIGIN, BROWSER_ORIGIN)
        .header(API_KEY_HEADER, product_key)
        .body(body)
        .send()
        .await
        .map_err(|error| CommunityAuthError::Transport(error.to_string()))
}

/// Pull the challenge `message` out of the response body. The app reads `data.message`; the HTTP
/// body itself carries `message`, so both shapes are tolerated.
fn challenge_from_body(text: &str) -> Option<String> {
    let value: serde_json::Value = serde_json::from_str(text).ok()?;
    let message = value
        .get("message")
        .or_else(|| value.get("data").and_then(|data| data.get("message")))
        .and_then(serde_json::Value::as_str)?;
    (!message.is_empty()).then(|| message.to_owned())
}

/// Pull the `{accessToken, refreshToken}` pair out of a verify/refresh body, tolerating a `data`
/// wrapper. Both must be present and non-empty or the whole read fails.
fn tokens_from_body(text: &str) -> Option<Tokens> {
    let value: serde_json::Value = serde_json::from_str(text).ok()?;
    let access = nonempty_str(&value, "accessToken")?;
    let refresh = nonempty_str(&value, "refreshToken")?;
    Some(Tokens {
        access: SecretString::from(access),
        refresh: SecretString::from(refresh),
    })
}

/// Read a non-empty string field, looking under a `data` wrapper too.
fn nonempty_str(value: &serde_json::Value, key: &str) -> Option<String> {
    let direct = value.get(key);
    let wrapped = value.get("data").and_then(|data| data.get(key));
    direct
        .or(wrapped)
        .and_then(serde_json::Value::as_str)
        .filter(|text| !text.is_empty())
        .map(str::to_owned)
}

/// The origin these routes live on, exposed so a caller can assert the session and the client's
/// shared-product-key map agree on it without hard-coding the string twice.
#[must_use]
pub fn community_origin() -> &'static str {
    ORIGIN
}

/// The websocket origin the per-community push channel lives on, exposed for the same reason as
/// [`community_origin`].
#[must_use]
pub fn community_ws_origin() -> &'static str {
    WS_ORIGIN
}

#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::{Signature, Verifier};

    fn fixed_signer() -> CommunityWalletSigner {
        // A fixed 32-byte seed so the signature is deterministic and never a real key.
        CommunityWalletSigner {
            signing_key: SigningKey::from_bytes(&[9u8; 32]),
            address: "TestAddress0000".to_owned(),
        }
    }

    #[test]
    fn a_text_challenge_is_signed_over_its_exact_bytes() {
        let signer = fixed_signer();
        let challenge =
            "coin-communities.xyz wants you to sign in with your Solana account:\nNonce: abc123";
        let signature = signer
            .sign_authentication_challenge(challenge)
            .expect("a text challenge is signed");
        let bytes = bs58::decode(&signature).into_vec().expect("valid base58");
        assert_eq!(bytes.len(), 64, "an ed25519 signature is 64 bytes");
        let parsed = Signature::from_slice(&bytes).expect("signature parses");
        signer
            .signing_key
            .verifying_key()
            .verify(challenge.as_bytes(), &parsed)
            .expect("the signature verifies over the exact challenge bytes");
        // A different message must not verify against this signature.
        assert!(
            signer
                .signing_key
                .verifying_key()
                .verify(b"a different message", &parsed)
                .is_err()
        );
    }

    #[test]
    fn a_binary_or_empty_challenge_is_refused_unsigned() {
        let signer = fixed_signer();
        // A NUL and other control bytes stand in for the raw pubkey/blockhash bytes of a
        // serialized transaction: not authentication-shaped text, so refused.
        assert!(matches!(
            signer.sign_authentication_challenge("sign\u{0}this\u{1}\u{2}binary"),
            Err(CommunityAuthError::UntrustedChallenge)
        ));
        assert!(matches!(
            signer.sign_authentication_challenge(""),
            Err(CommunityAuthError::UntrustedChallenge)
        ));
        let too_long = "a".repeat(CHALLENGE_MAX_BYTES + 1);
        assert!(matches!(
            signer.sign_authentication_challenge(&too_long),
            Err(CommunityAuthError::UntrustedChallenge)
        ));
    }

    #[test]
    fn the_guard_accepts_multiline_siws_style_text_and_rejects_control_bytes() {
        assert!(challenge_is_authentication_text(
            "Sign in.\r\n\tNonce: 7Hb9\u{2014}xyz"
        ));
        assert!(!challenge_is_authentication_text("\u{7}bell"));
        assert!(!challenge_is_authentication_text(""));
    }

    #[test]
    fn challenge_parses_from_message_and_data_wrapper() {
        assert_eq!(
            challenge_from_body(r#"{"message":"please sign nonce 42"}"#).as_deref(),
            Some("please sign nonce 42")
        );
        assert_eq!(
            challenge_from_body(r#"{"data":{"message":"wrapped nonce"}}"#).as_deref(),
            Some("wrapped nonce")
        );
        assert_eq!(challenge_from_body(r#"{"message":""}"#), None);
        assert_eq!(challenge_from_body(r#"{"nope":1}"#), None);
    }

    #[test]
    fn tokens_parse_only_when_both_are_present() {
        let both = r#"{"accessToken":"aaa.bbb.ccc","refreshToken":"rrr"}"#;
        let tokens = tokens_from_body(both).expect("both tokens present");
        assert_eq!(tokens.access.expose_secret(), "aaa.bbb.ccc");
        assert_eq!(tokens.refresh.expose_secret(), "rrr");
        let wrapped = r#"{"data":{"accessToken":"aaa","refreshToken":"rrr"}}"#;
        assert!(tokens_from_body(wrapped).is_some());
        // A missing or empty refresh token fails the whole read rather than yielding a half pair.
        assert!(tokens_from_body(r#"{"accessToken":"aaa"}"#).is_none());
        assert!(tokens_from_body(r#"{"accessToken":"aaa","refreshToken":""}"#).is_none());
    }

    #[test]
    fn debug_never_renders_the_secrets() {
        let session = CommunitySession {
            access: SecretString::from("ACCESS-SECRET".to_owned()),
            refresh: SecretString::from("REFRESH-SECRET".to_owned()),
            product_key: SecretString::from("cc_secret".to_owned()),
            access_expires_at: time::OffsetDateTime::UNIX_EPOCH,
            label: "community:coin-communities:TestAddr".to_owned(),
        };
        let rendered = format!("{session:?}");
        assert!(!rendered.contains("ACCESS-SECRET"));
        assert!(!rendered.contains("REFRESH-SECRET"));
        assert!(!rendered.contains("cc_secret"));
        assert!(rendered.contains("[REDACTED]"));
        let signer = fixed_signer();
        assert!(!format!("{signer:?}").contains("signing_key: SigningKey"));
    }

    #[test]
    fn material_is_refused_when_the_session_is_not_live() {
        let dead = CommunitySession {
            access: SecretString::from("aaa".to_owned()),
            refresh: SecretString::from("rrr".to_owned()),
            product_key: SecretString::from("cc".to_owned()),
            access_expires_at: time::OffsetDateTime::UNIX_EPOCH,
            label: "community:test".to_owned(),
        };
        assert!(!dead.is_live());
        assert!(matches!(dead.material(), Err(CommunityAuthError::NotLive)));
        let provider = CommunitySessionProvider::new(dead);
        assert!(matches!(
            provider.session_for(RouteSpec::for_id(crate::catalog::RouteId::CommunityMe)),
            Err(SessionError::Expired)
        ));

        let live = CommunitySession {
            access: SecretString::from("live-bearer".to_owned()),
            refresh: SecretString::from("rrr".to_owned()),
            product_key: SecretString::from("cc".to_owned()),
            access_expires_at: time::OffsetDateTime::now_utc() + time::Duration::hours(1),
            label: "community:test".to_owned(),
        };
        let material = live.material().expect("a live session yields material");
        assert_eq!(material.class(), "community:test");
    }

    #[test]
    fn a_ws_ticket_subject_must_be_shaped_like_a_public_mint() {
        assert!(token_address_is_public_mint(
            "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump"
        ));
        // Path traversal, query smuggling, emptiness, and off-length subjects are all refused
        // before any URL is built.
        assert!(!token_address_is_public_mint(""));
        assert!(!token_address_is_public_mint(
            "../users/me/xxxxxxxxxxxxxxxxxxxxxxxxx"
        ));
        assert!(!token_address_is_public_mint(
            "abc?ticket=stolenxxxxxxxxxxxxxxxxxxxxxxxx"
        ));
        assert!(!token_address_is_public_mint("short"));
        assert!(!token_address_is_public_mint(&"a".repeat(45)));
    }

    #[test]
    fn ticket_parses_from_ticket_and_data_wrapper_only_when_nonempty() {
        assert!(ticket_from_body(r#"{"ticket":"tkt-123"}"#).is_some());
        assert!(ticket_from_body(r#"{"data":{"ticket":"tkt-456"}}"#).is_some());
        assert!(ticket_from_body(r#"{"ticket":""}"#).is_none());
        assert!(ticket_from_body(r#"{"nope":1}"#).is_none());
        assert!(ticket_from_body("not json").is_none());
    }

    #[test]
    fn the_socket_url_carries_the_ticket_percent_encoded_and_debug_stays_redacted() {
        let ticket = WsTicket {
            value: SecretString::from("tkt+/= special".to_owned()),
        };
        let mint = "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump";
        let url = ticket.socket_url(mint).expect("a mint-shaped subject");
        assert!(url.starts_with(&format!(
            "wss://api.coin-communities.xyz/api/v1/communities/{mint}/ws?ticket="
        )));
        // The raw ticket text must not appear unencoded, and the encoded form must round-trip.
        assert!(!url.contains("tkt+/= special"));
        let parsed = url::Url::parse(&url).expect("the built URL parses");
        let (_, round_tripped) = parsed
            .query_pairs()
            .find(|(name, _)| name == "ticket")
            .expect("a ticket query parameter");
        assert_eq!(round_tripped, "tkt+/= special");
        assert!(matches!(
            ticket.socket_url("../smuggle/xxxxxxxxxxxxxxxxxxxxxxxxxxx"),
            Err(CommunityAuthError::UnsafeSubject)
        ));
        assert!(!format!("{ticket:?}").contains("tkt"));
    }

    #[test]
    fn a_ticket_mint_on_a_dead_session_is_refused_without_io() {
        let dead = CommunitySession {
            access: SecretString::from("aaa".to_owned()),
            refresh: SecretString::from("rrr".to_owned()),
            product_key: SecretString::from("cc".to_owned()),
            access_expires_at: time::OffsetDateTime::UNIX_EPOCH,
            label: "community:test".to_owned(),
        };
        let provider = CommunitySessionProvider::new(dead);
        let runtime = tokio::runtime::Builder::new_current_thread()
            .build()
            .expect("a current-thread runtime");
        let outcome = runtime
            .block_on(provider.mint_ws_ticket("XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump"));
        assert!(matches!(outcome, Err(CommunityAuthError::NotLive)));
        let unsafe_subject = runtime.block_on(provider.mint_ws_ticket("not-a-mint"));
        assert!(matches!(
            unsafe_subject,
            Err(CommunityAuthError::UnsafeSubject)
        ));
    }

    #[test]
    fn install_rotation_swaps_both_tokens_atomically() {
        let mut session = CommunitySession {
            access: SecretString::from("old-access".to_owned()),
            refresh: SecretString::from("old-refresh".to_owned()),
            product_key: SecretString::from("cc".to_owned()),
            access_expires_at: time::OffsetDateTime::UNIX_EPOCH,
            label: "community:test".to_owned(),
        };
        session.install_rotation(Tokens {
            access: SecretString::from("new-access".to_owned()),
            refresh: SecretString::from("new-refresh".to_owned()),
        });
        assert_eq!(session.access.expose_secret(), "new-access");
        assert_eq!(session.refresh.expose_secret(), "new-refresh");
        session.clear();
        assert_eq!(session.access.expose_secret(), "");
        assert_eq!(session.refresh.expose_secret(), "");
        assert!(!session.is_live());
    }
}
