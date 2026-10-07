"""Load source-bound evidence packets and reject fabricated model citations."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from pydantic import BaseModel

from core.logger import setup_logger
from schemas.document import DocumentBlock
from schemas.evidence import EvidenceRef
from schemas.evidence_packet import EvidencePacket, EvidencePacketDocument
from schemas.run_input import EvidencePacketRef


logger = setup_logger("evidence_input")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(path: str | Path, workspace: Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    return candidate.resolve()


def _normalized_path(path: str | Path) -> str:
    return str(path).replace("\\", "/").removeprefix("./").casefold()


def _normalized_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class EvidencePacketBinding:
    """Validated packet plus lookup maps used at LLM trust boundaries."""

    packet_path: Path
    packet: EvidencePacket
    reference: EvidencePacketRef
    documents: dict[str, EvidencePacketDocument]
    blocks: dict[str, DocumentBlock]


def bind_materialized_packet(
    packet: EvidencePacket,
    *,
    packet_path: str | Path = "<in-memory-evidence-packet>",
) -> EvidencePacketBinding:
    """Create an in-memory binding for an already validated materialized packet."""
    packet_bytes = (
        json.dumps(
            packet.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    documents = {document.document_id: document for document in packet.documents}
    reference = EvidencePacketRef(
        packet_id=packet.packet_id,
        packet_version=packet.packet_version,
        project_id=packet.project_id,
        packet_sha256=hashlib.sha256(packet_bytes).hexdigest(),
        manifest_sha256=packet.manifest_sha256,
        config_sha256=packet.config_sha256,
        parser_name=packet.parser_name,
        parser_version=packet.parser_version,
        document_ids=tuple(document.document_id for document in packet.documents),
        block_count=len(packet.blocks),
    )
    return EvidencePacketBinding(
        packet_path=Path(packet_path),
        packet=packet,
        reference=reference,
        documents=documents,
        blocks={block.block_id: block for block in packet.blocks},
    )


def render_evidence_material(binding: EvidencePacketBinding) -> str:
    """Render compact source text with unambiguous document/block anchors."""
    packet = binding.packet
    lines = [
        f"[PACKET {packet.packet_id} v{packet.packet_version}]",
        f"Project: {packet.project_id}",
        "Use only this evidence. Preserve unknowns and copy citation anchors exactly.",
        "",
        "[KNOWN GAPS]",
    ]
    lines.extend(
        f"- {gap.gap_id}: {gap.description} Disposition: {gap.disposition}"
        for gap in packet.known_gaps
    )

    current_document_id: str | None = None
    current_location: tuple[str, int, str | None, tuple[str, ...]] | None = None
    for block in packet.blocks:
        document = binding.documents[block.document_id]
        if block.document_id != current_document_id:
            current_document_id = block.document_id
            current_location = None
            lines.extend(
                [
                    "",
                    f"[DOCUMENT {document.document_id}]",
                    f"file_name: {document.source_file_name}",
                    f"file_path: {document.source_path}",
                    f"file_type: {Path(document.source_file_name).suffix.lstrip('.').lower()}",
                    f"source_sha256: {document.source_sha256}",
                    f"parser_version: {document.parser_version}",
                ]
            )

        location = (
            block.document_id,
            block.pdf_page,
            block.printed_page_label,
            tuple(block.section_path),
        )
        if location != current_location:
            current_location = location
            printed = block.printed_page_label if block.printed_page_label is not None else "null"
            lines.extend(
                [
                    "",
                    f"[LOCATION page={block.pdf_page}; printed_page={printed}; "
                    f"section={' > '.join(block.section_path)}]",
                ]
            )
        lines.append(f"[{block.block_id}] {block.text}")
    return "\n".join(lines).rstrip() + "\n"


def load_evidence_packet(
    packet_path: str | Path,
    *,
    workspace: str | Path | None = None,
    verify_source_files: bool = True,
) -> EvidencePacketBinding:
    """Load a packet, verify its manifest/sources, and create a compact state reference."""
    workspace_path = Path(workspace).resolve() if workspace is not None else Path.cwd().resolve()
    resolved_packet = _resolve(packet_path, workspace_path)
    if not resolved_packet.is_file():
        raise FileNotFoundError(f"Evidence packet does not exist: {resolved_packet}")

    packet_bytes = resolved_packet.read_bytes()
    packet = EvidencePacket.model_validate_json(packet_bytes)

    manifest_path = _resolve(packet.manifest_path, workspace_path)
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Evidence packet manifest does not exist: {manifest_path}")
    if _sha256(manifest_path) != packet.manifest_sha256:
        raise ValueError("Evidence packet manifest hash does not match the current file")

    documents = {document.document_id: document for document in packet.documents}
    if verify_source_files:
        for document in packet.documents:
            source_path = _resolve(document.source_path, workspace_path)
            if not source_path.is_file():
                raise FileNotFoundError(f"Evidence source does not exist: {source_path}")
            if _sha256(source_path) != document.source_sha256:
                raise ValueError(f"Evidence source hash mismatch: {document.document_id}")

    reference = EvidencePacketRef(
        packet_id=packet.packet_id,
        packet_version=packet.packet_version,
        project_id=packet.project_id,
        packet_sha256=hashlib.sha256(packet_bytes).hexdigest(),
        manifest_sha256=packet.manifest_sha256,
        config_sha256=packet.config_sha256,
        parser_name=packet.parser_name,
        parser_version=packet.parser_version,
        document_ids=tuple(document.document_id for document in packet.documents),
        block_count=len(packet.blocks),
    )
    return EvidencePacketBinding(
        packet_path=resolved_packet,
        packet=packet,
        reference=reference,
        documents=documents,
        blocks={block.block_id: block for block in packet.blocks},
    )


def validate_evidence_ref(evidence: EvidenceRef, binding: EvidencePacketBinding) -> EvidenceRef:
    """Require one model-produced evidence reference to resolve exactly to the packet."""
    source = evidence.source
    if source.document_id is None or source.block_id is None:
        raise ValueError(f"Evidence {evidence.evidence_id} must include document_id and block_id")

    document = binding.documents.get(source.document_id)
    block = binding.blocks.get(source.block_id)
    if document is None or block is None:
        raise ValueError(f"Evidence {evidence.evidence_id} references content outside the evidence packet")
    if block.document_id != document.document_id:
        raise ValueError(f"Evidence {evidence.evidence_id} has inconsistent document and block identifiers")

    expected_file_type = Path(document.source_file_name).suffix.lstrip(".").casefold()
    checks = {
        "file_name": source.file_name == document.source_file_name,
        "file_path": _normalized_path(source.file_path) == _normalized_path(document.source_path),
        "file_type": source.file_type.lstrip(".").casefold() == expected_file_type,
        "hash_sha256": source.hash_sha256 == document.source_sha256 == block.source_sha256,
        "parser_version": source.parser_version == document.parser_version == block.parser_version,
        "page_number": source.page_number == block.pdf_page,
        "printed_page_label": source.printed_page_label == block.printed_page_label,
        "section_path": source.section_path == block.section_path,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(
            f"Evidence {evidence.evidence_id} does not match block {block.block_id}: {', '.join(failed)}"
        )

    if evidence.quote is not None:
        quote = _normalized_text(evidence.quote)
        if not quote or quote not in _normalized_text(block.text):
            preview = quote[:120]
            raise ValueError(
                f"Evidence {evidence.evidence_id} quote is not present in block "
                f"{block.block_id}; invalid quote starts with {preview!r}"
            )
    return evidence


def iter_evidence_refs(value: Any) -> Iterator[EvidenceRef]:
    """Yield EvidenceRef instances recursively from a validated model result."""
    if isinstance(value, EvidenceRef):
        yield value
        return
    if isinstance(value, BaseModel):
        for field_name in type(value).model_fields:
            yield from iter_evidence_refs(getattr(value, field_name))
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from iter_evidence_refs(item)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from iter_evidence_refs(item)


def validate_evidence_bindings(value: Any, binding: EvidencePacketBinding) -> Any:
    """Semantic-validator adapter for any nested Pydantic result containing evidence."""
    for evidence in iter_evidence_refs(value):
        validate_evidence_ref(evidence, binding)
    return value


def _map_nested_evidence(value: Any, resolver) -> Any:
    """Return a copy with every EvidenceRef-shaped mapping resolved."""
    if isinstance(value, dict):
        source = value.get("source")
        if isinstance(source, dict) and source.get("block_id") is not None:
            return resolver(value)
        return {key: _map_nested_evidence(item, resolver) for key, item in value.items()}
    if isinstance(value, list):
        return [_map_nested_evidence(item, resolver) for item in value]
    return value


def canonicalize_evidence_payload(
    payload: dict[str, Any],
    binding: EvidencePacketBinding,
    *,
    allowed_block_ids: set[str] | frozenset[str] | None = None,
) -> dict[str, Any]:
    """Materialize source metadata and drop references outside an optional contract."""

    def resolve(raw: dict[str, Any]) -> dict[str, Any]:
        item = deepcopy(raw)
        raw_source = item.get("source", {})
        block = binding.blocks.get(raw_source.get("block_id"))
        if block is None:
            return item

        document = binding.documents[block.document_id]
        item.setdefault("evidence_id", f"EVD-{block.block_id.removeprefix('BLK-')[:12]}")
        item.setdefault("evidence_level", "direct")
        item.setdefault("confidence", "high")
        item.setdefault("retrieved_by", "node_field_retrieval")
        item.setdefault("is_human_confirmed", False)
        item["source"] = {
            "file_name": document.source_file_name,
            "file_path": document.source_path,
            "file_type": Path(document.source_file_name).suffix.lstrip(".").lower(),
            "document_id": document.document_id,
            "block_id": block.block_id,
            "parser_version": document.parser_version,
            "page_number": block.pdf_page,
            "printed_page_label": block.printed_page_label,
            "section_path": block.section_path,
            "hash_sha256": document.source_sha256,
        }
        quote = item.get("quote")
        normalized_quote = _normalized_text(str(quote)) if quote is not None else ""
        normalized_block = _normalized_text(block.text)
        if not normalized_quote or normalized_quote not in normalized_block:
            item["quote"] = block.text.strip() or None
            audit_note = (
                "系统已用规范文本块原文补全来源上下文；审阅时仍需确认该原文是否支持具体结论。"
            )
            existing_note = item.get("notes")
            item["notes"] = f"{existing_note}\n{audit_note}" if existing_note else audit_note
        return item

    dropped_unknown = 0
    dropped_outside_contract = 0

    def normalize(value: Any) -> Any:
        nonlocal dropped_unknown, dropped_outside_contract
        if isinstance(value, list):
            items = [normalize(item) for item in value]
            return [item for item in items if item is not None]
        if isinstance(value, dict):
            source = value.get("source")
            looks_like_evidence = isinstance(source, dict) and any(
                key in value
                for key in ("evidence_id", "evidence_level", "quote", "retrieved_by")
            )
            if looks_like_evidence:
                block_id = source.get("block_id")
                if block_id not in binding.blocks:
                    dropped_unknown += 1
                    return None
                if allowed_block_ids is not None and block_id not in allowed_block_ids:
                    dropped_outside_contract += 1
                    return None
                return resolve(value)
            return {key: normalize(item) for key, item in value.items()}
        return value

    normalized = normalize(payload)
    if dropped_unknown:
        logger.warning(
            "丢弃 %d 条无法绑定到客户材料 block_id 的模型引用；保留业务内容继续校验",
            dropped_unknown,
        )
    if dropped_outside_contract:
        logger.warning(
            "丢弃 %d 条不属于本段事实证据契约的模型引用；保留业务内容并标记为待审阅",
            dropped_outside_contract,
        )
    return normalized


def canonicalize_evidence_from_upstream(
    payload: dict[str, Any],
    *upstream_values: Any,
) -> dict[str, Any]:
    """Replace model-written references with exact validated upstream references."""
    references = [
        item
        for upstream in upstream_values
        for item in iter_evidence_refs(upstream)
    ]
    by_identity = {
        (item.evidence_id, item.source.block_id): item.model_dump(mode="json")
        for item in references
    }
    by_block: dict[str, dict[str, Any]] = {}
    for item in references:
        if item.source.block_id is not None:
            by_block.setdefault(item.source.block_id, item.model_dump(mode="json"))

    def resolve(raw: dict[str, Any]) -> dict[str, Any]:
        source = raw.get("source", {})
        identity = (raw.get("evidence_id"), source.get("block_id"))
        canonical = by_identity.get(identity) or by_block.get(source.get("block_id"))
        return deepcopy(canonical) if canonical is not None else deepcopy(raw)

    return _map_nested_evidence(payload, resolve)


def validate_evidence_subset(value: Any, *upstream_values: Any) -> Any:
    """Require every nested reference to exactly match an upstream reference."""
    allowed = {
        item.model_dump_json()
        for upstream in upstream_values
        for item in iter_evidence_refs(upstream)
    }
    invalid_ids = [
        item.evidence_id
        for item in iter_evidence_refs(value)
        if item.model_dump_json() not in allowed
    ]
    if invalid_ids:
        raise ValueError(
            "Evidence is not present in validated upstream results: "
            f"{sorted(set(invalid_ids))}."
        )
    return value


def validate_evidence_block_subset(value: Any, allowed_block_ids: set[str]) -> Any:
    """Require every nested EvidenceRef to use one explicitly retrieved block."""
    invalid_ids = [
        item.evidence_id
        for item in iter_evidence_refs(value)
        if item.source.block_id not in allowed_block_ids
    ]
    if invalid_ids:
        raise ValueError(
            "Evidence block was not retrieved for this node: "
            f"{sorted(set(invalid_ids))}."
        )
    return value


__all__ = [
    "EvidencePacketBinding",
    "bind_materialized_packet",
    "canonicalize_evidence_from_upstream",
    "canonicalize_evidence_payload",
    "iter_evidence_refs",
    "load_evidence_packet",
    "render_evidence_material",
    "validate_evidence_bindings",
    "validate_evidence_block_subset",
    "validate_evidence_ref",
    "validate_evidence_subset",
]
