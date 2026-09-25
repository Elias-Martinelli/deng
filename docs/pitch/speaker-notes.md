# Sprechnotizen zum Pitch (Deutsch)

Pro Folie: was du sagst, in einfachen Worten. Nicht auswendig lernen - der Kern
sind die **fett** markierten Sätze. Danach die Fragen, die erfahrungsgemäss
kommen, mit kurzen Antworten.

Faustregel für jede Antwort: zuerst der Satz, dann die Begründung, dann die
Alternative, die wir verworfen haben. Genau das wird bewertet.

Drei Wörter, die du sicher erklären können musst:

* **Pipeline** - ein Programm, das jeden Tag automatisch Daten holt und ordnet.
* **Roh (raw)** - die Antwort einer Quelle, genau so gespeichert, wie sie kam.
* **Fertig (curated)** - saubere Tabellen, mit denen man direkt arbeiten kann.

---

## Folie 1 - Titel (Elias, ca. 20 s)

"Wir bauen eine Datenpipeline rund um die Champions League. **Sie hält jeden Tag
fest, was man an diesem Tag über ein Spiel wusste.** Damit kann später ein
Modell vorhersagen, wer gewinnt."

---

## Folie 2 - Der Anwendungsfall (Elias, ca. 50 s)

* "Unser Anwendungsfall ist ein Modell, das den Sieger vorhersagt. **Alles, was
  wir bauen, gibt es wegen diesem Modell.**"
* "Die Frage lautet: Wer gewinnt ein Spiel? Und vor allem: **Können wir das
  fair beantworten?**"
* "Fair heisst: Das Modell darf nur Dinge benutzen, die **vor dem Anpfiff**
  bekannt waren."
* "Das Problem: Die Quellen liefern immer nur den heutigen Stand. Die
  Wetterprognose von letzter Woche ist weg. Die Quote von gestern ist weg."
* "**Wer das nicht jeden Tag speichert, hat diese Geschichte nicht.** Genau
  dieses Speichern ist unser Projekt. Das Modell selbst ist der Zweck, aber
  nicht Teil dieses Projekts."

---

## Folie 3 - Nutzer und Datenprodukt (Elias, ca. 45 s)

* "Hauptnutzer ist ein Data Scientist, also jemand, der ein Modell trainiert."
* "Er bekommt Tabellen, bei denen klar ist, **was eine Zeile bedeutet**: eine
  Zeile ist ein Spiel, oder ein Team in einem Spiel."
* "Die wichtigste Tabelle heisst `model_features`. **Eine Zeile ist ein Spiel:
  links das Ergebnis, rechts alles, was man vor dem Anpfiff wusste.** Genau das
  liest ein Modell."
* "Das Ergebnis nennt man Label, also die Antwort, die das Modell lernen soll.
  Die Merkmale sind Form, Wetter und Quoten."
* "Im Final kommt eine Zeile pro Spiel **pro Tag** dazu. Dann kann man fragen:
  Was wusste man fünf Tage vor dem Spiel?"
* "Daneben gibt es ein Dashboard. Das ist eine Webseite, die genau diese Daten
  zeigt - damit ein Mensch sieht, was das Modell sieht."

---

## Folie 4 - Datenquellen (Noah, ca. 55 s)

* "Vier Anbieter, fünf Schritte beim Holen. Alle gratis, alle dokumentiert,
  keine Scraper - wir kratzen nichts von Webseiten ab, wir fragen offizielle
  Schnittstellen."
* "football-data.org liefert Spielplan, Resultate, Teams und Tabelle. Zehn
  Anfragen pro Minute sind erlaubt; **wir brauchen vier pro Tag.**"
* "Von derselben Quelle holen wir die Vereinswappen. Das ist ein eigener
  Schritt, weil es Bilder sind und keine Zahlen. Jedes Wappen holen wir genau
  einmal."
* "Open-Meteo liefert die Wetterprognose, ganz ohne Schlüssel, aber nur 16 Tage
  im Voraus."
* "The Odds API liefert die Quoten von rund 25 Buchmachern. Gratis sind 500
  Abrufe pro Monat. Darum entscheidet die Pipeline selbst, wann sie einen
  ausgibt."
* "OpenStreetMap liefert die Stadion-Koordinaten. Die brauchen wir fürs Wetter,
  weil die Fussball-Schnittstelle keine hat."

---

## Folie 5 - Wie die Daten aussehen (Noah, ca. 55 s)

* "**Wenig Daten, aber viel Geschichte.** Und die Zahlen haben wir gemessen,
  nicht geschätzt."
* "Die aktuelle Ligaphase hat 144 Spiele. Davon sind erst wenige gespielt - für
  ein Modell ist das viel zu wenig."
* "**Darum holen wir alte Saisons.** Die Saison 2023/24 hat 125 Spiele, die
  Saison 2024/25 hat 189 Spiele. Und die Schnittstelle listet 47 Saisons auf."
* "Eine Saison ist **eine einzige Anfrage** von etwa 200 Kilobyte. Das ist
  weniger als ein Foto."
* "Mit zwei alten Saisons zusätzlich haben wir heute **458 Spiele, 60 Vereine,
  und 332 Spiele mit Resultat** - das sind die, mit denen man trainieren kann."
* "Ein Detail fürs Modell: 2024/25 wurde das Format geändert, von Gruppenphase
  auf eine einzige Ligaphase. Alte Saisons sind brauchbar, das Modell muss den
  Unterschied aber kennen."
* "Und: Nicht alles ist gleich früh bekannt. Der Spielplan Monate vorher, das
  Wetter 16 Tage vorher, das Resultat Minuten danach."

---

## Folie 6 - Risiken (Noah, ca. 50 s)

* "Wir haben die Schnittstelle getestet, nicht geraten. Drei Beispiele:"
* "**Der Status lügt:** Fragt man nach Spielen mit Status `SCHEDULED`, kommen
  Zeilen zurück, die als `TIMED` gespeichert sind. Wir wählen kommende Spiele
  darum über die Anstosszeit."
* "**Die Summen stimmen nicht:** Siege plus Unentschieden plus Niederlagen
  ergibt nicht die Anzahl Spiele. Deshalb rechnen wir die Form selbst aus den
  einzelnen Spielen."
* "**Die Stadionsuche lag daneben:** Beim ersten Versuch landete Napoli in
  Novara und Roma in Turin. Wir haben jede Koordinate einmal von Hand geprüft.
  Das Urteil steht in der Datenbank neben der unveränderten Antwort."
* "Dazu kommen die Gratis-Limits: zehn Anfragen pro Minute, 500 Quoten-Abrufe
  pro Monat. Damit muss die Pipeline umgehen können."
* "Das grösste Risiko ist aber nicht technisch, sondern **Data Leakage**. Das
  heisst: Das Modell sieht schon Informationen von nach dem Spiel. Dann sieht es
  im Test perfekt aus und ist in Wirklichkeit wertlos."

---

## Folie 7 - Wie wir holen und speichern (Elias, ca. 85 s)

Das ist die wichtigste Folie für die Bewertung. Sag sie in dieser Reihenfolge:

1. "**Zuerst holen wir alles, dann rechnen wir.**"
2. "Holen heisst: Wir fragen jede Quelle und speichern die Antwort
   **unverändert**. Dazu merken wir uns: wer hat geantwortet, auf welche Frage,
   an welchem Tag."
3. "Der Schlüssel ist: **eine Zeile pro Quelle, Frage und Tag.** Läuft derselbe
   Tag zweimal, wird dieselbe Zeile überschrieben statt verdoppelt. Darum ist
   ein zweiter Lauf ungefährlich."
4. "Erst danach rechnen wir, nur mit SQL: von roh zu sauberen Tabellen zu den
   fertigen Tabellen - alles in einem Schritt, der entweder ganz klappt oder gar
   nicht."
5. "Warum in dieser Reihenfolge? **Weil wir so jederzeit alles neu bauen können,
   ohne die Quellen noch einmal zu fragen.** Finden wir morgen einen
   Rechenfehler, reicht ein neuer Rechenlauf."
6. Zur Strategie pro Quelle: "Fussball laden wir jeden Tag komplett neu, weil es
   eine kleine Antwort ist und sich dabei selbst repariert. **Alte Saisons holen
   wir einmal - zwei Anfragen pro Saison, dann nie wieder, weil eine fertige
   Saison sich nicht mehr ändert.** Wetter nur für Spiele in den nächsten 16
   Tagen. Quoten nach Budget, häufiger kurz vor dem Anpfiff. Koordinaten einmal
   pro Verein."

---

## Folie 8 - Die drei Stufen (Elias, ca. 85 s)

**Das ist die Hauptfolie. Nimm dir hier am meisten Zeit.**

* "Dieses Bild ist das ganze Projekt. Es hat drei Stufen, und **jede Stufe ist
  ein Ordner im Repository.**"
* "**Erstens Holen:** pro Quelle eine kleine Python-Datei, alle nach dem
  gleichen Muster. Jede beantwortet nur zwei Fragen: Was soll ich holen, und wie
  hole ich es?"
* "**Zweitens Rechnen:** nummerierte SQL-Dateien, die der Reihe nach laufen. SQL
  ist die Sprache, mit der man Tabellen abfragt und baut."
* "**Drittens das Datenprodukt:** die fertigen Tabellen, die das Dashboard heute
  und ein Modell später liest."
* "Eine Regel hält das Bild zusammen: **Das Holen darf nur die Quellen und die
  Rohdaten lesen, nie die fertigen Tabellen.** Wir haben dafür einen Test
  geschrieben - hält sich jemand nicht daran, schlägt der Test fehl."
* "Jeder Lauf wird protokolliert. Die Frage *hat es gestern funktioniert?* ist
  bei uns eine kurze Abfrage, keine Suche in Logdateien."

---

## Folie 9 - Was heute schon läuft (Noah, ca. 45 s)

* "Dieses Bild zeigt dasselbe genauer, und **alles darin existiert im
  Repository.** Die Tabelle daneben sagt, wo."
* "Links die fünf Dateien, eine pro Quelle. In der Mitte eine einzige Datei, die
  sie der Reihe nach startet."
* "Die Datenbank hat drei Bereiche: roh, sauber, fertig. Elf Dateien bauen die
  Tabellen, dreizehn Dateien rechnen."
* "Lokal läuft alles in Docker Compose. Das heisst: Datenbank, Steuerung und
  Dashboard starten zusammen mit einem Befehl, auf jedem Rechner gleich."
* "Die Steuerung ist Dagster. Sie startet den Lauf jeden Tag um sechs Uhr, kann
  einzelne Tage nachholen und wiederholt Fehler, bei denen sich ein zweiter
  Versuch lohnt."
* "Zum Ausprobieren braucht man nicht einmal einen Schlüssel: Wir haben echte
  Beispiel-Antworten im Repository. **Ein fremdes Team tippt zwei Befehle und
  die Pipeline läuft.**"

---

## Folie 10 - Ziel und Aufgabenteilung (beide, ca. 50 s)

* Elias: "**Das ist unser Ziel.** Im Final schreibt derselbe Code die Rohdaten
  in einen Google-Cloud-Speicher und die fertigen Tabellen nach BigQuery. Das
  ist die Datenbank von Google für grosse Auswertungen."
* Elias: "Terraform stellt beides automatisch bereit - man klickt nichts von
  Hand zusammen, sondern beschreibt es in einer Datei."
* Elias: "Wichtig: **Die Quellen und das SQL bleiben gleich.** Es wechselt nur
  das Ziel. Der lokale Weg bleibt zum Entwickeln."
* Noah: "Die Aufgaben sind geteilt, aber jeder muss alles erklären können. Ich
  habe Wetter, Stadien, die Rechenschritte und das Dashboard. Elias hat
  Fussball, alte Saisons, Steuerung, Docker und die Quoten. Die Cloud machen
  wir zusammen."
* "Nächster Meilenstein ist der Midterm am 22. Oktober mit der lokalen Pipeline,
  danach die Cloud bis zum 10. Dezember."

---

# Fragen, die kommen - und kurze Antworten

**"Warum speichert ihr die Rohdaten überhaupt?"**
Weil die Quellen nur den heutigen Stand liefern. Prognosen und Quoten werden
überschrieben, Anstosszeiten ändern sich. Unser Rohbereich ist das einzige
Archiv, das wir besitzen - und die Grundlage, um alles neu zu rechnen, ohne die
Quelle erneut zu fragen.

**"Was passiert, wenn ihr die Pipeline zweimal am selben Tag laufen lasst?"**
Nichts Schlimmes. Der Schlüssel ist Quelle, Frage und Tag. Der zweite Lauf
überschreibt dieselbe Zeile. Wir melden sogar, ob sich die Antwort überhaupt
geändert hat.

**"Was passiert, wenn eine Quelle ausfällt?"**
Wir unterscheiden zwei Fehlerarten. Zu viele Anfragen, Serverfehler und
Netzprobleme werden wiederholt, mit wachsendem Abstand. Ein gesperrter Zugriff
oder ein fehlender Schlüssel wird sofort gemeldet, weil ein zweiter Versuch
nichts ändert. Der Lauf wird als fehlgeschlagen protokolliert, die alten Daten
bleiben unangetastet.

**"Warum keine Echtzeit?"**
Der Anwendungsfall ist eine Vorhersage vor dem Anpfiff. Ein Lauf pro Tag reicht,
und die Gratis-Limits erlauben ohnehin nicht mehr. Nur die Quoten holen wir kurz
vor dem Anpfiff häufiger, weil sie sich dann bewegen.

**"Wie verhindert ihr Data Leakage?"**
Durch die Konstruktion. Die Form eines Teams für ein Spiel benutzt nur Spiele,
die **vor** diesem Anpfiff fertig waren. Beim Wetter zählt nur eine Prognose,
die vor dem Anpfiff geholt wurde. Beides steht so im SQL. Das Dashboard rechnet
diese Regeln zusätzlich aus den Tabellen nach, statt sie nur zu behaupten.

**"Warum holt ihr alte Saisons - reicht die laufende nicht?"**
Nein. Die laufende Ligaphase hat 144 Spiele, und erst wenige davon sind
gespielt. Ein Modell braucht Beispiele mit bekanntem Ausgang. Eine fertige
Saison kostet zwei Anfragen, ändert sich nie mehr und bringt 125 bis 189 Spiele.
Welche Saisons wir laden, steht in einer Einstellung - eine Zeile ändern, fertig.

**"Sind alte Saisons überhaupt vergleichbar?"**
Teilweise. 2024/25 wurde das Format geändert. Wir speichern darum zu jedem Spiel
die Saison, damit ein Modell die Formate unterscheiden kann. Wir werfen nichts
weg und tun auch nicht so, als wäre alles gleich.

**"Warum PostgreSQL und nicht direkt die Cloud?"**
Lokal entwickeln ist schneller und kostenlos, und das Modul verlangt PostgreSQL
lokal. Der Aufbau - roh, sauber, fertig - ist derselbe wie später in BigQuery.
Der Umzug ist darum ein Wechsel des Ziels, kein Neubau.

**"Warum vier Anbieter und nicht einer?"**
Weil die Fussball-Schnittstelle kein Wetter, keine Koordinaten und keine echten
Quoten liefert. Jede Quelle schliesst genau eine Lücke, und jede ist gratis.

**"Wie viele Daten sind das?"**
Pro Tag unter zwei Megabyte. Eine Saison ist eine Anfrage von etwa 200 Kilobyte.
Die Tiefe kommt aus der Geschichte: 47 gelistete Saisons, die wir einmalig
holen könnten.

**"Was ist noch offen?"**
Die Tabelle mit einer Zeile pro Spiel **pro Tag**, der Cloud-Weg mit Terraform,
und die Entscheidung, wie viele alte Saisons wir am Ende laden. Das steht im
Backlog.
