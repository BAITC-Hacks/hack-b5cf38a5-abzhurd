# Аким на 5 часов

AI-симулятор управления городом Астана для HackAlem AI 2026.

## Current status

The **deterministic simulator is implemented and tested**: official JSON data, Pydantic contracts, scenario validation, scoring, and a numeric audit of direct effects, synergies, and clipping. Python performs all calculations without network access or an API key.

The OpenAI advisor and Streamlit interface are still empty placeholders; `run.sh` is not implemented. The complete application is not yet launchable. `mock_debrief.json` exists, but its scenario grounding and fallback integration belong to the advisor iteration.

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
│   └── advisor.py            # empty placeholder
├── tests/
│   └── test_simulator.py     # independent exact-arithmetic reference and regressions
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

Only results freshly calculated by `simulate` are authoritative. Result schemas validate structure, ranges, and selected consistency checks; they do not authenticate an imported or edited numeric audit. Regenerate results from their decisions before trusting imported data. The future advisor must receive the Python output and must not recalculate any value.

## OpenAI API and budget policy

The planned advisor uses the OpenAI Responses API with structured Pydantic output.

Reserved configuration for the advisor iteration:

```dotenv
OPENAI_API_KEY=
OPENAI_MODEL=gpt-6-sol
OPENAI_REASONING_EFFORT=low
OPENAI_MAX_OUTPUT_TOKENS=700
MOCK_MODE=false
```

The default is `gpt-6-sol`, subject to account availability. The official OpenAI documentation describes Sol as suitable for work requiring judgment. Current standard short-context pricing is $2 per million input tokens and $10 per million output tokens, so a representative 2,000-input-token and 600-output-token debrief is about $0.01. Prices can change; consult the [model page](https://developers.openai.com/api/docs/models/gpt-6-sol), [selection guide](https://developers.openai.com/api/docs/guides/model-selection), and [pricing page](https://developers.openai.com/api/docs/pricing).

The available $50 API credit will be protected by calling the model only for a complete valid scenario, limiting output to 700 tokens, caching results per scenario, recording usage when available, and never calling the API on every Streamlit rerun. Missing credentials, disabled API mode, unavailable models, malformed output, timeouts, rate limits, and network errors will use a cached mock briefing.

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
4. Responses API advisor and offline fallback.
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
