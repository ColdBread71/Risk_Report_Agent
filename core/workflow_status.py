"""Shared workflow statuses whose meaning crosses node and export boundaries."""

from collections.abc import Mapping
from typing import Any

from schemas.common import AssessmentVerdict

ASSET_IDENTIFICATION_BLOCKED = "asset_identification_blocked"
ASSET_IDENTIFICATION_COMPLETED = "asset_identification_completed"
ASSET_IDENTIFICATION_FAILED = "asset_identification_failed"
ASSET_IDENTIFICATION_PARTIAL_DRAFT = "asset_identification_partial_draft"
ASSET_IDENTIFICATION_TECHNICAL_INCOMPLETE = (
    "asset_identification_technical_incomplete"
)

ASSET_REVIEWABLE_STATUSES = frozenset(
    {
        ASSET_IDENTIFICATION_COMPLETED,
        ASSET_IDENTIFICATION_PARTIAL_DRAFT,
    }
)


def resolve_asset_identification_status(
    assessment: AssessmentVerdict | str | None,
    *,
    technical_incomplete: bool,
    asset_count: int,
) -> str:
    """Derive one truthful Node [2] status from content and runtime completeness."""
    if asset_count <= 0:
        return ASSET_IDENTIFICATION_FAILED
    if technical_incomplete:
        return ASSET_IDENTIFICATION_TECHNICAL_INCOMPLETE
    value = getattr(assessment, "value", assessment)
    if value == AssessmentVerdict.PASS.value:
        return ASSET_IDENTIFICATION_COMPLETED
    if value == AssessmentVerdict.PARTIAL.value:
        return ASSET_IDENTIFICATION_PARTIAL_DRAFT
    return ASSET_IDENTIFICATION_FAILED


def is_asset_reviewable_state(state: Mapping[str, Any]) -> bool:
    """Reject cross-layer status/assessment mismatches before review or export."""
    assets = state.get("assets") or []
    status = state.get("status")
    assessment = getattr(
        state.get("asset_assessment"),
        "value",
        state.get("asset_assessment"),
    )
    expected = resolve_asset_identification_status(
        assessment,
        technical_incomplete=False,
        asset_count=len(assets),
    )
    return status in ASSET_REVIEWABLE_STATUSES and status == expected
