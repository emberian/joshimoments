use std::fmt;
use std::fs;
use std::path::{Path, PathBuf};

use secrecy::{ExposeSecret, SecretString};
use serde::Deserialize;
use thiserror::Error;

use crate::catalog::RouteSpec;

#[derive(Error, Debug)]
pub enum SessionError {
    #[error(
        "route {0} needs Ember's authenticated Pump session, but no session provider is configured"
    )]
    Missing(String),
    #[error("unable to read session material from {path}: {source}")]
    Read {
        path: PathBuf,
        source: std::io::Error,
    },
    #[error("session file must be a regular file")]
    NotRegular,
    #[error("session file permissions must exclude group/other access (expected mode 0600)")]
    UnsafePermissions,
    #[error("invalid session-file contract: {0}")]
    Contract(#[from] serde_json::Error),
    #[error("session contract/version is not joshi.pump_api.session_file.v1")]
    WrongVersion,
    #[error("session material is expired or has an invalid expiresAt timestamp")]
    Expired,
    #[error("a CSRF header name and value must either both be present or both be absent")]
    PartialCsrf,
    #[error("the configured CSRF header name is outside the source-edge allowlist")]
    UnsafeCsrfName,
}

/// Secret request material. Its `Debug` representation never exposes values, and it is never
/// serialized into acquisitions, request fingerprints, fixtures, or logs.
pub struct SessionMaterial {
    pub(crate) bearer: Option<SecretString>,
    pub(crate) cookie: Option<SecretString>,
    pub(crate) csrf_name: Option<String>,
    pub(crate) csrf_value: Option<SecretString>,
    session_label: String,
}

impl fmt::Debug for SessionMaterial {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("SessionMaterial")
            .field("bearer", &self.bearer.as_ref().map(|_| "[REDACTED]"))
            .field("cookie", &self.cookie.as_ref().map(|_| "[REDACTED]"))
            .field("csrf_name", &self.csrf_name)
            .field(
                "csrf_value",
                &self.csrf_value.as_ref().map(|_| "[REDACTED]"),
            )
            .field("session_label", &self.session_label)
            .finish()
    }
}

impl SessionMaterial {
    /// Build session material carrying only a cookie header value, for a provider that obtained a
    /// bare token (a SIWS `auth_token`, for instance) rather than a full credential file.
    #[must_use]
    pub fn cookie_only(cookie: &str, session_label: &str) -> Self {
        Self {
            bearer: None,
            cookie: Some(SecretString::from(cookie.to_owned())),
            csrf_name: None,
            csrf_value: None,
            session_label: session_label.to_owned(),
        }
    }

    #[must_use]
    pub fn class(&self) -> &str {
        &self.session_label
    }

    pub(crate) fn bearer_secret(&self) -> Option<&str> {
        self.bearer.as_ref().map(ExposeSecret::expose_secret)
    }

    pub(crate) fn cookie_secret(&self) -> Option<&str> {
        self.cookie.as_ref().map(ExposeSecret::expose_secret)
    }

    pub(crate) fn csrf_secret(&self) -> Option<(&str, &str)> {
        self.csrf_name
            .as_deref()
            .zip(self.csrf_value.as_ref().map(ExposeSecret::expose_secret))
    }
}

/// Session lifecycle seam. Implementations may reload an ephemeral credential file or talk to a
/// future local session broker. They may not receive wallet signing material.
pub trait SessionProvider: Send + Sync {
    /// Acquire current session material immediately before one authenticated request.
    ///
    /// # Errors
    ///
    /// Returns a typed error when material is unavailable, expired, malformed, or stored with
    /// unsafe filesystem permissions.
    fn session_for(&self, route: RouteSpec) -> Result<SessionMaterial, SessionError>;

    /// Called on 401/403. Providers must stop or refresh honestly; callers never rotate identity,
    /// alter headers, or mine a replacement credential in response.
    fn invalidate(&self, _route: RouteSpec) {}
}

#[derive(Debug, Default)]
pub struct NoSession;

impl SessionProvider for NoSession {
    fn session_for(&self, route: RouteSpec) -> Result<SessionMaterial, SessionError> {
        Err(SessionError::Missing(route.id.to_string()))
    }
}

#[derive(Debug)]
pub struct CredentialFileSession {
    path: PathBuf,
}

impl CredentialFileSession {
    #[must_use]
    pub fn new(path: impl Into<PathBuf>) -> Self {
        Self { path: path.into() }
    }

    fn load(&self) -> Result<SessionMaterial, SessionError> {
        secure_file(&self.path)?;
        let bytes = fs::read(&self.path).map_err(|source| SessionError::Read {
            path: self.path.clone(),
            source,
        })?;
        let parsed: SessionFile = serde_json::from_slice(&bytes)?;
        if parsed.contract != "joshi.pump_api.session_file.v1" {
            return Err(SessionError::WrongVersion);
        }
        if let Some(expires_at) = parsed.expires_at {
            let expiry = time::OffsetDateTime::parse(
                &expires_at,
                &time::format_description::well_known::Rfc3339,
            )
            .map_err(|_| SessionError::Expired)?;
            if expiry <= time::OffsetDateTime::now_utc() {
                return Err(SessionError::Expired);
            }
        }
        if parsed.csrf_header_name.is_some() != parsed.csrf_token.is_some() {
            return Err(SessionError::PartialCsrf);
        }
        if let Some(name) = parsed.csrf_header_name.as_deref() {
            let allowed = ["x-csrf-token", "x-xsrf-token"];
            if !allowed.contains(&name.to_ascii_lowercase().as_str()) {
                return Err(SessionError::UnsafeCsrfName);
            }
        }
        Ok(SessionMaterial {
            bearer: parsed.bearer.map(SecretString::from),
            cookie: parsed.cookie.map(SecretString::from),
            csrf_name: parsed.csrf_header_name,
            csrf_value: parsed.csrf_token.map(SecretString::from),
            session_label: parsed.session_label,
        })
    }
}

impl SessionProvider for CredentialFileSession {
    fn session_for(&self, _route: RouteSpec) -> Result<SessionMaterial, SessionError> {
        self.load()
    }
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SessionFile {
    contract: String,
    session_label: String,
    expires_at: Option<String>,
    bearer: Option<String>,
    cookie: Option<String>,
    csrf_header_name: Option<String>,
    csrf_token: Option<String>,
}

fn secure_file(path: &Path) -> Result<(), SessionError> {
    let metadata = fs::metadata(path).map_err(|source| SessionError::Read {
        path: path.to_path_buf(),
        source,
    })?;
    if !metadata.is_file() {
        return Err(SessionError::NotRegular);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt as _;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err(SessionError::UnsafePermissions);
        }
    }
    Ok(())
}
