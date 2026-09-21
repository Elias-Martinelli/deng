# Reference data

Small, versioned files that the pipeline joins against. Reviewed like code.

## venues.csv

Stadium coordinates for the league-phase clubs. The football API delivers no
coordinates, and its venue names and addresses are partly outdated or point to
training grounds, so they cannot be geocoded blindly.

* **Built by** `make venues` (`scripts/build_venues.py`): one OpenStreetMap
  (Nominatim) search per club, preferring objects tagged as a stadium.
* **Checked by** an automatic plausibility test (a place name from the API
  address must occur in OSM's address) plus a manual review of every flagged
  row. `address_check` records the outcome; `note` records why a search term
  differs from the API's venue name.
* **Verifiable:** `https://www.openstreetmap.org/<osm_type>/<osm_id>`.
* **Not resolved (`status = NOT_AVAILABLE`):** Shakhtar Donetsk (home matches
  outside Ukraine since 2022, venue for 2026/27 not in any source we use) and
  Sabah FK (no venue in the API). Their matches get no weather rather than a
  guessed location.

Coordinates © OpenStreetMap contributors, licensed under the
[ODbL](https://opendatacommons.org/licenses/odbl/).
