"""Offline UI acceptance tests; every advisor credential and client is isolated."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import MagicMock, patch

from streamlit.testing.v1 import AppTest

from engine import advisor, simulator
from engine.advisor import AdvisorSettings
from engine.models import SimulationResult


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = [
    {"measure_id": "M7", "district": "Нура"},
    {"measure_id": "M8", "district": "Нура"},
    {"measure_id": "M10", "district": "Нура"},
    {"measure_id": "M12"},
    {"measure_id": "M5", "district": "Сарыарка"},
]


class AppTests(unittest.TestCase):
    benchmark: SimulationResult
    settings_mock: MagicMock
    client_class: MagicMock
    dotenv_mock: MagicMock

    @classmethod
    def setUpClass(cls) -> None:
        result = simulator.simulate(REFERENCE, simulator.load_dataset())
        if not isinstance(result, SimulationResult):
            raise AssertionError("Reference scenario must be valid")
        cls.benchmark = result

    def setUp(self) -> None:
        settings_patch = patch.object(
            AdvisorSettings, "from_environment",
            return_value=AdvisorSettings(
                openai_api_key="fake-openai-for-ui-test",
                nvidia_api_key="fake-nvidia-for-ui-test",
            ),
        )
        self.settings_mock = settings_patch.start()
        self.addCleanup(settings_patch.stop)
        client_patch = patch("engine.advisor.OpenAI")
        self.client_class = client_patch.start()
        self.addCleanup(client_patch.stop)
        # A regression must not silently load local credentials in these tests.
        dotenv_patch = patch("engine.advisor.load_dotenv", side_effect=AssertionError("Do not read .env"))
        self.dotenv_mock = dotenv_patch.start()
        self.addCleanup(dotenv_patch.stop)
        self.client_class.return_value.responses.parse.side_effect = self.openai_response
        self.client_class.return_value.chat.completions.create.return_value = self.nvidia_response()

    def model_text(self) -> dict[str, str]:
        return {
            field: options[0]
            for field, options in advisor._candidate_briefings(self.benchmark).items()
        }

    def openai_response(self, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            status="completed",
            output_parsed=kwargs["text_format"].model_validate(self.model_text()),
            usage=None,
            id="test-ui-response",
        )

    def nvidia_response(self) -> SimpleNamespace:
        return SimpleNamespace(
            choices=[SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content=json.dumps(self.model_text(), ensure_ascii=False)),
            )],
            usage=None,
            id="test-ui-chat",
        )

    def app(self) -> AppTest:
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=15).run()
        self.assertEqual(len(app.exception), 0)
        return app

    def visible_text(self, app: AppTest) -> str:
        return "\n".join(
            str(element.value)
            for kind in ("title", "header", "subheader", "markdown", "caption", "text", "info", "warning", "error", "success")
            for element in app.get(kind)
        )

    def errors(self, app: AppTest) -> str:
        return "\n".join(str(element.value) for element in app.error)

    def simulate(self, app: AppTest) -> AppTest:
        self.assertFalse(app.button(key="simulate").disabled)
        app.button(key="simulate").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertIsInstance(app.session_state["result"], SimulationResult)
        return app

    def assert_no_result(self, app: AppTest) -> None:
        self.assertIsNone(app.session_state["result"])
        self.assertIsNone(app.session_state["briefing"])
        self.assertNotIn("generate_briefing", [button.key for button in app.button])
        self.assertEqual(len(app.exception), 0)

    def test_startup_prefills_reference_without_simulation_or_api(self) -> None:
        with patch("engine.simulator.simulate", wraps=simulator.simulate) as simulate_call:
            app = self.app()
            simulate_call.assert_not_called()
        self.assertIn("Аким на 5 часов", self.visible_text(app))
        for index, decision in enumerate(REFERENCE):
            self.assertEqual(app.selectbox(key=f"measure_{index}").value, decision["measure_id"])
            if "district" in decision:
                self.assertEqual(app.selectbox(key=f"district_{index}").value, decision["district"])
        self.assertEqual(len([widget for widget in app.selectbox if str(widget.key).startswith("measure_")]), 5)
        self.assertIn("95", [metric.value for metric in app.metric])
        self.assertFalse(app.button(key="simulate").disabled)
        self.assertEqual(app.selectbox(key="provider").value, "openai")
        self.assert_no_result(app)
        self.client_class.assert_not_called()
        self.dotenv_mock.assert_not_called()

    def test_reference_kpis_and_table_match_python_result(self) -> None:
        app = self.simulate(self.app())
        self.assertEqual(app.session_state["result"], self.benchmark)
        metrics = list(app.metric)
        score = next(metric for metric in metrics if metric.value == "56.54")
        self.assertIn("+3.99", score.delta)
        values = " ".join(str(metric.value) for metric in metrics)
        for expected in ("95", "5", "Нура", "0"):
            self.assertIn(expected, values)
        self.assertIn("52.96", values + self.visible_text(app) + " ".join(str(metric.delta) for metric in metrics))
        tables = list(app.dataframe) + list(app.table)
        self.assertEqual(len(tables), 1)
        rows = tables[0].value.to_numpy().tolist()
        self.assertEqual(len(rows), 5)
        for row, district in zip(rows, self.benchmark.districts):
            self.assertEqual(row[0], district.name)
            for actual, expected in zip(row[1:], (district.score_before, district.score_after, district.delta)):
                self.assertAlmostEqual(float(actual), expected, places=10)
        self.client_class.assert_not_called()

    def test_empty_rows_and_original_row_number_for_missing_district(self) -> None:
        app = self.app()
        app.selectbox(key="measure_0").select(None).run()
        app.selectbox(key="district_4").select(None).run()
        self.assertTrue(app.button(key="simulate").disabled)
        errors = self.errors(app)
        self.assertRegex(errors, r"[Рр]ешени[ея]\s+5")
        self.assertIn("район", errors.lower())
        self.assertIn("5", errors)
        self.assert_no_result(app)
        self.client_class.assert_not_called()

    def test_invalid_selections_remain_visible_and_disable_simulation(self) -> None:
        cases = (
            ([(1, "M7")], "несколько раз"),
            ([(2, "M9")], "направлен"),
            ([(2, "M13")], "бюджет"),
            ([(0, "M1"), (1, "M3")], "M1"),
            ([(1, "M4")], "M4"),
        )
        for edits, phrase in cases:
            with self.subTest(edits=edits):
                app = self.app()
                for index, measure_id in edits:
                    app.selectbox(key=f"measure_{index}").select(measure_id).run()
                self.assertTrue(app.button(key="simulate").disabled)
                self.assertIn(phrase, self.errors(app))
                self.assertRegex(self.errors(app), "[А-Яа-я]")
                for index, measure_id in edits:
                    self.assertEqual(app.selectbox(key=f"measure_{index}").value, measure_id)
                self.assert_no_result(app)
        self.client_class.assert_not_called()

    def test_duplicate_measure_cost_includes_each_selected_row(self) -> None:
        app = self.app()
        app.selectbox(key="measure_1").select("M7").run()
        self.assertIn("99", [metric.value for metric in app.metric])
        self.assertTrue(app.button(key="simulate").disabled)

    def test_city_scope_clears_district_and_switch_back_requires_selection(self) -> None:
        app = self.app()
        app.selectbox(key="measure_0").select("M8").run()
        self.assertEqual(app.selectbox(key="district_0").value, "Нура")
        app.selectbox(key="measure_0").select("M2").run()
        self.assertNotIn("district_0", [widget.key for widget in app.selectbox])
        self.assertIn("Весь город", self.visible_text(app))
        self.simulate(app)
        city_decision = next(
            decision for decision in app.session_state["result"].decisions
            if decision.measure_id == "M2"
        )
        self.assertIsNone(city_decision.district)
        app.selectbox(key="measure_0").select("M7").run()
        self.assertIsNone(app.selectbox(key="district_0").value)
        self.assertTrue(app.button(key="simulate").disabled)
        self.assert_no_result(app)
        self.client_class.assert_not_called()

    def test_clear_reload_and_edits_remove_results_but_keep_briefing_cache(self) -> None:
        app = self.simulate(self.app())
        app.button(key="generate_briefing").click().run()
        cache = dict(app.session_state["advisor_cache"])
        self.assertEqual(len(cache), 1)
        app.selectbox(key="district_0").select("Есиль").run()
        self.assert_no_result(app)
        self.assertEqual(app.session_state["advisor_cache"], cache)
        app.button(key="load_reference").click().run()
        self.assert_no_result(app)
        self.simulate(app)
        app.button(key="generate_briefing").click().run()
        self.client_class.return_value.responses.parse.assert_called_once()
        app.selectbox(key="measure_0").select("M9").run()
        self.assert_no_result(app)
        app.button(key="clear_selection").click().run()
        self.assert_no_result(app)
        self.assertTrue(all(widget.value is None for widget in app.selectbox if str(widget.key).startswith("measure_")))
        self.assertTrue(app.button(key="simulate").disabled)
        self.assertEqual(app.session_state["advisor_cache"], cache)
        app.button(key="load_reference").click().run()
        self.assertFalse(app.button(key="simulate").disabled)
        self.assert_no_result(app)

    def test_explicit_briefing_only_and_provider_switch_preserves_result(self) -> None:
        app = self.app()
        app.selectbox(key="provider").select("nvidia").run()
        self.simulate(app)
        self.client_class.assert_not_called()
        before = app.session_state["result"].model_dump()
        app.button(key="generate_briefing").click().run()
        self.assertEqual(app.session_state["briefing"].source, "nvidia")
        self.assertIn("NVIDIA", self.visible_text(app))
        app.button(key="generate_briefing").click().run()
        self.client_class.return_value.chat.completions.create.assert_called_once()
        app.selectbox(key="provider").select("openai").run()
        self.assertIsNone(app.session_state["briefing"])
        self.assertEqual(app.session_state["result"].model_dump(), before)
        self.client_class.return_value.responses.parse.assert_not_called()
        app.button(key="generate_briefing").click().run()
        self.assertEqual(app.session_state["briefing"].source, "openai")
        self.assertIn("OpenAI", self.visible_text(app))
        self.client_class.return_value.responses.parse.assert_called_once()
        self.assertEqual(app.session_state["result"].model_dump(), before)
        self.assertNotIn("api_key", repr(app.session_state).lower())
        self.assertNotIn("fake-openai-for-ui-test", repr(app.session_state))
        self.assertNotIn("fake-nvidia-for-ui-test", repr(app.session_state))

    def test_configuration_selects_provider_and_mock_mode_forces_offline(self) -> None:
        self.settings_mock.return_value = AdvisorSettings(provider="nvidia")
        app = self.app()
        self.assertEqual(app.selectbox(key="provider").value, "nvidia")
        self.settings_mock.return_value = AdvisorSettings(provider="nvidia", mock_mode=True)
        app = self.simulate(self.app())
        self.assertEqual(app.selectbox(key="provider").value, "offline")
        self.assertTrue(app.selectbox(key="provider").disabled)
        app.button(key="generate_briefing").click().run()
        self.assertEqual(app.session_state["briefing"].source, "mock")
        self.assertIn("автоном", self.visible_text(app).lower())
        self.client_class.assert_not_called()

    def test_missing_keys_and_failed_calls_display_actual_offline_source(self) -> None:
        for provider in ("openai", "nvidia"):
            for missing_key in (True, False):
                with self.subTest(provider=provider, missing_key=missing_key):
                    self.client_class.reset_mock()
                    self.settings_mock.return_value = AdvisorSettings(
                        provider=provider,
                        openai_api_key="" if missing_key else "fake-openai",
                        nvidia_api_key="" if missing_key else "fake-nvidia",
                    )
                    self.client_class.return_value.responses.parse.side_effect = TimeoutError("test failure")
                    self.client_class.return_value.chat.completions.create.side_effect = TimeoutError("test failure")
                    app = self.simulate(self.app())
                    app.button(key="generate_briefing").click().run()
                    self.assertEqual(len(app.exception), 0)
                    self.assertEqual(app.session_state["briefing"].source, "mock")
                    self.assertIn("автоном", self.visible_text(app).lower())
                    app.button(key="generate_briefing").click().run()
                    if missing_key:
                        self.client_class.assert_not_called()
                    else:
                        self.client_class.assert_called_once()

    def test_offline_selection_makes_no_provider_call(self) -> None:
        app = self.simulate(self.app())
        app.selectbox(key="provider").select("offline").run()
        app.button(key="generate_briefing").click().run()
        self.assertEqual(app.session_state["briefing"].source, "mock")
        self.client_class.assert_not_called()

    def test_critical_pairs_are_displayed_for_affected_district(self) -> None:
        app = self.app()
        app.selectbox(key="district_0").select("Есиль").run()
        app.selectbox(key="district_1").select("Есиль").run()
        self.simulate(app)
        self.assertEqual(app.session_state["result"].critical_metrics, 2)
        text = self.visible_text(app)
        for expected in (
            "Нура", "Доступность школ и детских садов",
            "Доступность поликлиник и первичной помощи",
        ):
            self.assertIn(expected, text)
        warning_text = " ".join(str(item.value) for item in app.warning)
        self.assertNotIn("S1", warning_text)
        self.assertNotIn("S2", warning_text)

    def test_dataset_failure_stops_controls_without_traceback(self) -> None:
        with patch("engine.simulator.load_dataset", side_effect=simulator.DatasetError("private error details")):
            app = self.app()
        self.assertGreater(len(app.error), 0)
        self.assertNotIn("measure_0", [widget.key for widget in app.selectbox])
        self.assertNotIn("simulate", [button.key for button in app.button])
        self.assertNotIn("private error details", self.visible_text(app))
        self.client_class.assert_not_called()

    def test_simulation_and_briefing_failures_are_recoverable(self) -> None:
        app = self.app()
        with patch("engine.simulator.simulate", side_effect=RuntimeError("private failure")):
            app.button(key="simulate").click().run()
        self.assert_no_result(app)
        self.assertGreater(len(app.error), 0)
        self.assertNotIn("private failure", self.visible_text(app))
        self.simulate(app)
        with patch("engine.advisor.generate_debrief", side_effect=RuntimeError("private failure")):
            app.button(key="generate_briefing").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertIsNone(app.session_state["briefing"])
        self.assertIsInstance(app.session_state["result"], SimulationResult)
        self.assertGreater(len(app.error), 0)
        self.assertNotIn("private failure", self.visible_text(app))
        app.button(key="generate_briefing").click().run()
        self.assertEqual(app.session_state["briefing"].source, "openai")


if __name__ == "__main__":
    unittest.main()
