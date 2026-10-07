"""Persisted FAISS retrieval over existing page/section/block corpus artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import faiss
import numpy as np
from core.llm import estimate_text_tokens
from schemas.document import DocumentBlock, DocumentBlockType
from schemas.evidence_packet import (
    EvidencePacket,
    EvidencePacketDocument,
    EvidencePacketStats,
    EvidenceSelectionSummary,
    EvidenceTargetNode,
)
from schemas.retrieval import (
    RetrievalField,
    RetrievalFilters,
    RetrievalHit,
    RetrievalRequest,
    RetrievalTrace,
    VectorIndexMetadata,
)
from tools.evidence_input import EvidencePacketBinding, load_evidence_packet
from tools.evidence_packet import CorpusIndex, render_packet_text
from tools.embedding_provider import DashScopeEmbeddingProvider, EmbeddingProvider
from tools.retrieval_profiles import (
    PROFILE_VERSION,
    get_retrieval_profile,
    get_targeted_anchor_groups,
)


_EMBEDDING_TEXT_VERSION = "1.0"
_DEFAULT_EMBEDDING_INPUT_LIMIT = 7_500
_INDEX_FILE = "vectors.faiss"
_METADATA_FILE = "metadata.json"


@dataclass(frozen=True)
class LoadedVectorIndex:
    """Validated local index aligned to its current corpus blocks."""

    directory: Path
    metadata: VectorIndexMetadata
    corpus: CorpusIndex
    index: faiss.Index
    blocks: tuple[DocumentBlock, ...]


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(value: object) -> bytes:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def _resolve_inside_workspace(path: str | Path, workspace: Path) -> Path:
    candidate = Path(path)
    resolved = (workspace / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if not resolved.is_relative_to(workspace.resolve()):
        raise ValueError(f"Path escapes workspace: {path}")
    return resolved


def _embedding_text(block: DocumentBlock, source_file_name: str) -> str:
    return "\n".join(
        [
            f"Document: {source_file_name}",
            f"Section: {' > '.join(block.section_path)}",
            f"Type: {block.block_type.value}",
            block.text,
        ]
    )


def _index_identity(
    corpus: CorpusIndex,
    scope: EvidencePacketBinding,
    provider: EmbeddingProvider,
) -> str:
    identity = {
        "manifest_sha256": _sha256_bytes(corpus.manifest_bytes),
        "parser_version": corpus.manifest.parser_version,
        "scope_packet_sha256": scope.reference.packet_sha256,
        "embedding_model": provider.model_name,
        "embedding_dimensions": provider.dimensions,
        "embedding_text_version": _EMBEDDING_TEXT_VERSION,
    }
    return "IDX-" + _sha256_bytes(_json_bytes(identity))[:16].upper()


def _indexable_blocks(
    corpus: CorpusIndex,
    allowed_block_ids: set[str],
) -> list[DocumentBlock]:
    blocks = [
        block
        for block in corpus.blocks
        if block.block_id in allowed_block_ids
        and block.text.strip()
        and block.block_type != DocumentBlockType.UNRESOLVED_IMAGE
    ]
    if not blocks:
        raise ValueError("Corpus contains no indexable text blocks")
    return blocks


def _validate_source_files(corpus: CorpusIndex, document_ids: set[str]) -> None:
    """Reject an index whose source files no longer match the corpus manifest."""
    for reference in corpus.manifest.documents:
        if reference.document_id not in document_ids:
            continue
        source_path = _resolve_inside_workspace(reference.source_path, corpus.workspace)
        if not source_path.is_file():
            raise FileNotFoundError(f"Corpus source does not exist: {source_path}")
        if _sha256_file(source_path) != reference.source_sha256:
            raise ValueError(f"Corpus source hash mismatch: {reference.document_id}")


def build_vector_index(
    *,
    corpus: CorpusIndex,
    scope: EvidencePacketBinding,
    index_root: Path,
    provider: EmbeddingProvider,
) -> tuple[Path, VectorIndexMetadata, bool]:
    """Build or reuse a source-hash-versioned FAISS cosine index."""
    if scope.packet.project_id != corpus.manifest.project_id:
        raise ValueError("Index scope packet and corpus must share project_id")
    if scope.packet.manifest_sha256 != _sha256_bytes(corpus.manifest_bytes):
        raise ValueError("Index scope packet and corpus use different manifests")
    _validate_source_files(corpus, set(scope.documents))
    index_id = _index_identity(corpus, scope, provider)
    index_directory = index_root.resolve() / corpus.manifest.project_id / index_id
    metadata_path = index_directory / _METADATA_FILE
    faiss_path = index_directory / _INDEX_FILE
    if metadata_path.exists() or faiss_path.exists():
        if not metadata_path.is_file() or not faiss_path.is_file():
            raise ValueError(f"Incomplete vector index: {index_directory}")
        loaded = load_vector_index(index_directory=index_directory, workspace=corpus.workspace)
        return index_directory, loaded.metadata, True

    blocks = _indexable_blocks(corpus, set(scope.blocks))
    texts = []
    for block in blocks:
        reference = corpus.document_refs[block.document_id]
        text = _embedding_text(block, reference.source_file_name)
        token_count = estimate_text_tokens(text)
        if token_count > _DEFAULT_EMBEDDING_INPUT_LIMIT:
            raise ValueError(
                f"Block {block.block_id} requires {token_count} embedding tokens; "
                f"limit is {_DEFAULT_EMBEDDING_INPUT_LIMIT}. Split the source block before indexing."
            )
        texts.append(text)

    vectors = np.asarray(provider.embed_documents(texts), dtype="float32")
    if vectors.shape != (len(blocks), provider.dimensions):
        raise ValueError(
            f"Embedding matrix shape {vectors.shape} does not match "
            f"({len(blocks)}, {provider.dimensions})"
        )
    faiss.normalize_L2(vectors)
    vector_index = faiss.IndexFlatIP(provider.dimensions)
    vector_index.add(vectors)

    index_directory.mkdir(parents=True, exist_ok=False)
    temporary_faiss = faiss_path.with_suffix(".faiss.tmp")
    faiss.write_index(vector_index, str(temporary_faiss))
    temporary_faiss.replace(faiss_path)
    metadata = VectorIndexMetadata(
        index_id=index_id,
        project_id=corpus.manifest.project_id,
        manifest_path=str(corpus.manifest_path.relative_to(corpus.workspace)).replace("\\", "/"),
        manifest_sha256=_sha256_bytes(corpus.manifest_bytes),
        parser_name=corpus.manifest.parser_name,
        parser_version=corpus.manifest.parser_version,
        scope_packet_sha256=scope.reference.packet_sha256,
        scope_block_count=len(scope.blocks),
        embedding_model=provider.model_name,
        embedding_dimensions=provider.dimensions,
        embedding_text_version=_EMBEDDING_TEXT_VERSION,
        built_at=datetime.now(timezone.utc),
        block_ids=[block.block_id for block in blocks],
        faiss_sha256=_sha256_file(faiss_path),
    )
    _write_atomic(metadata_path, _json_bytes(metadata))
    return index_directory, metadata, False


def load_vector_index(*, index_directory: Path, workspace: Path) -> LoadedVectorIndex:
    """Load a local index and reject detached or modified index artifacts."""
    directory = index_directory.resolve()
    metadata_path = directory / _METADATA_FILE
    faiss_path = directory / _INDEX_FILE
    metadata = VectorIndexMetadata.model_validate_json(metadata_path.read_bytes())
    if directory.name != metadata.index_id:
        raise ValueError("Vector index directory does not match metadata index_id")
    if _sha256_file(faiss_path) != metadata.faiss_sha256:
        raise ValueError("FAISS index hash does not match metadata")

    corpus = CorpusIndex(manifest_path=Path(metadata.manifest_path), workspace=workspace.resolve())
    if _sha256_bytes(corpus.manifest_bytes) != metadata.manifest_sha256:
        raise ValueError("Vector index manifest hash does not match the current corpus")
    if corpus.manifest.project_id != metadata.project_id:
        raise ValueError("Vector index project does not match corpus project")
    if corpus.manifest.parser_version != metadata.parser_version:
        raise ValueError("Vector index parser version does not match corpus parser version")

    try:
        blocks = tuple(corpus.blocks_by_id[block_id] for block_id in metadata.block_ids)
    except KeyError as exc:
        raise ValueError(f"Vector index references an unknown corpus block: {exc.args[0]}") from exc
    _validate_source_files(corpus, {block.document_id for block in blocks})
    vector_index = faiss.read_index(str(faiss_path))
    if vector_index.ntotal != len(blocks) or vector_index.d != metadata.embedding_dimensions:
        raise ValueError("FAISS dimensions/count do not match metadata")
    return LoadedVectorIndex(
        directory=directory,
        metadata=metadata,
        corpus=corpus,
        index=vector_index,
        blocks=blocks,
    )


def _matches_filters(block: DocumentBlock, filters: RetrievalFilters) -> bool:
    if filters.document_ids and block.document_id not in filters.document_ids:
        return False
    if filters.block_types and block.block_type not in filters.block_types:
        return False
    if filters.exclude_review_required and block.needs_review:
        return False
    if filters.section_path_terms:
        section = " > ".join(block.section_path).casefold()
        if not any(term.casefold() in section for term in filters.section_path_terms):
            return False
    return True


def _allowed_blocks_for_node(
    scope: EvidencePacketBinding,
    node_id: EvidenceTargetNode,
) -> set[str]:
    """Honor the reviewed target_nodes attached to the static packet selections."""
    allowed: set[str] = set()
    for summary in scope.packet.selection_summaries:
        if node_id not in summary.target_nodes:
            continue
        section_ids = set(summary.section_ids)
        pdf_pages = set(summary.pdf_pages)
        for block in scope.packet.blocks:
            if (
                block.document_id == summary.document_id
                and block.section_id in section_ids
                and block.pdf_page in pdf_pages
            ):
                allowed.add(block.block_id)
    if not allowed:
        raise ValueError(f"Approved scope contains no selections for {node_id.value}")
    return allowed


def _ordered_unique(values: Sequence[object]) -> list[object]:
    return list(dict.fromkeys(values))


def _safe_identifier(value: str) -> str:
    result = re.sub(r"[^a-z0-9_-]+", "_", value.casefold()).strip("_-")
    return result or "project"


def _lexical_score(
    *,
    block: DocumentBlock,
    source_file_name: str,
    query: str,
) -> float:
    """Add a small exact-term signal to stabilize field-specific dense retrieval."""
    terms = [term.casefold() for term in query.split() if len(term.strip()) >= 2]
    if not terms:
        return 0.0
    searchable = " ".join(
        [source_file_name, " > ".join(block.section_path), block.text]
    ).casefold()
    return sum(term in searchable for term in terms) / len(terms)


def _promote_targeted_anchors(
    ranked: list[tuple[DocumentBlock, float]],
    *,
    source_names: dict[str, str],
    anchor_groups: tuple[tuple[str, ...], ...],
) -> list[tuple[DocumentBlock, float]]:
    """Place one best dense-ranked block for each reviewed anchor group first."""
    promoted: list[tuple[DocumentBlock, float]] = []
    promoted_ids: set[str] = set()
    for group in anchor_groups:
        terms = tuple(term.casefold() for term in group)
        for item in ranked:
            block = item[0]
            searchable = " ".join(
                [
                    source_names[block.document_id],
                    " > ".join(block.section_path),
                    block.text,
                ]
            ).casefold()
            if all(term in searchable for term in terms):
                if block.block_id not in promoted_ids:
                    promoted.append(item)
                    promoted_ids.add(block.block_id)
                break
    return promoted + [item for item in ranked if item[0].block_id not in promoted_ids]


def _materialize_packet(
    *,
    loaded: LoadedVectorIndex,
    scope: EvidencePacketBinding,
    request: RetrievalRequest,
    blocks: Sequence[DocumentBlock],
) -> EvidencePacket:
    config_payload = {
        "profile_version": PROFILE_VERSION,
        "index_id": loaded.metadata.index_id,
        "scope_packet_sha256": scope.reference.packet_sha256,
        "request": request.model_dump(mode="json"),
        "selected_block_ids": [block.block_id for block in blocks],
    }
    anchor_groups = get_targeted_anchor_groups(request.node_id, request.field_id)
    if anchor_groups:
        config_payload["targeted_anchor_groups"] = [
            list(group) for group in anchor_groups
        ]
    config_sha256 = _sha256_bytes(_json_bytes(config_payload))
    packet_id = "_".join(
        [
            "rag",
            _safe_identifier(request.project_id),
            request.node_id.value,
            request.field_id.value,
            config_sha256[:12],
        ]
    )

    corpus_position = {block.block_id: position for position, block in enumerate(loaded.corpus.blocks)}
    ordered_blocks = sorted(blocks, key=lambda block: corpus_position[block.block_id])
    blocks_by_document: dict[str, list[DocumentBlock]] = {}
    for block in ordered_blocks:
        blocks_by_document.setdefault(block.document_id, []).append(block)

    documents = []
    summaries = []
    for document_number, reference in enumerate(loaded.corpus.manifest.documents, start=1):
        document_blocks = blocks_by_document.get(reference.document_id, [])
        if not document_blocks:
            continue
        source_document = scope.documents[reference.document_id]
        section_pairs = _ordered_unique(
            [(block.section_id, tuple(block.section_path)) for block in document_blocks]
        )
        documents.append(
            EvidencePacketDocument(
                document_id=source_document.document_id,
                source_file_name=source_document.source_file_name,
                source_path=source_document.source_path,
                source_sha256=source_document.source_sha256,
                parser_version=source_document.parser_version,
                selected_section_ids=_ordered_unique(
                    [block.section_id for block in document_blocks]
                ),
                selected_pdf_pages=_ordered_unique(
                    [block.pdf_page for block in document_blocks]
                ),
                selected_block_count=len(document_blocks),
            )
        )
        summaries.append(
            EvidenceSelectionSummary(
                selection_id=(
                    f"SEL-RAG-{request.node_id.value}-{request.field_id.value}-{document_number}"
                ).upper(),
                document_id=reference.document_id,
                section_ids=[pair[0] for pair in section_pairs],
                section_paths=[list(pair[1]) for pair in section_pairs],
                pdf_pages=_ordered_unique([block.pdf_page for block in document_blocks]),
                block_count=len(document_blocks),
                character_count=sum(len(block.text) for block in document_blocks),
                rationale=(
                    f"Retrieved for {request.node_id.value}/{request.field_id.value} "
                    f"under index {loaded.metadata.index_id}."
                ),
                target_nodes=[request.node_id],
            )
        )

    return EvidencePacket(
        schema_version="1.0",
        packet_id=packet_id,
        packet_version=1,
        project_id=request.project_id,
        purpose=f"Bounded evidence for {request.node_id.value}/{request.field_id.value}.",
        manifest_path=loaded.metadata.manifest_path,
        manifest_sha256=loaded.metadata.manifest_sha256,
        config_sha256=config_sha256,
        parser_name=loaded.metadata.parser_name,
        parser_version=loaded.metadata.parser_version,
        documents=documents,
        selection_summaries=summaries,
        known_gaps=scope.packet.known_gaps,
        stats=EvidencePacketStats(
            document_count=len(documents),
            section_count=len({(block.document_id, block.section_id) for block in ordered_blocks}),
            page_count=len({(block.document_id, block.pdf_page) for block in ordered_blocks}),
            block_count=len(ordered_blocks),
            character_count=sum(len(block.text) for block in ordered_blocks),
            table_count=sum(block.block_type == DocumentBlockType.TABLE for block in ordered_blocks),
            review_block_count=sum(block.needs_review for block in ordered_blocks),
        ),
        blocks=ordered_blocks,
    )


def _validate_retrieval_boundary(
    loaded: LoadedVectorIndex,
    scope: EvidencePacketBinding,
    request: RetrievalRequest,
    provider: EmbeddingProvider,
) -> None:
    if request.project_id != loaded.metadata.project_id or request.project_id != scope.packet.project_id:
        raise ValueError("Retrieval request, index, and scope packet must share project_id")
    if scope.packet.manifest_sha256 != loaded.metadata.manifest_sha256:
        raise ValueError("Retrieval scope packet and vector index use different corpus manifests")
    if scope.reference.packet_sha256 != loaded.metadata.scope_packet_sha256:
        raise ValueError("Retrieval scope packet does not match the vector index scope")
    if provider.model_name != loaded.metadata.embedding_model:
        raise ValueError("Embedding provider model does not match vector index")
    if provider.dimensions != loaded.metadata.embedding_dimensions:
        raise ValueError("Embedding provider dimensions do not match vector index")
    unknown_documents = set(request.filters.document_ids) - set(scope.documents)
    if unknown_documents:
        raise ValueError(
            f"Retrieval filters reference documents outside the approved scope: {sorted(unknown_documents)}"
        )


def retrieve_evidence(
    *,
    loaded: LoadedVectorIndex,
    scope: EvidencePacketBinding,
    request: RetrievalRequest,
    provider: EmbeddingProvider,
) -> tuple[EvidencePacket, RetrievalTrace]:
    """Retrieve, expand, budget, and materialize one field-specific packet."""
    _validate_retrieval_boundary(loaded, scope, request, provider)
    profile = get_retrieval_profile(request.node_id, request.field_id)
    allowed_block_ids = _allowed_blocks_for_node(scope, request.node_id)
    effective_query = profile.query
    if request.field_id == RetrievalField.PRODUCT_IDENTITY:
        document_ids = {
            scope.blocks[block_id].document_id for block_id in allowed_block_ids
        }
        source_names = [
            scope.documents[document_id].source_file_name
            for document_id in sorted(document_ids)
        ]
        effective_query += "\n当前产品证据文件名：" + " ".join(source_names)
    if request.query:
        effective_query += "\n项目补充检索意图：" + request.query.strip()

    query_vector = np.asarray([provider.embed_query(effective_query)], dtype="float32")
    if query_vector.shape != (1, loaded.metadata.embedding_dimensions):
        raise ValueError("Query embedding dimensions do not match vector index")
    faiss.normalize_L2(query_vector)
    scores, positions = loaded.index.search(query_vector, loaded.index.ntotal)

    ranked = []
    for score, position in zip(scores[0], positions[0]):
        if position < 0:
            continue
        block = loaded.blocks[int(position)]
        if block.block_id not in allowed_block_ids or not _matches_filters(block, request.filters):
            continue
        source_name = loaded.corpus.document_refs[block.document_id].source_file_name
        exact_score = _lexical_score(
            block=block,
            source_file_name=source_name,
            query=effective_query,
        )
        combined_score = 0.80 * float(score) + 0.20 * exact_score
        ranked.append((block, combined_score))
    ranked.sort(key=lambda item: item[1], reverse=True)
    if not ranked:
        raise ValueError("Retrieval produced no blocks inside the approved scope and metadata filters")
    anchor_groups = get_targeted_anchor_groups(request.node_id, request.field_id)
    if anchor_groups:
        ranked = _promote_targeted_anchors(
            ranked,
            source_names={
                document_id: reference.source_file_name
                for document_id, reference in loaded.corpus.document_refs.items()
            },
            anchor_groups=anchor_groups,
        )

    corpus_positions = {
        block.block_id: position for position, block in enumerate(loaded.corpus.blocks)
    }
    candidates: list[tuple[DocumentBlock, float, bool, str | None]] = []
    seen: set[str] = set()
    for seed, score in ranked:
        if len(candidates) >= request.max_blocks:
            break
        if seed.block_id not in seen:
            candidates.append((seed, score, False, None))
            seen.add(seed.block_id)
        seed_position = corpus_positions[seed.block_id]
        for distance in range(1, request.neighbor_window + 1):
            for neighbor_position in (seed_position - distance, seed_position + distance):
                if len(candidates) >= request.max_blocks:
                    break
                if not 0 <= neighbor_position < len(loaded.corpus.blocks):
                    continue
                neighbor = loaded.corpus.blocks[neighbor_position]
                if (
                    neighbor.document_id != seed.document_id
                    or neighbor.section_id != seed.section_id
                    or neighbor.block_id in seen
                    or neighbor.block_id not in allowed_block_ids
                    or not _matches_filters(neighbor, request.filters)
                ):
                    continue
                candidates.append((neighbor, score, True, seed.block_id))
                seen.add(neighbor.block_id)

    selected: list[tuple[DocumentBlock, float, bool, str | None]] = []
    selected_token_count = 0
    truncated_by_budget = False
    for candidate in candidates:
        trial = selected + [candidate]
        trial_packet = _materialize_packet(
            loaded=loaded,
            scope=scope,
            request=request,
            blocks=[item[0] for item in trial],
        )
        trial_tokens = estimate_text_tokens(render_packet_text(trial_packet))
        if trial_tokens > request.token_budget:
            truncated_by_budget = True
            continue
        selected = trial
        selected_token_count = trial_tokens
    if not selected:
        first = candidates[0][0]
        raise ValueError(
            f"Token budget {request.token_budget} cannot fit the first intact block {first.block_id}; "
            "increase the budget or improve source block granularity."
        )

    packet = _materialize_packet(
        loaded=loaded,
        scope=scope,
        request=request,
        blocks=[item[0] for item in selected],
    )
    packet_bytes = _json_bytes(packet)
    hits = []
    for rank, (block, score, is_neighbor, seed_block_id) in enumerate(selected, start=1):
        source_name = loaded.corpus.document_refs[block.document_id].source_file_name
        hits.append(
            RetrievalHit(
                block_id=block.block_id,
                document_id=block.document_id,
                rank=rank,
                score=score,
                estimated_tokens=estimate_text_tokens(_embedding_text(block, source_name)),
                is_neighbor=is_neighbor,
                seed_block_id=seed_block_id,
            )
        )
    trace = RetrievalTrace(
        request=request,
        effective_query=effective_query,
        index_id=loaded.metadata.index_id,
        scope_packet_sha256=scope.reference.packet_sha256,
        packet_id=packet.packet_id,
        packet_sha256=_sha256_bytes(packet_bytes),
        candidate_count=len(ranked),
        selected_count=len(selected),
        selected_token_count=selected_token_count,
        truncated_by_budget=truncated_by_budget,
        truncated_by_max_blocks=len(ranked) > request.max_blocks,
        hits=hits,
    )
    return packet, trace


def write_retrieval_outputs(
    *,
    packet: EvidencePacket,
    trace: RetrievalTrace,
    packet_path: Path,
    trace_path: Path,
) -> None:
    """Persist one packet/trace pair after verifying their shared hash."""
    packet_bytes = _json_bytes(packet)
    if _sha256_bytes(packet_bytes) != trace.packet_sha256:
        raise ValueError("Retrieval trace does not match packet content")
    _write_atomic(packet_path, packet_bytes)
    _write_atomic(trace_path, _json_bytes(trace))


def _provider(*, query_cache_dir: Path | None = None) -> DashScopeEmbeddingProvider:
    return DashScopeEmbeddingProvider(query_cache_dir=query_cache_dir)


def _build_command(args: argparse.Namespace) -> None:
    workspace = args.workspace.resolve()
    corpus = CorpusIndex(manifest_path=args.manifest, workspace=workspace)
    scope = load_evidence_packet(args.scope_packet, workspace=workspace, verify_source_files=True)
    index_root = _resolve_inside_workspace(args.index_root, workspace)
    directory, metadata, reused = build_vector_index(
        corpus=corpus,
        scope=scope,
        index_root=index_root,
        provider=_provider(),
    )
    print(
        json.dumps(
            {
                "index_dir": str(directory),
                "index_id": metadata.index_id,
                "block_count": len(metadata.block_ids),
                "reused": reused,
            },
            ensure_ascii=False,
        )
    )


def _query_command(args: argparse.Namespace) -> None:
    workspace = args.workspace.resolve()
    loaded = load_vector_index(
        index_directory=_resolve_inside_workspace(args.index_dir, workspace),
        workspace=workspace,
    )
    scope = load_evidence_packet(args.scope_packet, workspace=workspace, verify_source_files=True)
    filters = RetrievalFilters(
        document_ids=tuple(args.document_id or ()),
        section_path_terms=tuple(args.section_term or ()),
        block_types=tuple(args.block_type or ()),
        exclude_review_required=args.exclude_review_required,
    )
    request = RetrievalRequest(
        project_id=scope.packet.project_id,
        node_id=args.node_id,
        field_id=args.field_id,
        query=args.query,
        filters=filters,
        token_budget=args.token_budget,
        max_blocks=args.max_blocks,
        neighbor_window=args.neighbor_window,
    )
    packet, trace = retrieve_evidence(
        loaded=loaded,
        scope=scope,
        request=request,
        provider=_provider(query_cache_dir=loaded.directory / "query_embeddings"),
    )
    packet_path = _resolve_inside_workspace(args.packet_output, workspace)
    trace_path = _resolve_inside_workspace(args.trace_output, workspace)
    write_retrieval_outputs(
        packet=packet,
        trace=trace,
        packet_path=packet_path,
        trace_path=trace_path,
    )
    print(trace.model_dump_json())


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="Build or reuse a persisted corpus index")
    build.add_argument("--manifest", required=True, type=Path)
    build.add_argument("--scope-packet", required=True, type=Path)
    build.add_argument("--workspace", type=Path, default=Path.cwd())
    build.add_argument("--index-root", type=Path, default=Path("rag_index"))
    build.set_defaults(handler=_build_command)

    query = subparsers.add_parser("query", help="Retrieve one Node/field evidence packet")
    query.add_argument("--index-dir", required=True, type=Path)
    query.add_argument("--scope-packet", required=True, type=Path)
    query.add_argument("--node-id", required=True, type=EvidenceTargetNode)
    query.add_argument("--field-id", required=True, type=RetrievalField)
    query.add_argument("--query")
    query.add_argument("--document-id", action="append")
    query.add_argument("--section-term", action="append")
    query.add_argument("--block-type", action="append", type=DocumentBlockType)
    query.add_argument("--exclude-review-required", action="store_true")
    query.add_argument("--token-budget", type=int, default=12_000)
    query.add_argument("--max-blocks", type=int, default=24)
    query.add_argument("--neighbor-window", type=int, default=1)
    query.add_argument("--packet-output", required=True, type=Path)
    query.add_argument("--trace-output", required=True, type=Path)
    query.add_argument("--workspace", type=Path, default=Path.cwd())
    query.set_defaults(handler=_query_command)
    return parser


def main() -> None:
    args = _argument_parser().parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()


__all__ = [
    "DashScopeEmbeddingProvider",
    "EmbeddingProvider",
    "LoadedVectorIndex",
    "build_vector_index",
    "load_vector_index",
    "retrieve_evidence",
    "write_retrieval_outputs",
]
