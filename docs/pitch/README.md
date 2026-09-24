# Initial pitch (Milestone 1, week 3)

Everything needed for the 10-minute pitch. Worth 10 points: 5 for the
repository state, 5 for the pitch itself and the answers to questions.

| File | What it is |
|---|---|
| [`slides.md`](slides.md) | the deck - one `##` heading per slide, in the order we present |
| [`speaker-notes.md`](speaker-notes.md) | what to say per slide, in German, plus the questions we expect and short answers |

## What the module asks for (project description §1.5)

The pitch must cover six points. Each one has its slide:

| Requirement | Slide |
|---|---|
| the selected dataset and source system | 4, 5 |
| the user or stakeholder and the analytics / ML use case | 2, 3 |
| the expected output or data product | 3 |
| relevant data characteristics, risks and anticipated challenges | 5, 6 |
| an initial ingestion and storage strategy | 7 |
| Architecture v0.1, including the planned division of responsibilities | 8, 9, 10 |

The repository must already contain a README, the dataset and use-case
description, Architecture v0.1 and a short plan or backlog - all present:
[`README.md`](../../README.md), [`docs/use-case.md`](../use-case.md),
[`docs/data-sources.md`](../data-sources.md),
[`docs/architecture/architecture-v0.1.md`](../architecture/architecture-v0.1.md),
[`docs/project-backlog.md`](../project-backlog.md).

## Timing - 10 minutes, both of us speak

| Min | Slides | Who |
|---|---|---|
| 0:00-1:30 | 1-3 title, the question, the data product | Elias |
| 1:30-4:00 | 4-6 sources, characteristics, risks | Noah |
| 4:00-6:00 | 7 ingestion and storage strategy | Elias |
| 6:00-8:00 | 8-9 architecture v0.1 now and target | Elias (8), Noah (9) |
| 8:00-9:00 | 10 plan, division of responsibilities | both |
| 9:00-10:00 | buffer, then questions | both |

Rule from the module description: both team members must contribute, and the
instructor directs questions at both. Whoever did not build a part should be
able to explain it anyway - that is what the speaker notes are for.

## How to show the slides

`slides.md` is plain Markdown; every `##` starts a slide. Three ways to present:

* open it in VS Code preview and scroll (no tooling needed);
* paste it into any slide tool that reads Markdown;
* or present straight from GitHub, which renders the diagrams.

The diagrams are SVG files in [`docs/`](..) and render in every browser.
