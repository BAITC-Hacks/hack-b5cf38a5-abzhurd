"""Russian-language scenario editor; all simulation values come from the engine."""

from __future__ import annotations

import logging

import streamlit as st

from engine import advisor, simulator
from engine.models import (
    DECISION_COUNT, MAX_PER_DIRECTION, Dataset, Debrief, SimulationResult,
    ValidationIssue, ValidationReport,
)


LOGGER = logging.getLogger(__name__)
REFERENCE = (
    ("M7", "Нура"), ("M8", "Нура"), ("M10", "Нура"),
    ("M12", None), ("M5", "Сарыарка"),
)
PROVIDERS = {"openai": "OpenAI", "nvidia": "NVIDIA", "offline": "Автономно"}
INDICATOR_LABELS = {
    "T1": "Свобода движения", "T2": "Доступность общественного транспорта",
    "E1": "Озеленение", "E2": "Качество зимнего воздуха",
    "S1": "Школы и детсады", "S2": "Поликлиники и первичная помощь",
    "B1": "Безопасность улиц", "B2": "Безопасность дорог",
    "C1": "Надёжность коммунальных сетей", "C2": "Скорость обработки обращений",
}


def _clear_result() -> None:
    st.session_state.result = None
    st.session_state.briefing = None


def _clear_briefing() -> None:
    st.session_state.briefing = None


def _set_rows(reference: bool) -> None:
    for index in range(DECISION_COUNT):
        measure, district = REFERENCE[index] if reference else (None, None)
        st.session_state[f"measure_{index}"] = measure
        st.session_state[f"district_{index}"] = district
    _clear_result()


def _measure_changed(index: int, district_measures: frozenset[str]) -> None:
    if st.session_state[f"measure_{index}"] not in district_measures:
        st.session_state[f"district_{index}"] = None
    _clear_result()


def _initialize(settings: advisor.AdvisorSettings) -> None:
    if "advisor_cache" not in st.session_state:
        st.session_state.advisor_cache = {}
        _set_rows(reference=True)
    if "provider" not in st.session_state:
        st.session_state.provider = (
            settings.provider if settings.provider in PROVIDERS else "offline"
        )
    if settings.mock_mode:
        if st.session_state.provider != "offline":
            _clear_briefing()
        st.session_state.provider = "offline"


def _draft(dataset: Dataset) -> tuple[list[dict[str, str | None]], list[int]]:
    """Keep engine positions separate from the five visible row positions."""
    measures = {measure.id: measure for measure in dataset.measures}
    decisions: list[dict[str, str | None]] = []
    rows: list[int] = []
    for index in range(DECISION_COUNT):
        measure_id = st.session_state.get(f"measure_{index}")
        if measure_id is None:
            continue
        decision: dict[str, str | None] = {"measure_id": measure_id}
        if measures[measure_id].scope == "Район":
            decision["district"] = st.session_state.get(f"district_{index}")
        decisions.append(decision)
        rows.append(index)
    return decisions, rows


def _issue_text(
    issue: ValidationIssue, report: ValidationReport,
    decisions: list[dict[str, str | None]], dataset: Dataset,
) -> str:
    """Translate stable error codes without interpreting the engine's prose."""
    affected = [decisions[index] for index in issue.decision_indices]
    ids = list(dict.fromkeys(str(item["measure_id"]) for item in affected))
    measures = {measure.id: measure for measure in dataset.measures}
    if issue.code == "decision_count":
        return f"Выберите ровно {DECISION_COUNT} мер. Сейчас выбрано: {len(decisions)}."
    if issue.code == "budget_exceeded":
        return (
            f"Стоимость {report.budget_used} превышает бюджет {report.budget_limit}. "
            "Замените одну или несколько мер на менее дорогие."
        )
    if issue.code == "duplicate_measure":
        return f"Мера {', '.join(ids)} выбрана несколько раз. Оставьте её только в одном решении."
    if issue.code == "direction_limit":
        direction = measures[ids[0]].direction
        return f"В направлении «{direction}» можно выбрать не более {MAX_PER_DIRECTION} мер."
    if issue.code in {"missing_district", "unknown_district"}:
        return f"Выберите район для меры {', '.join(ids)}."
    if issue.code == "forbidden_district":
        return f"Мера {', '.join(ids)} действует на весь город; район не нужен."
    if issue.code == "incompatible_measures":
        return f"Меры {' и '.join(ids)} несовместимы в одном сценарии. Замените одну из них."
    if issue.code == "district_conflict":
        return f"Меры {' и '.join(ids)} нельзя применять в одном районе. Измените район или меру."
    return "Проверьте меру и район: используйте только варианты из списка."


def _validation_messages(
    report: ValidationReport, decisions: list[dict[str, str | None]],
    rows: list[int], dataset: Dataset,
) -> tuple[dict[int, list[str]], list[str]]:
    per_row: dict[int, list[str]] = {}
    general: list[str] = []
    for issue in report.errors:
        message = _issue_text(issue, report, decisions, dataset)
        if issue.decision_indices:
            for position in issue.decision_indices:
                row = rows[position]
                per_row.setdefault(row, []).append(f"Решение {row + 1}: {message}")
        else:
            general.append(message)
    return per_row, general


def _render_direction_overview(dataset: Dataset, decisions: list[dict[str, str | None]]) -> None:
    """Show the selected measures grouped under their catalog directions."""
    measures = {measure.id: measure for measure in dataset.measures}
    selected_by_direction: dict[str, list[str]] = {
        direction: [] for direction in dict.fromkeys(m.direction for m in dataset.measures)
    }
    for decision in decisions:
        measure = measures[str(decision["measure_id"])]
        selected_by_direction[measure.direction].append(measure.id)

    st.subheader("Меры по направлениям")
    directions = list(selected_by_direction.items())
    for start in range(0, len(directions), 2):
        columns = st.columns(2)
        for column, (direction, measure_ids) in zip(columns, directions[start:start + 2]):
            with column:
                with st.container(border=True):
                    st.markdown(f"**{direction}**")
                    st.caption(f"Выбрано мер: {len(measure_ids)} / {MAX_PER_DIRECTION}")
                    if measure_ids:
                        st.write(" · ".join(measure_ids))
                    else:
                        st.caption("Пока нет выбранных мер")


def _render_editor(dataset: Dataset, errors: dict[int, list[str]]) -> None:
    measures = {measure.id: measure for measure in dataset.measures}
    district_measures = frozenset(m.id for m in dataset.measures if m.scope == "Район")

    def measure_label(measure_id: str | None) -> str:
        if measure_id is None:
            return "Выберите меру"
        measure = measures[measure_id]
        return f"{measure.id} · {measure.name} · {measure.cost} ед."

    def district_label(district: str | None) -> str:
        return district if district is not None else "Выберите район"

    for index in range(DECISION_COUNT):
        with st.container(border=True):
            st.markdown(f"**Решение {index + 1}**")
            measure_column, district_column = st.columns([3, 2])
            with measure_column:
                measure_id = st.selectbox(
                    f"Мера {index + 1}", [None, *measures],
                    key=f"measure_{index}", format_func=measure_label,
                    on_change=_measure_changed, args=(index, district_measures),
                )
            with district_column:
                if measure_id and measures[measure_id].scope == "Город":
                    st.caption("Территория действия")
                    st.write("Весь город")
                else:
                    st.selectbox(
                        f"Район {index + 1}", [None, *(d.name for d in dataset.districts)],
                        key=f"district_{index}", format_func=district_label,
                        disabled=measure_id is None, on_change=_clear_result,
                    )
            if measure_id:
                measure = measures[measure_id]
                st.markdown(f"**Направление: {measure.direction}** · Лаг: {measure.lag} кв.")
            for message in errors.get(index, []):
                st.error(message)


def _render_result(result: SimulationResult) -> None:
    st.header("Результат сценария")
    score, budget, weakest, critical = st.columns(4)
    with score:
        st.metric("Итоговый Score", f"{result.city_score_after:.2f}", f"{result.city_score_delta:+.2f}")
        st.caption(f"До решений: {result.city_score_before:.2f}")
    with budget:
        st.metric("Использовано бюджета", f"{result.budget_used} / {result.budget_limit}")
        st.caption(f"Осталось: {result.budget_remaining}")
    with weakest:
        st.metric("Самый слабый район", result.weakest_district)
        district = next(d for d in result.districts if d.name == result.weakest_district)
        st.caption(f"Районный балл: {district.score_after:.2f}")
    with critical:
        st.metric("Критические показатели", result.critical_metrics)
        st.caption(f"До решений: {result.critical_metrics_before}")
    for metric in result.critical_locations_after:
        st.warning(
            f"{metric.district} · {metric.indicator} — {INDICATOR_LABELS[metric.indicator]}: "
            f"{metric.value:.2f} (ниже критического порога)."
        )
    st.subheader("Изменения по районам")
    st.dataframe(
        [{"Район": d.name, "До": d.score_before, "После": d.score_after, "Изменение": d.delta}
         for d in result.districts],
        hide_index=True, use_container_width=True,
        column_config={
            "До": st.column_config.NumberColumn(format="%.2f"),
            "После": st.column_config.NumberColumn(format="%.2f"),
            "Изменение": st.column_config.NumberColumn(format="%+.2f"),
        },
    )
    st.caption("Расчёт учитывает лаги мер, синергии и ограничения шкалы показателей.")


def _render_briefing(settings: advisor.AdvisorSettings) -> None:
    st.header("Объяснение результата")
    st.selectbox(
        "Источник объяснения", list(PROVIDERS), key="provider",
        format_func=PROVIDERS.__getitem__, disabled=settings.mock_mode,
        on_change=_clear_briefing,
    )
    if settings.mock_mode:
        st.caption("В конфигурации включён автономный режим.")
    result: SimulationResult | None = st.session_state.result
    if result is None:
        st.caption("Сначала рассчитайте действующий сценарий, затем запросите объяснение.")
        return
    if st.button("Получить объяснение", key="generate_briefing"):
        _clear_briefing()
        try:
            with st.spinner("Готовим объяснение…"):
                st.session_state.briefing = advisor.generate_debrief(
                    result, st.session_state.advisor_cache,
                    provider=st.session_state.provider, settings=settings,
                )
        except Exception as exc:
            LOGGER.warning("ui_briefing_failed reason=%s", type(exc).__name__)
            st.error("Не удалось подготовить объяснение. Повторите запрос или выберите автономный режим.")
    briefing: Debrief | None = st.session_state.briefing
    if briefing is not None:
        if briefing.source == "mock":
            st.info("Автономная сводка · объяснение по рассчитанным результатам.")
        else:
            st.caption(f"Источник: {PROVIDERS[briefing.source]}")
        for title, text in (
            ("Почему изменился балл", briefing.why_score_changed),
            ("Главный риск", briefing.main_risk),
            ("Рекомендация", briefing.next_quarter_recommendation),
        ):
            st.subheader(title)
            st.write(text)


def _render_app() -> None:
    try:
        dataset = simulator.load_dataset()
    except simulator.DatasetError:
        _clear_result()
        st.error("Не удалось загрузить данные города. Проверьте файлы данных и перезапустите приложение.")
        return
    try:
        settings = advisor.AdvisorSettings.from_environment()
    except Exception as exc:
        LOGGER.warning("ui_configuration_failed reason=%s", type(exc).__name__)
        settings = advisor.AdvisorSettings(provider="offline", mock_mode=True)
        st.warning("Не удалось прочитать настройки объяснения. Включён автономный режим.")
    _initialize(settings)
    decisions, rows = _draft(dataset)
    report = simulator.validate_scenario(decisions, dataset)
    errors, general = _validation_messages(report, decisions, rows, dataset)

    st.caption(f"АСТАНА · БЮДЖЕТ {report.budget_limit} · ГОРИЗОНТ {dataset.horizon_quarters} КВАРТАЛОВ")
    st.title("Аким на 5 часов")
    st.markdown('<div style="height:4px;width:80px;background:#C69B39;margin-bottom:20px"></div>', unsafe_allow_html=True)
    st.write("Выберите пять решений для города и оцените, как изменится качество жизни в районах.")
    selected, spent, remaining = st.columns(3)
    selected.metric("Выбрано решений", f"{len(decisions)} / {DECISION_COUNT}")
    spent.metric("Стоимость выбора", report.budget_used if report.budget_used is not None else "—")
    remaining.metric(
        "Остаток бюджета",
        report.budget_limit - report.budget_used if report.budget_used is not None else "—",
    )
    load, clear = st.columns(2)
    load.button("Загрузить пример", key="load_reference", on_click=_set_rows, args=(True,))
    clear.button("Очистить выбор", key="clear_selection", on_click=_set_rows, args=(False,))
    _render_direction_overview(dataset, decisions)
    st.header("Ваши решения")
    _render_editor(dataset, errors)
    for message in general:
        st.error(message)
    if report.valid:
        st.success("Сценарий готов: бюджет и все ограничения соблюдены.")
    elif errors:
        st.info("Исправьте отмеченные решения, чтобы рассчитать сценарий.")
    if st.button("Рассчитать сценарий", key="simulate", type="primary", disabled=not report.valid):
        _clear_result()
        try:
            outcome = simulator.simulate(decisions, dataset)
            if isinstance(outcome, SimulationResult):
                st.session_state.result = outcome
            else:
                for issue in outcome.errors:
                    st.error(_issue_text(issue, outcome, decisions, dataset))
        except Exception as exc:
            LOGGER.warning("ui_simulation_failed reason=%s", type(exc).__name__)
            st.error("Не удалось рассчитать сценарий. Повторите расчёт или загрузите пример.")
    if st.session_state.result is not None:
        _render_result(st.session_state.result)
    else:
        st.info("Результат появится после расчёта текущего выбора.")
    st.divider()
    _render_briefing(settings)


def main() -> None:
    st.set_page_config(page_title="Аким на 5 часов · Астана", page_icon="🏙️", layout="wide")
    try:
        _render_app()
    except Exception as exc:
        _clear_result()
        LOGGER.warning("ui_failed reason=%s", type(exc).__name__)
        st.error("Не удалось открыть сценарий. Обновите страницу и попробуйте снова.")


if __name__ == "__main__":
    main()
