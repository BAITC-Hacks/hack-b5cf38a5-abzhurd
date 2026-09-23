# CODEX.md — AI Urban Simulator ("Аким на 5 часов")

> **HackAlem AI 2026** | Track: «Аким на 5 часов» - AI-симулятор управления городом  
> **Team:** Solo Vibecoder assisted by OpenAI Codex  
> **Stack:** Python 3.10+, Streamlit, Pydantic v2, OpenAI API (`gpt-4o` / `gpt-4o-mini`), python-dotenv  
> **Target:** 100% Launchable, Reproducible, and Fully Compliant MVP

---

## 1. Role & Operating Principles for Codex

You are acting as the **Principal Python Engineer & Lead Agentic Architect** for a solo participant at HackAlem AI 2026. 

### Core Rules:
1. **Mathematical Division of Labor (From Official HackAlem Specification):**
   > *"Роль ИИ: LLM получает результат расчёта (дельты по районам и показателям, вклад каждой меры) и объясняет его, сравнивает наборы, советует. Числа он не считает и не придумывает."*
   - **Python calculates:** Budget, lags, synergies, conflicts, $N_{crit}$, $D_{avg}$, and the final Score with 100% mathematical precision.
   - **LLM / Codex explains:** Acts as the **AI Mayoral Chief of Staff (Советник Акима)**, explaining trade-offs, district impacts, political/economic risks, and recommendations.
2. **Indestructible Resilience (No Crashes!):**
   - Every external API call (OpenAI) **must** have an automatic fallback to pre-cached realistic mock data if the key is missing or the network drops. The app must never throw an unhandled exception or show a traceback.
3. **Reproducibility (25 Points of Evaluation):**
   - The project must run with zero configuration friction:
     ```bash
     pip install -r requirements.txt
     streamlit run app.py
     ```
4. **Code Quality:**
   - Type hints on all functions and Pydantic models.
   - Modular file structure (`engine/`, `data/`, `app.py`).

---

## 2. Domain Data & Mathematical Model (Official HackAlem Specification)

### A. Districts Baseline Table
5 administrative districts of Astana with population weights and 10 indicator values (scale 0–100, 100 = best):

| District | Pop Weight (`pop_d`) | T1 | T2 | E1 | E2 | S1 | S2 | B1 | B2 | C1 | C2 | Base Score $D_d$ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **Есиль** | 0.27 | 45 | 62 | 68 | 72 | 48 | 55 | 78 | 60 | 75 | 70 | 62.99 |
| **Алматы** | 0.24 | 40 | 75 | 50 | 55 | 60 | 65 | 62 | 52 | 50 | 60 | 57.06 |
| **Сарыарка** | 0.20 | 50 | 70 | 42 | 40 | 62 | 68 | 58 | 55 | 45 | 55 | 54.65 |
| **Байконур** | 0.13 | 52 | 68 | 55 | 50 | 58 | 60 | 52 | 58 | 55 | 58 | 56.63 |
| **Нура** | 0.16 | 55 | 40 | 45 | 65 | 38 | 35 | 55 | 50 | 60 | 50 | 49.18 |

*District Profiles:*
- **Есиль:** High wealth, bridge congestion, overcrowded schools ($S1=48$).
- **Алматы:** Aging utility networks ($C1=50$), traffic jams ($T1=40$).
- **Сарыарка:** Heavy smog from private coal heating sector ($E2=40$), low greenery ($E1=42$).
- **Байконур:** Average across all metrics, no severe spikes.
- **Нура:** Lagging district; critical deficit in social facilities ($S1=38, S2=35$) and transit ($T2=40$).

### B. Indicator Codes & Weights ($w_k$, $\sum w_k = 1.0$)
- **Transport (0.20):** `T1` (Traffic relief, $w=0.10$), `T2` (Public transit access, $w=0.10$)
- **Ecology (0.20):** `E1` (Greenery $m^2$/resident, $w=0.09$), `E2` (Winter air quality AQI, $w=0.11$)
- **Social (0.22):** `S1` (Schools & kindergartens, $w=0.11$), `S2` (Polyclinics & primary care, $w=0.11$)
- **Safety (0.18):** `B1` (Street safety & cameras, $w=0.09$), `B2` (Road traffic safety, $w=0.09$)
- **City Services (0.20):** `C1` (Utility/heating reliability, $w=0.10$), `C2` (Speed of solving complaints, $w=0.10$)

### C. Catalog of 14 Measures
Horizon $H = 8$ quarters. Realized effect multiplier = $(8 - L) / 8$.

| ID | Direction | Measure Name | Scope | Cost | Lag $L$ | Raw Effects (Before Lag) |
|---|---|---|---|---|---|---|
| **M1** | Транспорт | Выделенные полосы для автобусов | Район | 18 | 2 | T1 +6, T2 +9 |
| **M2** | Транспорт | Умные светофоры (адаптивное управление) | Город | 22 | 2 | T1 +4, B2 +3 |
| **M3** | Транспорт | Линия ЛРТ / расширение | Район | 30 | 4 | T1 +16, T2 +20, E2 +4 |
| **M4** | Экология | Парк / сквер | Район | 15 | 2 | E1 +12, E2 +3, B1 +2 |
| **M5** | Экология | Перевод частного сектора на чистое топливо | Район | 25 | 3 | E2 +14, C1 +4 |
| **M6** | Экология | Городская программа озеленения | Город | 20 | 4 | E1 +5, E2 +3 |
| **M7** | Соцсфера | Школа + детсад (модульное строительство) | Район | 24 | 3 | S1 +16 |
| **M8** | Соцсфера | Центр семейного здоровья / поликлиника | Район | 20 | 3 | S2 +14 |
| **M9** | Соцсфера | Дворовые спорт-хабы | Район | 10 | 1 | S1 +3, S2 +3, B1 +3 |
| **M10** | Безопасность | Освещение и камеры (Safe City) | Район | 12 | 1 | B1 +12, B2 +2 |
| **M11** | Безопасность | Безопасные переходы и школьные зоны | Район | 10 | 1 | B2 +12, T1 -2 |
| **M12** | Сервисы | Единая цифровая платформа обращений | Город | 14 | 1 | C2 +5 |
| **M13** | Сервисы | Модернизация тепло- и водосетей | Район | 28 | 4 | C1 +18, E2 +2 |
| **M14** | Сервисы | Аварийные бригады ЖКХ + раннее оповещение | Город | 16 | 1 | C1 +5, C2 +2 |

### D. Synergies (Fixed bonuses, not scaled by lag)
- **M1 + M2:** T1 +2 in the district where M1 is applied.
- **M10 + M12:** B1 +2 in the district where M10 is applied.
- **M5 + M6:** E2 +2 in the district where M5 is applied.

### E. Incompatibilities (Strictly Forbidden)
- **M1 and M3:** Cannot both be chosen anywhere (BRT vs LRT conflict).
- **M4 and M7:** Cannot be in the same district (land plot conflict).
- **M5 and M13:** Cannot be in the same district (program duplication).

### F. Scoring Algorithm
1. **New Indicator Value:**
   $$I'_{dk} = \text{clip}\left(I_{dk} + \sum_{m} \text{effect}_{m,k} \times \frac{8 - L_m}{8} + \text{synergy}, 0, 100\right)$$
2. **District Score:**
   $$D_d = \sum_{k} w_k \times I'_{dk}$$
3. **Weighted City Score:**
   $$D_{avg} = \sum_{d} \text{pop}_d \times D_d$$
4. **Critical Metrics Count ($N_{crit}$):**
   Count of $(d, k)$ pairs where $I'_{dk} < 40$ strictly.
5. **Final Astana Quality of Life Score:**
   $$\text{Score} = 0.7 \times D_{avg} + 0.3 \times \min(D_d) - 1.0 \times N_{crit}$$
   - *Baseline without actions:* $52.56$ ($D_{avg}=56.86$, $\min(D_d)=49.18$ [Нура], $N_{crit}=2$ [$S1=38, S2=35$ in Нура]).
   - *Reference benchmark set:* M7(Нура), M8(Нура), M10(Нура), M12(Город), M5(Сарыарка) $\rightarrow$ Cost = 95, Score $\approx 56.5$ ($+4.0$ delta).

### G. Validation Constraints
- **Budget:** Total cost $\le 100$ (remaining does not expire or give bonus).
- **Count:** Exactly 5 decisions.
- **No repeats:** Each measure used at most once.
- **Direction balance:** Max 2 measures per direction (at least 3 directions touched).
- **District assignment:** Required for 'Район' type, must be `None` for 'Город' type.
- **Conflicts:** Must pass all incompatibility checks.

---

## 3. Project File Tree & Responsibilities

```text
├── CODEX.md                  <-- This specification file
├── README.md                 <-- Production documentation for hackathon judges
├── requirements.txt          <-- Minimal stable dependencies
├── .env.example              <-- Template for OpenAI API key
├── run.sh                    <-- One-click execution script
├── data/
│   ├── districts.json        <-- Static baseline data
│   ├── measures.json         <-- Static catalog of measures
│   └── mock_debrief.json     <-- Pre-cached LLM responses for offline demo
├── engine/
│   ├── __init__.py
│   ├── models.py             <-- Pydantic schemas (Decision, SimulationResult, Debrief)
│   ├── simulator.py          <-- Pure deterministic math engine & validator
│   └── advisor.py            <-- LLM Mayoral Chief of Staff with mock fallback
└── app.py                    <-- Streamlit interactive dashboard
```

---

## 4. UI Requirements for `app.py` (Streamlit)

1. **Header & High-Level KPIs:**
   - Astana City branding.
   - 4 Metric cards: `Budget Used: X / 100`, `Astana QoL Score: XX.X (+X.X)`, `Weakest District: [Name]`, `Critical Alerts: N`.
2. **Interactive Decision Panel:**
   - 3 One-Click Presets:
     - 🌟 *"Эталон баланса"* (M7 Нура, M8 Нура, M10 Нура, M12 Город, M5 Сарыарка)
     - 🌿 *"Зелёный рывок"* (Экология + Сервис)
     - 🚌 *"Транспортная реформа"* (Транспорт + Безопасность)
   - 5 Dynamic decision rows with category filter, measure selection, and conditional district picker.
   - Real-time budget progress bar with warning on $>100$.
3. **Visual Analytics:**
   - Comparison table / bar chart: Before vs. After for all 5 districts.
   - Indicator heat breakdown (highlighting resolved critical values $<40$).
4. **AI Mayoral Chief of Staff (Советник Акима):**
   - Executive Briefing box generated by LLM (or mock fallback).
   - "Почему вырос балл", "Главный риск", "Рекомендация на следующий квартал".
5. **Report Export:**
   - Download complete scenario audit as JSON.

---

## 5. Development Command Reference

```bash
# Setup venv
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run math engine tests
python -m engine.simulator

# Launch Streamlit app
streamlit run app.py
```
