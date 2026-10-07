"""Validate reusable PDF corpus artifacts against their source documents."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import pymupdf

from schemas.document import (
    CorpusManifest,
    DocumentBlockType,
    ParsedDocument,
    ParsedSection,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_inside_workspace(path_value: str, workspace: Path) -> Path:
    candidate = Path(path_value)
    resolved = (workspace / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if not resolved.is_relative_to(workspace):
        raise ValueError(f"Artifact path escapes workspace: {path_value}")
    return resolved


def validate_corpus(*, manifest_path: Path, workspace: Path) -> dict[str, object]:
    """Validate models, hashes, locators, counts, and page coverage."""
    workspace = workspace.resolve()
    manifest = CorpusManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    global_block_ids: set[str] = set()
    block_types: Counter[str] = Counter()
    totals = Counter()
    document_summaries = []

    for reference in manifest.documents:
        source_path = _resolve_inside_workspace(reference.source_path, workspace)
        artifact_path = _resolve_inside_workspace(reference.document_artifact, workspace)
        if _sha256_file(source_path) != reference.source_sha256:
            raise ValueError(f"Source hash mismatch: {reference.source_file_name}")

        parsed = ParsedDocument.model_validate_json(artifact_path.read_text(encoding="utf-8"))
        if parsed.document_id != reference.document_id or parsed.source_sha256 != reference.source_sha256:
            raise ValueError(f"Manifest/document identity mismatch: {reference.source_file_name}")
        if parsed.parser_version != manifest.parser_version:
            raise ValueError(f"Parser version mismatch: {reference.source_file_name}")

        source_document = pymupdf.open(source_path)
        if source_document.page_count != parsed.summary.page_count:
            raise ValueError(f"PDF page-count mismatch: {reference.source_file_name}")

        document_block_ids: set[str] = set()
        covered_pages: set[int] = set()
        review_pages: set[int] = set()
        table_count = 0
        block_count = 0
        for relative_section_path in parsed.section_files:
            section_path = (artifact_path.parent / relative_section_path).resolve()
            if not section_path.is_relative_to(artifact_path.parent.resolve()):
                raise ValueError(f"Section path escapes document version: {relative_section_path}")
            section = ParsedSection.model_validate_json(section_path.read_text(encoding="utf-8"))
            if section.document_id != parsed.document_id or section.source_sha256 != parsed.source_sha256:
                raise ValueError(f"Section identity mismatch: {relative_section_path}")
            if section.parser_version != parsed.parser_version:
                raise ValueError(f"Section parser-version mismatch: {relative_section_path}")
            if not section.blocks:
                raise ValueError(f"Empty section artifact: {relative_section_path}")
            actual_start = min(block.pdf_page for block in section.blocks)
            actual_end = max(block.pdf_page for block in section.blocks)
            if (actual_start, actual_end) != (section.start_pdf_page, section.end_pdf_page):
                raise ValueError(f"Section page range mismatch: {relative_section_path}")

            previous_locator = None
            for block in section.blocks:
                locator = (block.pdf_page, block.block_order)
                if previous_locator is not None and locator < previous_locator:
                    raise ValueError(f"Block order mismatch: {relative_section_path}")
                previous_locator = locator
                if block.section_id != section.section_id or block.section_path != section.section_path:
                    raise ValueError(f"Block section mismatch: {block.block_id}")
                if block.parser_version != parsed.parser_version:
                    raise ValueError(f"Block parser-version mismatch: {block.block_id}")
                if block.block_id in global_block_ids:
                    raise ValueError(f"Duplicate global block ID: {block.block_id}")
                global_block_ids.add(block.block_id)
                document_block_ids.add(block.block_id)
                covered_pages.add(block.pdf_page)
                if block.needs_review:
                    review_pages.add(block.pdf_page)
                expected_label = source_document[block.pdf_page - 1].get_label() or None
                if block.printed_page_label != expected_label:
                    raise ValueError(f"Printed page-label mismatch: {block.block_id}")
                if block.block_type == DocumentBlockType.TABLE:
                    table_count += 1
                    if not block.table_cells:
                        raise ValueError(f"Table block has no cells: {block.block_id}")
                block_types[block.block_type.value] += 1
                block_count += 1

        expected_pages = set(range(1, source_document.page_count + 1))
        missing_pages = sorted(expected_pages - covered_pages)
        if missing_pages:
            raise ValueError(f"Pages without blocks in {reference.source_file_name}: {missing_pages}")
        if block_count != parsed.summary.block_count:
            raise ValueError(f"Block-count mismatch: {reference.source_file_name}")
        if table_count != parsed.summary.table_count:
            raise ValueError(f"Table-count mismatch: {reference.source_file_name}")
        if sorted(review_pages) != parsed.summary.review_required_pages:
            raise ValueError(f"Review-page mismatch: {reference.source_file_name}")
        if len(parsed.section_files) != parsed.summary.section_file_count:
            raise ValueError(f"Section-count mismatch: {reference.source_file_name}")

        totals.update(
            pages=source_document.page_count,
            sections=len(parsed.section_files),
            blocks=block_count,
            tables=table_count,
            review_pages=len(review_pages),
        )
        document_summaries.append(
            {
                "document_id": parsed.document_id,
                "source_file_name": parsed.source_file_name,
                "pages": source_document.page_count,
                "sections": len(parsed.section_files),
                "blocks": block_count,
                "tables": table_count,
                "review_pages": sorted(review_pages),
            }
        )

    return {
        "project_id": manifest.project_id,
        "parser_version": manifest.parser_version,
        "documents": len(manifest.documents),
        "pages": totals["pages"],
        "sections": totals["sections"],
        "blocks": totals["blocks"],
        "tables": totals["tables"],
        "review_pages": totals["review_pages"],
        "block_types": dict(sorted(block_types.items())),
        "document_summaries": document_summaries,
    }


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    return parser


def main() -> None:
    """CLI entry point for corpus validation."""
    args = _build_argument_parser().parse_args()
    result = validate_corpus(manifest_path=args.manifest, workspace=args.workspace)
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary_path.write_text(serialized, encoding="utf-8")
        temporary_path.replace(args.output)
    print(serialized)


if __name__ == "__main__":
    main()


__all__ = ["validate_corpus"]
