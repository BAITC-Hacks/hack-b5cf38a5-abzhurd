"""Independent acceptance tests; the oracle uses exact rational arithmetic.

Run the optional complete assignment sweep with SIMULATOR_EXHAUSTIVE=1.
Synthetic boundary fixtures never replace or modify the official JSON files.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from fractions import Fraction
from itertools import combinations, permutations, product
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from engine.models import Dataset, Decision, SimulationResult, ValidationReport
from engine.simulator import DatasetError, load_dataset, simulate, validate_scenario

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = dict(zip(
    ('T1', 'T2', 'E1', 'E2', 'S1', 'S2', 'B1', 'B2', 'C1', 'C2'),
    (10, 10, 9, 11, 11, 11, 9, 9, 10, 10),
))
# Transcribed from AGENTS.md, not copied from production helpers.
DISTRICTS = (
    ('Есиль', 27, (45, 62, 68, 72, 48, 55, 78, 60, 75, 70), 62.99),
    ('Алматы', 24, (40, 75, 50, 55, 60, 65, 62, 52, 50, 60), 57.06),
    ('Сарыарка', 20, (50, 70, 42, 40, 62, 68, 58, 55, 45, 55), 54.65),
    ('Байконур', 13, (52, 68, 55, 50, 58, 60, 52, 58, 55, 58), 56.63),
    ('Нура', 16, (55, 40, 45, 65, 38, 35, 55, 50, 60, 50), 49.18),
)
# cost, lag, direction, scope, raw effects
MEASURES = {
    'M1': (18, 2, 'Транспорт', 'Район', {'T1': 6, 'T2': 9}),
    'M2': (22, 2, 'Транспорт', 'Город', {'T1': 4, 'B2': 3}),
    'M3': (30, 4, 'Транспорт', 'Район', {'T1': 16, 'T2': 20, 'E2': 4}),
    'M4': (15, 2, 'Экология', 'Район', {'E1': 12, 'E2': 3, 'B1': 2}),
    'M5': (25, 3, 'Экология', 'Район', {'E2': 14, 'C1': 4}),
    'M6': (20, 4, 'Экология', 'Город', {'E1': 5, 'E2': 3}),
    'M7': (24, 3, 'Соцсфера', 'Район', {'S1': 16}),
    'M8': (20, 3, 'Соцсфера', 'Район', {'S2': 14}),
    'M9': (10, 1, 'Соцсфера', 'Район', {'S1': 3, 'S2': 3, 'B1': 3}),
    'M10': (12, 1, 'Безопасность', 'Район', {'B1': 12, 'B2': 2}),
    'M11': (10, 1, 'Безопасность', 'Район', {'B2': 12, 'T1': -2}),
    'M12': (14, 1, 'Сервисы', 'Город', {'C2': 5}),
    'M13': (28, 4, 'Сервисы', 'Район', {'C1': 18, 'E2': 2}),
    'M14': (16, 1, 'Сервисы', 'Город', {'C1': 5, 'C2': 2}),
}
SYNERGIES = (('M1', 'M2', 'T1'), ('M10', 'M12', 'B1'), ('M5', 'M6', 'E2'))
BENCHMARK = [
    {'measure_id': 'M7', 'district': 'Нура'},
    {'measure_id': 'M8', 'district': 'Нура'},
    {'measure_id': 'M10', 'district': 'Нура'},
    {'measure_id': 'M12'},
    {'measure_id': 'M5', 'district': 'Сарыарка'},
]


def q(value: int | float) -> Fraction:
    """Convert decimal input exactly, without adopting its binary float error."""
    return Fraction(str(value))


def decisions(ids: tuple[str, ...] | list[str], district: str = 'Нура') -> list[dict[str, Any]]:
    return [dict(measure_id=mid, **({'district': district} if MEASURES[mid][3] == 'Район' else {})) for mid in ids]


def valid_oracle(items: list[dict[str, Any]], check_budget: bool = True) -> bool:
    """Independent official validation for well-formed catalog selections."""
    ids = [item['measure_id'] for item in items]
    if len(ids) != 5 or len(set(ids)) != 5:
        return False
    if check_budget and sum(MEASURES[mid][0] for mid in ids) > 100:
        return False
    if max(Counter(MEASURES[mid][2] for mid in ids).values()) > 2:
        return False
    locations = {item['measure_id']: item.get('district') for item in items}
    if {'M1', 'M3'} <= set(ids):
        return False
    for left, right in (('M4', 'M7'), ('M5', 'M13')):
        if left in locations and right in locations and locations[left] == locations[right]:
            return False
    return True


def calculate_oracle(dataset: Dataset, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate the formula independently using Fraction and official rules."""
    before = {d.name: {k: q(v) for k, v in d.indicators.items()} for d in dataset.districts}
    after = deepcopy(before)
    lookup = {m.id: m for m in dataset.measures}
    selected = {item['measure_id']: item.get('district') for item in items}
    direct: dict[str, dict[str, dict[str, Fraction]]] = {}
    for mid, district in selected.items():
        measure = lookup[mid]
        direct[mid] = {}
        for name in after if measure.scope == 'Город' else (district,):
            direct[mid][name] = {}
            for indicator, raw in measure.effects.items():
                effect = q(raw) * Fraction(8 - measure.lag, 8)
                after[name][indicator] += effect
                direct[mid][name][indicator] = effect
    synergy: list[tuple[str, str, str, str, Fraction]] = []
    for left, right, indicator in SYNERGIES:
        if left in selected and right in selected:
            name = selected[left]
            after[name][indicator] += 2
            synergy.append((left, right, name, indicator, Fraction(2)))
    clipping: dict[str, dict[str, Fraction]] = {}
    for name, values in after.items():
        clipping[name] = {}
        for key, value in values.items():
            after[name][key] = min(Fraction(100), max(Fraction(0), value))
            clipping[name][key] = after[name][key] - value
    aggregates: list[dict[str, Any]] = []
    for values in (before, after):
        scores = {name: sum(value * Fraction(WEIGHTS[k], 100) for k, value in row.items()) for name, row in values.items()}
        weighted = sum(q(d.population_weight) * scores[d.name] for d in dataset.districts)
        critical = [(name, key, value) for name, row in values.items() for key, value in row.items() if value < 40]
        weakest = min(scores, key=scores.get)
        score = Fraction(7, 10) * weighted + Fraction(3, 10) * scores[weakest] - len(critical)
        aggregates.append(dict(scores=scores, weighted=weighted, critical=critical, weakest=weakest, score=score))
    return dict(before=before, after=after, direct=direct, synergy=synergy, clipping=clipping, aggregates=aggregates)


def integer_oracle(items: list[dict[str, Any]]) -> tuple[list[list[int]], list[int], int, int, int, int]:
    """Exact official-data oracle for the large sweep (indicator units = 1/8).

    District-score units are 1/800, city-average units 1/80000, and final
    Score units 1/800000. This path is cross-checked against Fraction below.
    """
    names = [d[0] for d in DISTRICTS]
    weights = list(WEIGHTS.values())
    keys = list(WEIGHTS)
    rows = [[value * 8 for value in d[2]] for d in DISTRICTS]
    selected = {item['measure_id']: item.get('district') for item in items}
    for mid, district in selected.items():
        _, lag, _, scope, effects = MEASURES[mid]
        targets = range(5) if scope == 'Город' else (names.index(district),)
        for target in targets:
            for key, raw in effects.items():
                rows[target][keys.index(key)] += raw * (8 - lag)
    for left, right, key in SYNERGIES:
        if left in selected and right in selected:
            rows[names.index(selected[left])][keys.index(key)] += 16
    rows = [[min(800, max(0, value)) for value in row] for row in rows]
    scores = [sum(value * weight for value, weight in zip(row, weights)) for row in rows]
    weighted = sum(score * d[1] for score, d in zip(scores, DISTRICTS))
    critical = sum(value < 320 for row in rows for value in row)
    weakest = scores.index(min(scores))
    score = 7 * weighted + 300 * min(scores) - 800000 * critical
    return rows, scores, weighted, critical, weakest, score


class SimulatorTests(unittest.TestCase):
    dataset: Dataset

    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset = load_dataset(ROOT / 'data')

    def result(self, items: object, dataset: Dataset | None = None) -> SimulationResult:
        result = simulate(items, dataset or self.dataset)
        self.assertIsInstance(result, SimulationResult, str(result))
        return result

    def assert_invalid(self, items: object) -> ValidationReport:
        report = validate_scenario(items, self.dataset)
        self.assertFalse(report.valid)
        self.assertTrue(report.errors)
        for error in report.errors:
            self.assertTrue(error.code)
            self.assertTrue(error.message)
            self.assertTrue(all(isinstance(i, int) for i in error.decision_indices))
        result = simulate(items, self.dataset)
        self.assertIsInstance(result, ValidationReport)
        self.assertEqual(report.model_dump(), result.model_dump())
        self.assertFalse(any('score' in key for key in result.model_dump()))
        return report

    def assert_oracle(self, items: list[dict[str, Any]], dataset: Dataset | None = None) -> SimulationResult:
        data = dataset or self.dataset
        actual = self.result(items, data)
        expected = calculate_oracle(data, items)
        old, new = expected['aggregates']
        for field, value in (
            ('city_score_before', old['score']), ('city_score_after', new['score']),
            ('city_score_delta', new['score'] - old['score']),
            ('weighted_city_score_before', old['weighted']), ('weighted_city_score', new['weighted']),
        ):
            self.assertAlmostEqual(getattr(actual, field), float(value), places=11)
        self.assertEqual(actual.weakest_district_before, old['weakest'])
        self.assertEqual(actual.weakest_district, new['weakest'])
        self.assertEqual(actual.critical_metrics_before, len(old['critical']))
        self.assertEqual(actual.critical_metrics, len(new['critical']))
        for field, expected_pairs in (('critical_locations_before', old['critical']), ('critical_locations_after', new['critical'])):
            self.assertEqual([(p.district, p.indicator, p.value) for p in getattr(actual, field)], [(d, k, float(v)) for d, k, v in expected_pairs])
        for district in actual.districts:
            name = district.name
            self.assertEqual(district.indicators_before, {k: float(v) for k, v in expected['before'][name].items()})
            for key in WEIGHTS:
                self.assertAlmostEqual(district.indicators_after[key], float(expected['after'][name][key]), places=11)
                self.assertAlmostEqual(district.indicator_deltas[key], float(expected['after'][name][key] - expected['before'][name][key]), places=11)
                self.assertAlmostEqual(actual.clipping_adjustments[name].get(key, 0), float(expected['clipping'][name][key]), places=11)
            self.assertAlmostEqual(district.score_before, float(old['scores'][name]), places=11)
            self.assertAlmostEqual(district.score_after, float(new['scores'][name]), places=11)
            self.assertAlmostEqual(district.delta, float(new['scores'][name] - old['scores'][name]), places=11)
        self.assertEqual(actual.measure_contributions, expected['direct'])
        self.assertEqual([(s.measures[0], s.measures[1], s.district, s.indicator, s.bonus) for s in actual.synergy_contributions], expected['synergy'])
        cost = sum(next(m.cost for m in data.measures if m.id == item['measure_id']) for item in items)
        self.assertEqual(actual.budget_used, cost)
        self.assertEqual(actual.budget_remaining, 100 - cost)
        return actual

    def synthetic(self, changes: dict[str, dict[str, float]]) -> Dataset:
        payload = self.dataset.model_dump()
        for district in payload['districts']:
            district['indicators'].update(changes.get(district['name'], {}))
            district['base_score'] = float(sum(q(v) * Fraction(WEIGHTS[k], 100) for k, v in district['indicators'].items()))
        return Dataset.model_validate(payload)

    def test_official_dataset_fidelity(self) -> None:
        self.assertEqual(self.dataset.horizon_quarters, 8)
        self.assertEqual(len(self.dataset.districts), 5)
        for actual, (name, population, indicators, score) in zip(self.dataset.districts, DISTRICTS):
            self.assertEqual(actual.name, name)
            self.assertEqual(actual.population_weight, population / 100)
            self.assertEqual(actual.indicators, dict(zip(WEIGHTS, indicators)))
            self.assertEqual(actual.base_score, score)
        self.assertEqual(len(self.dataset.measures), 14)
        for actual in self.dataset.measures:
            self.assertEqual((actual.cost, actual.lag, actual.direction, actual.scope, actual.effects), MEASURES[actual.id])
        self.assertEqual([(s.measures, s.indicator, s.bonus, s.target_measure) for s in self.dataset.synergies], [(tuple((a, b)), key, 2, a) for a, b, key in SYNERGIES])
        self.assertEqual([(rule.measures, rule.scope) for rule in self.dataset.incompatibilities], [(('M1', 'M3'), 'global'), (('M4', 'M7'), 'same_district'), (('M5', 'M13'), 'same_district')])

    def test_baseline_and_benchmark(self) -> None:
        result = self.assert_oracle(BENCHMARK)
        self.assertEqual(round(result.city_score_before, 2), 52.56)
        self.assertEqual(round(result.weighted_city_score_before, 2), 56.86)
        self.assertEqual(result.critical_metrics_before, 2)
        self.assertEqual(result.budget_used, 95)
        self.assertAlmostEqual(result.city_score_after, 56.5, delta=0.1)
        self.assertAlmostEqual(result.city_score_delta, 4.0, delta=0.1)

    def test_all_measures_effects_and_target_isolation(self) -> None:
        for mid in MEASURES:
            items = next(decisions(list(ids)) for ids in combinations(MEASURES, 5) if mid in ids and valid_oracle(decisions(list(ids))))
            with self.subTest(measure=mid):
                self.assert_oracle(items)

    def test_synergies_presence_absence_target_and_order(self) -> None:
        for left, right, indicator in SYNERGIES:
            for wanted in ({left, right}, {left}, {right}):
                ids = next(ids for ids in combinations(MEASURES, 5) if set(ids) & {left, right} == wanted and valid_oracle(decisions(list(ids))))
                items = decisions(list(ids), 'Алматы')
                with self.subTest(pair=(left, right), selected=wanted):
                    result = self.assert_oracle(items)
                    found = [s for s in result.synergy_contributions if set(s.measures) == {left, right}]
                    self.assertEqual(len(found), int(len(wanted) == 2))
                    self.assertEqual(result.model_dump(), self.result(list(reversed(items))).model_dump())

    def test_clipping_both_bounds_and_sum_before_clip(self) -> None:
        items = decisions(['M1', 'M2', 'M9', 'M11', 'M12'])
        for value in (0, 1, 92.25, 100):
            with self.subTest(value=value):
                data = self.synthetic({'Нура': {'T1': value, 'B2': 99, 'S1': 100, 'C2': 100}})
                self.assert_oracle(items, data)
        # A positive effect followed by a negative one must not clip early.
        self.assert_oracle(decisions(['M1', 'M9', 'M10', 'M11', 'M12']), self.synthetic({'Нура': {'T1': 98}}))
        # No positive T1 effect: cross or exactly reach the lower bound.
        for value in (0, 1, 1.75):
            self.assert_oracle(decisions(['M4', 'M9', 'M10', 'M11', 'M12']), self.synthetic({'Нура': {'T1': value}}))
        # Synergy, rather than direct contribution, tips B1 over its upper bound.
        self.assert_oracle(BENCHMARK, self.synthetic({'Нура': {'B1': 88.5}}))

    def test_strict_critical_threshold_and_multiple_pairs(self) -> None:
        items = decisions(['M4', 'M9', 'M10', 'M11', 'M12'])
        for value in (39.999999, 40, 40.000001):
            with self.subTest(value=value):
                data = self.synthetic({'Есиль': {'T1': value, 'T2': value, 'S1': value}})
                result = self.assert_oracle(items, data)
                hits = [p for p in result.critical_locations_after if p.district == 'Есиль']
                self.assertEqual(len(hits), 3 if value < 40 else 0)
        # Count after the negative effect, without rounding values to 40.
        for value in (41.749999, 41.75, 41.750001):
            data = self.synthetic({'Нура': {'T1': value}})
            self.assert_oracle(items, data)

    def test_weakest_district_changes_and_ties(self) -> None:
        data = self.synthetic({name: {k: 50 for k in WEIGHTS} for name, *_ in DISTRICTS})
        result = self.assert_oracle(BENCHMARK, data)
        self.assertEqual(result.weakest_district_before, 'Есиль')
        changes = {name: {k: 50 for k in WEIGHTS} for name, *_ in DISTRICTS}
        changes['Нура'] = {k: 49 for k in WEIGHTS}
        changed = self.assert_oracle(BENCHMARK, self.synthetic(changes))
        self.assertEqual(changed.weakest_district_before, 'Нура')
        self.assertEqual(changed.weakest_district, 'Есиль')

    def test_count_duplicates_assignment_and_balance(self) -> None:
        for count in (0, 1, 4, 6):
            with self.subTest(count=count):
                self.assert_invalid((BENCHMARK * 2)[:count])
        for district in ('Нура', 'Алматы'):
            items = deepcopy(BENCHMARK)
            items[-1] = {'measure_id': 'M7', 'district': district}
            self.assert_invalid(items)
        self.assert_invalid(decisions(['M12', 'M12', 'M9', 'M10', 'M4']))
        for mid, spec in MEASURES.items():
            ids = next(ids for ids in combinations(MEASURES, 5) if mid in ids and valid_oracle(decisions(list(ids))))
            items = decisions([mid] + [other for other in ids if other != mid])
            items[0] = {'measure_id': mid, 'district': 'Город' if spec[3] == 'Город' else None}
            self.assert_invalid(items)
        items = deepcopy(BENCHMARK)
        items[0]['district'] = 'Unknown district'
        self.assert_invalid(items)
        self.assert_invalid(decisions(['M7', 'M8', 'M9', 'M10', 'M12']))
        for directions in (3, 4, 5):
            ids = next(ids for ids in combinations(MEASURES, 5) if len({MEASURES[mid][2] for mid in ids}) == directions and valid_oracle(decisions(list(ids))))
            self.assertTrue(validate_scenario(decisions(list(ids)), self.dataset).valid)

    def test_global_and_local_conflicts(self) -> None:
        for left, right in (('M1', 'M3'), ('M4', 'M7'), ('M5', 'M13')):
            items = decisions([left, right, 'M9', 'M10', 'M12'])
            for target in ('Нура', 'Алматы'):
                items[1]['district'] = target
                for ordered in (items, list(reversed(items))):
                    with self.subTest(pair=(left, right), target=target):
                        if left == 'M1' or target == 'Нура':
                            self.assert_invalid(ordered)
                        else:
                            self.assert_oracle(ordered)

    def test_budget_edges_and_no_unspent_bonus(self) -> None:
        for cost in (99, 100, 101):
            ids = next(ids for ids in combinations(MEASURES, 5) if sum(MEASURES[mid][0] for mid in ids) == cost and valid_oracle(decisions(list(ids)), check_budget=False))
            with self.subTest(cost=cost):
                if cost > 100:
                    self.assert_invalid(decisions(list(ids)))
                else:
                    self.assert_oracle(decisions(list(ids)))
        payload = self.dataset.model_dump()
        for measure in payload['measures']:
            measure['cost'] = 1
        cheap = Dataset.model_validate(payload)
        normal = self.result(BENCHMARK)
        reduced = self.assert_oracle(BENCHMARK, cheap)
        self.assertEqual(normal.city_score_after, reduced.city_score_after)

    def test_malformed_payloads_are_controlled_and_have_no_score(self) -> None:
        for payload in (None, True, 5, 'M7', {}, {'decisions': BENCHMARK}, [None] * 5, [1] * 5):
            with self.subTest(payload=payload):
                self.assert_invalid(payload)
        for replacement in ({}, {'measure_id': 7}, {'measure_id': True}, {'measure_id': 'M99'}, {'measure_id': ''}, {'measure_id': 'M7', 'district': 1}, {'measure_id': 'M7', 'district': ''}, {'measure_id': 'M7', 'district': 'Нура', 'extra': 1}):
            items = deepcopy(BENCHMARK)
            items[0] = replacement
            self.assert_invalid(items)
        with self.assertRaises(ValidationError):
            Decision(measure_id=7)
        self.assertTrue(validate_scenario([Decision(**item) for item in BENCHMARK], self.dataset).valid)

    def test_invalid_scenarios_never_enter_scoring(self) -> None:
        items = deepcopy(BENCHMARK)
        items[0] = {'measure_id': 'M99', 'district': 'Unknown district'}
        items[1] = {'measure_id': 'M10'}
        with patch('engine.simulator._score', side_effect=AssertionError('Invalid scenario reached scoring')):
            report = self.assert_invalid(items)
        self.assertIsNone(report.budget_used)
        self.assertGreaterEqual(len(report.errors), 3)
        self.assertEqual(report.model_dump(), validate_scenario(items, self.dataset).model_dump())

    def test_order_repetition_purity_and_json_round_trip(self) -> None:
        before_data = self.dataset.model_dump()
        before_decisions = deepcopy(BENCHMARK)
        first = self.result(BENCHMARK)
        snapshot = first.model_dump()
        for variant in permutations(BENCHMARK):
            self.assertEqual(self.result(list(variant)).model_dump(), snapshot)
        self.assertEqual(self.dataset.model_dump(), before_data)
        self.assertEqual(BENCHMARK, before_decisions)
        self.assertEqual(first.model_dump(), snapshot)
        self.assertEqual(SimulationResult.model_validate_json(first.model_dump_json()), first)
        self.assertNotIn('validation_errors', snapshot)
        self.assertEqual([d.measure_id for d in first.decisions], [mid for mid in MEASURES if mid in {i['measure_id'] for i in BENCHMARK}])
        self.assertEqual([d.name for d in first.districts], [d[0] for d in DISTRICTS])

    def test_result_contract_rejects_malformed_audit(self) -> None:
        original = self.result(BENCHMARK).model_dump()
        for kind in ('nan', 'infinite', 'out_of_range', 'missing_indicator', 'critical_count', 'duplicate_critical', 'budget', 'district_order', 'contribution', 'clipping'):
            payload = deepcopy(original)
            if kind in ('nan', 'infinite'):
                payload['city_score_after'] = float('nan' if kind == 'nan' else 'inf')
            elif kind == 'out_of_range':
                payload['districts'][0]['indicators_after']['T1'] = 101
            elif kind == 'missing_indicator':
                del payload['districts'][0]['indicator_deltas']['T1']
            elif kind == 'critical_count':
                payload['critical_metrics_before'] += 1
            elif kind == 'duplicate_critical':
                payload['critical_locations_before'][1] = deepcopy(payload['critical_locations_before'][0])
            elif kind == 'budget':
                payload['budget_remaining'] += 1
            elif kind == 'district_order':
                payload['districts'].reverse()
            elif kind == 'contribution':
                del payload['measure_contributions']['M7']
            else:
                del payload['clipping_adjustments']['Нура']['T1']
            with self.subTest(kind=kind):
                with self.assertRaises(ValidationError):
                    SimulationResult.model_validate(payload)

    def test_audit_reconciliation(self) -> None:
        data = self.synthetic({'Нура': {'B1': 99, 'S1': 99, 'S2': 99}})
        result = self.result(BENCHMARK, data)
        for district in result.districts:
            self.assertEqual(set(district.indicator_deltas), set(WEIGHTS))
            for key in WEIGHTS:
                direct = sum(targets.get(district.name, {}).get(key, 0) for targets in result.measure_contributions.values())
                synergy = sum(s.bonus for s in result.synergy_contributions if s.district == district.name and s.indicator == key)
                clipping = result.clipping_adjustments[district.name].get(key, 0)
                self.assertAlmostEqual(direct + synergy + clipping, district.indicator_deltas[key], places=11)

    def test_all_five_measure_combinations(self) -> None:
        for ids in combinations(MEASURES, 5):
            items = decisions(list(ids))
            with self.subTest(ids=ids):
                valid = valid_oracle(items)
                self.assertEqual(validate_scenario(items, self.dataset).valid, valid)
                if valid:
                    result = self.assert_oracle(items)
                    self.assert_integer_oracle(result, items)

    def assert_integer_oracle(self, result: SimulationResult, items: list[dict[str, Any]]) -> None:
        rows, scores, weighted, critical, weakest, score = integer_oracle(items)
        self.assertAlmostEqual(result.city_score_after, score / 800000, places=11)
        self.assertAlmostEqual(result.weighted_city_score, weighted / 80000, places=11)
        self.assertEqual(result.critical_metrics, critical)
        self.assertEqual(result.weakest_district, DISTRICTS[weakest][0])
        for district, row, district_score in zip(result.districts, rows, scores):
            self.assertEqual(district.indicators_after, dict(zip(WEIGHTS, (value / 8 for value in row))))
            self.assertAlmostEqual(district.score_after, district_score / 800, places=11)

    @unittest.skipUnless(os.environ.get('SIMULATOR_EXHAUSTIVE') == '1', 'optional complete district-assignment sweep')
    def test_complete_assignment_sweep(self) -> None:
        names = [d[0] for d in DISTRICTS]
        for ids in combinations(MEASURES, 5):
            scoped = [mid for mid in ids if MEASURES[mid][3] == 'Район']
            for locations in product(names, repeat=len(scoped)):
                assignments = dict(zip(scoped, locations))
                items = [{'measure_id': mid, **({'district': assignments[mid]} if mid in assignments else {})} for mid in ids]
                valid = valid_oracle(items)
                self.assertEqual(validate_scenario(items, self.dataset).valid, valid, str(items))
                if valid:
                    self.assert_integer_oracle(self.result(items), items)

    def test_no_network_ui_or_advisor_dependencies(self) -> None:
        script = '''
import builtins
original = builtins.__import__
def guarded(name: str, *args: object, **kwargs: object) -> object:
    if name.split('.')[0] in {'openai', 'streamlit', 'httpx', 'requests'} or name == 'engine.advisor':
        raise AssertionError('Forbidden dependency: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from engine.simulator import load_dataset, simulate
from engine.models import SimulationResult
items = %r
assert isinstance(simulate(items, load_dataset()), SimulationResult)
''' % BENCHMARK
        environment = dict(os.environ, OPENAI_API_KEY='', MOCK_MODE='true')
        process = subprocess.run([sys.executable, '-c', script], cwd=ROOT, env=environment, capture_output=True, text=True, check=False)
        self.assertEqual(process.returncode, 0, process.stderr)
        with patch.dict(os.environ, {'OPENAI_API_KEY': '', 'MOCK_MODE': 'true'}):
            offline = self.result(BENCHMARK).model_dump()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'not-a-real-key', 'MOCK_MODE': 'false'}):
            self.assertEqual(self.result(BENCHMARK).model_dump(), offline)


class DatasetFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.documents = {name: json.loads((ROOT / 'data' / name).read_text()) for name in ('districts.json', 'measures.json')}
        self.write_documents()

    def write_documents(self) -> None:
        for name, payload in self.documents.items():
            (self.path / name).write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')

    def assert_bad(self) -> None:
        self.write_documents()
        with self.assertRaises(DatasetError):
            load_dataset(self.path)

    def test_missing_unreadable_malformed_and_duplicate_keys(self) -> None:
        with self.assertRaises(DatasetError):
            load_dataset(self.path / 'absent')
        with patch('pathlib.Path.read_text', side_effect=PermissionError('unreadable')):
            with self.assertRaises(DatasetError):
                load_dataset(self.path)
        for contents in ('{', '[]', '{"districts": [], "districts": []}'):
            (self.path / 'districts.json').write_text(contents)
            with self.assertRaises(DatasetError):
                load_dataset(self.path)

    def test_strict_scale_and_noncoercing_numeric_fields(self) -> None:
        original = deepcopy(self.documents)
        mutations = [
            ('scale_min_bool', 'scale', 'min', False),
            ('scale_max_float', 'scale', 'max', 100.0),
            ('scale_higher_integer', 'scale', 'higher_is_better', 1),
            ('cost_bool', 'measure', 'cost', True),
            ('cost_string', 'measure', 'cost', '18'),
            ('lag_bool', 'measure', 'lag', False),
            ('lag_string', 'measure', 'lag', '2'),
            ('indicator_bool', 'indicator', 'T1', True),
        ]
        for name, target, key, value in mutations:
            self.documents = deepcopy(original)
            if target == 'scale':
                self.documents['districts.json']['indicator_scale'][key] = value
            elif target == 'indicator':
                self.documents['districts.json']['districts'][0]['indicators'][key] = value
            else:
                self.documents['measures.json']['measures'][0][key] = value
            with self.subTest(name=name):
                self.assert_bad()

    def test_missing_rules_and_finite_effect_overflow(self) -> None:
        original = deepcopy(self.documents)
        for rules in ('synergies', 'incompatibilities'):
            self.documents = deepcopy(original)
            self.documents['measures.json'][rules].pop()
            with self.subTest(rules=rules):
                self.assert_bad()
        self.documents = deepcopy(original)
        for measure in self.documents['measures.json']['measures'][:2]:
            measure['effects']['T1'] = 1.7e308
            measure['lag'] = 0
        self.assert_bad()

    def test_valid_data_needs_no_mock_briefing(self) -> None:
        self.assertFalse((self.path / 'mock_debrief.json').exists())
        dataset = load_dataset(self.path)
        self.assertIsInstance(simulate(BENCHMARK, dataset), SimulationResult)

    def test_invalid_district_data(self) -> None:
        original = deepcopy(self.documents)
        for kind in ('duplicate', 'unknown_name', 'missing_indicator', 'unknown_indicator', 'nan', 'infinite', 'out_of_range', 'wrong_type', 'population_sum', 'base_score'):
            self.documents = deepcopy(original)
            row = self.documents['districts.json']['districts'][0]
            if kind == 'duplicate':
                self.documents['districts.json']['districts'][1] = deepcopy(row)
            elif kind == 'unknown_name':
                row['name'] = 'Unknown'
            elif kind == 'missing_indicator':
                del row['indicators']['T1']
            elif kind == 'unknown_indicator':
                row['indicators']['X1'] = 5
            elif kind in ('nan', 'infinite'):
                row['indicators']['T1'] = float('nan' if kind == 'nan' else 'inf')
            elif kind == 'out_of_range':
                row['indicators']['T1'] = 101
            elif kind == 'wrong_type':
                row['indicators']['T1'] = '45'
            elif kind == 'population_sum':
                row['population_weight'] = 0.5
            else:
                row['base_score'] = 1
            with self.subTest(kind=kind):
                self.assert_bad()

    def test_invalid_measure_and_rule_data(self) -> None:
        original = deepcopy(self.documents)
        for kind in ('duplicate', 'unknown_id', 'cost', 'lag', 'effect', 'nonfinite', 'scope', 'direction', 'synergy_reference', 'conflict_reference', 'horizon', 'duplicate_rule', 'self_rule', 'synergy_target', 'conflict_scope', 'unknown_field'):
            self.documents = deepcopy(original)
            data = self.documents['measures.json']
            row = data['measures'][0]
            if kind == 'duplicate':
                data['measures'][1] = deepcopy(row)
            elif kind == 'unknown_id':
                row['id'] = 'M99'
            elif kind == 'cost':
                row['cost'] = -1
            elif kind == 'lag':
                row['lag'] = 9
            elif kind == 'effect':
                row['effects']['X1'] = 1
            elif kind == 'nonfinite':
                row['effects']['T1'] = float('nan')
            elif kind == 'scope':
                row['scope'] = 'unknown'
            elif kind == 'direction':
                row['direction'] = 'unknown'
            elif kind == 'synergy_reference':
                data['synergies'][0]['measures'][0] = 'M99'
            elif kind == 'conflict_reference':
                data['incompatibilities'][0]['measures'][0] = 'M99'
            elif kind == 'horizon':
                data['horizon_quarters'] = 0
            elif kind == 'duplicate_rule':
                data['synergies'].append(deepcopy(data['synergies'][0]))
            elif kind == 'self_rule':
                data['synergies'][0]['measures'] = ['M1', 'M1']
            elif kind == 'synergy_target':
                data['synergies'][0]['target_measure'] = 'M2'
            elif kind == 'conflict_scope':
                data['incompatibilities'][0]['scope'] = 'unknown'
            else:
                row['surprise'] = 1
            with self.subTest(kind=kind):
                self.assert_bad()


if __name__ == '__main__':
    unittest.main()
