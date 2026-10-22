# Fragen und kurze Antworten

Die Fragen, die wir zum Pitch und in den mündlichen Verteidigungen erwarten,
mit kurzen Antworten auf Deutsch. Sie beschreiben das Repository, nicht nur den
Pitch vom 1. Oktober: Zahlen und Quellen sind die der Pipeline, wie sie heute
läuft.

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

**"Warum ladet ihr jeden Tag alles neu statt nur die Änderungen?"**
Weil die Antwort klein und begrenzt ist: eine Anfrage, 212 Kilobyte, das ganze
Turnier. Nur die Änderungen zu holen würde eine zusätzliche Anfrage kosten, um
überhaupt zu erfahren, *was* sich geändert hat - und es würde die Spiele
übersehen, die die Schnittstelle **dazufügt**, etwa nach der Auslosung im
Dezember. Ein Volllauf heilt sich ausserdem selbst: ein verpasster Tag ist am
nächsten Tag wieder ausgeglichen. Genau dort, wo inkrementell richtig ist,
machen wir es auch inkrementell: alte Saisons einmal, Wappen einmal pro Adresse,
Stadien einmal pro Verein. Die Regel ist also nicht "immer voll", sondern "voll,
solange die Antwort klein und veränderlich ist".

**"Was passiert bei hundertmal so vielen Daten?"**
Die Ingestion bleibt, wie sie ist - sie ist durch die Gratis-Limits begrenzt,
nicht durch unsere Technik: zehn Anfragen pro Minute heisst, hundert Saisons
brauchen rund zwanzig Minuten, einmalig. Der Engpass wandert in die
Transformation, denn die baut die Tabellen heute komplett neu. Bei hundertmal
mehr Daten würden wir pro Saison beziehungsweise pro Tag partitionieren und nur
die betroffene Partition neu rechnen; der Rohbereich hat den Tag schon als
Schlüssel, die Struktur dafür steht also. In BigQuery wäre es dieselbe Idee mit
Partitionierung nach Datum. Ehrlich gesagt: gemessen haben wir das nicht, wir
haben es hergeleitet - heute sind es 458 Spiele, das ist für PostgreSQL nichts.

**"Warum Dagster und nicht Airflow?"**
Wegen der Backfills und wegen der Grösse. Unser Denkmodell ist "ein Lauf pro
Tag", und genau das ist in Dagster eine Partition: einen Zeitraum nachzuholen
ist ein Knopf, keine selbstgeschriebene Schleife. Dazu kommt der Aufwand im
Container: Dagster sind zwei Dienste neben unserer bestehenden Datenbank,
Airflow wären mindestens vier plus Warteschlange. Airflow ist der Industrie-
Standard, das ist der Nachteil unserer Wahl - aber wir müssen es in zehn
Minuten erklären können, und Dagsters Assets sind eins zu eins unsere Tabellen.
Der Vergleich mit vier Werkzeugen steht in ADR-002.

**"Wie wisst ihr, ob die Daten stimmen?"**
Wir behaupten es nicht, wir prüfen es nach jedem Lauf: 24 Prüfungen, deren
Ergebnis in der Datenbank landet. Sechzehn davon sind kritisch und brechen den
Lauf ab - zum Beispiel, wenn ein Formwert ein Spiel benutzt, das nach dem
Anpfiff lag. Acht sind Warnungen und bleiben sichtbar, etwa ein Verein ohne
Stadion. Wir haben das absichtlich nicht auf eine Folie genommen, weil es
Milestone 1 nicht verlangt - erklären können wir es.

**"Dürft ihr diese Daten überhaupt verwenden?"**
Ja, und wir haben es pro Quelle nachgelesen: Open-Meteo steht unter CC BY 4.0,
OpenStreetMap unter ODbL - beide verlangen Namensnennung, die im Repository
steht. Die Fussball-Schnittstelle und die Quoten nutzen wir im Gratis-Tarif für
Lern- und Evaluationszwecke, mit Schlüsseln, die nie im Repository liegen. Wir
scrapen nichts und wir veröffentlichen die Daten nicht weiter.
