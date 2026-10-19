"""Recover the saved Node2 review export offline; no model calls or source writes."""

from hashlib import sha256
import json
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def no_network(*args, **kwargs):
    raise RuntimeError('This export recovery is offline; network access is prohibited')


socket.create_connection = no_network
socket.getaddrinfo = no_network
socket.socket.connect = no_network

from core.exporter import export_asset_review, validate_asset_review_artifacts
from core.run_manifest import initialize_run_manifest, record_run_status
from nodes.asset_threat_modeler import _align_asset_scope_status
from schemas.legal import ScopeStatement
from schemas.methodology import RiskMethodology
from schemas.product import Asset, ProductContext
from schemas.risk import RiskAcceptanceCriteria
from schemas.run_input import EvidencePacketRef
from tools.evidence_input import load_evidence_packet, validate_evidence_bindings


source_id = 'emu-node2-resume-qwen38max-20261019-01'
run_id = source_id + '-export-fix'
source = ROOT / 'output' / source_id
destination = ROOT / 'output' / run_id
if destination.exists():
    raise SystemExit(f'Output already exists; refusing overwrite: {destination}')
cache = ROOT / 'project_artifacts/yangguang_emu/runs' / source_id / 'asset_sections'
protected = [*source.glob('*.*'), *cache.glob('*.json'), ROOT / 'CRA_TARA_workflow_prEN40000.md']
protected.extend((ROOT / 'output/emu-node012-qwen38max-20261015-01').glob('*.*'))
before = {p: sha256(p.read_bytes()).hexdigest() for p in protected}
raw = json.loads((source / 'report.json').read_text(encoding='utf-8'))['state']
manifest = json.loads((source / 'run_manifest.json').read_text(encoding='utf-8'))
assert raw['status'] == 'asset_identification_partial_draft'
assert raw['asset_review_approved'] is False and raw.get('threat_assessment') is None
state = {**raw,
    'evidence_packet_ref': EvidencePacketRef.model_validate(raw['evidence_packet_ref']),
    'scope': ScopeStatement.model_validate(raw['scope']),
    'product_context': ProductContext.model_validate(raw['product_context']),
    'risk_methodology': RiskMethodology.model_validate(raw['risk_methodology']),
    'risk_acceptance_criteria': RiskAcceptanceCriteria.model_validate(raw['risk_acceptance_criteria']),
}
state['assets'] = []
changes = []
for original in raw['assets']:
    asset = Asset.model_validate(original)
    repaired, _ = _align_asset_scope_status(asset, scope=state['scope'], product_context=state['product_context'])
    if repaired != asset:
        expected = asset.model_dump(mode='json')
        for objective in expected['related_objectives']:
            if objective['status'] == 'supported':
                objective['status'] = 'needs_confirmation'
                changes.append((asset.asset_id, objective['objective_id']))
        assert repaired.model_dump(mode='json') == expected, 'Unexpected product-data change'
    state['assets'].append(repaired)
assert changes == [('ASSET-028', 'OBJ-041'), ('ASSET-028', 'OBJ-042')], changes
state['asset_notes'] = (state.get('asset_notes') or '') + (
    '\n离线导出恢复：核心交换机 ASSET-028 已为待确认，其 OBJ-041、OBJ-042 支持状态同步为待确认；'
    '仅修复范围对齐后的状态不一致，未重新调用模型，未改变目标内容、依据或证据，未人工批准。')
binding = load_evidence_packet(ROOT / 'project_artifacts/yangguang_emu/evidence_packets/node_0_3_v2.json',
    workspace=ROOT, verify_source_files=True)
assert binding.reference == state['evidence_packet_ref']
validate_evidence_bindings(state, binding)
provenance = dict(manifest['provenance'])
provenance.update(operation='offline_review_export_recovery', new_llm_calls=0,
    recovery_script_sha256=sha256(Path(__file__).read_bytes()).hexdigest())
provenance['source_sha256'] = dict(provenance['source_sha256'])
provenance['source_sha256']['nodes/asset_threat_modeler.py'] = sha256(
    (ROOT / 'nodes/asset_threat_modeler.py').read_bytes()).hexdigest()
initialize_run_manifest(run_directory=destination, run_id=run_id, project_id=manifest['project_id'],
    evidence_packet_ref=manifest['evidence_packet_ref'], text_model=manifest['text_model'],
    requested_node='2-export-only', rule_versions={**manifest['rule_versions'], 'export_recovery': 'scope_objective_consistency.v1'},
    upstream={'completed_node_2': {'run_id': source_id, 'output_json': str(source / 'report.json'),
        'output_json_sha256': before[source / 'report.json'], 'business_reviewed': False}}, provenance=provenance)
paths = export_asset_review(state, destination, run_id)
summary = validate_asset_review_artifacts(*paths)
record_run_status(destination, state['status'], awaiting_review=True)
path = destination / 'run_manifest.json'
result_manifest = json.loads(path.read_text(encoding='utf-8'))
result_manifest['outputs'] = {p.name: sha256(p.read_bytes()).hexdigest() for p in paths}
result_manifest['offline_status_corrections'] = [{'asset_id': a, 'objective_id': o,
    'from': 'supported', 'to': 'needs_confirmation'} for a, o in changes]
path.write_text(json.dumps(result_manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
assert before == {p: sha256(p.read_bytes()).hexdigest() for p in protected}
print('OFFLINE_EXPORT_OK', json.dumps(summary, ensure_ascii=False))
print('ONLY_STATUS_CORRECTIONS', changes)
print('ORIGINAL_FILES_UNCHANGED', True)
print('NEW_LLM_CALLS', 0)
print('OUTPUT', destination)
