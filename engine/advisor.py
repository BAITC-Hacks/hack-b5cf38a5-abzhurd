"""Explicit, cached explanations of Python-computed simulation facts.

This module never calculates a Score. Calling generate_debrief is the only path
that may issue an API request; importing it or changing form state cannot.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from string import Formatter
from typing import Literal, MutableMapping

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, field_validator

from engine.models import Debrief, SimulationResult


Provider = Literal["openai", "nvidia", "offline"]
PROMPT_VERSION = "urban-advisor-v2"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class AdvisorSettings:
    """One briefing request's configuration; no credentials enter cache keys/logs."""

    provider: str = "openai"
    mock_mode: bool = False
    openai_api_key: str = ""
    nvidia_api_key: str = ""
    openai_model: str = "gpt-6-sol"
    nvidia_model: str = "mistralai/mistral-nemotron"
    openai_reasoning_effort: str = "low"
    max_output_tokens: int = 700
    timeout_seconds: int = 20

    @classmethod
    def from_environment(cls) -> AdvisorSettings:
        """Read .env only on an explicit briefing call; process environment wins."""
        load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
        mode = os.getenv("MOCK_MODE", "false").strip().lower()
        # An invalid mode disables paid requests until the configuration is fixed.
        offline = mode not in {"false", "0", "no", "off", ""}
        token_limit = os.getenv(
            "ADVISOR_MAX_OUTPUT_TOKENS", os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "700")
        )
        try:
            bounded_limit = max(1, min(700, int(token_limit)))
        except ValueError:
            bounded_limit = 700
        return cls(
            provider=os.getenv("ADVISOR_PROVIDER", "openai").strip().lower(),
            mock_mode=offline,
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            nvidia_api_key=os.getenv("NVIDIA_API_KEY", "").strip(),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-6-sol").strip(),
            nvidia_model=os.getenv("NVIDIA_MODEL", "mistralai/mistral-nemotron").strip(),
            openai_reasoning_effort=os.getenv("OPENAI_REASONING_EFFORT", "low").strip(),
            max_output_tokens=bounded_limit,
        )


class _DebriefText(BaseModel):
    """Only the three text fields are generated; Python assigns source."""

    model_config = ConfigDict(extra="forbid")

    why_score_changed: str
    main_risk: str
    next_quarter_recommendation: str

    @field_validator("why_score_changed", "main_risk", "next_quarter_recommendation")
    @classmethod
    def nonempty_text(cls, value: str) -> str:
        if not value.strip() or len(value) > 1500:
            raise ValueError("Briefing sections must contain 1–1500 nonblank characters.")
        return value.strip()


SYSTEM_PROMPT = (
    "Выбери краткое объяснение результата симулятора Астаны на русском языке. "
    "Python уже вычислил все числа и подготовил только подтверждённые варианты фраз. "
    "Для каждого из трёх ключей выбери ровно одну строку из соответствующего списка "
    "candidates и скопируй её дословно. Не дописывай текст, числа, события, меры, "
    "причины или эффекты. Верни только JSON с ключами why_score_changed, "
    "main_risk, next_quarter_recommendation; без Markdown и дополнительных полей."
)


def _facts_json(result: SimulationResult) -> str:
    """A canonical snapshot, including every district/indicator and audit contribution."""
    return json.dumps(
        result.model_dump(mode="json"), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )


def _cache_key(facts: str, provider: str, model: str, has_key: bool) -> str:
    encoded = json.dumps(
        [PROMPT_VERSION, provider, model, has_key, facts],
        ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _log_usage(provider: str, model: str, response: object) -> None:
    """Record only provider metadata and optional token counts, never prompts/keys."""
    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    if provider == "nvidia":
        input_tokens = getattr(usage, "prompt_tokens", input_tokens)
        output_tokens = getattr(usage, "completion_tokens", output_tokens)
    LOGGER.info(
        "advisor_usage provider=%s model=%s request_id=%s input_tokens=%s output_tokens=%s",
        provider, model, getattr(response, "id", None), input_tokens, output_tokens,
    )


def _advisor_input(facts: str, candidates: dict[str, tuple[str, ...]]) -> str:
    return "Факты симуляции (JSON):\n" + facts + "\nВарианты объяснения (JSON):\n" + json.dumps(
        candidates, ensure_ascii=False, separators=(",", ":"),
    )


def _openai_debrief(
    facts: str, candidates: dict[str, tuple[str, ...]], settings: AdvisorSettings,
) -> _DebriefText:
    client = OpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.timeout_seconds,
        max_retries=0,
    )
    response = client.responses.parse(
        model=settings.openai_model,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _advisor_input(facts, candidates)},
        ],
        text_format=_DebriefText,
        reasoning={"effort": settings.openai_reasoning_effort},
        max_output_tokens=settings.max_output_tokens,
        store=False,
    )
    _log_usage("openai", settings.openai_model, response)
    if response.status != "completed" or response.output_parsed is None:
        raise ValueError("OpenAI response was incomplete or refused.")
    return _DebriefText.model_validate(response.output_parsed)


def _nvidia_debrief(
    facts: str, candidates: dict[str, tuple[str, ...]], settings: AdvisorSettings,
) -> _DebriefText:
    client = OpenAI(
        base_url=NVIDIA_BASE_URL,
        api_key=settings.nvidia_api_key,
        timeout=settings.timeout_seconds,
        max_retries=0,
    )
    response = client.chat.completions.create(
        model=settings.nvidia_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _advisor_input(facts, candidates)},
        ],
        max_tokens=settings.max_output_tokens,
        stream=False,
    )
    _log_usage("nvidia", settings.nvidia_model, response)
    if not response.choices or response.choices[0].finish_reason != "stop":
        raise ValueError("NVIDIA response was incomplete or refused.")
    content = response.choices[0].message.content
    if not isinstance(content, str):
        raise ValueError("NVIDIA response contains no JSON text.")
    return _DebriefText.model_validate_json(content)


_DEFAULT_TEMPLATES = {
    "score_up": "Итоговая оценка выросла с {before} до {after}. Критических показателей: {critical_before} → {critical_after}.",
    "score_down": "Итоговая оценка снизилась с {before} до {after}. Критических показателей: {critical_before} → {critical_after}.",
    "score_same": "Итоговая оценка осталась на уровне {after}. Критических показателей: {critical_before} → {critical_after}.",
    "critical_risk": "Остаётся критический показатель {indicator} в районе {district}: {value} (порог строго ниже 40).",
    "weakest_risk": "Самый слабый район по итоговой оценке — {district}: {score}.",
    "recommendation": "В следующем квартале проверьте показатель {indicator} в районе {district} ({value}) и оцените фактический результат выбранных мер.",
}
_TEMPLATE_FIELDS = {
    "score_up": {"before", "after", "critical_before", "critical_after"},
    "score_down": {"before", "after", "critical_before", "critical_after"},
    "score_same": {"before", "after", "critical_before", "critical_after"},
    "critical_risk": {"indicator", "district", "value"},
    "weakest_risk": {"district", "score"},
    "recommendation": {"indicator", "district", "value"},
}


@lru_cache(maxsize=1)
def _templates() -> dict[str, str]:
    """Load editable fallback wording once; built-in safe text survives bad files."""
    try:
        path = Path(__file__).resolve().parent.parent / "data" / "mock_debrief.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) != set(_DEFAULT_TEMPLATES):
            raise ValueError("Invalid offline briefing template keys.")
        if any(not isinstance(text, str) or not text.strip() for text in data.values()):
            raise ValueError("Invalid offline briefing template text.")
        for name, template in data.items():
            parsed = tuple(Formatter().parse(template))
            fields = {field for _, field, _, _ in parsed if field is not None}
            if fields != _TEMPLATE_FIELDS[name]:
                raise ValueError("Offline briefing placeholders do not match calculated facts.")
            if any(spec or conversion for _, field, spec, conversion in parsed if field is not None):
                raise ValueError("Offline briefing formatting is limited to plain placeholders.")
            rendered = template.format(**{field: "1234567890" for field in fields})
            if not rendered.strip() or len(rendered) > 1400:
                raise ValueError("Offline briefing text is too long.")
        return data
    except (OSError, UnicodeError, ValueError):
        return _DEFAULT_TEMPLATES


def _offline_debrief(result: SimulationResult) -> Debrief:
    """Use calculated facts only; no LLM, arithmetic, or invented measures."""
    templates = _templates()
    direction = (
        "score_up" if result.city_score_delta > 0
        else "score_down" if result.city_score_delta < 0 else "score_same"
    )
    format_facts = {
        "before": f"{result.city_score_before:.2f}",
        "after": f"{result.city_score_after:.2f}",
        "critical_before": result.critical_metrics_before,
        "critical_after": result.critical_metrics,
    }
    weakest = next(d for d in result.districts if d.name == result.weakest_district)
    indicator = min(weakest.indicators_after, key=weakest.indicators_after.__getitem__)
    recommendation = templates["recommendation"].format(
        indicator=indicator, district=weakest.name,
        value=f"{weakest.indicators_after[indicator]:.2f}",
    )
    if result.critical_locations_after:
        metric = result.critical_locations_after[0]
        risk = templates["critical_risk"].format(
            indicator=metric.indicator, district=metric.district,
            value=f"{metric.value:.2f}",
        )
    else:
        risk = templates["weakest_risk"].format(
            district=weakest.name, score=f"{weakest.score_after:.2f}",
        )
    return Debrief(
        why_score_changed=templates[direction].format(**format_facts),
        main_risk=risk,
        next_quarter_recommendation=recommendation,
        source="mock",
    )


def _candidate_briefings(result: SimulationResult) -> dict[str, tuple[str, ...]]:
    """Offer only sentences whose factual claims Python can verify directly."""
    base = _offline_debrief(result)
    largest_district_change = max(result.districts, key=lambda district: abs(district.delta))
    contributions = (
        (abs(value), measure, district, indicator, value)
        for measure, districts in result.measure_contributions.items()
        for district, indicators in districts.items()
        for indicator, value in indicators.items()
    )
    _, measure, district, indicator, effect = max(contributions)
    lowest_district, lowest_indicator, lowest_value = min(
        (
            (district.name, indicator, value)
            for district in result.districts
            for indicator, value in district.indicators_after.items()
        ),
        key=lambda item: item[2],
    )
    synergy_options = tuple(
        f"Синергия {item.measures[0]} и {item.measures[1]} добавила "
        f"{item.bonus:+.2f} к {item.indicator} в районе {item.district}. "
        f"Итоговая оценка: {result.city_score_after:.2f}."
        for item in result.synergy_contributions
    )
    clipping_options = tuple(
        f"Ограничение шкалы скорректировало {indicator} в районе {district} "
        f"на {adjustment:+.2f}. Итоговая оценка: {result.city_score_after:.2f}."
        for district, indicators in result.clipping_adjustments.items()
        for indicator, adjustment in indicators.items() if adjustment != 0
    )
    return {
        "why_score_changed": (
            base.why_score_changed,
            f"Наибольшее изменение районного балла: {largest_district_change.name} "
            f"({largest_district_change.delta:+.2f}). Итоговая оценка: {result.city_score_after:.2f}.",
            f"Наибольший по модулю вклад отдельной меры в показатель: "
            f"{measure}, {district}, {indicator} ({effect:+.2f}). "
            f"Итоговая оценка: {result.city_score_after:.2f}.",
        ) + synergy_options + clipping_options,
        "main_risk": (
            base.main_risk,
            f"Минимальное значение показателя после решений: "
            f"{lowest_district}, {lowest_indicator} ({lowest_value:.2f}).",
            f"Самый слабый район по итоговой оценке: {result.weakest_district}.",
        ),
        "next_quarter_recommendation": (
            base.next_quarter_recommendation,
            f"Проверьте фактический результат меры {measure} для показателя "
            f"{indicator} в районе {district}; расчётный вклад: {effect:+.2f}.",
            f"Сопоставьте показатели района {lowest_district} до и после решений, "
            f"особенно {lowest_indicator} ({lowest_value:.2f} после решений).",
        ),
    }


def _validate_grounding(
    briefing: _DebriefText, candidates: dict[str, tuple[str, ...]],
) -> None:
    for field, value in briefing.model_dump().items():
        if value not in candidates[field]:
            raise ValueError(f"Advisor text for {field} is not a verified candidate.")


def generate_debrief(
    result: SimulationResult,
    cache: MutableMapping[str, Debrief],
    provider: str | None = None,
    settings: AdvisorSettings | None = None,
) -> Debrief:
    """Explain a fresh valid result after an explicit action; cache per scenario/provider."""
    config = settings if settings is not None else AdvisorSettings.from_environment()
    config = replace(
        config,
        max_output_tokens=max(1, min(700, config.max_output_tokens)),
        timeout_seconds=max(1, min(20, config.timeout_seconds)),
    )
    requested = "offline" if config.mock_mode else (provider if provider is not None else config.provider)
    selected = requested.lower() if isinstance(requested, str) else "offline"
    model = config.openai_model if selected == "openai" else config.nvidia_model if selected == "nvidia" else "offline"
    key_present = bool(config.openai_api_key) if selected == "openai" else bool(config.nvidia_api_key) if selected == "nvidia" else False
    facts = _facts_json(result)
    key = _cache_key(facts, selected, model, key_present)
    if key in cache:
        return cache[key]
    if selected == "offline" or selected not in {"openai", "nvidia"} or not key_present:
        debrief = _offline_debrief(result)
    else:
        try:
            candidates = _candidate_briefings(result)
            text = (
                _openai_debrief(facts, candidates, config) if selected == "openai"
                else _nvidia_debrief(facts, candidates, config)
            )
            _validate_grounding(text, candidates)
            debrief = Debrief(**text.model_dump(), source=selected)
        except Exception as exc:  # External APIs and model output must never break the app.
            LOGGER.warning("advisor_fallback provider=%s reason=%s", selected, type(exc).__name__)
            debrief = _offline_debrief(result)
    cache[key] = debrief
    return debrief
