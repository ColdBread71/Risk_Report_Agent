"""
Common types and enums used across all domain models.
"""

from enum import Enum
from typing import Optional

from pydantic import Field


class EvidenceLevel(str, Enum):
    """Evidence strength level per docs/03_evidence_policy.md."""

    DIRECT = "direct"
    DERIVED = "derived"
    MANUAL = "manual"
    UNKNOWN = "unknown"


class ConfidenceLevel(str, Enum):
    """Confidence level for model-generated or human-reviewed content."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class SeverityLevel(str, Enum):
    """Severity classification for risks and findings."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class TreatmentOption(str, Enum):
    """Risk treatment options per prEN 40000-1-2 section 6.5.1.6."""

    AVOID = "avoid"
    MITIGATE = "mitigate"
    ACCEPT = "accept"
    TRANSFER = "transfer"


class RiskStatus(str, Enum):
    """Current status of a risk item."""

    IDENTIFIED = "identified"
    EVALUATED = "evaluated"
    TREATED = "treated"
    RESIDUAL = "residual"
    CLOSED = "closed"


class AssessmentVerdict(str, Enum):
    """Assessment verdict per prEN 40000-1-2 assessment criteria."""

    PASS = "PASS"
    FAIL = "FAIL"
    PARTIAL = "PARTIAL"
