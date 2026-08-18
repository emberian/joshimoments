use std::{fmt, fs, path::PathBuf, time::Duration};

use secrecy::{ExposeSecret, SecretString};
use serde::{Deserialize, Serialize};
use thiserror::Error;
use url::Url;

use crate::backoff::BackoffPolicy;

const MAX_CREDENTIAL_BYTES: u64 = 16 * 1024;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(transparent)]
pub struct CredentialFile(pub PathBuf);

#[derive(Error, Debug)]
pub enum ConfigError {
    #[error("credential path is not a regular file: {0}")]
    CredentialNotFile(PathBuf),
    #[error("credential path must not be a symbolic link: {0}")]
    CredentialSymlink(PathBuf),
    #[error("credential file is too large: {0}")]
    CredentialTooLarge(PathBuf),
    #[error("credential file is empty: {0}")]
    CredentialEmpty(PathBuf),
    #[error("credential file permissions allow group/other access: {0}")]
    CredentialPermissions(PathBuf),
    #[error("unable to read credential file {path}: {source}")]
    CredentialRead {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error("invalid endpoint URL: {0}")]
    InvalidUrl(#[from] url::ParseError),
    #[error("endpoint must not contain credentials or secret-looking query parameters")]
    SecretInEndpoint,
    #[error("unexpected scheme for {kind}: {actual}")]
    WrongScheme { kind: &'static str, actual: String },
    #[error("credentialed endpoint host is not allowed for {provider}: {host}")]
    WrongCredentialHost {
        provider: &'static str,
        host: String,
    },
    #[error("configuration value is invalid: {0}")]
    Invalid(&'static str),
    #[error("{provider} credential carries wallet-signing authority and is forbidden here")]
    ForbiddenCredentialAuthority { provider: &'static str },
    #[error("{provider} live runtime is disabled pending canonical read-only admission")]
    ProviderRuntimeDisabled { provider: &'static str },
}

pub(crate) struct LoadedCredential(SecretString);

impl fmt::Debug for LoadedCredential {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("LoadedCredential([REDACTED])")
    }
}

impl LoadedCredential {
    pub(crate) fn expose(&self) -> &str {
        self.0.expose_secret()
    }
}

impl CredentialFile {
    /// Read once while constructing a live adapter. Offline parsers never call this method.
    pub(crate) fn load(&self) -> Result<LoadedCredential, ConfigError> {
        let metadata =
            fs::symlink_metadata(&self.0).map_err(|source| ConfigError::CredentialRead {
                path: self.0.clone(),
                source,
            })?;
        if metadata.file_type().is_symlink() {
            return Err(ConfigError::CredentialSymlink(self.0.clone()));
        }
        if !metadata.is_file() {
            return Err(ConfigError::CredentialNotFile(self.0.clone()));
        }
        if metadata.len() > MAX_CREDENTIAL_BYTES {
            return Err(ConfigError::CredentialTooLarge(self.0.clone()));
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            if metadata.permissions().mode() & 0o077 != 0 {
                return Err(ConfigError::CredentialPermissions(self.0.clone()));
            }
        }
        let value = fs::read_to_string(&self.0).map_err(|source| ConfigError::CredentialRead {
            path: self.0.clone(),
            source,
        })?;
        let value = value.trim().to_owned();
        if value.is_empty() {
            return Err(ConfigError::CredentialEmpty(self.0.clone()));
        }
        Ok(LoadedCredential(SecretString::from(value)))
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HeliusConfig {
    pub http_url: String,
    pub websocket_url: String,
    pub api_key_file: CredentialFile,
    pub request_timeout_ms: u64,
    pub websocket_inactivity_ms: u64,
    pub ingress_capacity: usize,
    pub backoff: BackoffPolicy,
}

impl HeliusConfig {
    #[must_use]
    pub fn mainnet(api_key_file: CredentialFile) -> Self {
        Self {
            http_url: "https://mainnet.helius-rpc.com/".to_owned(),
            websocket_url: "wss://mainnet.helius-rpc.com/".to_owned(),
            api_key_file,
            request_timeout_ms: 15_000,
            websocket_inactivity_ms: 60_000,
            ingress_capacity: 4_096,
            backoff: BackoffPolicy::default(),
        }
    }

    pub(crate) fn load(&self) -> Result<LoadedHeliusConfig, ConfigError> {
        if self.ingress_capacity == 0 {
            return Err(ConfigError::Invalid(
                "Helius ingress capacity must be nonzero",
            ));
        }
        self.backoff.validate().map_err(ConfigError::Invalid)?;
        let http_url =
            validate_endpoint(&self.http_url, "https", Some(("Helius", ".helius-rpc.com")))?;
        let websocket_url = validate_endpoint(
            &self.websocket_url,
            "wss",
            Some(("Helius", ".helius-rpc.com")),
        )?;
        Ok(LoadedHeliusConfig {
            http_url,
            websocket_url,
            api_key: self.api_key_file.load()?,
            request_timeout: Duration::from_millis(self.request_timeout_ms),
            websocket_inactivity: Duration::from_millis(self.websocket_inactivity_ms),
        })
    }
}

pub(crate) struct LoadedHeliusConfig {
    pub(crate) http_url: Url,
    pub(crate) websocket_url: Url,
    pub(crate) api_key: LoadedCredential,
    pub(crate) request_timeout: Duration,
    pub(crate) websocket_inactivity: Duration,
}

impl fmt::Debug for LoadedHeliusConfig {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("LoadedHeliusConfig")
            .field("http_origin", &origin(&self.http_url))
            .field("websocket_origin", &origin(&self.websocket_url))
            .field("api_key", &"[REDACTED]")
            .field("request_timeout", &self.request_timeout)
            .field("websocket_inactivity", &self.websocket_inactivity)
            .finish()
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PumpPortalConfig {
    pub websocket_url: String,
    pub api_key_file: Option<CredentialFile>,
    pub census_new_tokens: bool,
    pub census_migrations: bool,
    /// Retained legacy config; always disabled in this read-only runtime because the provider key
    /// is wallet-bearing authority.
    pub enable_metered_hot_scopes: bool,
    pub max_hot_keys: usize,
    pub max_keys_per_message: usize,
    pub max_subscription_messages_per_second: u16,
    pub websocket_inactivity_ms: u64,
    pub ingress_capacity: usize,
    pub backoff: BackoffPolicy,
}

impl Default for PumpPortalConfig {
    fn default() -> Self {
        Self {
            websocket_url: "wss://pumpportal.fun/api/data".to_owned(),
            api_key_file: None,
            census_new_tokens: true,
            census_migrations: true,
            enable_metered_hot_scopes: false,
            max_hot_keys: 2_000,
            max_keys_per_message: 1_000,
            max_subscription_messages_per_second: 20,
            websocket_inactivity_ms: 60_000,
            ingress_capacity: 4_096,
            backoff: BackoffPolicy::default(),
        }
    }
}

impl PumpPortalConfig {
    pub(crate) fn load(&self) -> Result<LoadedPumpPortalConfig, ConfigError> {
        // Refuse before reading a path or validating an endpoint. PumpPortal documents this API
        // key as wallet-bearing material; zero-priced methods do not make it read-only.
        if self.api_key_file.is_some() {
            return Err(ConfigError::ForbiddenCredentialAuthority {
                provider: "PumpPortal",
            });
        }
        Err(ConfigError::ProviderRuntimeDisabled {
            provider: "PumpPortal",
        })
    }
}

pub(crate) struct LoadedPumpPortalConfig {
    pub(crate) websocket_url: Url,
    pub(crate) api_key: Option<LoadedCredential>,
    pub(crate) websocket_inactivity: Duration,
}

impl fmt::Debug for LoadedPumpPortalConfig {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("LoadedPumpPortalConfig")
            .field("websocket_origin", &origin(&self.websocket_url))
            .field("api_key", &self.api_key.as_ref().map(|_| "[REDACTED]"))
            .field("websocket_inactivity", &self.websocket_inactivity)
            .finish()
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PublicSolanaRpcConfig {
    pub http_url: String,
    pub websocket_url: String,
    pub request_timeout_ms: u64,
    pub websocket_inactivity_ms: u64,
    pub ingress_capacity: usize,
    pub backoff: BackoffPolicy,
}

impl PublicSolanaRpcConfig {
    pub(crate) fn validate(&self) -> Result<(Url, Url), ConfigError> {
        if self.ingress_capacity == 0 {
            return Err(ConfigError::Invalid(
                "Solana RPC ingress capacity must be nonzero",
            ));
        }
        self.backoff.validate().map_err(ConfigError::Invalid)?;
        Ok((
            validate_endpoint(&self.http_url, "https", None)?,
            validate_endpoint(&self.websocket_url, "wss", None)?,
        ))
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SourceConfig {
    pub helius: Option<HeliusConfig>,
    pub pumpportal: Option<PumpPortalConfig>,
    pub public_solana: Option<PublicSolanaRpcConfig>,
}

fn validate_endpoint(
    raw: &str,
    expected_scheme: &'static str,
    credential_host: Option<(&'static str, &'static str)>,
) -> Result<Url, ConfigError> {
    let url = Url::parse(raw)?;
    if url.scheme() != expected_scheme {
        return Err(ConfigError::WrongScheme {
            kind: expected_scheme,
            actual: url.scheme().to_owned(),
        });
    }
    if !url.username().is_empty() || url.password().is_some() || url.fragment().is_some() {
        return Err(ConfigError::SecretInEndpoint);
    }
    for (name, _) in url.query_pairs() {
        let lower = name.to_ascii_lowercase();
        if lower.contains("key") || lower.contains("token") || lower.contains("secret") {
            return Err(ConfigError::SecretInEndpoint);
        }
    }
    if let Some((provider, suffix)) = credential_host {
        let host = url.host_str().unwrap_or_default();
        let allowed = if suffix.starts_with('.') {
            host.ends_with(suffix) && host.len() > suffix.len()
        } else {
            host == suffix || host.ends_with(&format!(".{suffix}"))
        };
        if !allowed {
            return Err(ConfigError::WrongCredentialHost {
                provider,
                host: host.to_owned(),
            });
        }
    }
    Ok(url)
}

pub(crate) fn authenticated_url(base: &Url, credential: Option<&LoadedCredential>) -> Url {
    let mut url = base.clone();
    if let Some(credential) = credential {
        url.query_pairs_mut()
            .append_pair("api-key", credential.expose());
    }
    url
}

fn origin(url: &Url) -> String {
    match url.port() {
        Some(port) => format!("{}://{}:{port}", url.scheme(), url.host_str().unwrap_or("")),
        None => format!("{}://{}", url.scheme(), url.host_str().unwrap_or("")),
    }
}

#[cfg(test)]
mod tests {
    use std::io::Write;

    use super::*;

    #[test]
    fn debug_never_contains_the_credential() {
        let mut file = tempfile::NamedTempFile::new().unwrap();
        file.write_all(b"super-secret-api-key\n").unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(file.path(), fs::Permissions::from_mode(0o600)).unwrap();
        }
        let config = HeliusConfig::mainnet(CredentialFile(file.path().to_owned()));
        let loaded = config.load().unwrap();
        let rendered = format!("{loaded:?}");
        assert!(!rendered.contains("super-secret-api-key"));
        assert!(rendered.contains("[REDACTED]"));
    }

    #[test]
    fn config_serializes_only_the_credential_path() {
        let config = HeliusConfig::mainnet(CredentialFile(PathBuf::from("/keys/helius")));
        let rendered = serde_json::to_string(&config).unwrap();
        assert!(rendered.contains("/keys/helius"));
        assert!(!rendered.contains("api-key="));
    }

    #[test]
    fn refuses_to_send_a_key_to_an_unexpected_host() {
        let mut config = HeliusConfig::mainnet(CredentialFile(PathBuf::from("unused")));
        config.http_url = "https://example.com".to_owned();
        assert!(matches!(
            config.load(),
            Err(ConfigError::WrongCredentialHost { .. })
        ));
    }

    #[test]
    fn credentialed_pumpportal_is_refused_for_authority_before_file_access() {
        let config = PumpPortalConfig {
            api_key_file: Some(CredentialFile(PathBuf::from("/does/not/exist"))),
            enable_metered_hot_scopes: true,
            ..PumpPortalConfig::default()
        };
        assert!(matches!(
            config.load(),
            Err(ConfigError::ForbiddenCredentialAuthority {
                provider: "PumpPortal"
            })
        ));
    }

    #[test]
    fn uncredentialed_pumpportal_runtime_is_classifier_only() {
        assert!(matches!(
            PumpPortalConfig::default().load(),
            Err(ConfigError::ProviderRuntimeDisabled {
                provider: "PumpPortal"
            })
        ));
    }
}
