"""Immutable calibration results and explicit selection of historical runs."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import shutil
import subprocess
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from time import perf_counter
from typing import Any, cast
from uuid import uuid4

import pandas as pd


def read_json(path: Path) -> dict[str, Any]:
    """Read a JSON object without creating files."""
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        msg = f"Expected an object in {path}"
        raise TypeError(msg)
    return cast("dict[str, Any]", value)


def write_json(path: Path, value: dict[str, Any]) -> None:
    """Replace one JSON file atomically on the same filesystem."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def file_hash(path: Path) -> str:
    """Hash persisted bytes to detect accidental changes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def provenance() -> dict[str, Any]:
    """Describe installed code, including uncommitted package source."""
    package = Path(__file__).parent
    digest = hashlib.sha256()
    for path in sorted(package.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    versions: dict[str, str | None] = {}
    for name in ("cn3s", "numpy", "pandas", "scipy", "pyarrow", "merge-downloader"):
        try:
            versions[name] = version(name)
        except PackageNotFoundError:  # noqa: PERF203
            versions[name] = None
    try:
        revision = subprocess.run(  # noqa: S603
            [shutil.which("git") or "/usr/bin/git", "rev-parse", "HEAD"],
            cwd=package,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        revision = None
    return {
        "git_revision": revision,
        "source_sha256": digest.hexdigest(),
        "python": platform.python_version(),
        "versions": versions,
    }


class CalibrationStore:
    """Save immutable runs; keep legacy artifacts and selection pointers separate."""

    def __init__(self, data_root: str | Path = "/data/CN3S") -> None:
        """Use a local data root without loading providers."""
        self.data_root = Path(data_root)

    @staticmethod
    def new_id() -> str:
        """Generate a sortable, collision-resistant run identifier."""
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:8]

    def folder(self, station_code: str | int, frequency: str) -> Path:
        """Validate station and frequency before forming a path."""
        if not str(station_code).isdecimal() or frequency not in ("D", "M"):
            msg = "Station must be numeric and frequency must be D or M"
            raise ValueError(msg)
        return self.data_root / "stations" / str(station_code) / "calibration" / frequency

    @staticmethod
    def _validate_id(run_id: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}", run_id):
            msg = "Invalid run ID"
            raise ValueError(msg)

    def resolve(self, station_code: str | int, frequency: str, run_id: str = "latest") -> Path:
        """Resolve a pointer or explicit run; fall back to legacy only without a pointer."""
        root = self.folder(station_code, frequency)
        self._validate_id(run_id)
        if run_id in ("latest", "selected"):
            pointer = root / f"{run_id}.json"
            if pointer.exists():
                run_id = str(read_json(pointer)["run_id"])
                self._validate_id(run_id)
            elif run_id == "latest" and (root / "summary.json").exists():
                run_id = "legacy"
            else:
                raise FileNotFoundError(pointer)
        return root if run_id == "legacy" else root / "runs" / run_id

    def load(
        self, station_code: str | int, frequency: str, run_id: str = "latest"
    ) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, Path]:
        """Validate a completed bundle and return summary, modeled data and history."""
        path = self.resolve(station_code, frequency, run_id)
        for name in ("summary.json", "modeled.parquet", "history.parquet"):
            if not (path / name).is_file():
                msg = f"Calibration artifacts missing: {path / name}"
                raise FileNotFoundError(msg)
        summary = read_json(path / "summary.json")
        if (
            summary.get("station_code") != str(station_code)
            or summary.get("frequency") != frequency
            or summary.get("status") not in ("completed", "manual", "interrupted")
        ):
            msg = "Calibration identity does not match requested station and frequency"
            raise ValueError(msg)
        legacy = path == self.folder(station_code, frequency)
        if not legacy:
            manifest = read_json(path / "manifest.json")
            if (
                manifest.get("schema_version") != 1
                or manifest.get("run_id") != path.name
                or manifest.get("status") != summary.get("status")
                or summary.get("run_id") != path.name
            ):
                msg = "Invalid calibration manifest identity or schema"
                raise ValueError(msg)
            hashes = manifest.get("sha256", {})
            required = {
                "summary.json",
                "modeled.parquet",
                "history.parquet",
                "inputs/rain.parquet",
                "inputs/discharge.parquet",
                "inputs/metadata.json",
            }
            if not required.issubset(hashes):
                msg = "Incomplete calibration manifest"
                raise ValueError(msg)
            for name, expected in hashes.items():
                target = path / name
                if not target.resolve().is_relative_to(path.resolve()):
                    msg = "Invalid manifest artifact path"
                    raise ValueError(msg)
                if not target.is_file() or file_hash(target) != expected:
                    msg = f"Calibration artifact checksum mismatch: {name}"
                    raise ValueError(msg)
        summary = dict(summary, run_id="legacy" if legacy else path.name)
        modeled = pd.read_parquet(path / "modeled.parquet")
        if (
            not {"q_m3s", "obs_q_m3s"}.issubset(modeled.columns)
            or modeled.empty
            or not isinstance(modeled.index, pd.DatetimeIndex)
            or modeled.index.has_duplicates
            or not modeled.index.is_monotonic_increasing
        ):
            msg = "Invalid modeled discharge schema or dates"
            raise ValueError(msg)
        return summary, modeled, pd.read_parquet(path / "history.parquet"), path

    def list_runs(self, station_code: str | int, frequency: str) -> pd.DataFrame:
        """List stored runs, including damaged bundles without hiding their identity."""
        root = self.folder(station_code, frequency)
        ids = [p.name for p in sorted((root / "runs").glob("*")) if p.is_dir()]
        if (root / "summary.json").exists():
            ids.insert(0, "legacy")
        rows: list[dict[str, Any]] = []
        for run_id in ids:
            try:
                summary, _, _, _ = self.load(station_code, frequency, run_id)
                rows.append(
                    {
                        key: summary.get(key)
                        for key in (
                            "run_id",
                            "label",
                            "kind",
                            "status",
                            "created_at",
                            "input_revision",
                            "warmup_steps",
                            "objective",
                            "train_nse",
                            "test_nse",
                            "converged",
                        )
                    }
                )
            except (OSError, ValueError, KeyError, TypeError) as exc:  # noqa: PERF203
                rows.append({"run_id": run_id, "status": "unreadable", "error": str(exc)})
        return pd.DataFrame(rows)

    def select(self, station_code: str | int, frequency: str, run_id: str) -> None:
        """Explicitly select a completed calibration for downstream consumers."""
        summary, _, _, _ = self.load(station_code, frequency, run_id)
        if (
            summary.get("status") != "completed"
            or summary.get("kind", "calibration") != "calibration"
        ):
            msg = "Only a completed calibration can be selected"
            raise ValueError(msg)
        write_json(
            self.folder(station_code, frequency) / "selected.json", {"run_id": summary["run_id"]}
        )

    def save(
        self,
        summary: dict[str, Any],
        modeled: pd.DataFrame,
        history: pd.DataFrame,
        rain: pd.Series,
        discharge: pd.Series,
        metadata: dict[str, Any],
        *,
        run_id: str | None = None,
        watershed_bytes: bytes | None = None,
        copy_current_watershed: bool = True,
    ) -> dict[str, Any]:
        """Commit a new bundle before moving latest; never overwrite a saved run."""
        started = perf_counter()
        run_id = run_id or self.new_id()
        self._validate_id(run_id)
        if run_id in ("legacy", "latest", "selected"):
            msg = "Reserved run ID"
            raise ValueError(msg)
        root = self.folder(summary["station_code"], summary["frequency"])
        target = root / "runs" / run_id
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = root / f".staging-{run_id}-{uuid4().hex}"
        stage.mkdir()
        saved = dict(summary, run_id=run_id, created_at=datetime.now(timezone.utc).isoformat())
        saved.setdefault("kind", "calibration")
        try:
            if saved.get("status") not in ("completed", "manual", "interrupted"):
                msg = "Only terminal simulation results can be committed"
                raise ValueError(msg)
            inputs = stage / "inputs"
            inputs.mkdir()
            rain.rename("prec").to_frame().to_parquet(inputs / "rain.parquet")
            discharge.rename("Vazao").to_frame().to_parquet(inputs / "discharge.parquet")
            write_json(inputs / "metadata.json", metadata)
            watershed = root.parent.parent / "watershed.parquet"
            if watershed_bytes is not None:
                (inputs / "watershed.parquet").write_bytes(watershed_bytes)
            elif copy_current_watershed and watershed.exists():
                shutil.copyfile(watershed, inputs / "watershed.parquet")
            modeled.to_parquet(stage / "modeled.parquet")
            history.drop(columns=["params"], errors="ignore").to_parquet(stage / "history.parquet")
            saved["artifact_data_write_seconds"] = perf_counter() - started
            write_json(stage / "summary.json", saved)
            manifest = {
                "schema_version": 1,
                "run_id": run_id,
                "status": saved["status"],
                "provenance": provenance(),
                "sha256": {
                    str(p.relative_to(stage)): file_hash(p)
                    for p in sorted(stage.rglob("*"))
                    if p.is_file()
                },
            }
            write_json(stage / "manifest.json", manifest)
            if target.exists():
                msg = f"Run already exists: {run_id}"
                raise FileExistsError(msg)
            stage.rename(target)
            if saved["status"] == "completed" and saved["kind"] == "calibration":
                write_json(root / "latest.json", {"run_id": run_id})
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        return saved

    def attempt_path(self, station_code: str | int, frequency: str, run_id: str) -> Path:
        """Return the mutable attempt/recovery record, outside immutable run bundles."""
        self._validate_id(run_id)
        return self.folder(station_code, frequency) / "attempts" / f"{run_id}.json"

    def list_attempts(self, station_code: str | int, frequency: str) -> pd.DataFrame:
        """Inspect running, failed, interrupted and completed calibration attempts."""
        return pd.DataFrame(
            [
                read_json(p)
                for p in sorted((self.folder(station_code, frequency) / "attempts").glob("*.json"))
            ]
        )
