"""Typed data and result contracts; numeric rules transcribed from AGENTS.md §3."""

from __future__ import annotations

from math import fsum, isclose, isfinite
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator


Indicator = Literal["T1", "T2", "E1", "E2", "S1", "S2", "B1", "B2", "C1", "C2"]
DistrictName = Literal["Есиль", "Алматы", "Сарыарка", "Байконур", "Нура"]
Direction = Literal["Транспорт", "Экология", "Соцсфера", "Безопасность", "Сервисы"]
Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
IndicatorValue = Annotated[Number, Field(ge=0, le=100)]
MeasureId = Annotated[StrictStr, Field(pattern=r"^M(?:[1-9]|1[0-4])$")]

INDICATOR_WEIGHTS = MappingProxyType({
    "T1": 0.10, "T2": 0.10, "E1": 0.09, "E2": 0.11,
    "S1": 0.11, "S2": 0.11, "B1": 0.09, "B2": 0.09,
    "C1": 0.10, "C2": 0.10,
})
DISTRICT_NAMES: tuple[DistrictName, ...] = ("Есиль", "Алматы", "Сарыарка", "Байконур", "Нура")
MEASURE_IDS: tuple[str, ...] = tuple(f"M{i}" for i in range(1, 15))
BUDGET_LIMIT = 100
DECISION_COUNT = 5
MAX_PER_DIRECTION = 2
HORIZON_QUARTERS = 8
CRITICAL_THRESHOLD = 40
CITY_WEIGHT = 0.7
WEAKEST_WEIGHT = 0.3


class Contract(BaseModel):
    """Reject extra fields and nonfinite numbers; instances are not reassigned."""

    model_config = ConfigDict(
        extra="forbid", allow_inf_nan=False, frozen=True, revalidate_instances="always"
    )


class IndicatorScale(Contract):
    min: Annotated[StrictInt, Field(ge=0, le=0)]
    max: Annotated[StrictInt, Field(ge=100, le=100)]
    higher_is_better: StrictBool

    @model_validator(mode="after")
    def check_orientation(self) -> IndicatorScale:
        if not self.higher_is_better:
            raise ValueError("All official indicators use higher-is-better orientation.")
        return self


class District(Contract):
    name: DistrictName
    population_weight: Annotated[Number, Field(gt=0, le=1)]
    indicators: dict[Indicator, IndicatorValue]
    base_score: IndicatorValue
    profile: StrictStr

    @model_validator(mode="after")
    def check_indicators(self) -> District:
        if set(self.indicators) != set(INDICATOR_WEIGHTS):
            raise ValueError("A district must contain all ten official indicators.")
        calculated = fsum(self.indicators[k] * w for k, w in INDICATOR_WEIGHTS.items())
        if not isclose(calculated, self.base_score, rel_tol=0, abs_tol=1e-9):
            raise ValueError("base_score disagrees with the weighted district indicators.")
        return self


class Measure(Contract):
    id: MeasureId
    direction: Direction
    name: Annotated[StrictStr, Field(min_length=1)]
    scope: Literal["Район", "Город"]
    cost: Annotated[StrictInt, Field(ge=0)]
    lag: Annotated[StrictInt, Field(ge=0, le=HORIZON_QUARTERS)]
    effects: Annotated[dict[Indicator, Number], Field(min_length=1)]


class Synergy(Contract):
    measures: tuple[MeasureId, MeasureId]
    indicator: Indicator
    bonus: Number
    target_measure: MeasureId


class Incompatibility(Contract):
    measures: tuple[MeasureId, MeasureId]
    scope: Literal["global", "same_district"]
    reason: Annotated[StrictStr, Field(min_length=1)]


class Dataset(Contract):
    """Validated numeric data. Synthetic datasets are supported for boundary tests."""

    indicator_scale: IndicatorScale
    districts: tuple[District, ...]
    horizon_quarters: Annotated[StrictInt, Field(ge=HORIZON_QUARTERS, le=HORIZON_QUARTERS)]
    measures: tuple[Measure, ...]
    synergies: Annotated[tuple[Synergy, ...], Field(min_length=3, max_length=3)]
    incompatibilities: Annotated[tuple[Incompatibility, ...], Field(min_length=3, max_length=3)]

    @model_validator(mode="after")
    def check_integrity(self) -> Dataset:
        if tuple(d.name for d in self.districts) != DISTRICT_NAMES:
            raise ValueError("Expected the five official districts in official order.")
        if tuple(m.id for m in self.measures) != MEASURE_IDS:
            raise ValueError("Expected unique measures M1 through M14 in catalog order.")
        if not isclose(fsum(d.population_weight for d in self.districts), 1, rel_tol=0, abs_tol=1e-12):
            raise ValueError("Population weights must sum to one.")
        measures = {m.id: m for m in self.measures}
        for rules in (self.synergies, self.incompatibilities):
            seen: set[frozenset[str]] = set()
            for rule in rules:
                pair = frozenset(rule.measures)
                if len(pair) != 2 or not pair <= measures.keys() or pair in seen:
                    raise ValueError("Rule pairs must be distinct, unique, known measures.")
                seen.add(pair)
                if isinstance(rule, Synergy):
                    if rule.target_measure not in pair or measures[rule.target_measure].scope != "Район":
                        raise ValueError("A synergy must target its district-scoped member.")
                elif rule.scope == "same_district" and any(measures[m].scope != "Район" for m in pair):
                    raise ValueError("A same-district conflict requires two district measures.")
        # Reject even finite inputs whose accumulation could overflow before clipping.
        try:
            for key in INDICATOR_WEIGHTS:
                bound = fsum([
                    100.0,
                    *(abs(m.effects.get(key, 0.0)) for m in self.measures),
                    *(abs(s.bonus) for s in self.synergies if s.indicator == key),
                ])
                if not isfinite(bound):
                    raise ValueError("Effect magnitudes exceed safe numeric accumulation.")
        except OverflowError:
            raise ValueError("Effect magnitudes exceed safe numeric accumulation.") from None
        return self


class Decision(Contract):
    """Structural parsing only; catalog and assignment checks belong to validation."""

    measure_id: Annotated[StrictStr, Field(min_length=2, max_length=3)]
    district: StrictStr | None = None


class ValidationIssue(Contract):
    code: StrictStr
    message: StrictStr
    decision_indices: list[StrictInt] = Field(default_factory=list)


class ValidationReport(Contract):
    """No score fields, including when validation succeeds without simulation."""

    errors: list[ValidationIssue] = Field(default_factory=list)
    budget_used: Annotated[StrictInt, Field(ge=0)] | None = None
    budget_limit: Literal[100] = BUDGET_LIMIT

    @property
    def valid(self) -> bool:
        return not self.errors


class CriticalMetric(Contract):
    district: DistrictName
    indicator: Indicator
    value: Annotated[IndicatorValue, Field(lt=CRITICAL_THRESHOLD)]


class SynergyContribution(Contract):
    measures: tuple[MeasureId, MeasureId]
    district: DistrictName
    indicator: Indicator
    bonus: Number


class DistrictResult(Contract):
    name: DistrictName
    indicators_before: dict[Indicator, IndicatorValue]
    indicators_after: dict[Indicator, IndicatorValue]
    indicator_deltas: dict[Indicator, Number]
    score_before: IndicatorValue
    score_after: IndicatorValue
    delta: Number

    @model_validator(mode="after")
    def check_maps(self) -> DistrictResult:
        for values in (self.indicators_before, self.indicators_after, self.indicator_deltas):
            if set(values) != set(INDICATOR_WEIGHTS):
                raise ValueError("Result maps must contain all ten indicators.")
        return self


class SimulationResult(Contract):
    """Successful calculation only. Contributions are indicator effects, not Score shares."""

    decisions: Annotated[list[Decision], Field(min_length=5, max_length=5)]
    budget_used: Annotated[StrictInt, Field(ge=0, le=BUDGET_LIMIT)]
    budget_limit: Literal[100] = BUDGET_LIMIT
    budget_remaining: Annotated[StrictInt, Field(ge=0, le=BUDGET_LIMIT)]
    city_score_before: Number
    city_score_after: Number
    city_score_delta: Number
    weighted_city_score_before: IndicatorValue
    weighted_city_score: IndicatorValue
    weakest_district_before: DistrictName
    weakest_district: DistrictName
    critical_metrics_before: Annotated[StrictInt, Field(ge=0, le=50)]
    critical_metrics: Annotated[StrictInt, Field(ge=0, le=50)]
    critical_locations_before: list[CriticalMetric]
    critical_locations_after: list[CriticalMetric]
    districts: Annotated[list[DistrictResult], Field(min_length=5, max_length=5)]
    measure_contributions: dict[MeasureId, dict[DistrictName, dict[Indicator, Number]]]
    synergy_contributions: list[SynergyContribution]
    clipping_adjustments: dict[DistrictName, dict[Indicator, Number]]

    @model_validator(mode="after")
    def check_summary(self) -> SimulationResult:
        ids = [d.measure_id for d in self.decisions]
        if len(set(ids)) != DECISION_COUNT or set(self.measure_contributions) != set(ids):
            raise ValueError("Each selected measure must have exactly one contribution entry.")
        if tuple(d.name for d in self.districts) != DISTRICT_NAMES:
            raise ValueError("Result must contain all districts in official order.")
        if self.budget_used + self.budget_remaining != self.budget_limit:
            raise ValueError("Budget fields do not reconcile.")
        for count, locations in (
            (self.critical_metrics_before, self.critical_locations_before),
            (self.critical_metrics, self.critical_locations_after),
        ):
            if count != len(locations) or len({(v.district, v.indicator) for v in locations}) != count:
                raise ValueError("Critical counts must match distinct district/indicator pairs.")
        if set(self.clipping_adjustments) != set(DISTRICT_NAMES) or any(
            set(values) != set(INDICATOR_WEIGHTS) for values in self.clipping_adjustments.values()
        ):
            raise ValueError("Clipping adjustments must cover every district and indicator.")
        return self


class Debrief(BaseModel):
    """Structured LLM explanation; it contains no authoritative calculations."""

    model_config = ConfigDict(extra="forbid")

    why_score_changed: str
    main_risk: str
    next_quarter_recommendation: str
    source: Literal["openai", "nvidia", "mock"]

    @field_validator("why_score_changed", "main_risk", "next_quarter_recommendation")
    @classmethod
    def nonempty_text(cls, value: str) -> str:
        if not value.strip() or len(value) > 1500:
            raise ValueError("Briefing sections must contain 1–1500 nonblank characters.")
        return value.strip()
