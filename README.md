# Napper Baby-Schlaftracker für Home Assistant (HACS)

Diese benutzerdefinierte Home Assistant Integration verbindet dein **Napper**-Konto (`https://api.napper.app`) mit Home Assistant – komplett auf **Deutsch** und inklusive der **Napper Schlafplan-Karte** (`custom:napper-card`).

---

## Funktionen

- **Napper Schlafplan-Karte (`custom:napper-card`)**:
  - Zeigt die vertikale Tages-Timeline mit **Aufwachzeit**, allen geplanten/getrackten **Nickerchen** (`1. Nickerchen`, `2. Nickerchen`, … – ohne ungeplante Einträge) sowie der **Schlafenszeit**.
  - Vergangene (getrackte) Ereignisse werden mit ihrer tatsächlichen Zeit und Dauer dargestellt, zukünftige Vorhersagen kursiv mit erwarteter Dauer (`~30m`).
  - Der **aktuelle Zeitpunkt** wird auf der Timeline visuell hervorgehoben (pulsierender `Jetzt`-Marker zwischen vergangenen und zukünftigen Ereignissen bzw. Hervorhebung des aktuell laufenden Schlafs).
  - Untere Aktionsleiste mit den drei Buttons **Aufwachen**, **Nickerchen** und **Schlafen**.
  - Unterstützt sowohl eine gemeinsame Karte (mit Kinder-Umschalter) als auch eine Einzelkarte pro Kind (`baby: "Max"`).
- **Aktionen sofort, mit `Zeitdifferenz` (`0–30 min`) oder zu einer absoluten `Uhrzeit` (z. B. `17:37`)**:
  - **Nickerchen** (startet ein Nickerchen – aktiv, wenn das Kind wach ist)
  - **Nickerchen pausieren** / **Nickerchen fortsetzen** (pausiert ein aktives Nickerchen bzw. setzt es fort)
  - **Schlafen** (startet die **Einschlafbegleitung** vor dem Nachtschlaf – aktiv, wenn das Kind wach ist)
  - **Eingeschlafen** (beendet die Einschlafbegleitung und startet den eigentlichen **Nachtschlaf**)
  - **Schlafen pausieren** / **Schlafen fortsetzen** (startet bzw. beendet ein nächtliches Aufwachen während des Nachtschlafs)
  - **Aufwachen** (beendet das aktuell laufende Nickerchen oder den Nachtschlaf)
  - Alle Buttons arbeiten sowohl mit dem **`Zeitdifferenz`**-Schieberegler (`number`, `0–30 min`) als auch mit der **`Uhrzeit`**-Auswahl (`time`, z. B. `17:37`, springt nach zwei Ziffern in `hh` automatisch in das `mm`-Feld) oder per Service-Aufruf (`minutes_ago` bzw. `time`).
- **Exakte API-Zeitstempel**: Zustandsänderungen (z. B. `Schlafstatus`, `Schläft gerade` u. a.) übernehmen den tatsächlichen Zeitpunkt aus der Napper-API (z. B. *„vor 10 Minuten“*, wenn ein Nickerchen in der App rückwirkend eingetragen wurde).
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
| `sensor` | `sensor.max_schlafstatus` | Aktueller **Schlafstatus** (mit exaktem API-Zeitstempel) | `Wach`, `Nickerchen`, `Einschlafbegleitung`, `Nachtschlaf` |
| `sensor` | `sensor.max_aufwachzeit` | **Aufwachzeit** am Morgen | `07:00` |
| `sensor` | `sensor.max_1_nickerchen` .. `4_nickerchen` | **1. bis 4. Nickerchen** (Start–Ende & Dauer) | `17:00 – 17:30 (30 Min.)` |
| `sensor` | `sensor.max_schlafenszeit` | **Schlafenszeit** am Abend | `19:30` |
| `sensor` | `sensor.max_wachzeit` | Aktuelle **Wachzeit** seit dem letzten Aufwachen | `2 Std. 00 Min.` |
| `sensor` | `sensor.max_tagesschlaf` | **Tagesschlaf** in Minuten | `135 min` |
| `binary_sensor` | `binary_sensor.max_schlaft_gerade` | **Schläft gerade** (`on` / `off`) | `off` |
| `number` | `number.max_zeitdifferenz` | **Zeitdifferenz** (Schieberegler `0–30 min`) für den nächsten Button-Klick (setzt sich nach Klick automatisch auf `0` zurück) | `0 min` |
| `time` | `time.max_uhrzeit` | **Uhrzeit** (Uhrzeit-Auswahl, z. B. `17:37`, automatischer Fokus auf `mm` nach 2 Ziffern in `hh`) für den nächsten Button-Klick (leert sich nach Klick automatisch) | `17:37:00` |
| `button` | `button.max_aufwachen` | **Aufwachen** – beendet ein laufendes Nickerchen oder den Nachtschlaf | – |
| `button` | `button.max_nickerchen` | **Nickerchen** – startet ein Nickerchen | – |
| `button` | `button.max_schlafen` | **Schlafen** – startet die Einschlafbegleitung vor dem Nachtschlaf | – |
| `button` | `button.max_eingeschlafen` | **Eingeschlafen** – beendet die Einschlafbegleitung und startet den Nachtschlaf | – |

---

## Lovelace Schlafplan-Karte (`custom:napper-card`)

Die Integration registriert das Frontend-Modul beim Start von Home Assistant **automatisch**.

### Automatisch alle Kinder anzeigen (mit Tab-Umschalter oben)

Füge auf deinem Dashboard eine **Manuelle Karte** mit folgendem YAML hinzu:

```yaml
type: custom:napper-card
```

### Nur ein bestimmtes Kind anzeigen (Einzelkarte pro Kind)

Du kannst im visuellen Karten-Editor einfach das gewünschte Kind im Dropdown auswählen oder im YAML `baby` (Name des Kindes), `entity` oder `baby_id` angeben. Bei einer Einzelkarte werden die Tab-Umschalter für andere Kinder automatisch ausgeblendet:

```yaml
type: custom:napper-card
baby: "Max"
```

*(Alternativ funktionieren auch `type: custom:napper-circle-card`, `entity: sensor.max_nachstes_ereignis` oder `baby_id: "<DEINE_BABY_ID>"`.)*

---

## Home Assistant Aktionen (Services)

Alle drei Services akzeptieren unter `baby_id` entweder die **Baby-ID** oder einfach den **Namen des Kindes** (z. B. `"Max"`) sowie optional `time` (absolute Uhrzeit wie `"17:37"`) oder `minutes_ago` (Zeitdifferenz in Minuten; falls beides leer/0 ist, werden die Entitäten `time.<kind>_uhrzeit` bzw. `number.<kind>_zeitdifferenz` verwendet):

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
