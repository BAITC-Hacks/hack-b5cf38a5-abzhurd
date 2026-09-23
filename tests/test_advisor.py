"""Offline acceptance tests for the two advisor adapters and their fallback."""

from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import json
import unittest
from unittest.mock import patch

from engine import advisor
from engine.advisor import AdvisorSettings, generate_debrief
from engine.models import Dataset, Debrief, SimulationResult
from engine.simulator import load_dataset, simulate


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = [
    {"measure_id": "M7", "district": "Нура"},
    {"measure_id": "M8", "district": "Нура"},
    {"measure_id": "M10", "district": "Нура"},
    {"measure_id": "M12"},
    {"measure_id": "M5", "district": "Сарыарка"},
]
def result_for(dataset: Dataset, decisions: list[dict[str, str]]) -> SimulationResult:
    result = simulate(decisions, dataset)
    if not isinstance(result, SimulationResult):
        raise AssertionError(f"Fixture must be valid: {result.model_dump()}")
    return result


def all_100_dataset(dataset: Dataset) -> Dataset:
    """A valid synthetic fixture for zero and negative score changes."""
    payload = dataset.model_dump()
    for district in payload["districts"]:
        district["indicators"] = {key: 100.0 for key in district["indicators"]}
        district["base_score"] = 100.0
    return Dataset.model_validate(payload)


class AdvisorTests(unittest.TestCase):
    dataset: Dataset
    benchmark: SimulationResult

    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset = load_dataset(ROOT / "data")
        cls.benchmark = result_for(cls.dataset, BENCHMARK)

    def model_text(self, result: SimulationResult | None = None) -> dict[str, str]:
        """Select one exact Python-grounded candidate for each text section."""
        return {
            field: options[0]
            for field, options in advisor._candidate_briefings(result or self.benchmark).items()
        }

    def openai_response(self, kwargs: dict[str, Any], *, status: str = "completed", text: dict[str, str] | None = None) -> SimpleNamespace:
        parsed_type = kwargs["text_format"]
        parsed = parsed_type.model_validate(text if text is not None else self.model_text())
        return SimpleNamespace(status=status, output_parsed=parsed, usage=SimpleNamespace(input_tokens=100, output_tokens=40), id="response-test")

    def nvidia_response(self, *, content: str | None = None, finish_reason: str = "stop") -> SimpleNamespace:
        message = SimpleNamespace(content=content if content is not None else json.dumps(self.model_text(), ensure_ascii=False))
        choice = SimpleNamespace(message=message, finish_reason=finish_reason)
        return SimpleNamespace(choices=[choice], usage=SimpleNamespace(prompt_tokens=100, completion_tokens=40), id="chat-test")

    def assert_mock(self, briefing: Debrief) -> None:
        self.assertIsInstance(briefing, Debrief)
        self.assertEqual(briefing.source, "mock")
        self.assertTrue(briefing.why_score_changed.strip())
        self.assertTrue(briefing.main_risk.strip())
        self.assertTrue(briefing.next_quarter_recommendation.strip())

    def test_openai_success_uses_responses_parse_and_python_source(self) -> None:
        cache: dict[str, Debrief] = {}
        settings = AdvisorSettings(openai_api_key="test-openai-key")
        with patch("engine.advisor.OpenAI") as client_class:
            client = client_class.return_value
            client.responses.parse.side_effect = lambda **kwargs: self.openai_response(kwargs)
            briefing = generate_debrief(self.benchmark, cache, settings=settings)

        self.assertEqual(briefing.source, "openai")
        self.assertEqual(briefing.why_score_changed, self.model_text()["why_score_changed"])
        client_class.assert_called_once()
        self.assertEqual(client_class.call_args.kwargs["timeout"], 20)
        self.assertEqual(client_class.call_args.kwargs["max_retries"], 0)
        called = client.responses.parse.call_args.kwargs
        self.assertEqual(called["model"], "gpt-6-sol")
        self.assertEqual(called["reasoning"], {"effort": "low"})
        self.assertEqual(called["max_output_tokens"], 700)
        self.assertIs(called["store"], False)
        self.assertEqual(len(called["input"]), 2)
        self.assertEqual([item["role"] for item in called["input"]], ["system", "user"])
        self.assertNotIn("source", called["text_format"].model_fields)

    def test_nvidia_success_uses_hosted_chat_and_local_json_validation(self) -> None:
        cache: dict[str, Debrief] = {}
        settings = AdvisorSettings(provider="nvidia", nvidia_api_key="test-nvidia-key")
        with patch("engine.advisor.OpenAI") as client_class:
            client = client_class.return_value
            client.chat.completions.create.return_value = self.nvidia_response()
            briefing = generate_debrief(self.benchmark, cache, settings=settings)

        self.assertEqual(briefing.source, "nvidia")
        self.assertEqual(briefing.main_risk, self.model_text()["main_risk"])
        self.assertEqual(client_class.call_args.kwargs["base_url"], "https://integrate.api.nvidia.com/v1")
        self.assertEqual(client_class.call_args.kwargs["timeout"], 20)
        self.assertEqual(client_class.call_args.kwargs["max_retries"], 0)
        called = client.chat.completions.create.call_args.kwargs
        self.assertEqual(called["model"], "mistralai/mistral-nemotron")
        self.assertEqual(called["max_tokens"], 700)
        self.assertIs(called["stream"], False)
        self.assertEqual([item["role"] for item in called["messages"]], ["system", "user"])

    def test_explicit_settings_cannot_exceed_request_limits(self) -> None:
        for provider in ("openai", "nvidia"):
            with self.subTest(provider=provider), patch("engine.advisor.OpenAI") as client_class:
                client = client_class.return_value
                client.responses.parse.side_effect = lambda **kwargs: self.openai_response(kwargs)
                client.chat.completions.create.return_value = self.nvidia_response()
                settings = AdvisorSettings(
                    provider=provider,
                    openai_api_key="test-openai-key",
                    nvidia_api_key="test-nvidia-key",
                    max_output_tokens=900,
                    timeout_seconds=60,
                )
                briefing = generate_debrief(self.benchmark, {}, settings=settings)
                self.assertEqual(briefing.source, provider)
                self.assertEqual(client_class.call_args.kwargs["timeout"], 20)
                if provider == "openai":
                    self.assertEqual(client.responses.parse.call_args.kwargs["max_output_tokens"], 700)
                else:
                    self.assertEqual(client.chat.completions.create.call_args.kwargs["max_tokens"], 700)

    def test_prompt_contains_authoritative_facts_and_no_secrets(self) -> None:
        settings = AdvisorSettings(openai_api_key="secret-never-in-prompt")
        with patch("engine.advisor.OpenAI") as client_class:
            client_class.return_value.responses.parse.side_effect = lambda **kwargs: self.openai_response(kwargs)
            generate_debrief(self.benchmark, {}, settings=settings)
            prompt = json.dumps(client_class.return_value.responses.parse.call_args.kwargs["input"], ensure_ascii=False)

        for fact in (
            "56.54307", "52.55768", "95", "Нура", "Сарыарка", "M10", "M12",
            "indicator_deltas", "measure_contributions", "synergy_contributions", "clipping_adjustments",
        ):
            with self.subTest(fact=fact):
                self.assertIn(fact, prompt)
        self.assertNotIn("secret-never-in-prompt", prompt)
        for sentence in self.model_text().values():
            self.assertIn(sentence, prompt)

    def test_environment_configuration_and_offline_override(self) -> None:
        values = {
            "ADVISOR_PROVIDER": "nvidia",
            "MOCK_MODE": "true",
            "OPENAI_API_KEY": "openai-secret",
            "NVIDIA_API_KEY": "nvidia-secret",
            "OPENAI_MODEL": "custom-openai",
            "NVIDIA_MODEL": "custom-nvidia",
            "OPENAI_REASONING_EFFORT": "medium",
            "ADVISOR_MAX_OUTPUT_TOKENS": "900",
        }
        with patch("engine.advisor.load_dotenv"), patch.dict(os.environ, values):
            settings = AdvisorSettings.from_environment()
        self.assertEqual(settings.provider, "nvidia")
        self.assertTrue(settings.mock_mode)
        self.assertEqual(settings.openai_api_key, "openai-secret")
        self.assertEqual(settings.nvidia_api_key, "nvidia-secret")
        self.assertEqual(settings.openai_model, "custom-openai")
        self.assertEqual(settings.nvidia_model, "custom-nvidia")
        self.assertEqual(settings.openai_reasoning_effort, "medium")
        self.assertEqual(settings.max_output_tokens, 700)

        with patch("engine.advisor.OpenAI") as client_class:
            briefing = generate_debrief(self.benchmark, {}, settings=settings)
            client_class.assert_not_called()
        self.assert_mock(briefing)

    def test_usage_is_recorded_without_credentials_or_prompt(self) -> None:
        for provider in ("openai", "nvidia"):
            with self.subTest(provider=provider), patch("engine.advisor.OpenAI") as client_class:
                client = client_class.return_value
                client.responses.parse.side_effect = lambda **kwargs: self.openai_response(kwargs)
                client.chat.completions.create.return_value = self.nvidia_response()
                settings = AdvisorSettings(
                    provider=provider,
                    openai_api_key="openai-secret-usage",
                    nvidia_api_key="nvidia-secret-usage",
                )
                with self.assertLogs("engine.advisor", level="INFO") as logs:
                    generate_debrief(self.benchmark, {}, settings=settings)
                output = "\n".join(logs.output)
                self.assertIn(f"provider={provider}", output)
                self.assertIn("input_tokens=100", output)
                self.assertIn("output_tokens=40", output)
                self.assertNotIn("openai-secret-usage", output)
                self.assertNotIn("nvidia-secret-usage", output)
                self.assertNotIn("Нура", output)

    def test_explicit_provider_override_and_mock_mode(self) -> None:
        settings = AdvisorSettings(provider="openai", nvidia_api_key="test-nvidia-key")
        with patch("engine.advisor.OpenAI") as client_class:
            client_class.return_value.chat.completions.create.return_value = self.nvidia_response()
            chosen = generate_debrief(self.benchmark, {}, provider="nvidia", settings=settings)
        self.assertEqual(chosen.source, "nvidia")

        with patch("engine.advisor.OpenAI") as client_class:
            forced = generate_debrief(
                self.benchmark, {}, provider="nvidia",
                settings=AdvisorSettings(provider="nvidia", mock_mode=True, nvidia_api_key="test-nvidia-key"),
            )
            client_class.assert_not_called()
        self.assert_mock(forced)

    def test_offline_and_missing_key_never_instantiate_client(self) -> None:
        for provider in ("offline", "openai", "nvidia"):
            with self.subTest(provider=provider), patch("engine.advisor.OpenAI") as client_class:
                briefing = generate_debrief(self.benchmark, {}, settings=AdvisorSettings(provider=provider))
                client_class.assert_not_called()
                self.assert_mock(briefing)

    def test_provider_failures_fall_back_without_calling_other_provider(self) -> None:
        failures: tuple[Exception, ...] = (
            TimeoutError("timed out"),
            ConnectionError("network down"),
            RuntimeError("429 rate limit"),
            RuntimeError("model not found"),
        )
        for provider in ("openai", "nvidia"):
            for failure in failures:
                with self.subTest(provider=provider, failure=str(failure)), patch("engine.advisor.OpenAI") as client_class:
                    client = client_class.return_value
                    if provider == "openai":
                        client.responses.parse.side_effect = failure
                    else:
                        client.chat.completions.create.side_effect = failure
                    settings = AdvisorSettings(provider=provider, openai_api_key="openai-test", nvidia_api_key="nvidia-test")
                    briefing = generate_debrief(self.benchmark, {}, settings=settings)
                    self.assert_mock(briefing)
                    client_class.assert_called_once()
                    if provider == "openai":
                        client.chat.completions.create.assert_not_called()
                    else:
                        client.responses.parse.assert_not_called()

    def test_openai_incomplete_malformed_and_refusal_fall_back(self) -> None:
        def malformed(kwargs: dict[str, Any]) -> SimpleNamespace:
            return SimpleNamespace(status="completed", output_parsed={"main_risk": "missing fields"})

        cases = (
            lambda kwargs: self.openai_response(kwargs, status="incomplete"),
            malformed,
            lambda kwargs: SimpleNamespace(status="completed", output_parsed=None),
        )
        for response_factory in cases:
            with self.subTest(case=response_factory), patch("engine.advisor.OpenAI") as client_class:
                client_class.return_value.responses.parse.side_effect = lambda **kwargs: response_factory(kwargs)
                briefing = generate_debrief(self.benchmark, {}, settings=AdvisorSettings(openai_api_key="test-key"))
                self.assert_mock(briefing)

    def test_nvidia_malformed_truncated_refusal_and_bad_shape_fall_back(self) -> None:
        cases = (
            self.nvidia_response(content="not JSON"),
            self.nvidia_response(content=json.dumps({"main_risk": "missing fields"})),
            self.nvidia_response(content=json.dumps({**self.model_text(), "source": "nvidia"})),
            self.nvidia_response(finish_reason="length"),
            self.nvidia_response(content="", finish_reason="content_filter"),
            SimpleNamespace(choices=[]),
        )
        for response in cases:
            with self.subTest(response=response), patch("engine.advisor.OpenAI") as client_class:
                client_class.return_value.chat.completions.create.return_value = response
                briefing = generate_debrief(self.benchmark, {}, settings=AdvisorSettings(provider="nvidia", nvidia_api_key="test-key"))
                self.assert_mock(briefing)

    def test_invented_budget_event_and_measure_are_rejected_by_both_providers(self) -> None:
        invented = (
            ("why_score_changed", "Бюджет города вырос на 1000 единиц."),
            ("main_risk", "В следующем квартале произойдёт наводнение."),
            ("next_quarter_recommendation", "Постройте новый аэропорт M99."),
        )
        for provider in ("openai", "nvidia"):
            for field, sentence in invented:
                with self.subTest(provider=provider, field=field), patch("engine.advisor.OpenAI") as client_class:
                    text = {**self.model_text(), field: sentence}
                    client = client_class.return_value
                    if provider == "openai":
                        client.responses.parse.side_effect = lambda **kwargs: self.openai_response(kwargs, text=text)
                    else:
                        client.chat.completions.create.return_value = self.nvidia_response(
                            content=json.dumps(text, ensure_ascii=False)
                        )
                    settings = AdvisorSettings(
                        provider=provider, openai_api_key="openai-test", nvidia_api_key="nvidia-test"
                    )
                    briefing = generate_debrief(self.benchmark, {}, settings=settings)
                    self.assert_mock(briefing)
                    client_class.assert_called_once()
                    if provider == "openai":
                        client.chat.completions.create.assert_not_called()
                    else:
                        client.responses.parse.assert_not_called()

    def test_cache_hit_and_provider_model_scenario_isolation(self) -> None:
        cache: dict[str, Debrief] = {}
        settings = AdvisorSettings(openai_api_key="test-openai-key", nvidia_api_key="test-nvidia-key")
        alternative = result_for(self.dataset, [
            {"measure_id": "M1", "district": "Нура"},
            {"measure_id": "M4", "district": "Сарыарка"},
            {"measure_id": "M8", "district": "Нура"},
            {"measure_id": "M10", "district": "Нура"},
            {"measure_id": "M12"},
        ])
        with patch("engine.advisor.OpenAI") as client_class:
            client = client_class.return_value
            client.responses.parse.side_effect = lambda **kwargs: self.openai_response(kwargs)
            client.chat.completions.create.return_value = self.nvidia_response()

            first = generate_debrief(self.benchmark, cache, settings=settings)
            repeated = generate_debrief(self.benchmark, cache, settings=settings)
            self.assertEqual(first, repeated)
            self.assertEqual(client.responses.parse.call_count, 1)
            changed_model = generate_debrief(
                self.benchmark, cache,
                settings=AdvisorSettings(openai_api_key="test-openai-key", openai_model="other-model"),
            )
            client.responses.parse.side_effect = lambda **kwargs: self.openai_response(
                kwargs, text=self.model_text(alternative)
            )
            changed_scenario = generate_debrief(alternative, cache, settings=settings)
            changed_provider = generate_debrief(self.benchmark, cache, provider="nvidia", settings=settings)

            self.assertEqual(changed_model.source, "openai")
            self.assertEqual(changed_scenario.source, "openai")
            self.assertEqual(changed_provider.source, "nvidia")
            self.assertEqual(client.responses.parse.call_count, 3)
            self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_missing_key_cache_does_not_poison_online_request(self) -> None:
        cache: dict[str, Debrief] = {}
        missing = generate_debrief(self.benchmark, cache, settings=AdvisorSettings())
        self.assert_mock(missing)
        with patch("engine.advisor.OpenAI") as client_class:
            client_class.return_value.responses.parse.side_effect = lambda **kwargs: self.openai_response(kwargs)
            online = generate_debrief(self.benchmark, cache, settings=AdvisorSettings(openai_api_key="test-key"))
            client_class.return_value.responses.parse.assert_called_once()
        self.assertEqual(online.source, "openai")

    def test_failed_provider_fallback_is_cached(self) -> None:
        cache: dict[str, Debrief] = {}
        with patch("engine.advisor.OpenAI") as client_class:
            client_class.return_value.responses.parse.side_effect = TimeoutError("timed out")
            settings = AdvisorSettings(openai_api_key="test-key")
            first = generate_debrief(self.benchmark, cache, settings=settings)
            second = generate_debrief(self.benchmark, cache, settings=settings)
            self.assertEqual(first, second)
            self.assert_mock(first)
            client_class.return_value.responses.parse.assert_called_once()

    def test_decision_order_is_canonical_for_cache(self) -> None:
        reversed_result = result_for(self.dataset, list(reversed(BENCHMARK)))
        self.assertEqual(self.benchmark.model_dump(), reversed_result.model_dump())
        cache: dict[str, Debrief] = {}
        with patch("engine.advisor.OpenAI") as client_class:
            client_class.return_value.responses.parse.side_effect = lambda **kwargs: self.openai_response(kwargs)
            settings = AdvisorSettings(openai_api_key="test-key")
            generate_debrief(self.benchmark, cache, settings=settings)
            generate_debrief(reversed_result, cache, settings=settings)
            client_class.return_value.responses.parse.assert_called_once()

    def test_offline_briefing_is_deterministic_and_scenario_grounded(self) -> None:
        synthetic = all_100_dataset(self.dataset)
        zero = result_for(synthetic, BENCHMARK)
        negative = result_for(synthetic, [
            {"measure_id": "M11", "district": "Нура"},
            {"measure_id": "M12"},
            {"measure_id": "M14"},
            {"measure_id": "M4", "district": "Нура"},
            {"measure_id": "M8", "district": "Нура"},
        ])
        self.assertGreater(self.benchmark.city_score_delta, 0)
        self.assertEqual(zero.city_score_delta, 0)
        self.assertLess(negative.city_score_delta, 0)

        with patch("engine.advisor.OpenAI") as client_class:
            outputs = [generate_debrief(result, {}, provider="offline") for result in (self.benchmark, zero, negative)]
            client_class.assert_not_called()
        for briefing in outputs:
            self.assert_mock(briefing)
        self.assertEqual(outputs[0], generate_debrief(self.benchmark, {}, provider="offline"))
        self.assertEqual(len({briefing.why_score_changed for briefing in outputs}), 3)
        self.assertNotIn("улучш", outputs[1].why_score_changed.lower())
        self.assertNotIn("улучш", outputs[2].why_score_changed.lower())

    def test_malformed_offline_template_uses_safe_built_in_text(self) -> None:
        for replacement in ("{invented_fact}", "{before:.2000f}"):
            with self.subTest(replacement=replacement):
                templates = json.loads((ROOT / "data" / "mock_debrief.json").read_text(encoding="utf-8"))
                templates["score_up"] += " " + replacement
                try:
                    advisor._templates.cache_clear()
                    with patch("engine.advisor.Path.read_text", return_value=json.dumps(templates, ensure_ascii=False)):
                        actual = generate_debrief(self.benchmark, {}, provider="offline")
                finally:
                    advisor._templates.cache_clear()
                self.assert_mock(actual)
                self.assertEqual(
                    actual.why_score_changed,
                    advisor._DEFAULT_TEMPLATES["score_up"].format(
                        before=f"{self.benchmark.city_score_before:.2f}",
                        after=f"{self.benchmark.city_score_after:.2f}",
                        critical_before=self.benchmark.critical_metrics_before,
                        critical_after=self.benchmark.critical_metrics,
                    ),
                )

    def test_advisor_does_not_mutate_or_recalculate_simulator_result(self) -> None:
        before = deepcopy(self.benchmark.model_dump())
        with patch("engine.advisor.OpenAI") as client_class:
            client_class.return_value.responses.parse.side_effect = lambda **kwargs: self.openai_response(kwargs)
            briefing = generate_debrief(self.benchmark, {}, settings=AdvisorSettings(openai_api_key="test-key"))
        self.assertEqual(self.benchmark.model_dump(), before)
        self.assertEqual(briefing.source, "openai")
        self.assertEqual(self.benchmark.city_score_after, 56.54307)


if __name__ == "__main__":
    unittest.main()
