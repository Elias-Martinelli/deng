# Initial pitch (Milestone 1, week 3)

Everything needed for the 10-minute pitch. Worth 10 points: 5 for the
repository state, 5 for the pitch itself and the answers to questions.

| File | What it is |
|---|---|
| [`slides.md`](slides.md) | the deck - one `##` heading per slide, in the order we present |
| [`speaker-notes.md`](speaker-notes.md) | what to say per slide, in German, plus the questions we expect and short answers |
| [`../code-walkthrough.md`](../code-walkthrough.md) | nine stops through the code, for the questions that go past the slides |

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

## The three diagrams

| Slide | File | What it is for |
|---|---|---|
| 8 | [`architecture-overview.svg`](../architecture-overview.svg) | **the main picture**: the three stages - ingest, transform, data product. Most speaking time goes here. |
| 9 | [`architecture-detail.svg`](../architecture-detail.svg) | the same thing in detail, and slide 9 names the file or folder behind every box |
| 10 | [`architecture-target.svg`](../architecture-target.svg) | **the target**: local path today next to the cloud path of the final milestone |

## Two things deliberately left out

* **The data-quality checks.** They run in the pipeline and are described in the
  repository README, but they are not part of the story on stage.
* **The model itself.** It is the reason the use case exists (slide 2), not a
  deliverable of this project.

## Timing - 10 minutes, both of us speak

| Min | Slide | Who |
|---|---|---|
| 0:00-0:20 | 1 title | Elias |
| 0:20-1:10 | 2 the use case | Elias |
| 1:10-1:55 | 3 user and data product | Elias |
| 1:55-2:50 | 4 sources | Noah |
| 2:50-3:45 | 5 what the data looks like | Noah |
| 3:45-4:35 | 6 risks | Noah |
| 4:35-6:00 | 7 ingestion and storage strategy | Elias |
| 6:00-7:25 | **8 the three stages - the main slide** | Elias |
| 7:25-8:10 | 9 what runs today | Noah |
| 8:10-9:00 | 10 target and division of responsibilities | both |
| 9:00-10:00 | buffer, then questions | both |

Speaking time: Elias ~4:45, Noah ~3:25, slide 10 shared.

Rule from the module description: both team members must contribute, and the
instructor directs questions at both. Whoever did not build a part should be
able to explain it anyway - that is what the speaker notes are for.

## How to show the slides

`slides.md` is plain Markdown; every `##` starts a slide. Three ways to present:

* open it in VS Code preview and scroll (no tooling needed);
* paste it into any slide tool that reads Markdown;
* or present straight from GitHub, which renders the diagrams.

The three diagrams are SVG files in [`docs/`](..) and render in every browser.
