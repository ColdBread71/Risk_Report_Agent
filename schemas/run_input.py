"""Validated identities for source material supplied to one workflow run."""

import re

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvidencePacketRef(BaseModel):
    """Compact, immutable identity of a validated evidence packet.

    The packet path and its materialized blocks remain runtime inputs. Only this
    reproducibility identity is allowed into LangGraph state.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    packet_id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9_-]+$")
    packet_version: int = Field(..., ge=1)
    project_id: str = Field(..., min_length=1)
    packet_sha256: str = Field(..., pattern=r"^[a-f0-9]{64}$")
    manifest_sha256: str = Field(..., pattern=r"^[a-f0-9]{64}$")
    config_sha256: str = Field(..., pattern=r"^[a-f0-9]{64}$")
    parser_name: str = Field(..., min_length=1)
    parser_version: str = Field(..., min_length=1)
    document_ids: tuple[str, ...] = Field(..., min_length=1)
    block_count: int = Field(..., ge=1)

    @model_validator(mode="after")
    def validate_document_ids(self) -> "EvidencePacketRef":
        """Require unique canonical parsed-document identifiers."""
        if len(self.document_ids) != len(set(self.document_ids)):
            raise ValueError("document_ids must be unique")
        if any(re.fullmatch(r"DOC-[A-F0-9]{12}", item) is None for item in self.document_ids):
            raise ValueError("document_ids must use canonical DOC identifiers")
        return self


__all__ = ["EvidencePacketRef"]
