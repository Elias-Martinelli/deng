# Sprechnotizen zum Pitch (Deutsch)

Pro Folie: was du in einfachen Worten sagst. Nicht auswendig lernen - der Kern
sind die **fett** markierten Sätze. Danach die Fragen, die erfahrungsgemäss
kommen, mit kurzen Antworten.

Faustregel für alle Antworten: erst der Satz, dann die Begründung, dann die
Alternative, die wir verworfen haben. Genau das wird bewertet.

---

## Folie 1 - Titel (Elias, ca. 20 s)

"Wir bauen eine Datenpipeline rund um die Champions League. **Sie hält jeden Tag
fest, was man an diesem Tag über ein Spiel wusste.** Damit kann später ein
Modell vorhersagen, wer gewinnt."

---

## Folie 2 - Die Frage (Elias, ca. 60 s)

* "Die Frage lautet: Wer gewinnt ein Spiel? Und vor allem: **Können wir das
  fair beantworten?**"
* "Fair heisst: Das Modell darf nur Dinge benutzen, die **vor dem Anpfiff**
  bekannt waren."
* "Das Problem ist, dass die Quellen immer nur den heutigen Stand liefern. Die
  Wetterprognose von letzter Woche ist weg. Die Quote von gestern ist weg."
* "**Wer das nicht täglich speichert, hat diese Geschichte nicht.** Genau das
  Speichern ist unser Projekt. Das Modell selbst ist der Zweck, aber nicht Teil
  dieses Projekts."

---

## Folie 3 - Nutzer und Datenprodukt (Elias, ca. 50 s)

* "Hauptnutzer ist ein Data Scientist, der ein Modell trainieren will."
* "Er bekommt Tabellen, bei denen klar ist, **was eine Zeile bedeutet**: eine
  Zeile ist ein Spiel, oder ein Team in einem Spiel."
* "Das Label ist das Ergebnis. Die Merkmale sind Form, Wetter und Marktquoten -
  jeweils nur mit Informationen von vor dem Anpfiff."
* "Die geplante Tabelle `fact_match_snapshot` ist die eigentliche
  Trainingstabelle: **ein Spiel an einem Tag, mit allem, was man an dem Tag
  wusste.**"

---

## Folie 4 - Datenquellen (Noah, ca. 60 s)

* "Vier Quellen, alle gratis und dokumentiert, keine Scraper."
* "football-data.org liefert Spielplan, Resultate, Teams und Tabelle. Zehn
  Anfragen pro Minute sind erlaubt; **wir brauchen vier pro Tag.**"
* "Open-Meteo liefert die Wetterprognose, ohne Schlüssel, aber nur 16 Tage
  voraus."
* "The Odds API liefert die Quoten von rund 25 Buchmachern. Gratis sind 500
  Abrufe pro Monat, deshalb entscheidet die Pipeline selbst, wann sie einen
  ausgibt."
* "OpenStreetMap liefert die Stadion-Koordinaten, die wir fürs Wetter brauchen,
  weil die Fussball-API keine hat."

---

## Folie 5 - Daten-Eigenschaften (Noah, ca. 50 s)

* "Die Datenmenge ist klein, die Historie ist tief: **144 Spiele in der aktuellen
  Ligaphase, 189 in der letzten Saison mit K.-o.-Runden, und 47 Saisons sind
  gelistet.**"
* "Eine Saison ist eine einzige Anfrage von etwa 200 Kilobyte."
* "Wichtig fürs Modell: 2024/25 wurde das Format geändert, von Gruppenphase auf
  eine Ligaphase. Ältere Saisons sind brauchbar, das Modell muss den Unterschied
  aber kennen."
* "Und: Nicht alles ist gleich früh bekannt. Der Spielplan Monate vorher, die
  Wetterprognose 16 Tage vorher, das Resultat Minuten danach."

---

## Folie 6 - Risiken (Noah, ca. 60 s)

* "Wir haben die API gemessen, nicht geraten. Drei Beispiele:"
* "**Der Status lügt:** Fragt man nach `SCHEDULED`, kommen Zeilen zurück, die als
  `TIMED` gespeichert sind. Wir wählen kommende Spiele darum über die
  Anstosszeit."
* "**Die Summen stimmen nicht:** Siege plus Unentschieden plus Niederlagen ergibt
  nicht die Anzahl Spiele. Deshalb rechnen wir die Form selbst aus einzelnen
  Spielen."
* "**Elf von 36 Clubs** haben im Gratis-Tarif keine Liga. Darum haben wir
  entschieden: nur Champions-League-Spiele, für alle Clubs gleich."
* "Das grösste Risiko ist aber nicht technisch, sondern **Data Leakage**: Ein
  Modell, das das Spiel schon kennt, das es vorhersagen soll, sieht im Test
  perfekt aus und ist in Wirklichkeit wertlos."

---

## Folie 7 - Ingestion und Speicherung (Elias, ca. 90 s)

Das ist die wichtigste Folie für die Bewertung. Sag sie in dieser Reihenfolge:

1. "**Zuerst holen wir alles, dann transformieren wir.**"
2. "Holen heisst: Wir fragen jede Quelle und speichern die Antwort
   **unverändert** als JSON. Dazu speichern wir, wer geantwortet hat, auf welche
   Frage und an welchem Tag."
3. "Der Schlüssel ist: **eine Zeile pro Quelle, Endpunkt, Parameter und Tag.**
   Läuft derselbe Tag zweimal, wird die Zeile überschrieben statt verdoppelt.
   Darum ist ein zweiter Lauf ungefährlich."
4. "Erst danach transformieren wir, nur mit SQL: von roh zu typisierten Tabellen
   zu den fertigen Fakten und Dimensionen, alles in einer Transaktion."
5. "Warum in dieser Reihenfolge? **Weil wir so jederzeit alles neu bauen können,
   ohne die APIs noch einmal zu fragen.** Wenn wir morgen einen Rechenfehler
   finden, reicht ein neuer Transform-Lauf."
6. Zur Strategie pro Quelle: "Fussball laden wir jeden Tag komplett neu, weil es
   eine kleine Antwort ist und sich selbst repariert. Alte Saisons holen wir
   einmal, die ändern sich nicht mehr. Wetter nur für Spiele im 16-Tage-Fenster.
   Quoten nach Budget, häufiger kurz vor dem Anpfiff."

---

## Folie 8 - Architektur, die drei Stufen (Elias, ca. 60 s)

* "Die Architektur hat drei Stufen, und jede Stufe ist ein Ordner im Repository."
* "**Ingest:** pro Quelle eine kleine Python-Datei, alle nach dem gleichen
  Muster. Jede beantwortet zwei Fragen: Was soll ich holen, und wie hole ich es?"
* "**Transform:** nummerierte SQL-Dateien, die der Reihe nach laufen."
* "**Datenprodukt:** die fertigen Tabellen, die das Dashboard und später das
  Modell lesen."
* "Jeder Lauf wird protokolliert. Die Frage *hat es gestern funktioniert?* ist
  bei uns eine SQL-Abfrage, keine Suche in Logdateien."

---

## Folie 9 - Was heute schon läuft (Noah, ca. 60 s)

* "Das Bild zeigt den heutigen Stand, und alles darin existiert im Repository."
* "Lokal läuft alles in Docker Compose: die Datenbank, der Orchestrator und das
  Dashboard."
* "Der Orchestrator ist Dagster. Er startet den Tageslauf um sechs Uhr, kann
  einzelne Tage nachholen und wiederholt nur Fehler, die sich wiederholen
  lohnen."
* "Zum Ausprobieren braucht man nicht einmal einen API-Schlüssel: Wir haben echte
  Beispielantworten im Repository, damit ein fremdes Team die Pipeline sofort
  laufen lassen kann."

---

## Folie 10 - Ziel und Aufgabenteilung (beide, ca. 60 s)

* Elias: "Im Final schreibt derselbe Code die Rohdaten nach Google Cloud Storage
  und die fertigen Tabellen nach BigQuery. Terraform stellt beides bereit. Der
  lokale Weg bleibt für die Entwicklung."
* Noah: "Die Aufgaben sind geteilt, aber jeder muss alles erklären können. Ich
  habe Wetter, Stadien, Transformationen und das Dashboard, Elias Fussball,
  Orchestrierung, Docker und die Quoten."
* "Nächster Meilenstein ist der Midterm am 22. Oktober mit der lokalen Pipeline,
  danach die Cloud bis zum 10. Dezember."

---

# Fragen, die kommen - und kurze Antworten

**"Warum speichert ihr die Rohdaten überhaupt?"**
Weil die APIs nur den heutigen Stand liefern. Prognosen und Quoten werden
überschrieben, Anstosszeiten ändern sich. Unser Rohbereich ist das einzige
Archiv, das wir besitzen - und die Grundlage, um alles neu zu berechnen, ohne
die API erneut zu fragen.

**"Was passiert, wenn ihr die Pipeline zweimal am selben Tag laufen lasst?"**
Nichts Schlimmes. Der Schlüssel ist Quelle, Endpunkt, Parameter und Tag. Der
zweite Lauf überschreibt dieselbe Zeile. Wir melden sogar, ob sich die Antwort
überhaupt geändert hat.

**"Was passiert, wenn die API ausfällt?"**
Wir unterscheiden zwei Fehlerarten. Rate-Limit, Serverfehler und Netzprobleme
werden wiederholt, mit wachsendem Abstand. Ein 403 oder ein fehlender Schlüssel
wird sofort gemeldet, weil ein zweiter Versuch nichts ändert. Der Lauf wird als
fehlgeschlagen protokolliert, die alten Daten bleiben unangetastet.

**"Warum keine Echtzeit?"**
Der Anwendungsfall ist eine Vorhersage vor dem Anpfiff. Ein Tageslauf reicht,
und die Gratis-Limits erlauben nichts anderes. Nur die Quoten holen wir kurz vor
dem Anpfiff häufiger, weil sie sich dann bewegen.

**"Wie verhindert ihr Data Leakage?"**
Durch die Konstruktion. Die Form eines Teams für ein Spiel benutzt nur Spiele,
die **vor** diesem Anpfiff beendet waren. Für das Wetter gilt dasselbe: Es zählt
nur eine Prognose, die vor dem Anpfiff abgerufen wurde. Beides ist im SQL
festgelegt und wird zusätzlich unabhängig nachgerechnet.

**"Warum PostgreSQL und nicht direkt die Cloud?"**
Lokal entwickeln ist schneller und kostenlos, und das Modul verlangt PostgreSQL
lokal. Die Struktur - roh, typisiert, fertig - ist dieselbe wie später in
BigQuery, deshalb ist der Umzug ein Austausch des Ziels, kein Neubau.

**"Warum vier Quellen und nicht eine?"**
Weil die Fussball-API kein Wetter, keine Koordinaten und keine echten Quoten
liefert. Jede Quelle deckt genau eine Lücke, und jede ist gratis.

**"Wie viele Daten sind das?"**
Pro Tag unter zwei Megabyte. Eine Saison ist eine Anfrage von etwa 200 Kilobyte.
Die Tiefe kommt aus der Historie: 47 gelistete Saisons, die wir einmalig holen.

**"Was ist noch offen?"**
Die Trainingstabelle `fact_match_snapshot`, der Cloud-Pfad mit Terraform, und
die Entscheidung, wie viele Saisons wir laden. Das steht im Backlog.
