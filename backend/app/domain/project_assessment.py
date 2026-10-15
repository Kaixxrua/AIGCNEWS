"""Legacy REST response types; retired assessments are always returned as null."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ASSESSMENT_VERSION = 1


class AssessmentClaim(BaseModel):
    text_zh: str = Field(min_length=1, max_length=180)
    text_en: str = Field(min_length=1, max_length=360)
    source: Literal["description", "readme"]
    quote: str = Field(min_length=12, max_length=600)


class ProjectAssessment(BaseModel):
    version: Literal[1] = ASSESSMENT_VERSION
    decision: Literal["evaluate", "insufficient", "out_of_scope"]
    relevance: Literal["core", "adjacent", "unrelated", "unknown"]
    relevance_evidence: AssessmentClaim | None = None
    audience: list[AssessmentClaim] = Field(default_factory=list, max_length=2)
    value: list[AssessmentClaim] = Field(default_factory=list, max_length=2)
    setup: list[AssessmentClaim] = Field(default_factory=list, max_length=2)
    limitations: list[AssessmentClaim] = Field(default_factory=list, max_length=2)
    assessed_at: str
    readme_sha256: str = ""
    license_spdx_id: str = ""
