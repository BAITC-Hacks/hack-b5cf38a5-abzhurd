"""Typed contracts shared by the deterministic engine, advisor, and UI."""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class Decision(BaseModel):
    """One selected measure and its optional district assignment."""

    model_config = ConfigDict(extra="forbid")

    measure_id: str = Field(min_length=2, max_length=3)
    district: Optional[str] = None


class DistrictResult(BaseModel):
    """Calculated result for one district."""

    model_config = ConfigDict(extra="forbid")

    name: str
    indicators_before: Dict[str, float]
    indicators_after: Dict[str, float]
    score_before: float
    score_after: float
    delta: float


class SimulationResult(BaseModel):
    """Complete deterministic output consumed by the advisor and UI."""

    model_config = ConfigDict(extra="forbid")

    decisions: List[Decision]
    budget_used: int
    budget_limit: int = 100
    city_score_before: float
    city_score_after: float
    city_score_delta: float
    weighted_city_score: float
    weakest_district: str
    critical_metrics: int
    districts: List[DistrictResult]
    measure_contributions: Dict[str, Dict[str, float]]
    validation_errors: List[str] = Field(default_factory=list)


class Debrief(BaseModel):
    """Structured LLM explanation; it contains no authoritative calculations."""

    model_config = ConfigDict(extra="forbid")

    why_score_changed: str
    main_risk: str
    next_quarter_recommendation: str
    source: str = "openai"
