# Sprechnotizen · Initial project pitch · 1. Oktober 2026

Kurze Notizen zu den acht Folien der
[PowerPoint-Präsentation](initial-project-pitch-2026-10-01.pptx).
Reihenfolge und Umfang entsprechen dieser Präsentation.

## 1 · Champions League Match Intelligence

Wir speichern jeden Tag, was über ein Spiel bekannt war. Diese Daten sollen
später ein Modell ermöglichen, das den Spielausgang vorhersagt.

## 2 · Wer gewinnt — und lässt sich das fair vorhersagen?

Ein Modell darf nur Informationen verwenden, die vor dem Anpfiff bekannt waren.
Spieltermine können sich verschieben, Tabelle und Form ändern sich nach jedem
Spieltag. Wetterprognosen reichen höchstens 16 Tage voraus und werden laufend
ersetzt. Deshalb müssen wir den jeweiligen Stand selbst speichern.

## 3 · Nutzer und Datenprodukt

Unser Hauptnutzer ist ein Data Scientist, der ein Modell trainiert und testet.
Das Datenprodukt enthält eine Zeile pro Spiel: das Resultat als Zielwert sowie
Form und Wetterprognose als Merkmale. Ein Dashboard macht dieselben Daten für
Menschen sichtbar.

## 4 · Drei kostenlose Quellen, vier Ingestion-Schritte

football-data.org liefert Spiele, Resultate, Tabelle und Vereinswappen.
Open-Meteo liefert die Wetterprognose zur Anstosszeit. OpenStreetMap liefert
Stadionkoordinaten, die wir einmal pro Verein ermitteln. Die Quellen sind
dokumentiert; wir benötigen kein Scraping. Die Abrufe berücksichtigen die
jeweiligen Grenzen der kostenlosen Angebote.

## 5 · Risiken

Wir wählen kommende Spiele über die Anstosszeit, weil der Statusfilter
unzuverlässig ist. Die Form berechnen wir aus einzelnen Spielen, weil Summen der
Quelle nicht immer stimmen. Stadionkoordinaten werden von Hand geprüft.
Abrufpausen und Wiederholungen berücksichtigen die Zugriffslimits.

Das grösste Risiko ist Data Leakage: Informationen aus dem vorherzusagenden
Spiel dürfen nicht schon in dessen Eingangsmerkmalen stecken.

## 6 · Architektur v0.1 — drei Stufen

Die drei Stufen anhand des Diagramms auf der Folie erklären. Die zentrale
Trennungsregel lautet: Die Ingestion liest keine transformierten Tabellen.
Ein Test prüft diese Regel.

## 7 · Ziel und Aufgabenteilung

Fussballdaten und vergangene Saisons übernehmen wir gemeinsam. Elias kümmert
sich um Wetter, Stadien, Dashboard und Notebook. Noah übernimmt Transformationen,
Datenmodell, Orchestrierung, Docker und CI. Die Cloud mit Terraform und BigQuery
bearbeiten wir gemeinsam. Jeder Pull Request wird vom anderen geprüft.

Zum Midterm am 22. Oktober steht die lokale Pipeline im Mittelpunkt, zum Final
am 10. Dezember die Cloud-Pipeline.

## 8 · Fragen

Für die Aufmerksamkeit danken und die Fragerunde öffnen.
