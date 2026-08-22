//! Bounded read-only reconnaissance of a per-coin live tape.
//!
//! Connects to the keyless `PumpPortal` data endpoint, asks for one mint's trades, and reports
//! exactly what came back inside a hard wall-clock, frame and byte budget. It sends no credential,
//! constructs nothing, and signs nothing.

use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use futures_util::{SinkExt, StreamExt};
use tokio_tungstenite::tungstenite::Message;

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    let mint = flag(&arguments, "--mint").ok_or("usage: tape_probe --mint <mint> [--seconds n]")?;
    let seconds: u64 = flag(&arguments, "--seconds").map_or(Ok(30), |v| v.parse())?;
    let max_frames: usize = flag(&arguments, "--max-frames").map_or(Ok(400), |v| v.parse())?;
    let max_bytes: usize = flag(&arguments, "--max-bytes").map_or(Ok(4 * 1024 * 1024), |v| v.parse())?;

    // The key is read from a 0600 file, never from a flag, and is never printed. It is attached
    // only when explicitly asked for, because PumpPortal documents this credential as carrying
    // wallet-signing authority.
    let endpoint = match flag(&arguments, "--key-file") {
        None => "wss://pumpportal.fun/api/data".to_owned(),
        Some(path) => {
            let key = std::fs::read_to_string(path)?.trim().to_owned();
            format!("wss://pumpportal.fun/api/data?api-key={key}")
        }
    };
    let (mut socket, response) = tokio_tungstenite::connect_async(endpoint).await?;
    eprintln!("connected: http {}", response.status());
    let keys: Vec<&str> = mint.split(',').filter(|value| !value.is_empty()).collect();
    let subscribe = serde_json::json!({"method": "subscribeTokenTrade", "keys": keys});
    socket.send(Message::Text(subscribe.to_string().into())).await?;
    eprintln!("sent: {subscribe}");

    let deadline = Instant::now() + Duration::from_secs(seconds);
    let mut frames = 0usize;
    let mut bytes = 0usize;
    while frames < max_frames && bytes < max_bytes {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            eprintln!("stop: wall-clock budget");
            break;
        }
        match tokio::time::timeout(remaining, socket.next()).await {
            Err(_) => {
                eprintln!("stop: wall-clock budget");
                break;
            }
            Ok(None) => {
                eprintln!("stop: provider closed the socket after {frames} frames");
                break;
            }
            Ok(Some(Err(error))) => {
                eprintln!("stop: transport error: {error}");
                break;
            }
            Ok(Some(Ok(message))) => {
                let body = match message {
                    Message::Text(text) => text.as_bytes().to_vec(),
                    Message::Binary(binary) => binary.to_vec(),
                    Message::Close(frame) => {
                        eprintln!("stop: close frame {frame:?}");
                        break;
                    }
                    _ => continue,
                };
                frames += 1;
                bytes += body.len();
                println!(
                    "{} {} {}",
                    now_millis(),
                    body.len(),
                    String::from_utf8_lossy(&body)
                );
            }
        }
    }
    eprintln!("frames={frames} bytes={bytes}");
    Ok(())
}

fn flag(arguments: &[String], name: &str) -> Option<String> {
    arguments
        .iter()
        .position(|value| value == name)
        .and_then(|index| arguments.get(index + 1))
        .cloned()
}

fn now_millis() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_millis())
        .unwrap_or_default()
}
