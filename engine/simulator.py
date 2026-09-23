"""Deterministic, side-effect-free validation and simulation; no advisor or UI imports.

Only load_dataset performs I/O. Numeric rules come from AGENTS.md §3; no
intermediate rounding or budget bonus is applied. Invalid scenarios have no Score.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from math import fsum
from pathlib import Path
from typing import Any, NoReturn, cast

from pydantic import ValidationError

from engine.models import (
    BUDGET_LIMIT, CITY_WEIGHT, CRITICAL_THRESHOLD, DECISION_COUNT,
    INDICATOR_WEIGHTS, MAX_PER_DIRECTION, WEAKEST_WEIGHT,
    CriticalMetric, Dataset, Decision, DistrictName, DistrictResult, Indicator,
    SimulationResult, SynergyContribution, ValidationIssue, ValidationReport,
)


class DatasetError(ValueError):
    """Invalid or unavailable installation data; callers should display this message."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    raise ValueError(f"Nonfinite JSON number: {value}")


def _read_json(path: Path, expected_keys: set[str]) -> dict[str, Any]:
    contents = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )
    if not isinstance(contents, dict) or set(contents) != expected_keys:
        raise ValueError(f"{path.name} must contain exactly: {', '.join(sorted(expected_keys))}")
    return contents


def load_dataset(data_dir: Path | None = None) -> Dataset:
    """Read and validate the repository JSON; never substitute invented defaults."""
    directory = Path(data_dir) if data_dir is not None else Path(__file__).resolve().parent.parent / "data"
    try:
        districts = _read_json(directory / "districts.json", {"indicator_scale", "districts"})
        measures = _read_json(
            directory / "measures.json",
            {"horizon_quarters", "measures", "synergies", "incompatibilities"},
        )
        return Dataset.model_validate({**districts, **measures})
    except (OSError, UnicodeError, ValueError) as exc:
        if isinstance(exc, ValidationError):
            detail = "; ".join(
                f"{'.'.join(map(str, error['loc']))}: {error['msg']}"
                for error in exc.errors(include_url=False, include_input=False)
            )
        else:
            detail = str(exc)
        raise DatasetError(f"Cannot load simulator data: {detail}") from None


def _validate(decisions: object, dataset: Dataset) -> tuple[ValidationReport, list[Decision]]:
    errors: list[ValidationIssue] = []

    def issue(code: str, message: str, indices: list[int] | None = None) -> None:
        errors.append(ValidationIssue(code=code, message=message, decision_indices=indices or []))

    if not isinstance(decisions, (list, tuple)):
        issue("invalid_payload", "Provide a list of exactly five decision objects.")
        return ValidationReport(errors=errors), []
    if len(decisions) != DECISION_COUNT:
        issue("decision_count", f"Select exactly {DECISION_COUNT} decisions; received {len(decisions)}.")

    measures = {m.id: m for m in dataset.measures}
    district_names = {d.name for d in dataset.districts}
    parsed: list[Decision] = []
    positions: dict[str, list[int]] = defaultdict(list)
    directions: dict[str, list[int]] = defaultdict(list)
    assigned: dict[str, list[tuple[int, str]]] = defaultdict(list)
    cost_known = True
    total = 0
    for index, item in enumerate(decisions):
        try:
            decision = Decision.model_validate(item)
        except ValidationError as exc:
            detail = "; ".join(
                f"{'.'.join(map(str, e['loc'])) or 'decision'}: {e['msg']}"
                for e in exc.errors(include_url=False, include_input=False)
            )
            issue("invalid_decision", f"Decision {index + 1}: {detail}", [index])
            cost_known = False
            continue
        parsed.append(decision)
        if decision.measure_id not in measures:
            issue("unknown_measure", f"Choose a catalog measure instead of {decision.measure_id!r}.", [index])
            cost_known = False
            continue
        measure = measures[decision.measure_id]
        positions[measure.id].append(index)
        directions[measure.direction].append(index)
        total += measure.cost
        if measure.scope == "Город":
            if decision.district is not None:
                issue("forbidden_district", f"{measure.id} is citywide; omit its district.", [index])
        elif decision.district is None:
            issue("missing_district", f"Choose a district for {measure.id}.", [index])
        elif decision.district not in district_names:
            issue("unknown_district", f"Choose one of the five official districts for {measure.id}.", [index])
        else:
            assigned[measure.id].append((index, decision.district))

    for measure in dataset.measures:
        indices = positions[measure.id]
        if len(indices) > 1:
            issue("duplicate_measure", f"Select {measure.id} only once, even across different districts.", indices)
    for direction, indices in directions.items():
        if len(indices) > MAX_PER_DIRECTION:
            issue("direction_limit", f"Select at most {MAX_PER_DIRECTION} measures from {direction}.", indices)
    if cost_known and total > BUDGET_LIMIT:
        issue("budget_exceeded", f"Cost {total} exceeds budget {BUDGET_LIMIT}; remove or replace a measure.")
    for conflict in dataset.incompatibilities:
        first, second = conflict.measures
        if not positions[first] or not positions[second]:
            continue
        if conflict.scope == "global":
            issue("incompatible_measures", f"{first} + {second}: {conflict.reason}", sorted(positions[first] + positions[second]))
        else:
            overlapping = sorted({
                index
                for i, district_a in assigned[first]
                for j, district_b in assigned[second]
                if district_a == district_b
                for index in (i, j)
            })
            if overlapping:
                issue("district_conflict", f"{first} + {second}: {conflict.reason}", overlapping)
    return ValidationReport(errors=errors, budget_used=total if cost_known else None), parsed


def validate_scenario(decisions: object, dataset: Dataset) -> ValidationReport:
    """Validate raw objects or Decisions; indices are zero-based input positions.

    Budget is unknown if any row cannot be resolved. Otherwise it is the submitted
    row total, including duplicates (which independently make the scenario invalid).
    """
    return _validate(decisions, dataset)[0]


@dataclass(frozen=True)
class _Snapshot:
    district_scores: dict[DistrictName, float]
    weighted_score: float
    weakest_district: DistrictName
    critical: list[CriticalMetric]
    score: float


def _score(indicators: dict[DistrictName, dict[Indicator, float]], dataset: Dataset) -> _Snapshot:
    scores = {
        d.name: fsum(indicators[d.name][k] * w for k, w in INDICATOR_WEIGHTS.items())
        for d in dataset.districts
    }
    weighted = fsum(d.population_weight * scores[d.name] for d in dataset.districts)
    # dict insertion order is the fixed official district order, also the tie rule.
    weakest = min(scores, key=scores.__getitem__)
    critical = [
        CriticalMetric(district=d.name, indicator=k, value=indicators[d.name][k])
        for d in dataset.districts
        for k in INDICATOR_WEIGHTS
        if indicators[d.name][k] < CRITICAL_THRESHOLD
    ]
    score = CITY_WEIGHT * weighted + WEAKEST_WEIGHT * scores[weakest] - len(critical)
    return _Snapshot(scores, weighted, weakest, critical, score)


def simulate(decisions: object, dataset: Dataset) -> SimulationResult | ValidationReport:
    """Revalidate, then calculate a complete audit. Never score an invalid scenario."""
    report, parsed = _validate(decisions, dataset)
    if not report.valid:
        return report
    selected = {d.measure_id: d for d in parsed}
    ordered = [selected[m.id] for m in dataset.measures if m.id in selected]
    before = {d.name: dict(d.indicators) for d in dataset.districts}
    contributions: dict[str, dict[DistrictName, dict[Indicator, float]]] = {}
    for measure in dataset.measures:
        if measure.id not in selected:
            continue
        targets = (
            tuple(before) if measure.scope == "Город"
            else (cast(DistrictName, selected[measure.id].district),)
        )
        factor = (dataset.horizon_quarters - measure.lag) / dataset.horizon_quarters
        contributions[measure.id] = {
            district: {
                cast(Indicator, k): measure.effects[k] * factor
                for k in INDICATOR_WEIGHTS if k in measure.effects
            }
            for district in targets
        }
    synergies = [
        SynergyContribution(
            measures=synergy.measures,
            district=cast(DistrictName, selected[synergy.target_measure].district),
            indicator=synergy.indicator,
            bonus=synergy.bonus,
        )
        for synergy in dataset.synergies
        if all(m in selected for m in synergy.measures)
    ]
    after: dict[DistrictName, dict[Indicator, float]] = {}
    clipping: dict[DistrictName, dict[Indicator, float]] = {}
    for district, values in before.items():
        after[district] = {}
        clipping[district] = {}
        for key, initial in values.items():
            unbounded = fsum([
                initial,
                *(effect.get(district, {}).get(key, 0.0) for effect in contributions.values()),
                *(s.bonus for s in synergies if s.district == district and s.indicator == key),
            ])
            final = min(100.0, max(0.0, unbounded))
            after[district][key] = final
            clipping[district][key] = final - unbounded
    baseline = _score(before, dataset)
    outcome = _score(after, dataset)
    assert report.budget_used is not None  # All rows resolved before this branch.
    return SimulationResult(
        decisions=ordered,
        budget_used=report.budget_used,
        budget_remaining=BUDGET_LIMIT - report.budget_used,
        city_score_before=baseline.score,
        city_score_after=outcome.score,
        city_score_delta=outcome.score - baseline.score,
        weighted_city_score_before=baseline.weighted_score,
        weighted_city_score=outcome.weighted_score,
        weakest_district_before=baseline.weakest_district,
        weakest_district=outcome.weakest_district,
        critical_metrics_before=len(baseline.critical),
        critical_metrics=len(outcome.critical),
        critical_locations_before=baseline.critical,
        critical_locations_after=outcome.critical,
        districts=[
            DistrictResult(
                name=d.name,
                indicators_before=before[d.name],
                indicators_after=after[d.name],
                indicator_deltas={k: after[d.name][k] - before[d.name][k] for k in before[d.name]},
                score_before=baseline.district_scores[d.name],
                score_after=outcome.district_scores[d.name],
                delta=outcome.district_scores[d.name] - baseline.district_scores[d.name],
            )
            for d in dataset.districts
        ],
        measure_contributions=contributions,
        synergy_contributions=synergies,
        clipping_adjustments=clipping,
    )
