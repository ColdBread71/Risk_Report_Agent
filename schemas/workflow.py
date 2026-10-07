"""
Workflow metadata and orchestration support models.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class NodeExecutionRecord(BaseModel):
    """Execution record for one workflow node."""

    node_id: str = Field(..., description="Workflow node identifier.")
    started_at: datetime = Field(default_factory=datetime.utcnow, description="Node start time.")
    finished_at: Optional[datetime] = Field(default=None, description="Node finish time.")
    status: str = Field(default="pending", description="Node status, e.g., pending, running, completed, failed, interrupted.")
    input_ref: Optional[str] = Field(default=None, description="Reference to the node input artifact.")
    output_ref: Optional[str] = Field(default=None, description="Reference to the node output artifact.")
    notes: Optional[str] = Field(default=None, description="Execution notes.")


class HumanReviewRequest(BaseModel):
    """Human-in-the-loop review request."""

    review_id: str = Field(..., description="Unique review request identifier.")
    step_id: str = Field(..., description="Workflow step requiring review.")
    title: str = Field(..., description="Short review title.")
    description: str = Field(..., description="What the reviewer should inspect.")
    candidate_data: Dict[str, Any] = Field(default_factory=dict, description="Data presented to the reviewer.")
    required_action: str = Field(..., description="Expected action from the reviewer.")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Review request time.")
    resolved_at: Optional[datetime] = Field(default=None, description="When the review was resolved.")
    reviewer_notes: Optional[str] = Field(default=None, description="Reviewer remarks.")


class WorkflowMetadata(BaseModel):
    """Metadata for a workflow run."""

    run_id: str = Field(..., description="Unique run identifier.")
    plan_version: str = Field(..., description="Active implementation plan version.")
    contract_version: str = Field(..., description="Project contract version.")
    started_at: datetime = Field(default_factory=datetime.utcnow, description="Workflow start time.")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Last update time.")
    current_step: str = Field(default="step_0", description="Current workflow step.")
    completed_steps: List[str] = Field(default_factory=list, description="List of completed steps.")
    interrupted: bool = Field(default=False, description="Whether the workflow is paused for human review.")
