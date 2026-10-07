"""Query a parsed corpus and build deterministic, manually curated evidence packets."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from schemas.document import CorpusManifest, DocumentBlock, DocumentBlockType, ParsedDocument, ParsedSection
from schemas.evidence_packet import (
    EvidencePacket,
    EvidencePacketConfig,
    EvidencePacketDocument,
    EvidencePacketSelection,
    EvidencePacketStats,
    EvidenceSelectionSummary,
    EvidenceSelectorKind,
)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _resolve_inside_workspace(path_value: str | Path, workspace: Path) -> Path:
    candidate = Path(path_value)
    resolved = (workspace / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if not resolved.is_relative_to(workspace):
        raise ValueError(f"Path escapes workspace: {path_value}")
    return resolved


def _ordered_unique(values: list[object]) -> list[object]:
    return list(dict.fromkeys(values))


class CorpusIndex:
    """In-memory deterministic lookup over validated R2 section artifacts."""

    def __init__(self, *, manifest_path: Path, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.manifest_path = _resolve_inside_workspace(manifest_path, self.workspace)
        self.manifest_bytes = self.manifest_path.read_bytes()
        self.manifest = CorpusManifest.model_validate_json(self.manifest_bytes)
        self.document_refs = {item.document_id: item for item in self.manifest.documents}
        self.documents: dict[str, ParsedDocument] = {}
        self.sections: dict[str, ParsedSection] = {}
        self.blocks: list[DocumentBlock] = []
        self.blocks_by_id: dict[str, DocumentBlock] = {}

        for reference in self.manifest.documents:
            artifact_path = _resolve_inside_workspace(reference.document_artifact, self.workspace)
            document = ParsedDocument.model_validate_json(artifact_path.read_text(encoding="utf-8"))
            if document.document_id != reference.document_id:
                raise ValueError(f"Document identity mismatch: {reference.document_id}")
            if document.source_sha256 != reference.source_sha256:
                raise ValueError(f"Document source hash mismatch: {reference.document_id}")
            if document.parser_version != self.manifest.parser_version:
                raise ValueError(f"Document parser version mismatch: {reference.document_id}")
            self.documents[document.document_id] = document
            for relative_path in document.section_files:
                section_path = (artifact_path.parent / relative_path).resolve()
                if not section_path.is_relative_to(artifact_path.parent.resolve()):
                    raise ValueError(f"Section path escapes document version: {relative_path}")
                section = ParsedSection.model_validate_json(section_path.read_text(encoding="utf-8"))
                if section.section_id in self.sections:
                    raise ValueError(f"Duplicate section ID: {section.section_id}")
                self.sections[section.section_id] = section
                for block in section.blocks:
                    if block.block_id in self.blocks_by_id:
                        raise ValueError(f"Duplicate block ID: {block.block_id}")
                    self.blocks.append(block)
                    self.blocks_by_id[block.block_id] = block
        document_order = {
            reference.document_id: position for position, reference in enumerate(self.manifest.documents)
        }
        self.blocks.sort(
            key=lambda block: (document_order[block.document_id], block.pdf_page, block.block_order)
        )

    def query(
        self,
        *,
        document_id: str | None = None,
        document_name: str | None = None,
        section: str | None = None,
        pdf_page_start: int | None = None,
        pdf_page_end: int | None = None,
        block_ids: list[str] | None = None,
        keyword: str | None = None,
    ) -> list[DocumentBlock]:
        """Return blocks matching all provided filters in corpus order."""
        if document_id is not None and document_id not in self.documents:
            raise ValueError(f"Unknown document_id: {document_id}")
        if pdf_page_start is not None and pdf_page_end is not None and pdf_page_start > pdf_page_end:
            raise ValueError("pdf_page_start must not exceed pdf_page_end")
        requested_ids = set(block_ids or [])
        missing_ids = requested_ids - self.blocks_by_id.keys()
        if missing_ids:
            raise ValueError(f"Unknown block IDs: {sorted(missing_ids)}")
        document_name_folded = document_name.casefold() if document_name else None
        section_folded = section.casefold() if section else None
        keyword_folded = keyword.casefold() if keyword else None

        matches = []
        for block in self.blocks:
            reference = self.document_refs[block.document_id]
            if document_id is not None and block.document_id != document_id:
                continue
            if document_name_folded and document_name_folded not in reference.source_file_name.casefold():
                continue
            if section_folded and section_folded not in " > ".join(block.section_path).casefold():
                continue
            if pdf_page_start is not None and block.pdf_page < pdf_page_start:
                continue
            if pdf_page_end is not None and block.pdf_page > pdf_page_end:
                continue
            if requested_ids and block.block_id not in requested_ids:
                continue
            if keyword_folded and keyword_folded not in block.text.casefold():
                continue
            matches.append(block)
        return matches

    def resolve_selection(self, selection: EvidencePacketSelection) -> list[DocumentBlock]:
        """Resolve one reviewed selector, failing closed on missing identities."""
        document_blocks = self.query(document_id=selection.document_id)
        if selection.selector_kind == EvidenceSelectorKind.SECTION_IDS:
            requested = set(selection.section_ids)
            known = {block.section_id for block in document_blocks}
            missing = requested - known
            if missing:
                raise ValueError(f"{selection.selection_id} has unknown section IDs: {sorted(missing)}")
            matches = [block for block in document_blocks if block.section_id in requested]
        elif selection.selector_kind == EvidenceSelectorKind.SECTION_PATH_PREFIX:
            prefix = selection.section_path_prefix
            matches = [block for block in document_blocks if block.section_path[: len(prefix)] == prefix]
        elif selection.selector_kind == EvidenceSelectorKind.PAGE_RANGE:
            matches = self.query(
                document_id=selection.document_id,
                pdf_page_start=selection.pdf_page_start,
                pdf_page_end=selection.pdf_page_end,
            )
        else:
            matches = self.query(document_id=selection.document_id, block_ids=selection.block_ids)
        if not matches:
            raise ValueError(f"Selection resolved to zero blocks: {selection.selection_id}")
        return matches


def _serialize_model(model: EvidencePacket) -> bytes:
    payload = model.model_dump(mode="json")
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def render_packet_text(packet: EvidencePacket) -> str:
    """Render compact LLM input while retaining every selected block anchor."""
    lines = [
        f"[PACKET {packet.packet_id} v{packet.packet_version}]",
        f"Project: {packet.project_id}",
        f"Purpose: {packet.purpose}",
        "Source rule: use only the cited document/page/block text; preserve stated uncertainties.",
        "",
        "[KNOWN GAPS]",
    ]
    for gap in packet.known_gaps:
        lines.append(f"- {gap.gap_id}: {gap.description} Disposition: {gap.disposition}")

    documents = {document.document_id: document for document in packet.documents}
    current_document_id = None
    current_group = None
    grouped_blocks: list[DocumentBlock] = []

    def flush_group() -> None:
        if not grouped_blocks:
            return
        first = grouped_blocks[0]
        printed = f"; printed page {first.printed_page_label}" if first.printed_page_label else ""
        block_ids = ",".join(block.block_id for block in grouped_blocks)
        lines.extend(
            [
                "",
                f"[PDF page {first.pdf_page}{printed}; section {' > '.join(first.section_path)}; blocks {block_ids}]",
                "\n\n".join(block.text for block in grouped_blocks if block.text),
            ]
        )

    for block in packet.blocks:
        if block.document_id != current_document_id:
            flush_group()
            grouped_blocks = []
            current_group = None
            current_document_id = block.document_id
            source = documents[block.document_id]
            lines.extend(
                [
                    "",
                    f"[DOCUMENT {source.document_id}]",
                    f"File: {source.source_file_name}",
                    f"SHA-256: {source.source_sha256}",
                ]
            )
        group_key = (block.document_id, block.pdf_page, tuple(block.section_path))
        if current_group is not None and group_key != current_group:
            flush_group()
            grouped_blocks = []
        current_group = group_key
        grouped_blocks.append(block)
    flush_group()
    return "\n".join(lines).rstrip() + "\n"


def build_evidence_packet(
    *, config_path: Path, output_path: Path, workspace: Path
) -> tuple[EvidencePacket, str]:
    """Materialize one source-bound packet and return its file SHA-256."""
    workspace = workspace.resolve()
    resolved_config = _resolve_inside_workspace(config_path, workspace)
    resolved_output = _resolve_inside_workspace(output_path, workspace)
    config_bytes = resolved_config.read_bytes()
    config = EvidencePacketConfig.model_validate_json(config_bytes)
    index = CorpusIndex(manifest_path=Path(config.manifest_path), workspace=workspace)
    if config.project_id != index.manifest.project_id:
        raise ValueError("Packet project_id does not match corpus manifest")

    selected_ids: set[str] = set()
    selection_summaries = []
    for selection in config.selections:
        matches = index.resolve_selection(selection)
        selected_ids.update(block.block_id for block in matches)
        section_pairs = _ordered_unique([(block.section_id, tuple(block.section_path)) for block in matches])
        selection_summaries.append(
            EvidenceSelectionSummary(
                selection_id=selection.selection_id,
                document_id=selection.document_id,
                section_ids=[pair[0] for pair in section_pairs],
                section_paths=[list(pair[1]) for pair in section_pairs],
                pdf_pages=_ordered_unique([block.pdf_page for block in matches]),
                block_count=len(matches),
                character_count=sum(len(block.text) for block in matches),
                rationale=selection.rationale,
                target_nodes=selection.target_nodes,
            )
        )

    selected_blocks = [block for block in index.blocks if block.block_id in selected_ids]
    blocks_by_document: dict[str, list[DocumentBlock]] = defaultdict(list)
    for block in selected_blocks:
        blocks_by_document[block.document_id].append(block)

    packet_documents = []
    for reference in index.manifest.documents:
        document_blocks = blocks_by_document.get(reference.document_id, [])
        if not document_blocks:
            continue
        packet_documents.append(
            EvidencePacketDocument(
                document_id=reference.document_id,
                source_file_name=reference.source_file_name,
                source_path=reference.source_path,
                source_sha256=reference.source_sha256,
                parser_version=index.manifest.parser_version,
                selected_section_ids=_ordered_unique([block.section_id for block in document_blocks]),
                selected_pdf_pages=_ordered_unique([block.pdf_page for block in document_blocks]),
                selected_block_count=len(document_blocks),
            )
        )

    packet = EvidencePacket(
        schema_version=config.schema_version,
        packet_id=config.packet_id,
        packet_version=config.packet_version,
        project_id=config.project_id,
        purpose=config.purpose,
        manifest_path=config.manifest_path,
        manifest_sha256=_sha256_bytes(index.manifest_bytes),
        config_sha256=_sha256_bytes(config_bytes),
        parser_name=index.manifest.parser_name,
        parser_version=index.manifest.parser_version,
        documents=packet_documents,
        selection_summaries=selection_summaries,
        known_gaps=config.known_gaps,
        stats=EvidencePacketStats(
            document_count=len(packet_documents),
            section_count=len({(block.document_id, block.section_id) for block in selected_blocks}),
            page_count=len({(block.document_id, block.pdf_page) for block in selected_blocks}),
            block_count=len(selected_blocks),
            character_count=sum(len(block.text) for block in selected_blocks),
            table_count=sum(block.block_type == DocumentBlockType.TABLE for block in selected_blocks),
            review_block_count=sum(block.needs_review for block in selected_blocks),
        ),
        blocks=selected_blocks,
    )
    serialized = _serialize_model(packet)
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = resolved_output.with_suffix(resolved_output.suffix + ".tmp")
    temporary_path.write_bytes(serialized)
    temporary_path.replace(resolved_output)
    return packet, _sha256_bytes(serialized)


def write_review_summary(
    *,
    packet: EvidencePacket,
    packet_sha256: str,
    output_path: Path,
    workspace: Path,
    packet_size_bytes: int | None = None,
    prompt_sha256: str | None = None,
    prompt_size_bytes: int | None = None,
) -> None:
    """Write a compact human-review view without duplicating packet block text."""
    resolved_output = _resolve_inside_workspace(output_path, workspace.resolve())
    lines = [
        f"# Evidence Packet Review: {packet.packet_id} v{packet.packet_version}",
        "",
        "Status: AWAITING USER APPROVAL",
        "",
        f"Purpose: {packet.purpose}",
        f"Packet SHA-256: `{packet_sha256}`",
        f"Manifest SHA-256: `{packet.manifest_sha256}`",
        f"Config SHA-256: `{packet.config_sha256}`",
        f"Parser: `{packet.parser_name}` v`{packet.parser_version}`",
        "",
        "## Size",
        "",
        f"- Documents: {packet.stats.document_count}",
        f"- Sections: {packet.stats.section_count}",
        f"- Physical pages: {packet.stats.page_count}",
        f"- Blocks: {packet.stats.block_count} ({packet.stats.table_count} tables)",
        f"- Extracted characters: {packet.stats.character_count}",
        f"- Review-flagged blocks: {packet.stats.review_block_count}",
        *([f"- Full trace packet: {packet_size_bytes} bytes"] if packet_size_bytes is not None else []),
        *(
            [f"- Compact R5 input projection: {prompt_size_bytes} bytes; SHA-256 `{prompt_sha256}`"]
            if prompt_size_bytes is not None and prompt_sha256 is not None
            else []
        ),
        "",
        "## Included sources",
        "",
    ]
    for document in packet.documents:
        pages = document.selected_pdf_pages
        lines.append(
            f"- `{document.document_id}` — {document.source_file_name}; "
            f"{len(document.selected_section_ids)} sections, {len(pages)} pages "
            f"(PDF {min(pages)}–{max(pages)}), {document.selected_block_count} blocks."
        )
    lines.extend(["", "## Selection rationale", ""])
    for summary in packet.selection_summaries:
        section_names = [path[-1] for path in summary.section_paths]
        lines.append(
            f"- `{summary.selection_id}` — {summary.rationale} "
            f"Sections: {'; '.join(section_names)}. PDF pages: {', '.join(map(str, summary.pdf_pages))}."
        )
    lines.extend(["", "## Known gaps", ""])
    for gap in packet.known_gaps:
        nodes = ", ".join(node.value for node in gap.affected_nodes)
        lines.append(f"- `{gap.gap_id}` ({nodes}) — {gap.description} Disposition: {gap.disposition}")
    lines.extend(
        [
            "",
            "## Approval gate",
            "",
            "Approval freezes this packet for the first controlled Node [0]–[3] run. "
            "The expert workbook is not included and R4 has not started.",
            "",
        ]
    )
    content = "\n".join(lines)
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = resolved_output.with_suffix(resolved_output.suffix + ".tmp")
    temporary_path.write_text(content, encoding="utf-8")
    temporary_path.replace(resolved_output)


def _query_command(args: argparse.Namespace) -> None:
    index = CorpusIndex(manifest_path=args.manifest, workspace=args.workspace)
    matches = index.query(
        document_id=args.document_id,
        document_name=args.document_name,
        section=args.section,
        pdf_page_start=args.page_start,
        pdf_page_end=args.page_end,
        block_ids=args.block_id,
        keyword=args.keyword,
    )
    result = []
    for block in matches[: args.limit]:
        item = {
            "block_id": block.block_id,
            "document_id": block.document_id,
            "pdf_page": block.pdf_page,
            "printed_page_label": block.printed_page_label,
            "section_path": block.section_path,
            "block_type": block.block_type.value,
        }
        if args.include_text:
            item["text"] = block.text
        result.append(item)
    print(json.dumps({"match_count": len(matches), "results": result}, ensure_ascii=False, indent=2))


def _build_command(args: argparse.Namespace) -> None:
    packet, packet_hash = build_evidence_packet(
        config_path=args.config,
        output_path=args.output,
        workspace=args.workspace,
    )
    packet_path = _resolve_inside_workspace(args.output, args.workspace)
    prompt_hash = None
    prompt_size = None
    if args.prompt_output is not None:
        prompt_path = _resolve_inside_workspace(args.prompt_output, args.workspace)
        prompt_bytes = render_packet_text(packet).encode("utf-8")
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = prompt_path.with_suffix(prompt_path.suffix + ".tmp")
        temporary_path.write_bytes(prompt_bytes)
        temporary_path.replace(prompt_path)
        prompt_hash = _sha256_bytes(prompt_bytes)
        prompt_size = len(prompt_bytes)
    if args.review is not None:
        write_review_summary(
            packet=packet,
            packet_sha256=packet_hash,
            output_path=args.review,
            workspace=args.workspace,
            packet_size_bytes=packet_path.stat().st_size,
            prompt_sha256=prompt_hash,
            prompt_size_bytes=prompt_size,
        )
    print(json.dumps({**packet.stats.model_dump(), "packet_sha256": packet_hash}, ensure_ascii=False))


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    query = subparsers.add_parser("query", help="Look up corpus blocks using AND-combined filters")
    query.add_argument("--manifest", required=True, type=Path)
    query.add_argument("--workspace", type=Path, default=Path.cwd())
    query.add_argument("--document-id")
    query.add_argument("--document-name")
    query.add_argument("--section")
    query.add_argument("--page-start", type=int)
    query.add_argument("--page-end", type=int)
    query.add_argument("--block-id", action="append")
    query.add_argument("--keyword")
    query.add_argument("--limit", type=int, default=20)
    query.add_argument("--include-text", action="store_true")
    query.set_defaults(handler=_query_command)

    build = subparsers.add_parser("build", help="Build a packet from a reviewed static config")
    build.add_argument("--config", required=True, type=Path)
    build.add_argument("--output", required=True, type=Path)
    build.add_argument("--review", type=Path)
    build.add_argument("--prompt-output", type=Path)
    build.add_argument("--workspace", type=Path, default=Path.cwd())
    build.set_defaults(handler=_build_command)
    return parser


def main() -> None:
    args = _build_argument_parser().parse_args()
    args.workspace = args.workspace.resolve()
    args.handler(args)


if __name__ == "__main__":
    main()


__all__ = ["CorpusIndex", "build_evidence_packet", "render_packet_text", "write_review_summary"]
