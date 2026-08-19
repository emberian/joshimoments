//! Abrupt child-termination coordination for the executable G0 fault adapters.
//!
//! Normal in-process fault tests never arm this module. The hidden child-process command arms one
//! marker before entering a requested fault path; the exact matching boundary durably publishes
//! the marker and either parks for an external kill or triggers a real Rust panic.

use std::{
    fs::{self, File},
    io::Write as _,
    path::{Path, PathBuf},
    sync::OnceLock,
    thread,
};

#[derive(Clone, Copy)]
enum ArmedTermination {
    ProcessKill,
    Panic,
}

struct ArmedFault {
    marker: PathBuf,
    termination: ArmedTermination,
}

static ARMED_FAULT: OnceLock<ArmedFault> = OnceLock::new();

pub(crate) fn arm_process_kill_marker(marker: &Path) -> std::io::Result<()> {
    arm_marker(marker, ArmedTermination::ProcessKill)
}

pub(crate) fn arm_panic_marker(marker: &Path) -> std::io::Result<()> {
    arm_marker(marker, ArmedTermination::Panic)
}

fn arm_marker(marker: &Path, termination: ArmedTermination) -> std::io::Result<()> {
    if marker.exists() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::AlreadyExists,
            "G0 abrupt-termination marker already exists",
        ));
    }
    ARMED_FAULT
        .set(ArmedFault {
            marker: marker.to_path_buf(),
            termination,
        })
        .map_err(|_| std::io::Error::other("G0 abrupt-termination marker was already armed"))
}

pub(crate) fn pause_if_process_kill_armed(family: &str, point: &str) {
    let Some(armed) = ARMED_FAULT.get() else {
        return;
    };
    publish_marker(&armed.marker, family, point).unwrap_or_else(|error| {
        panic!("failed to publish G0 abrupt-termination marker: {error}");
    });
    match armed.termination {
        ArmedTermination::ProcessKill => loop {
            thread::park();
        },
        ArmedTermination::Panic => {
            panic!("intentional G0 child panic after durable boundary marker")
        }
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
