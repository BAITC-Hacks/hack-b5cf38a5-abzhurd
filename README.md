# Аким на 5 часов

AI-симулятор управления городом Астана для HackAlem AI 2026.

## Current status

The **deterministic simulator is implemented and tested**: official JSON data, Pydantic contracts, scenario validation, scoring, and a numeric audit of direct effects, synergies, and clipping. Python performs all calculations without network access or an API key.

The advisor now supports OpenAI, NVIDIA, and a deterministic offline briefing. The Streamlit interface is still an empty placeholder and `run.sh` is not implemented, so the complete application is not yet launchable. Provider calls are covered by mocked tests; a live call still requires the user's own key and account access.

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

Python will calculate the complete scenario. The LLM will receive those calculated facts and explain strengths, risks, consequences, and next-step recommendations. It will not calculate or invent authoritative numbers.

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

Our planned MVP adds Streamlit KPI cards, presets, before/after analytics, an indicator heat breakdown, a structured AI briefing, cached offline fallback, and JSON audit export. These are team implementation choices, not additional official rules.

## Target architecture

```text
├── AGENTS.md
├── README.md
├── requirements.txt
├── .env.example
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
│   └── test_advisor.py       # mocked provider and fallback tests
└── app.py                    # empty placeholder
```

## Run the deterministic engine tests

From the repository root, using Python 3.10 or later:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install 'pydantic>=2.7.0,<3'
.venv/bin/python -m unittest discover -s tests -v
```

Only Pydantic and the Python standard library are needed for this iteration. The tests use independent exact rational arithmetic to check the official formulas and all 2,002 distinct five-measure combinations with a fixed district assignment, plus dedicated assignment, conflict, budget, clipping, threshold, and permutation cases. Synthetic boundary fixtures never modify the official JSON files.

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
    print(str(error))  # A future UI must display this without a traceback.
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

The advisor accepts only a complete `SimulationResult` from the deterministic engine. Calling `generate_debrief` is the explicit briefing action; imports and simulation do not contact a provider. The caller supplies a per-session cache dictionary. The future Streamlit UI will offer the provider dropdown; this iteration selects it through configuration.

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

An explicit `provider="nvidia"` argument overrides `ADVISOR_PROVIDER` for that call; mock mode still wins. A missing key or failed call returns `source="mock"` without trying the other provider. The advisor sends only calculated scenario facts and Python-generated candidate sentences, never conversation history. The model selects one candidate for each briefing field. Pydantic validates the returned structure and Python rejects any text that is not an exact candidate, preventing invented numbers, events, or measures from reaching the UI. Python also assigns `source`. The cached fallback uses `data/mock_debrief.json` templates filled with the actual score direction, critical metrics, and weakest district, so it works when the API is unavailable. Imported audit JSON must be recomputed by `simulate` before use.

Cache keys include the chosen provider, model, prompt version, and canonical simulation facts. A request has a 700-token maximum, a 20-second timeout, and no SDK retries. The adapter logs request ID and token usage when supplied, without logging keys or prompt contents. A timeout, rate limit, refusal, malformed or truncated response, or unavailable model produces the offline briefing. After changing credentials or model settings in a running UI session, clear that session's cache to force a fresh briefing.

Run the mocked advisor and simulator tests with `.venv/bin/python -m unittest discover -s tests -v`. No live API request is part of the automated test suite. The OpenAI SDK requirement is `openai>=3.17,<4`, which supports the Responses parse helper used here.

## Reproducible launch

The intended final launch commands are:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

**These commands are planned, not yet a working acceptance claim.** This section will be promoted to verified setup instructions only after the simulator, UI, data files, fallback, and smoke tests are implemented.

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
5. Streamlit MVP and JSON export.
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
