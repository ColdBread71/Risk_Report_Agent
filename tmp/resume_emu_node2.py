"""One-off recovery; default is offline validation, --execute permits LLM calls."""

import argparse
from functools import partial
from hashlib import sha256
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
from langchain_openai import ChatOpenAI
from openai import APIConnectionError

from core.exporter import export_asset_review, export_workflow_progress, validate_asset_review_artifacts
from core.run_manifest import initialize_run_manifest, record_run_status
from core.workflow import node2_graph
from core.workflow_status import ASSET_REVIEWABLE_STATUSES
from main import _configured_text_model, _log_result, _run_with_progress
from nodes import asset_threat_modeler as node
from nodes.field_extractor import NodeFactBundle, _cache_inputs, _load_field_checkpoint
from schemas.evidence_packet import EvidenceTargetNode
from schemas.legal import ScopeStatement
from schemas.methodology import RiskMethodology
from schemas.product import ProductContext
from schemas.retrieval import RetrievalTrace
from schemas.risk import RiskAcceptanceCriteria
from tools.evidence_input import bind_materialized_packet, load_evidence_packet
from tools.rag_retriever import _json_bytes, _materialize_packet, load_vector_index
from tools.retrieval_profiles import get_profiles_for_node


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--run-id', default='emu-node2-resume-qwen38max-20261019-01')
    args = parser.parse_args()
    import re
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', args.run_id):
        raise ValueError('Invalid run-id')
    source_id = 'emu-node012-qwen38max-20261015-01'
    source = ROOT / 'output' / source_id
    report_path = source / 'report.json'
    manifest_path = source / 'run_manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    report = json.loads(report_path.read_text(encoding='utf-8'))
    raw = report['state']
    model = 'qwen3.8-max-0902'
    # The expensive recovery has already finished if its separately repaired
    # review package exists. Validate and show it; do not re-enter generation.
    completed = ROOT / 'output' / (args.run_id + '-export-fix')
    if completed.exists():
        saved = json.loads((completed / 'run_manifest.json').read_text(encoding='utf-8'))
        upstream = saved.get('upstream', {}).get('completed_node_2', {})
        resumed_report = ROOT / 'output' / args.run_id / 'report.json'
        if not (
            saved.get('run_id') == completed.name
            and saved.get('requested_node') == '2-export-only'
            and saved.get('text_model') == manifest.get('text_model') == model
            and saved.get('evidence_packet_ref') == manifest.get('evidence_packet_ref')
            and saved.get('status') in ASSET_REVIEWABLE_STATUSES
            and upstream.get('run_id') == args.run_id
            and upstream.get('output_json_sha256') == sha256(resumed_report.read_bytes()).hexdigest()
        ):
            raise ValueError('Existing completed result identity mismatch; no model call allowed')
        for name in ('report.json', 'report.xlsx'):
            if sha256((completed / name).read_bytes()).hexdigest() != saved.get('outputs', {}).get(name):
                raise ValueError(f'Existing completed result hash mismatch: {name}; no model call allowed')
        payload = json.loads((completed / 'report.json').read_text(encoding='utf-8'))
        if not (payload.get('run_id') == completed.name
                and payload.get('evidence_packet_ref') == saved.get('evidence_packet_ref')
                and payload.get('workflow_status') == saved.get('status')
                and payload.get('awaiting_asset_approval') is True):
            raise ValueError('Existing completed report identity mismatch; no model call allowed')
        summary = validate_asset_review_artifacts(completed / 'report.json', completed / 'report.xlsx')
        print('Node2 已完成；现有审核包校验通过，本次未调用模型。')
        print(f'资产 {summary["asset_count"]} 项，保护目标 {summary["objective_count"]} 项；仍待人工复核。')
        print(f'JSON: {completed / "report.json"}')
        print(f'Excel: {completed / "report.xlsx"}')
        return 0
    if not (manifest['run_id'] == report['run_id'] == source_id
            and manifest['text_model'] == _configured_text_model() == model
            and report['completed_node'] == 'build_product_context'
            and raw['status'] == manifest['status'] == 'node_1_completed'):
        raise ValueError('Source identity/status/model does not match; no LLM request made')
    for relative, expected in manifest['provenance']['source_sha256'].items():
        if sha256((ROOT / relative).read_bytes()).hexdigest() != expected:
            raise ValueError(f'Source code changed since original run: {relative}')
    packet_path = ROOT / 'project_artifacts/yangguang_emu/evidence_packets/node_0_3_v2.json'
    binding = load_evidence_packet(packet_path, workspace=ROOT, verify_source_files=True)
    if not (binding.reference.model_dump(mode='json') == raw['evidence_packet_ref']
            == manifest['evidence_packet_ref']):
        raise ValueError('Evidence packet mismatch')
    state = {
        'evidence_packet_ref': binding.reference,
        'scope': ScopeStatement.model_validate(raw['scope']),
        'product_context': ProductContext.model_validate(raw['product_context']),
        'risk_methodology': RiskMethodology.model_validate(raw['risk_methodology']),
        'risk_acceptance_criteria': RiskAcceptanceCriteria.model_validate(raw['risk_acceptance_criteria']),
        'errors': list(raw.get('errors', [])), 'status': raw['status'],
        'assets': [], 'asset_review_approved': False, 'threat_assessment': None,
    }
    source_cache = ROOT / 'project_artifacts' / manifest['project_id'] / 'runs' / source_id
    index = load_vector_index(index_directory=Path(manifest['provenance']['rag_index']), workspace=ROOT)
    batches, traces, field_paths = [], [], []
    for profile in get_profiles_for_node(EvidenceTargetNode.ASSETS):
        path = source_cache / 'field_facts/node_2' / (profile.field_id.value + '.json')
        cached = json.loads(path.read_text(encoding='utf-8'))
        trace = RetrievalTrace.model_validate(cached['retrieval_trace'])
        if trace.request.field_id != profile.field_id or trace.index_id != index.metadata.index_id:
            raise ValueError(f'Field/index identity mismatch: {path.name}')
        packet = _materialize_packet(loaded=index, scope=binding, request=trace.request,
            blocks=[index.corpus.blocks_by_id[h.block_id] for h in trace.hits])
        if sha256(_json_bytes(packet)).hexdigest() != trace.packet_sha256:
            raise ValueError(f'Retrieved input changed: {path.name}')
        expected = _cache_inputs(request=trace.request, trace=trace, text_model=model, profile=profile)
        result, reason = _load_field_checkpoint(path, request=trace.request,
            binding=bind_materialized_packet(packet), cache_inputs=expected, max_facts=profile.max_facts)
        if result is None:
            raise ValueError(f'Cannot reuse {path.name}: {reason}; no field regeneration allowed')
        batches.append(result)
        traces.append(trace)
        field_paths.append(path)
    facts = NodeFactBundle(batches=tuple(batches), traces=tuple(traces),
        retrieved_block_ids=frozenset(h.block_id for t in traces for h in t.hits))
    destination = ROOT / 'output' / args.run_id
    cache = ROOT / 'project_artifacts' / manifest['project_id'] / 'runs' / args.run_id
    if destination.exists() or cache.exists():
        raise ValueError('Target run-id already exists; use --run-id with a new value')
    print(f'Preflight OK: Node1 snapshot + {len(batches)} cached Node2 fields; model={model}')
    print(f'New output: {destination}')
    if not args.execute:
        print('Offline validation only. Add --execute to run the 3 synthesis sections and mapping.')
        return 0

    upstream = {
        'run_id': source_id, 'snapshot': str(report_path),
        'snapshot_sha256': sha256(report_path.read_bytes()).hexdigest(),
        'manifest_sha256': sha256(manifest_path.read_bytes()).hexdigest(),
        'business_reviewed': False,
        'field_sha256': {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest() for p in field_paths},
    }
    initialize_run_manifest(run_directory=destination, run_id=args.run_id,
        project_id=manifest['project_id'], evidence_packet_ref=manifest['evidence_packet_ref'],
        text_model=model, requested_node='2', rule_versions=manifest['rule_versions'],
        upstream={'restored_node_1_and_node_2_fields': upstream},
        provenance={**manifest['provenance'], 'mode': 'resume_node2_only', 'cache_policy': 'reuse',
            'recovery_script_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
            'read_timeout_seconds': 1800, 'sdk_max_retries': 0})
    config = {'configurable': {
        'thread_id': args.run_id, 'workspace': str(ROOT),
        'evidence_packet_path': str(packet_path), 'rag_index_dir': str(index.directory),
        'extraction_log_dir': str(destination / 'diagnostics'),
        'asset_section_checkpoint_dir': str(cache / 'asset_sections'),
        'asset_section_cache_policy': 'reuse',
    }}
    export_workflow_progress(state, destination, args.run_id, 'restore_node1_snapshot')
    record_run_status(destination, state['status'])
    factory = node.get_llm

    class StopOnTransportFailure:
        model_name = model

        def __init__(self):
            self.delegate = factory()

        def invoke(self, prompt):
            try:
                return self.delegate.invoke(prompt)
            except APIConnectionError as exc:
                raise SystemExit('LLM timeout/connection failure: stopped without retry. '
                    'Successful sections remain saved in the NEW run cache.') from exc

    with patch('core.llm.ChatOpenAI', partial(ChatOpenAI,
            timeout=httpx.Timeout(connect=30, read=1800, write=60, pool=60), max_retries=0)), \
         patch.object(node, 'get_llm', StopOnTransportFailure), \
         patch.object(node, 'extract_node_facts', return_value=facts):
        result = _run_with_progress(node2_graph, state, config, destination, args.run_id)
    _log_result(result)
    if result.get('status') in ASSET_REVIEWABLE_STATUSES and result.get('__interrupt__'):
        export_asset_review(result, destination, args.run_id)
        print(f'Node2 draft saved: {destination}; awaiting human review. Node3 was not run.')
        return 0
    print(f'Node2 did not reach review; inspect NEW run diagnostics: {destination}')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
