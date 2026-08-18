use joshi_export::rewrite_snapshot_v1;
use std::{env, path::PathBuf};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|path| path.parent())
        .ok_or("crate has no repository root")?
        .to_owned();
    let source = root.join("analysis/fixtures/snapshot_v1");
    let destination = env::args_os().nth(1).map_or_else(
        || root.join("fixtures/export/rust_snapshot_v1"),
        PathBuf::from,
    );
    let snapshot = rewrite_snapshot_v1(&source, &destination)?;
    println!("{}", snapshot.snapshot_id());
    Ok(())
}
