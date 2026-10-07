"""Deterministic PDF-to-page/section JSON extraction for project evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pymupdf

from schemas.document import (
    CorpusDocumentRef,
    CorpusManifest,
    DocumentBlock,
    DocumentBlockType,
    DocumentParseSummary,
    DocumentSectionRef,
    ExtractionMethod,
    PageLabelRule,
    ParsedDocument,
    ParsedSection,
)


PARSER_NAME = "pymupdf-page-section-parser"
PARSER_VERSION = "1.5.0"
LOW_TEXT_THRESHOLD = 50
IMAGE_ONLY_TEXT_THRESHOLD = 20


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_id(prefix: str, *parts: object, length: int) -> str:
    material = "|".join(str(part) for part in parts)
    value = hashlib.sha256(material.encode("utf-8")).hexdigest()[:length].upper()
    return f"{prefix}-{value}"


def _document_id(path: Path) -> str:
    normalized_name = path.stem.strip().casefold()
    return _stable_id("DOC", normalized_name, length=12)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalize_heading(value: str) -> str:
    return re.sub(r"[\s\u3000]+", "", value).strip("：:。.．")


def _safe_relative_path(path: Path, workspace: Path) -> str:
    try:
        return path.resolve().relative_to(workspace.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _write_model(path: Path, model: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(model.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _build_toc(document_id: str, source_hash: str, raw_toc: list[list[Any]]) -> list[DocumentSectionRef]:
    sections: list[DocumentSectionRef] = []
    path_stack: list[str] = []
    for toc_index, item in enumerate(raw_toc):
        level, raw_title, raw_page = int(item[0]), str(item[1]), int(item[2])
        title = _normalize_text(raw_title)
        if not title or raw_page < 1:
            continue
        path_stack = path_stack[: max(level - 1, 0)]
        path_stack.append(title)
        section_id = _stable_id(
            "SEC",
            document_id,
            source_hash,
            toc_index,
            level,
            title,
            raw_page,
            length=16,
        )
        sections.append(
            DocumentSectionRef(
                section_id=section_id,
                toc_index=toc_index,
                level=level,
                title=title,
                pdf_page=raw_page,
                section_path=list(path_stack),
            )
        )
    return sections


def _unmapped_section(document_id: str, source_hash: str) -> DocumentSectionRef:
    return DocumentSectionRef(
        section_id=_stable_id("SEC", document_id, source_hash, "unmapped", length=16),
        toc_index=0,
        level=1,
        title="Unmapped",
        pdf_page=1,
        section_path=["Unmapped"],
    )


def _front_matter_section(document_id: str, source_hash: str) -> DocumentSectionRef:
    return DocumentSectionRef(
        section_id=_stable_id("SEC", document_id, source_hash, "front_matter", length=16),
        toc_index=0,
        level=1,
        title="Front Matter",
        pdf_page=1,
        section_path=["Front Matter"],
    )


def _default_section_for_page(
    pdf_page: int,
    sections: list[DocumentSectionRef],
    fallback: DocumentSectionRef,
) -> DocumentSectionRef:
    eligible = [section for section in sections if section.pdf_page <= pdf_page]
    if not eligible:
        return fallback
    return max(eligible, key=lambda section: (section.pdf_page, section.level, section.toc_index))


def _match_heading(
    text: str,
    page_sections: list[DocumentSectionRef],
) -> DocumentSectionRef | None:
    normalized_text = _normalize_heading(text)
    if not normalized_text:
        return None
    matches = []
    for section in page_sections:
        normalized_title = _normalize_heading(section.title)
        if normalized_text == normalized_title or normalized_text.startswith(normalized_title):
            matches.append(section)
    if not matches:
        return None
    return max(matches, key=lambda section: (len(_normalize_heading(section.title)), section.level))


def _rect_overlap_ratio(first: pymupdf.Rect, second: pymupdf.Rect) -> float:
    if first.is_empty or first.get_area() == 0:
        return 0.0
    intersection = first & second
    return max(intersection.get_area(), 0.0) / first.get_area()


def _classify_text_block(text: str, is_heading: bool) -> DocumentBlockType:
    if is_heading:
        return DocumentBlockType.HEADING
    first_line = text.splitlines()[0].strip() if text.splitlines() else ""
    if re.match(r"^(图|Figure)\s*[A-Za-z0-9一二三四五六七八九十.-]+", first_line, re.IGNORECASE):
        return DocumentBlockType.FIGURE_CAPTION
    if re.match(r"^(?:[-•●▪]|\d+[.)、])\s*", first_line):
        return DocumentBlockType.LIST
    return DocumentBlockType.PARAGRAPH


def _extract_native_blocks(page: pymupdf.Page) -> list[tuple[pymupdf.Rect, str]]:
    blocks: list[tuple[pymupdf.Rect, str]] = []
    page_dict = page.get_text("dict", sort=True)
    for raw_block in page_dict.get("blocks", []):
        if raw_block.get("type") != 0:
            continue
        lines = []
        for line in raw_block.get("lines", []):
            line_text = "".join(span.get("text", "") for span in line.get("spans", []))
            if line_text.strip():
                lines.append(line_text.strip())
        text = "\n".join(lines).strip()
        if not text:
            continue
        blocks.append((pymupdf.Rect(raw_block["bbox"]), text))
    return blocks


def _normalize_table_cell(value: str | None) -> str | None:
    if value is None:
        return None
    lines = [line.strip() for line in value.splitlines()]
    normalized = "\n".join(line for line in lines if line)
    return normalized or None


def _join_header_words(words: list[tuple[float, float, str]]) -> str | None:
    if not words:
        return None
    lines: list[list[str]] = []
    line_positions: list[float] = []
    for y_position, _, text in sorted(words):
        if not lines or abs(y_position - line_positions[-1]) > 2.0:
            lines.append([text])
            line_positions.append(y_position)
        else:
            lines[-1].append(text)
    return "\n".join(" ".join(line) for line in lines)


def _detect_external_header(
    page: pymupdf.Page,
    table: Any,
) -> tuple[list[str | None], float] | None:
    column_intervals = sorted(
        {
            (round(cell[0], 3), round(cell[2], 3))
            for cell in table.cells
            if cell is not None
        }
    )
    if len(column_intervals) != table.col_count:
        return None

    table_rect = pymupdf.Rect(table.bbox)
    header_words: list[list[tuple[float, float, str]]] = [
        [] for _ in column_intervals
    ]
    for x0, y0, x1, y1, text, *_ in page.get_text("words", sort=True):
        center_x = (x0 + x1) / 2
        distance = table_rect.y0 - y1
        if distance < -1 or distance > 18 or center_x < table_rect.x0 or center_x > table_rect.x1:
            continue
        for column_index, (column_x0, column_x1) in enumerate(column_intervals):
            if column_x0 <= center_x <= column_x1:
                header_words[column_index].append((y0, x0, str(text)))
                break

    header = [_join_header_words(words) for words in header_words]
    minimum_populated = max(2, table.col_count // 2)
    if sum(bool(value) for value in header) < minimum_populated:
        return None
    header_top = min(word[0] for words in header_words for word in words)
    return header, header_top


def _extract_tables(page: pymupdf.Page) -> list[tuple[pymupdf.Rect, list[list[str | None]]]]:
    extracted = []
    table_finder = page.find_tables(
        vertical_strategy="text",
        horizontal_strategy="lines",
    )
    for table in table_finder.tables:
        rows = []
        for row in table.extract():
            rows.append([_normalize_table_cell(cell) for cell in row])
        if not rows:
            continue
        width = max(len(row) for row in rows)
        nonempty_rows = sum(
            sum(bool(cell) for cell in row) >= 2
            for row in rows
        )
        nonempty_columns = sum(
            sum(bool(row[column]) for row in rows if column < len(row)) >= 2
            for column in range(width)
        )
        if len(rows) >= 2 and width >= 2 and nonempty_rows >= 2 and nonempty_columns >= 2:
            table_bbox = pymupdf.Rect(table.bbox)
            detected = _detect_external_header(page, table)
            if detected is not None:
                external_header, header_top = detected
                first_row = [_normalize_heading(cell or "") for cell in rows[0]]
                detected_header = [_normalize_heading(cell or "") for cell in external_header]
                if detected_header != first_row:
                    rows.insert(0, external_header)
                    table_bbox = pymupdf.Rect(
                        table_bbox.x0,
                        min(table_bbox.y0, header_top),
                        table_bbox.x1,
                        table_bbox.y1,
                    )
            extracted.append((table_bbox, rows))
    return extracted


def _table_text(rows: Iterable[Iterable[str | None]]) -> str:
    return "\n".join("\t".join(cell or "" for cell in row) for row in rows).strip()


def _parse_document(
    *,
    project_id: str,
    source_path: Path,
    output_root: Path,
    workspace: Path,
) -> tuple[ParsedDocument, Path]:
    source_hash = _sha256_file(source_path)
    document_id = _document_id(source_path)
    version_root = output_root / document_id / "versions" / source_hash[:12] / PARSER_VERSION
    document_artifact_path = version_root / "document.json"

    if document_artifact_path.exists():
        existing = ParsedDocument.model_validate_json(document_artifact_path.read_text(encoding="utf-8"))
        expected_files = [version_root / relative_path for relative_path in existing.section_files]
        if (
            existing.source_sha256 == source_hash
            and existing.parser_version == PARSER_VERSION
            and all(path.exists() for path in expected_files)
        ):
            return existing, document_artifact_path

    document = pymupdf.open(source_path)
    raw_toc = document.get_toc(simple=True)
    toc = _build_toc(document_id, source_hash, raw_toc)
    fallback = _unmapped_section(document_id, source_hash)
    front_matter = _front_matter_section(document_id, source_hash)
    sections_by_page: dict[int, list[DocumentSectionRef]] = defaultdict(list)
    sections_by_id = {section.section_id: section for section in toc}
    sections_by_id[fallback.section_id] = fallback
    sections_by_id[front_matter.section_id] = front_matter
    for section in toc:
        sections_by_page[section.pdf_page].append(section)

    blocks_by_section: dict[str, list[DocumentBlock]] = defaultdict(list)
    low_text_pages: list[int] = []
    image_only_pages: list[int] = []
    unmapped_pages: list[int] = []
    review_required_pages: set[int] = set()
    table_count = 0

    for page_index, page in enumerate(document):
        pdf_page = page_index + 1
        printed_page_label = page.get_label() or None
        page_text = page.get_text("text", sort=True).strip()
        image_count = len(page.get_images(full=True))
        page_review_notes: list[str] = []
        if len(page_text) < LOW_TEXT_THRESHOLD:
            low_text_pages.append(pdf_page)
            page_review_notes.append("low_text_page")
        if len(page_text) < IMAGE_ONLY_TEXT_THRESHOLD and image_count:
            image_only_pages.append(pdf_page)
            page_review_notes.append("image_only_or_image_dominant_page")

        default_fallback = front_matter if toc else fallback
        current_section = _default_section_for_page(pdf_page, toc, default_fallback)
        if current_section.section_id == fallback.section_id:
            unmapped_pages.append(pdf_page)
            page_review_notes.append("section_unmapped")
        page_sections = sections_by_page.get(pdf_page, [])
        try:
            tables = _extract_tables(page)
        except Exception as exc:
            tables = []
            page_review_notes.append(f"table_extraction_failed:{type(exc).__name__}")
            review_required_pages.add(pdf_page)
        table_rectangles = [bbox for bbox, _ in tables]
        ordered_items: list[tuple[float, float, str, pymupdf.Rect, Any]] = []

        for bbox, rows in tables:
            ordered_items.append((bbox.y0, bbox.x0, "table", bbox, rows))
        for bbox, text in _extract_native_blocks(page):
            if any(_rect_overlap_ratio(bbox, table_bbox) >= 0.5 for table_bbox in table_rectangles):
                continue
            compact = _normalize_text(text)
            if compact == str(printed_page_label) or re.fullmatch(r"[ivxlcdm\d]+", compact, re.IGNORECASE):
                continue
            ordered_items.append((bbox.y0, bbox.x0, "text", bbox, text))

        ordered_items.sort(key=lambda item: (item[0], item[1], item[2]))
        for block_order, (_, _, item_type, bbox, payload) in enumerate(ordered_items):
            if item_type == "table":
                rows = payload
                text = _table_text(rows)
                block_type = DocumentBlockType.TABLE
                method = ExtractionMethod.TABLE_EXTRACTION
                table_cells = rows
                table_count += 1
            else:
                text = str(payload).strip()
                heading_section = _match_heading(text, page_sections)
                if heading_section is not None:
                    current_section = heading_section
                block_type = _classify_text_block(text, heading_section is not None)
                method = ExtractionMethod.NATIVE_TEXT
                table_cells = None

            block_id = _stable_id(
                "BLK",
                document_id,
                source_hash,
                PARSER_VERSION,
                pdf_page,
                block_order,
                length=16,
            )
            block = DocumentBlock(
                block_id=block_id,
                document_id=document_id,
                source_sha256=source_hash,
                parser_version=PARSER_VERSION,
                pdf_page=pdf_page,
                printed_page_label=printed_page_label,
                block_order=block_order,
                section_id=current_section.section_id,
                section_path=current_section.section_path,
                section_title=current_section.title,
                block_type=block_type,
                text=text,
                table_cells=table_cells,
                bbox=tuple(round(value, 3) for value in bbox),
                extraction_method=method,
                needs_review=bool(page_review_notes),
                review_notes=list(page_review_notes),
            )
            blocks_by_section[current_section.section_id].append(block)

        if not ordered_items and image_count:
            block_id = _stable_id(
                "BLK",
                document_id,
                source_hash,
                PARSER_VERSION,
                pdf_page,
                0,
                length=16,
            )
            blocks_by_section[current_section.section_id].append(
                DocumentBlock(
                    block_id=block_id,
                    document_id=document_id,
                    source_sha256=source_hash,
                    parser_version=PARSER_VERSION,
                    pdf_page=pdf_page,
                    printed_page_label=printed_page_label,
                    block_order=0,
                    section_id=current_section.section_id,
                    section_path=current_section.section_path,
                    section_title=current_section.title,
                    block_type=DocumentBlockType.UNRESOLVED_IMAGE,
                    text="",
                    extraction_method=ExtractionMethod.NATIVE_TEXT,
                    needs_review=True,
                    review_notes=list(page_review_notes or ["unresolved_image"]),
                )
            )
        if page_review_notes:
            review_required_pages.add(pdf_page)

    section_files: list[str] = []
    for file_index, (section_id, blocks) in enumerate(
        sorted(
            blocks_by_section.items(),
            key=lambda item: (min(block.pdf_page for block in item[1]), min(block.block_order for block in item[1])),
        )
    ):
        section_ref = sections_by_id[section_id]
        section = ParsedSection(
            project_id=project_id,
            document_id=document_id,
            source_sha256=source_hash,
            parser_version=PARSER_VERSION,
            section_id=section_id,
            section_path=section_ref.section_path,
            section_title=section_ref.title,
            start_pdf_page=min(block.pdf_page for block in blocks),
            end_pdf_page=max(block.pdf_page for block in blocks),
            blocks=sorted(blocks, key=lambda block: (block.pdf_page, block.block_order)),
        )
        relative_path = Path("sections") / f"{file_index:04d}_{section_id}.json"
        _write_model(version_root / relative_path, section)
        section_files.append(relative_path.as_posix())

    summary = DocumentParseSummary(
        page_count=document.page_count,
        toc_entry_count=len(toc),
        section_file_count=len(section_files),
        block_count=sum(len(blocks) for blocks in blocks_by_section.values()),
        table_count=table_count,
        low_text_pages=low_text_pages,
        image_only_pages=image_only_pages,
        unmapped_pages=unmapped_pages,
        review_required_pages=sorted(review_required_pages),
    )
    page_label_rules = [
        PageLabelRule(
            start_page_index=int(rule.get("startpage", 0)),
            prefix=str(rule.get("prefix", "")),
            first_page_number=int(rule.get("firstpagenum", 1)),
            style=str(rule.get("style", "")),
        )
        for rule in document.get_page_labels()
    ]
    metadata = {
        str(key): str(value) if value is not None else None
        for key, value in (document.metadata or {}).items()
    }
    parsed_document = ParsedDocument(
        project_id=project_id,
        document_id=document_id,
        source_file_name=source_path.name,
        source_path=_safe_relative_path(source_path, workspace),
        source_sha256=source_hash,
        source_size_bytes=source_path.stat().st_size,
        parser_name=PARSER_NAME,
        parser_version=PARSER_VERSION,
        parsed_at=datetime.now(timezone.utc),
        metadata=metadata,
        page_label_rules=page_label_rules,
        table_of_contents=toc,
        section_files=section_files,
        summary=summary,
    )
    _write_model(document_artifact_path, parsed_document)
    return parsed_document, document_artifact_path


def parse_project_pdfs(
    *,
    project_id: str,
    source_directory: Path,
    corpus_directory: Path,
    workspace: Path,
) -> CorpusManifest:
    """Parse every PDF in a project directory into reusable section artifacts."""
    source_directory = source_directory.resolve()
    corpus_directory = corpus_directory.resolve()
    workspace = workspace.resolve()
    pdf_paths = sorted(source_directory.glob("*.pdf"), key=lambda path: path.name.casefold())
    if not pdf_paths:
        raise FileNotFoundError(f"No PDF files found in {source_directory}")

    references: list[CorpusDocumentRef] = []
    for source_path in pdf_paths:
        parsed, artifact_path = _parse_document(
            project_id=project_id,
            source_path=source_path,
            output_root=corpus_directory,
            workspace=workspace,
        )
        references.append(
            CorpusDocumentRef(
                document_id=parsed.document_id,
                source_file_name=parsed.source_file_name,
                source_path=parsed.source_path,
                source_sha256=parsed.source_sha256,
                document_artifact=_safe_relative_path(artifact_path, workspace),
                page_count=parsed.summary.page_count,
                section_file_count=parsed.summary.section_file_count,
                review_required_pages=parsed.summary.review_required_pages,
            )
        )

    manifest_path = corpus_directory / "manifest.json"
    existing_manifest = None
    if manifest_path.exists():
        existing_manifest = CorpusManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    proposed_signature = [
        (reference.document_id, reference.source_sha256, reference.document_artifact)
        for reference in references
    ]
    existing_signature = (
        [
            (reference.document_id, reference.source_sha256, reference.document_artifact)
            for reference in existing_manifest.documents
        ]
        if existing_manifest is not None
        else None
    )
    if (
        existing_manifest is not None
        and existing_manifest.project_id == project_id
        and existing_manifest.parser_version == PARSER_VERSION
        and existing_signature == proposed_signature
    ):
        return existing_manifest

    manifest = CorpusManifest(
        project_id=project_id,
        parser_name=PARSER_NAME,
        parser_version=PARSER_VERSION,
        generated_at=datetime.now(timezone.utc),
        source_directory=_safe_relative_path(source_directory, workspace),
        documents=references,
    )
    _write_model(manifest_path, manifest)
    return manifest


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--corpus-dir", required=True, type=Path)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    return parser


def main() -> None:
    """CLI entry point for deterministic project PDF parsing."""
    args = _build_argument_parser().parse_args()
    manifest = parse_project_pdfs(
        project_id=args.project_id,
        source_directory=args.source_dir,
        corpus_directory=args.corpus_dir,
        workspace=args.workspace,
    )
    total_pages = sum(document.page_count for document in manifest.documents)
    total_sections = sum(document.section_file_count for document in manifest.documents)
    review_pages = sum(len(document.review_required_pages) for document in manifest.documents)
    print(
        json.dumps(
            {
                "project_id": manifest.project_id,
                "parser_version": manifest.parser_version,
                "documents": len(manifest.documents),
                "pages": total_pages,
                "section_files": total_sections,
                "review_required_pages": review_pages,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()


__all__ = ["parse_project_pdfs"]
