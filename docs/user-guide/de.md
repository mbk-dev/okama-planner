# Benutzerhandbuch

[English](en.md) · [Русский](ru.md) · [Deutsch](de.md) · [Español](es.md) · [中文](zh.md)

## Installation und erster Lauf

okama Planner erstellt monatliche Haushaltszahlungsströme und Monte-Carlo-Prognosen. Python ab Version 3.11 wird unterstützt. Installieren Sie die Erweiterung `reports` für Excel-Exporte. Die Entwicklungskonfiguration verwendet Python 3.14; wählen Sie diesen Interpreter ausdrücklich aus, wenn Sie am Code arbeiten:

```bash
git clone https://github.com/mbk-dev/okama-planner.git
cd okama-planner
poetry env use python3.14
poetry install --extras reports
poetry run python examples/localized_plan.py --output-dir tmp/localized-example
```

Das Beispiel benötigt weder Marktdatenabrufe noch einen Browser oder eine Kundendatenbank. Es verwendet fiktive USD-Beträge und festgeschriebene synthetische Monatsrenditen. Es berechnet die Prognose einmal mit `seed=42`, speichert `request.json` und `result.json` und erstellt anschließend `plan-en.xlsx`, `plan-ru.xlsx`, `plan-de.xlsx`, `plan-es.xlsx`, `plan-zh.xlsx` sowie interaktive, offline nutzbare Dateien `forecast.html` in den Verzeichnissen `linear/` und `log/` jeder Sprache. Öffnen Sie eine HTML-Datei lokal, um Portfolio und Nettokapital zu untersuchen. Alle fünf Ausgaben enthalten dieselben USD-Beträge, Annahmen und Zahlenwerte. Ein Startwert fixiert keine Abhängigkeiten: Bewahren Sie die Umgebungsversionen für eine genaue Wiederholung auf.

Mit `--languages en de` wählen Sie einzelne Ausgaben aus. Ergänzen Sie `--image-format png` oder `--image-format svg`, um bei installiertem Chrome oder Chromium statische Grafiken zu erzeugen; `--browser-executable /path/to/chromium` legt die ausführbare Browserdatei fest. HTML und Excel benötigen keinen Browser.

## Einen Plan erstellen

Beginnen Sie mit [der fiktiven Anfrage](../../examples/baseline-request.json). Übergeben Sie die vollständige Anfrage an `forecast(request)` aus `okama_planner`. `plan.t0` bezeichnet den ersten Monat; geben Sie Planungshorizont, Rentenbeginn, Vermögen, Verbindlichkeiten sowie monatliche Einnahmen und Ausgaben an. Definieren Sie für jedes Ziel eine eindeutige `goal_id`, die Bezeichnung `label`, den Typ `kind`, den heutigen Betrag `amount_pv`, das Bewertungsjahr `pv_year` und den Zieltermin. Zinssätze und Wahrscheinlichkeiten sind Bruchteile: `0.02` bedeutet 2 %. Einnahmen und Ausgaben werden als positive Beträge eingegeben; das Zahlungsjournal versieht Ausgaben mit einem negativen Vorzeichen.

`currency="USD"` legt die Rechenwährung fest. `language="de"` in `export_report` oder `export_charts` wählt die deutsche Darstellung. Die Sprache rechnet kein Geld um und verändert weder Inflation noch Portfoliorenditen oder rechtliche Annahmen. Benutzerbezeichnungen bleiben unverändert; übersetzen Sie sie selbst für eine andere Ausgabe. Der [Lokalisierungsvertrag](../localization.md) erläutert unterstützte Meldungen, Formate und die Spracheinstellung beim MCP-Start.

Anfragen mit einer Währung verwenden eine einzige Währung. Mehrwährungsanfragen definieren ausdrücklich `reporting_currency`, native `currency_groups` und Wechselkursannahmen. Übersetzte Berichte erhalten die Währungen der Gruppen und die Berichtswährung. Siehe [Mehrwährungsplanung](../multicurrency.md) und [Portfoliomodi](../portfolio-modes.md). Die Lokalisierung ergänzt weder fehlende Steuern und Gebühren noch nicht unterstützte gamma/alpha-Felder in der Prognoseanfrage.

## Ergebnisse lesen und aufbewahren

Beträge in Berichten und Grafiken sind nominal; die Indexierung folgt den vorgegebenen Sätzen. Inflation führt nicht automatisch zu einer Darstellung in konstanter Kaufkraft. Auf logarithmischen Achsen werden null und negative Werte ausgelassen; betroffene Bänder weisen Lücken auf. Prüfen Sie diese Zeiträume in der linearen Grafik.

Exporte verwenden gespeicherte Anfrage- und Ergebnisschnappschüsse ohne erneute Prognose:

```python
import json
from pathlib import Path
from okama_planner.reports import export_report
from okama_planner.charts import export_charts

folder = Path("tmp/localized-example")
request = json.loads((folder / "request.json").read_text())
result = json.loads((folder / "result.json").read_text())
export_report([{"label": "Synthetic USD", "request": request, "result": result}],
              folder / "review.xlsx", language="de")
export_charts(result, folder / "review", language="de")
```

Das Bearbeiten von Zahlen in der Arbeitsmappe berechnet Monte Carlo nicht neu. Ändern Sie die Eingaben, führen Sie `forecast` erneut aus und speichern Sie neue Schnappschüsse vor dem Export eines geänderten Plans. Berechnen Sie Excel-Zusammenfassungsformeln neu, bevor Sie zwischengespeicherte Formelwerte verwenden. Bewahren Sie Original-JSON und Herkunftsinformationen zusammen mit den Exporten auf.

## Lokale Daten und Datenschutz

Das optionale SQLite-Register speichert Kunden, Planversionen, Szenarien und Ergebnisse lokal. Namen und Kontaktdaten gehören ins Register; verwenden Sie in gemeinsam genutzten Materialien Kundencodes. Halten Sie Datenbanken und echte Kundendokumente außerhalb öffentlicher Git-Repositories. Die Lokalisierung verändert Anzeigetexte; SQL-Tabellen- und Spaltennamen, JSON-Schlüssel, Aufzählungswerte und technische Kennungen bleiben stabil. Siehe [Datenspeicherung](../storage.md) für Einrichtung und API-Beispiele.
