# FootballDatabase-Weltranking pro Match

Stand: 16. Oktober 2026. Quelle:
[FootballDatabase World Ranking](https://footballdatabase.com/ranking/world/1).
Die Seite nennt den Datenstand als "Updated after matches played on 11 October 2026".
Das ist ein Spiele-Stichtag und kein belegter Veroeffentlichungszeitpunkt.

## Neue Spalten

| Spalte | Bedeutung |
|---|---|
| home_world_rank / away_world_rank | Welt-Rang der beiden Clubs; kleiner ist besser |
| home_world_rating_points / away_world_rating_points | FootballDatabase-Rating-Punkte; hoeher ist staerker |
| world_rating_points_difference | Heim-Punkte minus Auswaerts-Punkte |
| world_rank_advantage_home | Auswaerts-Rang minus Heim-Rang; positiv bedeutet Heimvorteil im Ranking |
| audit_home_world_ranking_date / audit_away_world_ranking_date | Spiele-Stichtag der Quelle |
| audit_home_world_ranking_observed_at / audit_away_world_ranking_observed_at | Erster erfolgreicher Abruf |
| audit_home_world_ranking_source / audit_away_world_ranking_source | URL der jeweiligen Rankingseite |

Die Punkte sind Rating-Punkte, keine Ligatabellen-Punkte.
Die sechs audit-Spalten sind Herkunftsangaben und keine Modellmerkmale.
Fehlt eine Seite, bleiben auch beide Differenzen NULL.

## Zeitliche Korrektheit

Pro Team und Match wird das neueste geeignete Ranking gewaehlt:

1. Der erste beobachtete Abruf liegt strikt vor Anstoss.
2. Der Spiele-Stichtag liegt vor dem UTC-Spieltag.
3. Der Stichtag ist am Spieltag hoechstens 35 Tage alt.

Dadurch werden aktuelle Werte nicht in vergangene Spiele kopiert und auch nicht
unbegrenzt fuer weit entfernte zukuenftige Spiele weiterverwendet. Ein unveraenderter
erneuter Abruf behaelt den ersten Beobachtungszeitpunkt. Eine geaenderte Tabelle
wird als neue Beobachtung gespeichert. Die 35 Tage sind eine dokumentierte
Projektentscheidung; sie machen aus einem alten Snapshot keine neue Prognose.

Historische Rankings sind damit noch nicht rueckwirkend erfasst. Eine historische
Quelle muesste den damaligen Snapshot und seine Verfuegbarkeit nachweisen.
Die bestehende Modellbaseline wurde nicht mit diesen neu erfassten Rankings
neu trainiert; ihre historischen Trainingszeilen haben keine solchen Werte.

## Import und Betrieb

Kein API-Key erforderlich. Der Import ruft die oeffentlichen HTML-Seiten ab,
validiert Datum, Rangfolge, positive Punkte und eindeutige Clubs und speichert
HTML, normalisierte Zeilen, SHA-256 der normalisierten Zeilen, URL und Lauf-ID.
Aenderungen am Seitenaufbau oder Zugriffsfehler werden als Fehler protokolliert.
Die optionale Quelle stoppt bei solchen Fehlern; sie umgeht keine Zugriffssperren.

```bash
make init
.venv/bin/python -m deng.pipeline ingest --only ranking
make transform
make dq
make export
```

`make run` und die taegliche Dagster-Ingestion enthalten den Import ebenfalls.
FOOTBALLDATABASE_ENABLED=true aktiviert ihn, FOOTBALLDATABASE_MAX_PAGES=63
begrenzt den Abruf. Eine Sekunde Abstand zwischen neuen Seiten; bereits gepruefte
Seiten werden am selben Tag wiederverwendet. Ein Fehler auf einer spaeteren Seite
verwirft die zuvor gespeicherten Rohseiten nicht. Ohne vollstaendigen erfolgreichen
Durchlauf ist der Laufstatus massgeblich, nicht nur die Zahl vorhandener Rohseiten.
Fuer vergangene logische Daten erfolgt kein Live-Abruf. Im Offline-Samplemodus
bleibt diese Quelle leer; die Rankingregeln werden separat mit synthetischen
Testdaten geprueft. Geaenderte Compose-Konfiguration benoetigt einen Neustart bzw.
Neuerstellung der betroffenen Dienste; in diesem Arbeitslauf wurde die CLI genutzt.

## Team-Zuordnung

Automatisch nur eindeutige normalisierte Namen im selben Land, einschliesslich
vorhandener Namensaliase. Keine automatische unscharfe Aehnlichkeitszuordnung.
Abweichende Identitaeten werden in
[data/reference/footballdatabase_team_ids.csv](../data/reference/footballdatabase_team_ids.csv)
explizit gepflegt. Beispielsweise gehoert AS Monaco im Fussballdatenanbieter zum
Land Monaco, wird im Ranking aber unter Frankreich gefuehrt; das ist eine
gepruefte Zuordnung. Stabile Anbieter-Club-Slugs verhindern Verwechslungen bei
kurzen oder uebersetzten Namen.

Die Rohzuordnung steht in raw.footballdatabase_team_map. Die Transformation
schreibt staging.team_world_ranking; die Match-Ansicht verbindet je einen
zeitlich geeigneten Heim- und Auswaerts-Snapshot. Die Tabellenansicht bietet
dafuer die neue Spaltengruppe "Welt-Ranking".

## Gemessener Stand

- 63 Seiten, 3'122 weltweit gelistete Clubs.
- Alle 203 Projektteams zugeordnet, davon 38 ueber explizit gepruefte Slugs.
- 10'103 Matchzeilen; jetzt 304 statt 292 Spalten.
- 303 Matchzeilen mit Rang und Punkten fuer beide Teams; 9'800 ohne zeitlich
  geeigneten Snapshot. Dazu gehoeren historische und zu weit entfernte Spiele.
- Ranking-Spalten sind in allen acht Wettbewerben befuellt:
  BL1 36, CL 36, DED 36, FL1 36, PD 41, PL 40, PPL 28, SA 50.
- Beispiel Match 558872: Heerenveen Rang 296 / 1'517 Punkte, Excelsior Rang 633 /
  1'417 Punkte; Differenz +100 Punkte fuer Heerenveen.
- 211 Tests bestanden; zwei neue kritische Rankingpruefungen bestanden.
- Gesamte DQ: 29/31 bestanden, keine kritischen Fehler. Die Warnungen betreffen
  25 Wetterluecken im am 16. Oktober verschobenen Prognosehorizont und zehn
  zuvor dokumentierte auffaellige Quoten. Wetter/Quoten wurden hier nicht neu geladen.

Export: data/processed/world-ranking-2026-10-16/ mit matches.csv,
manifest.json, data_dictionary.json und coverage.json.

## Quellenangabe und Weitergabe

Die Quellseite weist **CC BY-SA 4.0** aus. Quellenangabe:
FootballDatabase.com, World Football / Soccer Clubs Ranking,
https://footballdatabase.com/ranking/world/1, abgerufen am 16. Oktober 2026.
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
Die Daten wurden normalisiert, Club-IDs zugeordnet und mit Matchzeilen verbunden;
Rang- und Punktedifferenzen wurden berechnet. Der Export traegt diese Angaben
im Manifest. Fuer die Weitergabe der Rankingdaten und daraus abgeleiteter Daten
sind die Bedingungen dieser Datenlizenz zu beachten; die Code-Lizenz des Projekts
ersetzt sie nicht.
