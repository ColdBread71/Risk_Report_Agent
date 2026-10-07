"""Versioned run manifests and checked-upstream selection for Node [0]-[2]."""

from __future__ import annotations

import json
from hashlib import sha256
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.workflow_status import ASSET_REVIEWABLE_STATUSES


MANIFEST_SCHEMA_VERSION = "node_run_manifest.v1"
STAGE_MANIFEST_SCHEMA_VERSION = "staged_node_run_manifest.v2"
REGISTRY_SCHEMA_VERSION = "checked_upstream_registry.v1"

_STAGE_FILES = {
    "0": "progress/node_0_scope.json",
    "1": "progress/node_1_context.json",
    "2": "progress/node_2_assets.json",
}

_STAGED_FILES = {
    "0": ("node0.json", "node0.xlsx"),
    "1": ("node1.json", "node1.xlsx"),
    "2": ("node2.json", "node2.xlsx"),
}

_EXPECTED_STATUSES = {
    "0": "node_0_completed",
    "1": "node_1_completed",
    "2": "asset_identification_completed",
}


def _is_successful_status(node_id: str, status: str | None) -> bool:
    if node_id == "2":
        return status in ASSET_REVIEWABLE_STATUSES
    return status == _EXPECTED_STATUSES[node_id]


def _base_attempt_id(node_id: str) -> str:
    return f"node{node_id}"


def _migrate_stage_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert the single-record v1 layout to append-only attempts in memory."""
    version = payload.get("schema_version")
    if version == STAGE_MANIFEST_SCHEMA_VERSION:
        return payload
    if version != "staged_node_run_manifest.v1":
        raise ValueError("Unsupported stage manifest schema")

    migrated_stages: dict[str, Any] = {}
    for node_key, record in payload.get("stages", {}).items():
        node_id = node_key.removeprefix("node_")
        attempt = dict(record)
        attempt_id = Path(attempt["output_json"]).stem
        successful = _is_successful_status(node_id, attempt.get("status"))
        attempt.update(
            attempt_id=attempt_id,
            attempt_number=0,
            selected_for_downstream=successful,
            downstream_usable=successful,
            business_reviewed=False,
        )
        migrated_stages[node_key] = {
            "selected_attempt": attempt_id if successful else None,
            "downstream_status": "draft_eligible" if successful else "unavailable",
            "attempts": [attempt],
        }
    payload["schema_version"] = STAGE_MANIFEST_SCHEMA_VERSION
    payload["stages"] = migrated_stages
    return payload


def _stage_group(payload: dict[str, Any], node_id: str) -> dict[str, Any]:
    return payload.setdefault("stages", {}).setdefault(
        f"node_{node_id}",
        {
            "selected_attempt": None,
            "downstream_status": "unavailable",
            "attempts": [],
        },
    )


def _find_attempt(group: dict[str, Any], attempt_id: str | None) -> dict[str, Any]:
    attempts = group.get("attempts", [])
    if attempt_id is None and attempts:
        return attempts[-1]
    for attempt in attempts:
        if attempt.get("attempt_id") == attempt_id:
            return attempt
    raise ValueError(f"Unknown stage attempt: {attempt_id}")


def _next_attempt_id(run_directory: Path, node_id: str, attempts: list[dict[str, Any]]) -> tuple[str, int]:
    base = _base_attempt_id(node_id)
    used = {str(item.get("attempt_id")) for item in attempts}
    number = 0
    while True:
        attempt_id = base if number == 0 else f"{base}_{number}"
        if (
            attempt_id not in used
            and not (run_directory / f"{attempt_id}.json").exists()
            and not (run_directory / f"{attempt_id}.xlsx").exists()
        ):
            return attempt_id, number
        number += 1


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def prepare_stage_manifest(
    *,
    run_directory: Path,
    run_id: str,
    project_id: str,
    evidence_packet_ref: dict[str, Any],
    text_model: str,
    node_id: str,
    rule_versions: dict[str, str],
    upstream: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
) -> tuple[Path, str]:
    """Prepare one append-only attempt and return its manifest path and artifact stem."""
    if node_id not in _STAGED_FILES:
        raise ValueError(f"Unsupported staged node: {node_id}")
    path = run_directory / "stage_manifest.json"
    run_directory.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        payload = _migrate_stage_manifest(json.loads(path.read_text(encoding="utf-8")))
        if payload.get("run_id") != run_id or payload.get("project_id") != project_id:
            raise ValueError("Stage manifest run or project identity does not match")
        saved_packet = payload.get("evidence_packet_ref", {}).get("packet_sha256")
        if saved_packet != evidence_packet_ref.get("packet_sha256"):
            raise ValueError("Stage manifest evidence packet does not match")
    else:
        created_at = _now()
        payload = {
            "schema_version": STAGE_MANIFEST_SCHEMA_VERSION,
            "run_id": run_id,
            "project_id": project_id,
            "created_at": created_at,
            "updated_at": created_at,
            "evidence_packet_ref": evidence_packet_ref,
            "stages": {},
        }

    group = _stage_group(payload, node_id)
    attempt_id, attempt_number = _next_attempt_id(run_directory, node_id, group["attempts"])
    output_json, output_excel = f"{attempt_id}.json", f"{attempt_id}.xlsx"

    prepared_at = _now()
    group["attempts"].append({
        "attempt_id": attempt_id,
        "attempt_number": attempt_number,
        "status": "prepared",
        "prepared_at": prepared_at,
        "generated_at": None,
        "text_model": text_model,
        "rule_versions": rule_versions,
        "upstream": upstream or {},
        "provenance": provenance or {},
        "output_json": output_json,
        "output_excel": output_excel,
        "output_json_sha256": None,
        "output_excel_sha256": None,
        "selected_for_downstream": False,
        "downstream_usable": False,
        "business_reviewed": False,
    })
    payload["updated_at"] = prepared_at
    _atomic_write(path, payload)
    return path, attempt_id


def record_stage_status(
    run_directory: Path,
    node_id: str,
    status: str,
    awaiting_review: bool = False,
    attempt_id: str | None = None,
) -> None:
    """Update runtime status for one attempt without touching run_manifest.json."""
    path = run_directory / "stage_manifest.json"
    payload = _migrate_stage_manifest(json.loads(path.read_text(encoding="utf-8")))
    record = _find_attempt(_stage_group(payload, node_id), attempt_id)
    record["status"] = status
    record["awaiting_asset_approval"] = awaiting_review
    record["updated_at"] = _now()
    payload["updated_at"] = record["updated_at"]
    _atomic_write(path, payload)


def record_stage_result(
    *,
    run_directory: Path,
    node_id: str,
    status: str,
    completed_node: str,
    attempt_id: str | None = None,
) -> Path:
    """Finalize one attempt and select the latest successful result for draft downstream use."""
    path = run_directory / "stage_manifest.json"
    payload = _migrate_stage_manifest(json.loads(path.read_text(encoding="utf-8")))
    group = _stage_group(payload, node_id)
    record = _find_attempt(group, attempt_id)
    json_path = run_directory / record["output_json"]
    excel_path = run_directory / record["output_excel"]
    if not json_path.is_file() or not excel_path.is_file():
        raise ValueError("Staged node is missing its JSON or Excel artifact")
    generated_at = _now()
    record.update(
        status=status,
        completed_node=completed_node,
        generated_at=generated_at,
        output_json_sha256=_file_sha256(json_path),
        output_excel_sha256=_file_sha256(excel_path),
    )
    if _is_successful_status(node_id, status):
        for candidate in group["attempts"]:
            candidate["selected_for_downstream"] = False
        record["selected_for_downstream"] = True
        record["downstream_usable"] = True
        group["selected_attempt"] = record["attempt_id"]
        group["downstream_status"] = "draft_eligible"
    else:
        record["downstream_usable"] = False
        if group.get("selected_attempt") is None:
            group["downstream_status"] = "unavailable"
    payload["updated_at"] = generated_at
    _atomic_write(path, payload)
    return path


def load_stage_upstream(
    *,
    run_directory: Path,
    upstream_node_id: str,
    expected_packet_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the exact preceding artifact from the same version directory."""
    path = run_directory / "stage_manifest.json"
    if not path.is_file():
        raise ValueError(f"No stage manifest exists: {path}")
    payload = _migrate_stage_manifest(json.loads(path.read_text(encoding="utf-8")))
    node_key = f"node_{upstream_node_id}"
    group = payload.get("stages", {}).get(node_key)
    if group is None or group.get("downstream_status") != "draft_eligible":
        raise ValueError(f"No completed {node_key} exists in this version directory")
    record = _find_attempt(group, group.get("selected_attempt"))
    if (
        not _is_successful_status(upstream_node_id, record.get("status"))
        or not record.get("downstream_usable")
        or not record.get("selected_for_downstream")
    ):
        raise ValueError(f"Selected {node_key} attempt is not eligible for downstream use")
    snapshot_path = run_directory / record["output_json"]
    if not snapshot_path.is_file() or _file_sha256(snapshot_path) != record.get("output_json_sha256"):
        raise ValueError(f"Staged upstream hash does not match for {node_key}")
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if snapshot.get("run_id") != payload.get("run_id"):
        raise ValueError("Staged upstream run identity does not match")
    state = snapshot.get("state", {})
    packet_ref = state.get("evidence_packet_ref") or {}
    if packet_ref.get("packet_sha256") != expected_packet_sha256:
        raise ValueError("Staged upstream evidence packet does not match")
    return state, {
        "run_id": payload["run_id"],
        "attempt_id": record["attempt_id"],
        "output_json": record["output_json"],
        "output_json_sha256": record["output_json_sha256"],
        "generated_at": record["generated_at"],
        "downstream_status": group["downstream_status"],
        "business_reviewed": record.get("business_reviewed", False),
    }


def initialize_run_manifest(
    *,
    run_directory: Path,
    run_id: str,
    project_id: str,
    evidence_packet_ref: dict[str, Any],
    text_model: str,
    requested_node: str,
    rule_versions: dict[str, str],
    upstream: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
) -> Path:
    """Create the immutable run identity before executing a business node."""
    path = run_directory / "run_manifest.json"
    if path.exists() or (run_directory.exists() and any(run_directory.iterdir())):
        raise ValueError(f"Run manifest already exists; choose a new run-id: {path}")
    created_at = _now()
    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "run_id": run_id,
        "project_id": project_id,
        "created_at": created_at,
        "updated_at": created_at,
        "requested_node": requested_node,
        "evidence_packet_ref": evidence_packet_ref,
        "text_model": text_model,
        "rule_versions": rule_versions,
        "upstream": upstream or {},
        "nodes": {},
        "provenance": provenance or {},
    }
    _atomic_write(path, payload)
    return path


def record_node_result(
    *,
    run_directory: Path,
    node_id: str,
    status: str,
    completed_node: str,
) -> Path:
    """Record one generated node artifact without marking it business-checked."""
    manifest_path = run_directory / "run_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    stage_json = "report.json" if (run_directory / "report.json").exists() else _STAGE_FILES[node_id]
    stage_excel = stage_json.removesuffix(".json") + ".xlsx"
    if status in {"node_0_completed", "node_1_completed"} or status in ASSET_REVIEWABLE_STATUSES:
        if not all((run_directory / name).is_file() for name in (stage_json, stage_excel)):
            raise ValueError("Completed node is missing its JSON or Excel artifact")
    payload["nodes"][f"node_{node_id}"] = {
        "status": status,
        "completed_node": completed_node,
        "generated_at": _now(),
        "output_json": stage_json,
        "output_excel": stage_excel,
        "checked_usable": False,
        "checked_at": None,
    }
    payload["updated_at"] = _now()
    _atomic_write(manifest_path, payload)
    return manifest_path


def record_run_status(run_directory: Path, status: str, awaiting_review: bool = False) -> None:
    """Keep one compact manifest for full and single-node runs alike."""
    path = run_directory / "run_manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(
        status=status,
        awaiting_asset_approval=awaiting_review,
        business_reviewed=False,
        output_json="report.json",
        output_excel="report.xlsx",
        updated_at=_now(),
    )
    _atomic_write(path, payload)


def _registry_path(project_output_directory: Path) -> Path:
    return project_output_directory / "checked_upstreams.json"


def mark_node_checked(
    *,
    project_output_directory: Path,
    run_id: str,
    node_id: str,
) -> tuple[Path, Path]:
    """Mark a reviewed node usable and invalidate checked downstream pointers."""
    run_directory = project_output_directory / run_id
    manifest_path = run_directory / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    node_key = f"node_{node_id}"
    node_record = manifest.get("nodes", {}).get(node_key)
    if node_record is None:
        raise ValueError(f"Run {run_id} has no generated {node_key} output")
    if not _is_successful_status(node_id, node_record.get("status")):
        raise ValueError("An incomplete or failed node cannot be marked checked usable")
    output_json = run_directory / node_record["output_json"]
    output_excel = run_directory / node_record["output_excel"]
    if not output_json.is_file() or not output_excel.is_file():
        raise ValueError(f"Run {run_id} is missing the JSON or Excel artifact for {node_key}")

    registry_path = _registry_path(project_output_directory)
    if registry_path.is_file():
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    else:
        registry = {
            "schema_version": REGISTRY_SCHEMA_VERSION,
            "project_id": manifest["project_id"],
            "updated_at": _now(),
            "nodes": {},
        }

    required_upstream = {"1": "node_0", "2": "node_1"}.get(node_id)
    if required_upstream is not None:
        expected = registry.get("nodes", {}).get(required_upstream)
        actual = manifest.get("upstream", {}).get(required_upstream)
        if expected is None or expected.get("requires_revalidation"):
            raise ValueError(f"No currently checked usable {required_upstream} is registered")
        if actual is None or actual.get("run_id") != expected.get("run_id"):
            raise ValueError(
                f"{node_key} was not generated from the currently checked {required_upstream}"
            )

    checked_at = _now()
    node_record["checked_usable"] = True
    node_record["checked_at"] = checked_at
    manifest["updated_at"] = checked_at
    _atomic_write(manifest_path, manifest)

    registry.setdefault("nodes", {})[node_key] = {
        "run_id": run_id,
        "manifest": f"{run_id}/run_manifest.json",
        "output_json": f"{run_id}/{node_record['output_json']}",
        "output_excel": f"{run_id}/{node_record['output_excel']}",
        "checked_at": checked_at,
        "checked_usable": True,
        "requires_revalidation": False,
    }
    for downstream_id in range(int(node_id) + 1, 3):
        downstream_key = f"node_{downstream_id}"
        previous = registry["nodes"].get(downstream_key)
        if previous is not None:
            previous["checked_usable"] = False
            previous["requires_revalidation"] = True
            previous["invalidated_by"] = {"node_id": node_key, "run_id": run_id}
    registry["updated_at"] = checked_at
    _atomic_write(registry_path, registry)
    return manifest_path, registry_path


def load_checked_upstream(
    *,
    project_output_directory: Path,
    upstream_node_id: str,
    expected_packet_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the latest explicitly checked upstream snapshot, never a latest-named file."""
    registry_path = _registry_path(project_output_directory)
    if not registry_path.is_file():
        raise ValueError(f"No checked upstream registry exists: {registry_path}")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    node_key = f"node_{upstream_node_id}"
    pointer = registry.get("nodes", {}).get(node_key)
    if (
        pointer is None
        or not pointer.get("checked_usable")
        or pointer.get("requires_revalidation")
    ):
        raise ValueError(f"No checked usable {node_key} output is registered")
    snapshot_path = project_output_directory / pointer["output_json"]
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    state = snapshot.get("state", {})
    packet_ref = state.get("evidence_packet_ref") or {}
    if packet_ref.get("packet_sha256") != expected_packet_sha256:
        raise ValueError("Checked upstream evidence packet does not match this run")
    return state, {
        "run_id": pointer["run_id"],
        "output_json": pointer["output_json"],
        "checked_at": pointer["checked_at"],
    }


__all__ = [
    "initialize_run_manifest",
    "load_stage_upstream",
    "load_checked_upstream",
    "mark_node_checked",
    "prepare_stage_manifest",
    "record_node_result",
    "record_stage_result",
    "record_stage_status",
]
