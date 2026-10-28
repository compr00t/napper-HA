# Napper Baby-Schlaftracker für Home Assistant (HACS)

Diese benutzerdefinierte Home Assistant Integration verbindet dein **Napper**-Konto (`https://api.napper.app`) mit Home Assistant – komplett auf **Deutsch** und inklusive der originalgetreuen **Napper Kreis-Ansicht** (`custom:napper-circle-card`).

---

## Funktionen

- **Vollständige Kreis-Ansicht (`custom:napper-circle-card`)** wie in der Napper-App:
  - Startet bei der **Aufwachzeit** (getrackt oder erwartet) unten links.
  - Zeigt jedes **Nickerchen** (1. bis 4. Nickerchen) als Segment auf dem Kreisbogen mit **Startzeit**, **Endzeit** und **Schlafdauer** (getrackt, aktiv oder erwartet).
  - Endet bei der **Schlafenszeit** (getrackt oder erwartet) unten rechts.
  - Zeigt in der Mitte den **Countdown zum nächsten Ereignis** (z. B. *„Drittes Nickerchen in 44 min – Um 17:07“*, *„Aufwachen in …“* oder *„Schlafenszeit in …“*).
  - Zeigt unten auf dem Bogen die aktuelle **Wachzeit** (z. B. `1h 56m`) sowie die **aktuelle Uhrzeit-Markierung** auf dem Kreis.
  - Tab-Umschalter für mehrere Kinder (z. B. *Kind 1* & *Kind 2*).
- **Aktionen sofort, mit `Zeitdifferenz` oder zu einer absoluten `Uhrzeit` (z. B. `17:37`)**:
  - **Aufwachen** (beendet das aktuell laufende Nickerchen oder den Nachtschlaf – **nur aktiv, wenn das Kind gerade schläft**)
  - **Nickerchen starten** (startet ein Nickerchen – **nur aktiv, wenn das Kind aktuell nicht schläft**)
  - **Schlafen starten** (startet den Nachtschlaf – **nur aktiv, wenn das Kind aktuell nicht schläft**)
  - Alle drei Buttons arbeiten sowohl mit der `number`-Entität **`Zeitdifferenz`** (`0–360 min`) als auch mit der `text`-Entität **`Uhrzeit`** (z. B. `17:37`), über die Eingabefelder in der Karte oder per Service-Aufruf (`minutes_ago` bzw. `time`).
- **Komplett auf Deutsch**: Alle Entitätsnamen, Zustände, Attribute, Buttons, Services und die Lovelace-Karte sind auf Deutsch.

---

## Installation über HACS

1. Öffne **HACS** in Home Assistant.
2. Klicke oben rechts auf das **Drei-Punkte-Menü (⋮)** → **Benutzerdefinierte Repositories** (*Custom repositories*).
3. Füge die URL deines Git-Repositories ein und wähle als Kategorie **Integration** (bzw. *Integration*).
4. Suche in HACS nach **Napper** und klicke auf **Herunterladen**.
5. **Starte Home Assistant neu.**

### Manuelle Installation (ohne Git/HACS)
Kopiere den Ordner `custom_components/napper` in das Verzeichnis `<config>/custom_components/napper` deiner Home Assistant Installation und starte Home Assistant neu.

---

## Einrichtung in Home Assistant

1. Gehe zu **Einstellungen** → **Geräte & Dienste** → **Integration hinzufügen**.
2. Suche nach **Napper**.
3. Gib deine **Napper-E-Mail-Adresse** ein und bestätige anschließend den **6-stelligen Einmalcode (OTP)**, der dir per E-Mail zugesendet wird.

Für jedes Kind in deinem Napper-Konto wird automatisch ein eigenes Gerät angelegt.

---

## Entitäten pro Kind (Beispiel: `Max`)

| Plattform | Entität (Beispiel) | Beschreibung | Beispiel-Zustand |
| :--- | :--- | :--- | :--- |
| `sensor` | `sensor.max_nachstes_ereignis` | **Nächstes Ereignis** als Home Assistant Zeitstempel (`timestamp`), wird im Dashboard automatisch als *„in 2 Stunden“* bzw. *„3. November 2026 um 07:00“* dargestellt (enthält außerdem alle Kreis-Daten für die Karte) | `in 45 Minuten` (`2026-11-03T07:00:00+01:00`) |
| `sensor` | `sensor.max_countdown_nachstes_ereignis` | **Countdown nächstes Ereignis** in Minuten | `45 min` |
| `sensor` | `sensor.max_schlafstatus` | Aktueller **Schlafstatus** | `Wach`, `Nickerchen`, `Nachtschlaf` |
| `sensor` | `sensor.max_aufwachzeit` | **Aufwachzeit** am Morgen | `07:00` |
| `sensor` | `sensor.max_1_nickerchen` .. `4_nickerchen` | **1. bis 4. Nickerchen** (Start–Ende & Dauer) | `17:00 – 17:30 (30 Min.)` |
| `sensor` | `sensor.max_schlafenszeit` | **Schlafenszeit** am Abend | `19:30` |
| `sensor` | `sensor.max_wachzeit` | Aktuelle **Wachzeit** seit dem letzten Aufwachen | `2 Std. 00 Min.` |
| `sensor` | `sensor.max_tagesschlaf` | **Tagesschlaf** in Minuten | `135 min` |
| `binary_sensor` | `binary_sensor.max_schlaft_gerade` | **Schläft gerade** (`on` / `off`) | `off` |
| `number` | `number.max_zeitdifferenz` | **Zeitdifferenz** in Minuten für den nächsten Button-Klick (`0–360 min`, setzt sich nach Klick automatisch auf `0` zurück) | `0 min` |
| `text` | `text.max_uhrzeit` | **Uhrzeit** (absolut im Format `HH:MM`, z. B. `17:37`) für den nächsten Button-Klick (leert sich nach Klick automatisch) | `17:37` |
| `button` | `button.max_aufwachen` | **Aufwachen** – beendet ein laufendes Nickerchen oder den Nachtschlaf (nutzt `Uhrzeit` oder `Zeitdifferenz`; nur aktiv, wenn das Kind gerade schläft) | – |
| `button` | `button.max_nickerchen_starten` | **Nickerchen starten** (nutzt `Uhrzeit` oder `Zeitdifferenz`; nur aktiv, wenn das Kind nicht schläft) | – |
| `button` | `button.max_schlafen_starten` | **Schlafen starten** – startet den Nachtschlaf (nutzt `Uhrzeit` oder `Zeitdifferenz`; nur aktiv, wenn das Kind nicht schläft) | – |

---

## Lovelace Kreis-Karte (`custom:napper-circle-card`)

Die Integration registriert das Frontend-Modul `/napper_static/napper-circle-card.js` beim Start von Home Assistant **automatisch**.

### Automatisch alle Kinder anzeigen (mit Tab-Umschalter oben)

Füge auf deinem Dashboard eine **Manuelle Karte** mit folgendem YAML hinzu:

```yaml
type: custom:napper-circle-card
```

### Nur ein bestimmtes Kind anzeigen (Einzelkarte pro Kind)

Du kannst im visuellen Karten-Editor einfach das gewünschte Kind im Dropdown auswählen oder im YAML `baby` (Name des Kindes), `entity` oder `baby_id` angeben. Bei einer Einzelkarte werden die Tab-Umschalter für andere Kinder automatisch ausgeblendet:

```yaml
type: custom:napper-circle-card
baby: "Max"
```

*(Alternativ funktionieren auch `entity: sensor.max_nachstes_ereignis` oder `baby_id: "<DEINE_BABY_ID>"`.)*

---

## Home Assistant Aktionen (Services)

Alle drei Services akzeptieren unter `baby_id` entweder die **Baby-ID** oder einfach den **Namen des Kindes** (z. B. `"Max"`) sowie optional `time` (absolute Uhrzeit wie `"17:37"`) oder `minutes_ago` (Zeitdifferenz in Minuten; falls beides leer/0 ist, werden die Entitäten `text.<kind>_uhrzeit` bzw. `number.<kind>_zeitdifferenz` verwendet):

### 1. Aufwachen (beendet Nickerchen oder Nachtschlaf – nur wenn das Kind schläft)
```yaml
action: napper.wake_up
data:
  baby_id: "Max"
  time: "17:37"
```

### 2. Nickerchen starten (nur wenn das Kind nicht schläft)
```yaml
action: napper.start_nap
data:
  baby_id: "Max"
  minutes_ago: 15
```

### 3. Schlafen starten (Nachtschlaf starten – nur wenn das Kind nicht schläft)
```yaml
action: napper.start_sleep
data:
  baby_id: "Max"
  time: "19:30"
```
