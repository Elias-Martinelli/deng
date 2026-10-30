# Trainingsdatensatz: Ergaenzungen und verbleibende Grenzen

## World ranking update — 16 October 2026

Neu: [FootballDatabase-Ranking](world-ranking.md) mit Rang und Rating-Punkten beider Teams. 203 Teams zugeordnet, 303 zeitlich geeignete Matchzeilen befuellt; der neue Export hat 304 Spalten. Die folgenden Zahlen beschreiben weiterhin den Stand vom 15. Oktober.

Stand: 15. Oktober 2026. Diese Seite ersetzt die fruehere Liste offener
Trainingsdaten-Punkte. Der lokale Export umfasst 10'103 Spiele, acht Wettbewerbe
und 292 Spalten. Eine vorhandene Spalte bedeutet nicht, dass sie historisch
vollstaendig gefuellt ist. Fehlende Werte bleiben NULL.

## Status der fuenf Punkte

| Punkt | Umgesetzt / gemessen | Was noch fehlt |
|---|---|---|
| Historische Marktwerte | Validierter Import datierter Team-Snapshots vorhanden; 0 befuellte Marktwerte | Geeignete Quelle mit Nutzungsrecht, Stichtag und Team-ID-Zuordnung |
| Spieler und Trainer | Spieler-Snapshots, Kaderaggregate und Trainerkontext vorhanden; Heimkader bei 2'082, Auswaertskader bei 2'085 Matchzeilen; Traineralter bei 1'705 / 1'711 | Historische Kader/Trainer-Zuordnungen und detaillierte Spielerleistungen |
| Buchmacherquoten | 143 Spiele aus allen acht Wettbewerben mit echten, vor Anstoss erfassten Quoten | Historische Quoten vor Beginn unserer Erfassung; noch kein historischer API-Connector |
| Wetter | 110 Stadionabfragen erfolgreich; aktuelle MISSING-Luecke von 101 auf 1 reduziert; 213 Matchzeilen mit nutzbarer Temperatur | Ein Nullwert am Vorhersagehorizont; historische Prognosen und unbekannte Stadien |
| Modell | Logistische Regression trainiert, spaetere Saison separat getestet und mit einfacher Referenz verglichen | Gute Unentschieden-Erkennung, weitere Validierungsperioden und spaetere Modellentwicklung |

Die Zahlen beziehen sich auf Matchzeilen, nicht auf unterschiedliche Spieler
oder Trainer. Quoten und Wetter betreffen vor allem anstehende Spiele; sie
machen alte Spiele nicht nachtraeglich vollstaendig.

## 1. Historische Marktwerte

Ein heutiger Wert darf nicht in eine Matchzeile von 2023 uebernommen werden.
Eine Quelle muss Wert in EUR, den damals zugehoerigen Kader und einen belegten
Veroeffentlichungs-/Gueltigkeitszeitpunkt liefern. Transfergebuehren sind keine
Kader-Marktwerte. Die bisherigen Antworten enthalten keine belastbare solche
Historie. Das ist eine fehlende Datenquelle, keine technische Unmoeglichkeit.

Bereit: [Importvertrag und Anleitung](team-context.md),
[CSV-Vorlage](../data/reference/team_context_template.csv).
Ein geeigneter lizenzierter Export kann ueber TEAM_CONTEXT_CSV_PATH importiert
werden. Der Import prueft Pflichtfelder, Zeitstempel, Werte und Team-IDs;
Quellenbeleg und tatsaechliche damalige Verfuegbarkeit muessen belegt werden.
Kein neuer kostenpflichtiger Zugang wurde bestellt oder vorausgesetzt.

## 2. Spielerleistungen und Trainerhistorie

football-data.org beschreibt seine Team-Kader als Daten der aktuellen Saison:
[API policies](https://docs.football-data.org/general/v4/policies.html),
[Team resource](https://docs.football-data.org/general/v4/team.html).
FOOTBALL_DATA_TEAM_DETAILS=true fuehrt zusaetzliche Team-Abfragen aus, schaltet
aber keine historischen oder kostenpflichtigen Felder frei.

Vorhanden sind Profilbeobachtungen, Kadergroesse/Alter/Positionen und Trainerdaten.
Die Trainer-Siegquote verwendet nur abgedeckte fruehere Spiele mit nachgewiesener
Trainerzuordnung; sie ist keine vollstaendige Karrierequote. Minuten, Assists,
xG, Verletzungshistorie und historische Aufstellungen werden derzeit nicht
importiert. Der CSV-Kontextimport ersetzt keinen Spielerleistungs-Connector.

Moegliche weitere Quellen:

- [Sportmonks](https://www.sportmonks.com/football-api/plans-pricing/) beschreibt
  Spieler-/Trainerstatistiken und historische Daten. Vor einer Integration muessen
  der konkrete Zugang, alle acht Wettbewerbe und die benoetigten Saisons anhand
  von Beispielantworten geprueft werden. Ein API-Key allein beweist die Abdeckung nicht.
- [StatsBomb Open Data](https://github.com/hudl/open-data) bietet Events und
  Aufstellungen fuer ausgewaehlte Wettbewerbe. Die Quelle ist eine moegliche
  Teil-Ergaenzung, keine belegte Vollabdeckung unserer acht Ligen. ID-Zuordnung,
  Lizenzhinweise und zeitlich korrekte Aggregate sind noch zu implementieren.

Leistungen aus einem Spiel duerfen erst fuer spaetere Spiele verwendet werden.
Saison-Endstatistiken duerfen nicht rueckwirkend als Vor-Spiel-Wissen dienen.
Fuer historische Trainer/Kader kann der bestehende datierte Kontextimport
verwendet werden. Detaillierte Spielerstatistiken benoetigen weitere Integration.

## 3. Quoten fuer acht Wettbewerbe

ODDS_API_SPORTS erweitert den bisherigen einzelnen Sport. Abrufintervall je
Sport/Region/Markt, gemeinsames Kontingent und globale Reserve werden getrennt
behandelt. Ein Abruf fuer Portugal markiert englische Quoten nicht mehr als
zurueckgezogen. Die Namensvariante Rennes ist explizit Stade Rennais zugeordnet.

| Wettbewerb | Spiele mit nutzbaren Quoten |
|---|---:|
| Champions League | 18 |
| Premier League | 20 |
| Bundesliga | 18 |
| La Liga | 21 |
| Serie A | 20 |
| Ligue 1 | 18 |
| Eredivisie | 18 |
| Portugal | 10 |
| Gesamt | 143 |

Alle 143 Anbieter-Events wurden zugeordnet. Ein CL-Abruf und sieben weitere
Liga-Abrufe verbrauchten zusammen acht Credits; zuletzt 492 verbleibend.
ODDS_REFRESH_MINUTES=1440 begrenzt die regulaeren Abrufe auf einen pro Tag und
Sport. Acht Sportarten, eine Region und h2h entsprechen normalerweise maximal
248 Credits in 31 Tagen ohne zusaetzliche erzwungene Abrufe/weitere Abfragen.
Die bereits vorhandenen Dagster-Zeitplaene nutzen diese Konfiguration nach
Neuladen; laufende Compose-Dienste muessen mit aktualisierter Umgebung neu
erstellt werden. Dieser Arbeitslauf hat die CLI ausgefuehrt und keine laufenden
Container oder Hintergrunddienste neu gestartet.

**Qualitaet:** Zehn reale betfair_ex_eu-Beobachtungen haben extreme implizite
Margen (46,4 % bis 171,1 %). Rohdaten und Beobachtungen bleiben erhalten und die
DQ-Warnung bleibt sichtbar. Fuer Trainingskonsens werden nur vollstaendige
Dreiwegquoten mit Preisen 1,01-1000 und Marge -2 % bis 30 % verwendet. Erst wird
die neueste Quote ausgewaehlt, dann geprueft; eine unplausible neue Quote darf
keine alte Quote wieder aktivieren. Die genaue Ursache der Boersenwerte ist
nicht geklaert. Das Modell verwendet ohnehin noch keine Quoten.

**Historie:** Der historische Endpoint von
[The Odds API](https://the-odds-api.com/liveapi/guides/v4/) ist laut Dokumentation
kostenpflichtig. Der vorhandene Key wurde fuer aktuelle Quoten erfolgreich
geprueft; ein historischer Zugang wurde nicht abgefragt oder gekauft. Selbst mit
Zugang braucht es einen separaten Backfill-Connector: Provider-Snapshot-Zeit,
Abrufzeit und Veroeffentlichungszeit muessen getrennt gespeichert werden.
Heutige Abrufzeiten werden nicht einfach rueckdatiert.

Als alternative historische Quelle wurde football-data.co.uk untersucht;
Datenbeschreibung und Notizen antworteten bei der Recherche mit HTTP 429.
Abdeckung, Zeitstempel und Nutzungsbedingungen sind daher hier nicht verifiziert.
Sie bleibt ein moeglicher weiterer Integrationsweg, nicht ein zugesagter Import.

## 4. Wetter: aktuelle Luecke behoben, Rest erklaert

Neu geladen: 110/110 Stadionantworten. MISSING ist von 101 auf 1 gesunken.
Bei Match 559639 am 30. Oktober 2026 liefert Open-Meteo fuer die Anstosstunde
noch NULL als Temperatur; die Stunde liegt am Ende des 16-Tage-Horizonts.
Der naechste regulaere Lauf fragt sie erneut ab. Ein kuenstlicher Wert oder das
Entfernen der Qualitaetswarnung waere keine Loesung.

Wetterstatus im ganzen Datensatz:

| Status | Matchzeilen | Bedeutung |
|---|---:|---|
| AVAILABLE | 213 | Nutzbare, vor Anstoss erfasste Prognose |
| MISSING | 1 | Innerhalb des Horizonts, Anbieterwert noch leer |
| NOT_CAPTURED | 6'992 | Keine rechtzeitig erfasste historische Prognose |
| NOT_YET_AVAILABLE | 1'667 | Noch ausserhalb des Prognosehorizonts |
| VENUE_UNKNOWN | 1'230 | Keine bestaetigten Stadionkoordinaten |

Historisches beobachtetes Wetter ist kein damaliger Forecast.
[Open-Meteo Previous Runs](https://open-meteo.com/en/docs/previous-runs-api) und
[Historical Forecast](https://open-meteo.com/en/docs/historical-forecast-api)
bieten moegliche Archivwege. Ein weiterer Connector muss Modelllauf und damalige
Verfuegbarkeit pruefen. Diese Archive sind derzeit nicht integriert; die
vorhandene Datenbasis wird nicht als vollstaendige Wetterhistorie ausgegeben.

## 5. Trainiertes Basismodell

Ergebnis und reproduzierbare Anleitung: [Modellevaluation](model-baseline.md).
5'040 Trainingsspiele vor 1. Juli 2025, 2'552 Testspiele vom 1. Juli 2025 bis
vor 1. Juli 2026. Modellgewichte, Imputation und Skalierung werden nur aus dem
Training gelernt. Der Testzeitraum wurde nicht fuer Parametertuning verwendet.

| Metrik | Logistische Regression | Trainings-Klassenhaeufigkeit |
|---|---:|---:|
| Accuracy | 50,63 % | 44,16 % |
| Macro-F1 | 0,3861 | 0,2042 |
| Log Loss (kleiner besser) | 1,0313 | 1,0709 |

Nur 6 von 642 Unentschieden werden als solche erkannt. Das Ergebnis ist ein
nachvollziehbarer Anfang und ein Test der Nutzbarkeit der Tabelle, kein fertig
optimiertes Prognosesystem. Weitere Experimente benoetigen ein eigenes
Validierungsfenster; der bereits ausgewertete Test ist nicht mehr unberuehrt.

## Verifikation und Abgabe

Export: data/processed/training-ready-2026-10-15/ mit CSV, Manifest,
Datenwoerterbuch und Vollstaendigkeitsbericht. Fruehere Exporte bleiben historische
Staende. Aktuell 27/29 DQ-Pruefungen bestanden, keine kritischen Fehler; die zwei
Warnungen betreffen den einen Wetterwert und die zehn gespeicherten Boersenquoten.
Die auffaelligen Quoten sind aus den Trainingsaggregaten ausgeschlossen.

[Messnachweis](evidence/training-enrichment-2026-10-15.md).
Reproduktion durch Peers, Review/Commit und Kursabgabe bleiben separate Aufgaben.
