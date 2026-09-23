# AGENTS.md - AI Urban Simulator ("Аким на 5 часов")

> **HackAlem AI 2026** | Track: «Аким на 5 часов» - AI-симулятор управления городом
>
> **Team:** Solo Vibecoder assisted by OpenAI Codex
>
> **Planned stack:** Python 3.10+, Streamlit, Pydantic v2, OpenAI Responses API, NVIDIA Chat Completions API, python-dotenv
>
> **Default advisor model:** `gpt-6-sol` (configurable, with offline fallback)
>
> **Goal:** a launchable, reproducible, and specification-compliant MVP built in small verified iterations

---

## 1. Authority, Role, and Source of Truth

Codex acts as the **Principal Python Engineer and Lead Agentic Architect** for this project.

For project implementation, testing, reproduction, and judge setup, use this authority order:

1. The user's latest explicit request.
2. This `AGENTS.md`.
3. `README.md`.
4. Deterministic JSON data in `data/`.
5. Tests and validated simulator outputs.
6. Team implementation decisions documented in this `AGENTS.md`.

The original HackAlem PDFs are archival background only. They must not be required for implementation, testing, reproduction, or judge setup. The official requirements, district values, measures, formulas, constraints, and rubric needed by the project are already copied into this repository. Never invent missing values. If the repository sources are ambiguous or contradictory, report the ambiguity and ask the user before making a consequential assumption.

### Mathematical division of labor

The official dataset states:

> «Роль ИИ: LLM получает результат расчёта (дельты по районам и показателям, вклад каждой меры) и объясняет его, сравнивает наборы, советует. Числа он не считает и не придумывает.»

- **Python calculates:** budget, lags, realized effects, synergies, conflicts, district deltas, measure contributions, $N_{crit}$, $D_{avg}$, and final Score.
- **The LLM explains:** trade-offs, district impacts, strengths, risks, consequences, and recommendations using only facts supplied by Python.
- **The LLM must not:** calculate authoritative values, invent measures or effects, silently repair invalid scenarios, or contradict simulator output.

### Reliability and code quality

- Every external API call must have a deterministic cached fallback for a missing key, disabled API mode, timeout, rate limit, malformed response, or network failure.
- The app must not expose an unhandled exception or traceback to the user.
- All functions and Pydantic models must have type hints.
- The deterministic engine must remain independent from Streamlit and the OpenAI client.
- Commits and pushes happen only when the user explicitly requests them.

---

## 2. Official HackAlem Requirements

### 2.1 Must-have product behavior

- Every participant starts from the same fixed virtual budget and district baseline.
- The user makes exactly 5 management decisions drawn from a catalog covering 5 city-development directions.
- The system prevents or clearly rejects budget overflow and every other invalid decision set.
- Valid decisions change the modeled district indicators and Astana Quality of Life Score.
- AI explains the final result, main trade-offs, risks, and possible consequences.
- Changing the decision set changes the score when the deterministic effects differ.

### 2.2 Official optional enhancements

These features are valuable but are not official must-haves:

- comparing results from multiple teams or scenarios;
- visualizing district-indicator changes;
- AI recommendations for improving a scenario;
- modeling unexpected city events that require budget redistribution;
- automatically generating a short presentation of the team's decision.

### 2.3 Evaluation rubric

| Criterion | What judges assess | Points |
|---|---|---:|
| Task compliance and operability | The main scenario works and matches the problem statement | 25 |
| Technical implementation | Architecture, component interaction, AI/agentic use, and correspondence between claimed and actual logic | 25 |
| README and reproducibility | Clear structure, technologies, launch steps, scenario, and reproducibility from repository materials | 25 |
| Value and applicability | Practical usefulness for the stated urban-management problem | 15 |
| Development potential and originality | Scalability and justified original approaches | 10 |
| **Total** |  | **100** |

---

## 3. Official Domain Data and Mathematical Model

### 3.1 District baseline

All indicators use a 0-100 scale where higher is better.

| District | Pop Weight (`pop_d`) | T1 | T2 | E1 | E2 | S1 | S2 | B1 | B2 | C1 | C2 | Base Score $D_d$ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Есиль** | 0.27 | 45 | 62 | 68 | 72 | 48 | 55 | 78 | 60 | 75 | 70 | 62.99 |
| **Алматы** | 0.24 | 40 | 75 | 50 | 55 | 60 | 65 | 62 | 52 | 50 | 60 | 57.06 |
| **Сарыарка** | 0.20 | 50 | 70 | 42 | 40 | 62 | 68 | 58 | 55 | 45 | 55 | 54.65 |
| **Байконур** | 0.13 | 52 | 68 | 55 | 50 | 58 | 60 | 52 | 58 | 55 | 58 | 56.63 |
| **Нура** | 0.16 | 55 | 40 | 45 | 65 | 38 | 35 | 55 | 50 | 60 | 50 | 49.18 |

District profiles:

- **Есиль:** affluent, but congested bridges and overcrowded schools.
- **Алматы:** aging utilities and traffic congestion.
- **Сарыарка:** private-sector smog and weak greenery.
- **Байконур:** balanced middle performer without severe spikes.
- **Нура:** the main lagging district in social infrastructure and transit.

### 3.2 Indicator weights

- **Transport (0.20):** `T1` traffic relief ($w=0.10$), `T2` public-transit access ($w=0.10$).
- **Ecology (0.20):** `E1` greenery ($w=0.09$), `E2` winter air quality ($w=0.11$).
- **Social (0.22):** `S1` schools and kindergartens ($w=0.11$), `S2` polyclinics and primary care ($w=0.11$).
- **Safety (0.18):** `B1` street safety and cameras ($w=0.09$), `B2` road safety ($w=0.09$).
- **City services (0.20):** `C1` utility/heating reliability ($w=0.10$), `C2` complaint-resolution speed ($w=0.10$).

The weights sum to 1.0.

### 3.3 Catalog of measures

The simulation horizon is $H=8$ quarters. A measure with lag $L$ realizes $(8-L)/8$ of its raw effect.

| ID | Direction | Measure | Scope | Cost | Lag | Raw effects before lag |
|---|---|---|---|---:|---:|---|
| **M1** | Транспорт | Выделенные полосы для автобусов | Район | 18 | 2 | T1 +6, T2 +9 |
| **M2** | Транспорт | Умные светофоры (адаптивное управление) | Город | 22 | 2 | T1 +4, B2 +3 |
| **M3** | Транспорт | Линия ЛРТ / расширение | Район | 30 | 4 | T1 +16, T2 +20, E2 +4 |
| **M4** | Экология | Парк / сквер | Район | 15 | 2 | E1 +12, E2 +3, B1 +2 |
| **M5** | Экология | Перевод частного сектора на чистое топливо | Район | 25 | 3 | E2 +14, C1 +4 |
| **M6** | Экология | Городская программа озеленения и ветрозащитных полос | Город | 20 | 4 | E1 +5, E2 +3 |
| **M7** | Соцсфера | Школа + детсад (модульное строительство) | Район | 24 | 3 | S1 +16 |
| **M8** | Соцсфера | Центр семейного здоровья / поликлиника | Район | 20 | 3 | S2 +14 |
| **M9** | Соцсфера | Дворовые спорт-хабы | Район | 10 | 1 | S1 +3, S2 +3, B1 +3 |
| **M10** | Безопасность | Освещение и камеры (расширение Safe City) | Район | 12 | 1 | B1 +12, B2 +2 |
| **M11** | Безопасность | Безопасные переходы и школьные зоны | Район | 10 | 1 | B2 +12, T1 -2 |
| **M12** | Сервисы | Единая цифровая платформа обращений | Город | 14 | 1 | C2 +5 |
| **M13** | Сервисы | Модернизация тепло- и водосетей | Район | 28 | 4 | C1 +18, E2 +2 |
| **M14** | Сервисы | Аварийные бригады ЖКХ + раннее оповещение | Город | 16 | 1 | C1 +5, C2 +2 |

### 3.4 Synergies

Synergy bonuses are fixed and are not scaled by lag:

- **M1 + M2:** T1 +2 in the district assigned to M1.
- **M10 + M12:** B1 +2 in the district assigned to M10.
- **M5 + M6:** E2 +2 in the district assigned to M5.

### 3.5 Incompatibilities

- **M1 and M3:** cannot both be selected anywhere.
- **M4 and M7:** cannot be selected in the same district.
- **M5 and M13:** cannot be selected in the same district.

### 3.6 Scoring

1. New indicator value:

   $$I'_{dk}=\operatorname{clip}\left(I_{dk}+\sum_m \operatorname{effect}_{m,k}\frac{8-L_m}{8}+\operatorname{synergy},0,100\right)$$

2. District score:

   $$D_d=\sum_k w_k I'_{dk}$$

3. Population-weighted city score:

   $$D_{avg}=\sum_d pop_d D_d$$

4. Critical metric count:

   $$N_{crit}=\#\{(d,k):I'_{dk}<40\}$$

   The threshold is strictly less than 40.

5. Final score:

   $$Score=0.7D_{avg}+0.3\min(D_d)-N_{crit}$$

Verified fixtures:

- **Baseline:** $D_{avg}=56.86$, weakest district Нура at 49.18, $N_{crit}=2$, final Score $=52.56$.
- **Reference benchmark:** M7(Нура), M8(Нура), M10(Нура), M12(Город), M5(Сарыарка); cost 95; Score approximately 56.5; delta approximately +4.0. The M10 + M12 synergy applies.

### 3.7 Validation constraints

- Total cost must be at most 100; unused budget gives no bonus.
- A scenario contains exactly 5 decisions, not up to 5.
- Every measure may be selected at most once.
- At most 2 measures may come from one direction, so at least 3 directions are represented.
- A district is mandatory for `Район` measures and forbidden for `Город` measures.
- Every incompatibility must be enforced.
- Decision order has no effect.
- An invalid scenario has no Score; the validator returns an actionable reason for the failure.

---

## 4. Team Implementation Decisions

The choices in this section are team decisions, not claims about mandatory hackathon technology.

### 4.1 Current and target architecture

The deterministic data, simulator, advisor, Streamlit core flow, and their tests are implemented. Later components are explicitly marked below.

```text
├── AGENTS.md                 # Project rules and verified specification
├── README.md                 # Judge-facing status, setup, and architecture
├── requirements.txt          # Minimal stable dependencies
├── .env.example              # Non-secret environment template
├── .streamlit/config.toml    # Light Astana theme
├── run.sh                    # Planned one-command launch helper
├── data/                     # Verified deterministic source data
│   ├── districts.json
│   ├── measures.json
│   └── mock_debrief.json
├── engine/
│   ├── __init__.py
│   ├── models.py             # Validated data, scenario, and audit contracts
│   ├── simulator.py          # Deterministic validation, scoring, and JSON loader
│   └── advisor.py            # OpenAI/NVIDIA adapters + deterministic fallback
├── tests/
│   ├── test_simulator.py     # Independent arithmetic oracle and regressions
│   ├── test_advisor.py       # Mocked provider and fallback tests
│   └── test_app.py           # Offline Streamlit acceptance tests
└── app.py                    # Russian-language Streamlit core flow
```

The core UI uses `load_dataset`, `validate_scenario`, `simulate`, and `generate_debrief` without changing their contracts or official calculations. It groups currently selected measure IDs under the five catalog directions and labels each decision row with its measure's direction. Charts, heatmaps, additional presets, audit export, and `run.sh` remain work for subsequent iterations. Documentation must never describe a planned component as already operational.

Simulator contract decisions:

- Invalid inputs return a structured validation report with no Score. Dataset loading failures raise `DatasetError`; the UI displays a concise Russian error without a traceback.
- Weights and scalar constraints are transcribed from §3 into Python constants. JSON encodes explicit synergy targets and conflict scopes; no descriptive prose is parsed for behavior.
- Python calculates per-measure lag-adjusted district/indicator effects before clipping, separate synergy bonuses, separate clipping adjustments, and explicit indicator deltas. Per-measure attribution of final Score is not defined or required.
- Calculate without intermediate rounding, accumulate in canonical order, and round only for display. Weakest-district ties use the first district in the official order. Critical detection remains strictly `<40`.
- The unchanged scoring formula can map different indicator outcomes to the same scalar Score. Score-change acceptance uses scenarios whose calculated Scores differ; it does not impose universal uniqueness on the formula.
- Tests verify baseline Score `52.55768` (display `52.56`) and benchmark Score `56.54307`, using independent Python arithmetic. Synthetic fixtures exercise boundaries without replacing official data.
- The core accepts a validated `Dataset`; only freshly generated simulator results are authoritative. Structural validation of an imported audit is not proof that its numbers are correct; recalculate from decisions.

### 4.2 Implemented core experience and planned enhancements

Implemented core behavior:

- Astana-branded Streamlit dashboard.
- KPI cards for budget, final Score and delta, weakest district, and critical alerts.
- Five decision rows with measure and conditional district selection.
- Real-time local validation and budget feedback.
- A before/after district comparison table in official district order.
- A structured AI briefing with "Почему изменился балл", "Главный риск", and "Рекомендация".
- The verified reference scenario is prefilled, with clear and reload-example actions. Initial rendering does not simulate or request a briefing.
- Editing any decision clears the displayed result and briefing. Citywide measures submit no district; switching back to district scope requires a district selection.
- Only a valid explicit simulation produces results. A separate briefing button invokes the selected provider. Changing providers clears only the briefing; mock mode forces offline selection.
- The session cache survives decision edits and resets. Credentials remain in local configuration, outside UI session state.
- Dataset and operational failures display recoverable Russian messages without tracebacks.

Planned enhancements:

- Charts and indicator heat breakdown.
- JSON scenario-audit download.
- Ecology/service and transport/safety presets.

These choices implement or extend the official must-haves; charts, presets, comparisons, recommendations, and exports remain team-selected enhancements.

### 4.3 Implemented dual-provider advisor and API budget controls

- `ADVISOR_PROVIDER=openai` is the default. `nvidia` selects NVIDIA; `offline` or `MOCK_MODE=true` skips APIs. The provider is chosen explicitly for each briefing; failure never charges the other provider.
- OpenAI uses the Responses API structured-output helper with `OPENAI_MODEL=gpt-6-sol` and `OPENAI_REASONING_EFFORT=low`. NVIDIA uses its hosted Chat Completions endpoint with `NVIDIA_MODEL=mistralai/mistral-nemotron`. Both models are configurable.
- Credentials are independent: `OPENAI_API_KEY` and `NVIDIA_API_KEY`. Never commit, print, or log either key. The NVIDIA-hosted default is a Mistral AI model; NVIDIA's catalog publishes Russian-language evaluation for it.
- `ADVISOR_MAX_OUTPUT_TOKENS` defaults to 700 and cannot exceed 700. Each selected provider uses a 20-second maximum timeout, zero SDK retries, and one call per uncached explicit briefing request.
- The caller supplies a per-session cache; its key includes provider, model, prompt version, credential presence, and canonical Python-calculated facts. API responses and deterministic offline briefings are cached. There is no automatic API request on import, form edit, or simulation.
- A valid `SimulationResult` supplies the prompt facts and Python-generated Russian candidate sentences. The model selects one sentence per briefing field; Python rejects any text outside those candidates after Pydantic validation and assigns `Debrief.source`. This prevents invented facts from being displayed. Missing keys, mock mode, refusal, incomplete output, malformed JSON, unsupported model, timeout, rate limit, and network failure lead to a cached offline briefing.
- Offline wording comes from `mock_debrief.json` templates populated with the actual Python result. If templates are missing or malformed, built-in templates preserve the fallback. Request ID and token usage are logged when available, without prompts or secrets.
- Model access and NVIDIA billing depend on the user's account. No fixed NVIDIA price or credit consumption is assumed; check current provider billing before final submission.

Official references: [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [GPT-6 Sol](https://developers.openai.com/api/docs/models/gpt-6-sol), [NVIDIA endpoint](https://docs.api.nvidia.com/nim/reference/mistralai-mistral-nemotron-infer), [NVIDIA-hosted model](https://docs.api.nvidia.com/nim/reference/mistralai-mistral-nemotron).

---

## 5. Small-Iteration Delivery Contract

Every iteration must have one measurable outcome and the smallest coherent diff that achieves it.

1. Inspect the current repository documentation, deterministic data, and relevant tests before editing.
2. State the iteration outcome and acceptance checks.
3. Implement only the files needed for that outcome.
4. Run focused tests plus the baseline and benchmark regressions when simulator behavior is in scope.
5. Review the diff independently for scope drift, unsupported claims, and accidental changes.
6. Report changed files, verification evidence, remaining limitations, and stop before starting a new iteration.

Required end-of-iteration checks:

- `git diff --check`.
- Relevant automated tests or an explicit explanation if the iteration is documentation-only.
- `git status --short` to confirm no unrelated files changed.
- No commit or push unless the user asks.

### Subagent policy

Use subagents when a task splits into genuinely independent lanes, such as specification research, isolated implementation, deterministic test design, or independent review.

- Give each subagent exact files, authoritative sources, constraints, and acceptance criteria.
- Keep changes disjoint when multiple implementation subagents work in parallel.
- The lead agent owns integration, resolves conflicts, runs final tests, and reports the result.
- Treat every subagent conclusion as untrusted until checked against source files, deterministic output, or tests.
- Never delegate authoritative scoring to an LLM or accept invented official values.
- Use an independent review subagent for high-risk math, API-boundary, or cross-file changes when available.
- Do not create redundant subagents for trivial edits or use delegation as a substitute for reading the source.

---

## 6. Anti-Hallucination and Verification Gates

- Official district values, weights, measures, lags, effects, costs, synergies, conflicts, and formulas come only from the verified dataset.
- Python is the sole authority for numerical results.
- Advisor input must include the final validated facts, per-district/per-indicator deltas, and per-measure contributions needed for explanation.
- Advisor prompts explicitly forbid arithmetic, unsupported causal claims, invented events, and invented policy measures.
- Structured output must pass Pydantic validation and match Python-generated fact-grounded candidates before display; otherwise use the mock fallback. The model is never the source of authoritative numeric facts.
- Baseline Score 52.56 and the reference benchmark near 56.5 are mandatory regression fixtures.
- Tests must cover strict `<40` critical detection, clipping, lag scaling, citywide effects, synergies, conflicts, duplicate measures, district assignment, count, balance, and budget.
- When evidence is missing or contradictory, label the uncertainty and ask rather than guessing.
- A passing LLM response can never compensate for a failing deterministic test.

---

## 7. Iteration Roadmap

1. **Documentation governance:** align `AGENTS.md` and `README.md` with the repository authority order and current API guidance.
2. **Deterministic data and models:** add JSON data, Pydantic contracts, and validation fixtures.
3. **Simulator engine:** implement and exhaustively test official math and constraints.
4. **Advisor boundary:** add Responses API structured output, usage controls, and cached fallback.
5. **Streamlit MVP:** core selection, validation, KPIs, district table, and explicit briefing controls are implemented; charts, additional presets, and export remain.
6. **Reproducibility and polish:** add `run.sh`, complete README launch instructions, perform offline/API smoke tests, and verify the judge rubric.

Do not silently combine roadmap stages. Begin the next iteration only after the current outcome is verified and reported.
