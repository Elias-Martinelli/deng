# ADR-006 — multi-league match training product

Status: ACCEPTED, 3 October 2026. Supersedes ADR-004's CL-only feature scope.

## Context

458 CL fixtures and a small feature view do not provide enough varied historical
examples. The user approved CL, PL, BL1, PD, SA, FL1, DED and PPL.

## Decision

Use the existing football-data.org provider across configurable competitions and
season start years. Keep its stable match/team IDs. Cache completed historical
endpoints and support an explicit refresh. Store current squad/coach observations
from team payloads; support dated licensed CSVs for valuations and extra context.
Build a distinct wide training product with 90-minute labels, observed snapshot
guards and multiple prior-result windows. Export the target/feature contract.

## Evidence and consequences

The existing account successfully imported eight leagues and 2023–2025 history;
the warehouse now holds 10,103 matches. No new key was required for this scope.
Coverage depends on account permissions. Optional individual team details cost
extra calls and do not unlock paid information.

Overall form now includes all ingested competitions, with separate same-competition
and venue form. Coverage must be disclosed: it is not every competitive appearance.
Market values and older squad/coach history remain absent without dated evidence.
Adding unverified APIs or fabricated values would weaken the dataset.

Provider references:
[API resources](https://docs.football-data.org/general/v4/index.html),
[team schema](https://docs.football-data.org/general/v4/team.html),
[coverage](https://www.football-data.org/coverage).
