# QalaMind

Симулятор городских решений для Астаны. Проект для кейса «Аким на 5 часов» на HackAlem AI 2026.

## Current status

The **deterministic simulator is implemented and tested**: official JSON data, Pydantic contracts, scenario validation, scoring, and a numeric audit of direct effects, synergies, and clipping. Python performs all calculations without network access or an API key.

The **Streamlit core flow is launchable**: five decision rows, live validation and budget feedback, a visual grouping of selected measures across the five directions, explicit simulation, result KPIs, a district comparison table, and a separate briefing button. Each decision row also labels its measure's direction. The reference scenario is prefilled. The advisor supports OpenAI, NVIDIA, and a deterministic offline briefing, with a provider selector and per-session cache. Automated provider tests use mocked responses; live calls require your own key and account access.

Charts, indicator heatmaps, additional presets, JSON audit export, and `run.sh` remain planned enhancements. The current interface is in Russian with a light Astana theme.

The decision count, current cost, and remaining budget stay visible in a pinned summary panel. It smoothly becomes compact while scrolling and expands again near the top. The panel supports narrow screens and respects reduced-motion preferences. Its local styling script only controls presentation; Python supplies all displayed values. This uses Streamlit 1.52 or later, as declared in `requirements.txt`.

## Repository authority

For implementation, testing, reproduction, and judge setup, use this order:

1. The latest user request.
2. [AGENTS.md](AGENTS.md).
3. This `README.md`.
4. Deterministic JSON data in `data/`.
5. Tests and validated simulator outputs.
6. Team implementation decisions documented in [AGENTS.md](AGENTS.md).

The original HackAlem PDF files are archival background only. They are not required for implementation, testing, reproduction, or judge setup. All official HackAlem requirements, dataset values, formulas, constraints, and the judging rubric needed by this project are already captured in the repository.

## The challenge

The user receives a fixed budget of 100 units and must make exactly 5 management decisions across transport, ecology, social infrastructure, safety, and city services. A deterministic simulator applies costs, lags, effects, synergies, incompatibilities, and validation rules to five Astana districts.

Python calculates the complete scenario. The advisor selects briefing sentences grounded in those calculated facts. It does not calculate or invent authoritative numbers.

## Official scoring model

All 10 district indicators use a 0-100 scale where higher is better. Measure effects are realized over an 8-quarter horizon:

$$I'_{dk}=\operatorname{clip}\left(I_{dk}+\sum_m \operatorname{effect}_{m,k}\frac{8-L_m}{8}+\operatorname{synergy},0,100\right)$$

$$D_d=\sum_k w_kI'_{dk}$$

$$D_{avg}=\sum_d pop_dD_d$$

$$Score=0.7D_{avg}+0.3\min(D_d)-N_{crit}$$

`N_crit` counts district/indicator pairs whose final value is strictly less than 40.

Verified reference values:

- Baseline: unrounded `D_avg = 56.8624`, weakest district `Нура = 49.18`, `N_crit = 2`, final `Score = 52.55768` (displayed as 52.56).
- Benchmark: M7(Нура), M8(Нура), M10(Нура), M12(Город), M5(Сарыарка), cost 95, `D_avg = 58.0776`, `N_crit = 0`, `Score = 56.54307`, delta `+3.98539`.

The complete district table, measure catalog, weights, synergies, conflicts, and validation rules are maintained in [AGENTS.md](AGENTS.md).

## Official requirements and team enhancements

Official must-haves:

- a common fixed budget and common starting data;
- exactly 5 decisions with automatic validation;
- deterministic effects on district indicators and final Astana Quality of Life Score;
- AI explanation of the final result and major trade-offs;
- a changed decision set can produce a changed score.

The case also lists scenario comparison, indicator visualizations, AI recommendations, unexpected-event modeling, and presentation generation as optional enhancements.

The implemented core UI adds KPI cards, the reference example, a visual measure-by-direction overview with measure names, a district before/after table, full Russian indicator labels with a glossary, and structured briefings with cached offline fallback. Charts, additional presets, an indicator heat breakdown, and JSON audit export remain planned. These are team implementation choices, not additional official rules.

## Target architecture

```text
├── AGENTS.md
├── README.md
├── requirements.txt
├── .env.example
├── .streamlit/config.toml    # light Astana theme
├── assets/summary_header.html # pinned summary styling and scroll animation
├── run.sh                    # planned
├── data/                     # verified source data
│   ├── districts.json
│   ├── measures.json
│   └── mock_debrief.json
├── engine/
│   ├── models.py             # data, validation, and audit contracts
│   ├── simulator.py          # pure validation and scoring; JSON loader
│   └── advisor.py            # OpenAI/NVIDIA adapters and offline fallback
├── tests/
│   ├── test_simulator.py     # independent exact-arithmetic reference and regressions
│   ├── test_advisor.py       # mocked provider and fallback tests
│   └── test_app.py           # offline UI acceptance and API-call boundary tests
└── app.py                    # Russian-language Streamlit core flow
```

## Run the tests

From the repository root, using Python 3.10 or later:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

The full suite includes simulator regressions, mocked provider tests, and Streamlit AppTest acceptance tests. The UI tests isolate environment settings and SDK clients, so they do not read your keys or make paid requests. They cover initial state, validation, scope changes, stale-result removal, provider selection, cache reuse, offline fallback, and recoverable failures.

The simulator tests use independent exact rational arithmetic to check the official formulas and all 2,002 distinct five-measure combinations with a fixed district assignment, plus dedicated assignment, conflict, budget, clipping, threshold, and permutation cases. Synthetic boundary fixtures never modify the official JSON files. To run only that suite, use `.venv/bin/python -m unittest tests.test_simulator -v`; it needs only Pydantic and the Python standard library.

The complete sweep checks all 1,407,050 scope-correct district assignments against an independent validator and exact integer arithmetic, including every valid scenario's indicators and Score. It takes several minutes and is opt-in:

```bash
SIMULATOR_EXHAUSTIVE=1 .venv/bin/python -m unittest discover -s tests -v
```

## Simulator API

```python
from engine.models import SimulationResult
from engine.simulator import DatasetError, load_dataset, simulate, validate_scenario

decisions = [
    {"measure_id": "M7", "district": "Нура"},
    {"measure_id": "M8", "district": "Нура"},
    {"measure_id": "M10", "district": "Нура"},
    {"measure_id": "M12"},  # Citywide: omit district (or use None).
    {"measure_id": "M5", "district": "Сарыарка"},
]
try:
    dataset = load_dataset()  # Resolves data/ relative to the module, not the cwd.
except DatasetError as error:
    print(str(error))  # Command-line example; the UI shows a concise Russian error.
else:
    report = validate_scenario(decisions, dataset)  # Optional form feedback.
    outcome = simulate(decisions, dataset)  # Always revalidates.
    if isinstance(outcome, SimulationResult):
        print(f"Score: {outcome.city_score_after:.2f}")
        audit_json = outcome.model_dump_json(indent=2)
    else:
        for issue in outcome.errors:
            print(issue.code, issue.decision_indices, issue.message)
```

`load_dataset(data_dir=None)` is the only operation that reads files. It rejects malformed/incomplete data with `DatasetError`; it never invents replacements. Weights and scalar rules are transcribed from AGENTS.md §3 into `engine/models.py`. JSON contains explicit synergy target measures and global/same-district conflict scopes. Dataset checks cover structure and arithmetic integrity; official-value fidelity is enforced by the regression tests.

`validate_scenario(decisions, dataset)` and `simulate(decisions, dataset)` accept lists or tuples of decision dictionaries or `Decision` instances. Both require a validated `Dataset`. Issues contain stable codes, actionable messages, and zero-based input positions. Budget feedback is unknown when a row cannot be resolved; otherwise it totals submitted rows, including duplicates that independently invalidate the scenario. Invalid scenarios return a `ValidationReport` with no Score fields. Baseline evaluation is internal: an empty decision list is still invalid.

Successful results use catalog order for decisions and official district order for district outputs. The first district in official order wins a weakest-district tie. `city_score_before/after` contain final penalized Scores; `weighted_city_score_before` and `weighted_city_score` contain before/after population-weighted averages. Python calculates all deltas, critical locations, and budget remaining. No intermediate rounding is performed; tests tolerate only floating-point representation error. The critical threshold is strictly `<40`, with no epsilon.

`measure_contributions` is measure → district → indicator, containing lag-adjusted direct effects **before clipping**. Omitted contribution indicators mean zero. `synergy_contributions` contains separate pair bonuses. Full district/indicator `clipping_adjustments` reconcile direct effects plus synergies with the final indicator deltas. These are not additive shares of final Score. Different district outcomes may have equal scalar Scores; the formula is preserved without imposing score uniqueness.

Only results freshly calculated by `simulate` are authoritative. Result schemas validate structure, ranges, and selected consistency checks; they do not authenticate an imported or edited numeric audit. Regenerate results from their decisions before trusting imported data. The advisor receives the Python output and does not recalculate any value.

## Advisor API and provider selection

The advisor accepts only a complete `SimulationResult` from the deterministic engine. Calling `generate_debrief` is the explicit briefing action; imports and simulation do not contact a provider. The UI supplies a per-session cache dictionary. The provider dropdown starts from configuration, and only the separate briefing button invokes the advisor.

Copy `.env.example` to an untracked `.env`, then set the key for the provider you intend to use:

```dotenv
ADVISOR_PROVIDER=openai
MOCK_MODE=false
OPENAI_API_KEY=
OPENAI_MODEL=gpt-6-sol
OPENAI_REASONING_EFFORT=low
NVIDIA_API_KEY=
NVIDIA_MODEL=mistralai/mistral-nemotron
ADVISOR_MAX_OUTPUT_TOKENS=700
```

`ADVISOR_PROVIDER` accepts `openai` (default), `nvidia`, or `offline`. `MOCK_MODE=true` always selects offline. OpenAI uses the [Responses API structured-output helper](https://developers.openai.com/api/docs/guides/structured-outputs) with [GPT-6 Sol](https://developers.openai.com/api/docs/models/gpt-6-sol). NVIDIA uses its [hosted Chat Completions endpoint](https://docs.api.nvidia.com/nim/reference/mistralai-mistral-nemotron-infer) and a [configurable model](https://build.nvidia.com/mistralai/mistral-nemotron). The NVIDIA-hosted default is supplied by Mistral AI, not by OpenAI. Availability and charges depend on your NVIDIA account; the app does not estimate its pricing or credit balance.

```python
from engine.advisor import generate_debrief
from engine.models import SimulationResult
from engine.simulator import load_dataset, simulate

dataset = load_dataset()
result = simulate(decisions, dataset)  # Use the five decisions defined above.
if isinstance(result, SimulationResult):
    session_cache = {}
    briefing = generate_debrief(result, session_cache)
    print(briefing.source, briefing.why_score_changed)
```

An explicit `provider="nvidia"` argument overrides `ADVISOR_PROVIDER` for that call; mock mode still wins. A missing key or failed call returns `source="mock"` without trying the other provider. The advisor sends only calculated scenario facts and Python-generated analytical candidates, never conversation history. Live candidates highlight district changes, measure contributions, synergies, clipping, or remaining risks, use full Russian indicator names, and differ from the offline summary. The model selects one candidate for each briefing field. Pydantic validates the returned structure and Python rejects any text that is not an exact candidate, preventing invented numbers, events, or measures from reaching the UI. Python also assigns `source`. The cached fallback uses `data/mock_debrief.json` templates filled with actual scores, human-readable indicator names, and the weakest district, so it works when the API is unavailable. Imported audit JSON must be recomputed by `simulate` before use.

Cache keys include the chosen provider, model, prompt version, and canonical simulation facts. A request has a 700-token maximum, a 20-second timeout, and no SDK retries. The adapter logs request ID and token usage when supplied, without logging keys or prompt contents. A timeout, rate limit, refusal, malformed or truncated response, or unavailable model produces the offline briefing. After editing `.env`, restart the Streamlit process and reload the browser page to load new settings and start a fresh session cache. Clearing the decision rows or loading the example intentionally preserves the existing briefing cache.

Run the mocked advisor and simulator tests with `.venv/bin/python -m unittest discover -s tests -v`. No live API request is part of the automated test suite. The OpenAI SDK requirement is `openai>=3.17,<4`, which supports the Responses parse helper used here.

## Reproducible launch

From the repository root, install the declared dependencies and launch the core UI:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py
```

For a fully offline demonstration on macOS/Linux, launch with an environment override:

```bash
MOCK_MODE=true .venv/bin/python -m streamlit run app.py
```

Open the local URL printed by Streamlit. No API key is needed for the simulator or offline briefing. The core flow was checked in a browser at desktop and phone widths; provider success/failure and call counts are covered by mocked AppTest tests.

1. Keep the prefilled reference scenario and press **«Рассчитать сценарий»**. Expect Score **56.54**, delta **+3.99**, budget **95 / 100**, weakest district **Нура / 52.96**, and **0** critical metrics.
2. Review the district table, select a briefing provider, and press **«Получить объяснение»**. With `MOCK_MODE=true`, the provider is fixed to **«Автономно»**. The displayed source reflects the actual response, including offline fallback.
3. Change any decision: the previous result and briefing disappear. Validation and budget update immediately; the simulation button is disabled until the selection is valid.
4. Use **«Очистить выбор»** for five empty rows or **«Загрузить пример»** to restore the reference. Neither action makes a provider request. Changing the provider clears only the briefing.

`run.sh`, charts, heatmaps, additional presets, and JSON audit download are not implemented yet.

## Delivery workflow

Development proceeds in small verified iterations:

1. choose one measurable outcome;
2. inspect repository documentation, deterministic data, and current code;
3. make the smallest coherent change;
4. run focused tests and required regression fixtures;
5. independently review the diff;
6. report evidence and stop before the next iteration.

Subagents may handle independent research, isolated implementation, test design, or review lanes. The lead agent remains responsible for integration and verifies every subagent result against files, simulator output, or tests. No LLM or subagent is an authority for numerical scoring.

Planned iterations:

1. Documentation governance.
2. Deterministic data and Pydantic models.
3. Simulator engine and regression tests.
4. Dual-provider advisor and offline fallback — implemented with mocked provider tests.
5. Streamlit MVP — core flow implemented; analytics, additional presets, and JSON export remain.
6. Reproducibility, smoke testing, and judge-facing polish.

## Evaluation rubric

| Criterion | Points |
|---|---:|
| Task compliance and operability | 25 |
| Technical implementation | 25 |
| README and reproducibility | 25 |
| Value and applicability | 15 |
| Development potential and originality | 10 |
| **Total** | **100** |

## Verification gate

Each completed implementation iteration must finish with:

- focused automated tests;
- baseline Score `52.56` regression;
- benchmark Score near `56.5` regression when simulator logic is involved;
- `git diff --check`;
- inspection of `git status --short` for unrelated changes;
- no commit or push unless explicitly requested.
