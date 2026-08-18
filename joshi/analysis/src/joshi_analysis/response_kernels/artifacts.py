from __future__ import annotations

import os
import platform
import tempfile
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from .. import __version__
from ..canonical import (
    canonical_json_bytes,
    logical_table_sha256,
    qualified_sha256_bytes,
    qualified_sha256_file,
    schema_descriptor,
    schema_sha256,
)
from ..errors import ImmutableOutputError


def analysis_root() -> Path:
    return Path(__file__).resolve().parents[3]


def environment_manifest() -> dict[str, Any]:
    package_root = Path(__file__).resolve().parents[1]
    source_parts: list[bytes] = []
    for path in sorted(package_root.rglob("*.py")):
        relative = path.relative_to(package_root).as_posix()
        source_parts.append(relative.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    lock_path = analysis_root() / "uv.lock"
    return {
        "package_version": __version__,
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "duckdb": duckdb.__version__,
        "pyarrow": pa.__version__,
        "uv_lock_digest": qualified_sha256_file(lock_path),
        "source_tree_digest": qualified_sha256_bytes(b"".join(source_parts)),
    }


def _write_table(table: pa.Table, path: Path) -> None:
    pq.write_table(
        table,
        path,
        compression="zstd",
        use_dictionary=False,
        write_statistics=True,
        data_page_version="1.0",
        version="2.6",
        row_group_size=max(1, table.num_rows),
    )


def publish_bundle(
    output_root: str | Path,
    *,
    prefix: str,
    id_field: str,
    preimage: dict[str, Any],
    artifacts: list[tuple[str, str, pa.Table, list[str]]],
) -> Path:
    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(tempfile.mkdtemp(prefix=f".joshi-{prefix}-", dir=output))
    try:
        artifact_manifests: list[dict[str, Any]] = []
        for filename, schema_id, table, primary_key in artifacts:
            path = temporary_root / filename
            _write_table(table, path)
            artifact_manifests.append(
                {
                    "path": filename,
                    "schema_id": schema_id,
                    "schema": schema_descriptor(table.schema),
                    "schema_digest": schema_sha256(table.schema),
                    "physical_digest": qualified_sha256_file(path),
                    "logical_digest": logical_table_sha256(table, primary_key),
                    "row_count": table.num_rows,
                    "primary_key": primary_key,
                }
            )
        complete_preimage = {**preimage, "artifacts": artifact_manifests}
        identity = qualified_sha256_bytes(canonical_json_bytes(complete_preimage))
        manifest_bytes = canonical_json_bytes(
            {**complete_preimage, id_field: identity}, newline=True
        )
        (temporary_root / "manifest.json").write_bytes(manifest_bytes)
        run_dir = output / f"{prefix}-{identity.removeprefix('sha256:')}"
        if run_dir.exists():
            expected_paths = {"manifest.json", *(item[0] for item in artifacts)}
            if {path.name for path in run_dir.iterdir()} != expected_paths:
                raise ImmutableOutputError(f"artifact closure differs for existing run: {run_dir}")
            if (run_dir / "manifest.json").read_bytes() != manifest_bytes:
                raise ImmutableOutputError(f"artifact manifest differs for existing run: {run_dir}")
            for filename, _, _, _ in artifacts:
                current = qualified_sha256_file(run_dir / filename)
                staged = qualified_sha256_file(temporary_root / filename)
                if current != staged:
                    raise ImmutableOutputError(f"artifact differs for existing run: {filename}")
            return run_dir
        os.replace(temporary_root, run_dir)
        return run_dir
    finally:
        if temporary_root.exists():
            for child in temporary_root.iterdir():
                child.unlink()
            temporary_root.rmdir()
