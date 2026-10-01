# Initial project pitch · 1 October 2026

Outline of the eight slides in
[the PowerPoint presentation](initial-project-pitch-2026-10-01.pptx).
The PowerPoint is the reference version, including its architecture diagram.

## 1 · Champions League Match Intelligence

Recording every day what was known about a match, so a model can later predict
who wins.

HSLU · DENG Data Engineering · HS26
Elias Martinelli · Noah Rodriguez
Repository: [Elias-Martinelli/deng](https://github.com/Elias-Martinelli/deng)

## 2 · Who wins — and can we answer that fairly?

A fair model may only use what was known before kick-off.

- Fixtures exist months ahead; kick-off times still move.
- Table and form change after every matchday.
- Weather forecasts exist at most 16 days ahead and are then overwritten.

What is not stored today is gone tomorrow. Storing it is the project.

## 3 · End user and data product

The primary user is a data scientist who trains and tests a match-outcome model.
A secondary use is a dashboard that shows what the model would see.

One row per match combines:

- **Label:** result — home win, draw or away win.
- **Features known before kick-off:** form from earlier matches and the forecast
  for the kick-off hour.

## 4 · Three free sources, four ingestion steps

| Source | Data | Access and collection |
|---|---|---|
| football-data.org | Fixtures, results, standings and crests | 4 requests a day; limit of 10 per minute |
| Open-Meteo | Forecast for the kick-off hour | At most 16 days ahead; no key |
| OpenStreetMap | Stadium coordinates | Once per club |

All sources are documented and free; no scraping.

## 5 · Risks

| Finding | Our answer |
|---|---|
| Status filter is unreliable | Select by kick-off time |
| API sums do not add up | Compute form ourselves |
| Napoli found in Novara | Check every stadium by hand |
| Free-tier limits | Pacing and retries |
| Sources overwrite history | Keep every answer |

The biggest risk is data leakage: a model must not see the result of the match
it is meant to predict.

## 6 · Architecture v0.1 — three stages

The diagram in the PowerPoint shows the three stages of the architecture.

Rule: ingestion never reads the transformed tables. A test enforces this rule.

## 7 · Where it goes, and who does what

| Area | Owner |
|---|---|
| Football, past seasons | Both |
| Weather, stadiums | Elias |
| Transformations, model | Noah |
| Orchestration, Docker, CI | Noah |
| Dashboard, notebook | Elias |
| Cloud: Terraform, BigQuery | Both |

Every pull request is reviewed by the other team member.

- **Midterm · 22 October:** local pipeline.
- **Final · 10 December:** cloud pipeline.

## 8 · Questions

Thank you.

[Elias-Martinelli/deng](https://github.com/Elias-Martinelli/deng)
