"""Structured output schemas. Each parser/analyzer agent emits one of these
as enforced JSON via ADK's `output_schema`, so downstream agents and the API
get machine-readable data instead of free-form prose."""

from typing import List, Optional
from pydantic import BaseModel, Field
from typing_extensions import Literal


class JDRequirements(BaseModel):
    title: str
    seniority: str
    required_skills: List[str]
    nice_to_have_skills: List[str]
    responsibilities: List[str]
    ats_keywords: List[str] = Field(
        description="Important terms an applicant-tracking system would scan for."
    )


class ResumeProfile(BaseModel):
    skills: List[str]
    technologies: List[str]
    experience_bullets: List[str] = Field(
        description="The candidate's experience bullet points, quoted verbatim."
    )
    years_experience: Optional[float] = None


class SkillMatch(BaseModel):
    skill: str
    status: Literal["covered", "partial", "missing"]
    evidence: str = Field(
        description="Where in the resume this is supported; empty string if missing."
    )


class MatchAnalysis(BaseModel):
    match_score: int = Field(ge=0, le=100)
    matches: List[SkillMatch]
    summary: str


class TailoredBullet(BaseModel):
    original: str
    tailored: str
    rationale: str


class TailoredOutput(BaseModel):
    tailored_bullets: List[TailoredBullet]
    ats_keywords_to_add: List[str] = Field(
        description="Keywords to add ONLY where they reflect real experience."
    )
    honest_gaps: List[str] = Field(
        description="Genuinely missing skills the candidate must address truthfully, "
        "never fabricate."
    )
