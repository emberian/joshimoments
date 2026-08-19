//! Process-kill coordination for the executable G0 fault adapters.
//!
//! Normal in-process fault tests never arm this module. The hidden child-process command arms one
//! marker before entering a requested fault path; the exact matching boundary durably publishes
//! the marker and parks until its parent terminates the process.

use std::{
    fs::{self, File},
    io::Write as _,
    path::{Path, PathBuf},
    sync::OnceLock,
    thread,
};

static PROCESS_KILL_MARKER: OnceLock<PathBuf> = OnceLock::new();

pub(crate) fn arm_process_kill_marker(marker: &Path) -> std::io::Result<()> {
    if marker.exists() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::AlreadyExists,
            "G0 process-kill marker already exists",
        ));
    }
    PROCESS_KILL_MARKER
        .set(marker.to_path_buf())
        .map_err(|_| std::io::Error::other("G0 process-kill marker was already armed"))
}

pub(crate) fn pause_if_process_kill_armed(family: &str, point: &str) {
    let Some(marker) = PROCESS_KILL_MARKER.get() else {
        return;
    };
    publish_marker(marker, family, point).unwrap_or_else(|error| {
        panic!("failed to publish G0 process-kill marker: {error}");
    });
    loop {
        thread::park();
    }
}

fn publish_marker(marker: &Path, family: &str, point: &str) -> std::io::Result<()> {
    let parent = marker.parent().ok_or_else(|| {
        std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "G0 process-kill marker has no parent directory",
        )
    })?;
    fs::create_dir_all(parent)?;
    let temporary = marker.with_extension("tmp");
    let mut file = File::create(&temporary)?;
    writeln!(file, "{family}:{point}")?;
    file.sync_all()?;
    fs::rename(&temporary, marker)?;
    File::open(parent)?.sync_all()?;
    Ok(())
}
