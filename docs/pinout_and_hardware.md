# Hardware, Pinbelegung & Technische Hintergründe

## 1. Übersicht: LD06 DToF LiDAR Sensor

Der **LD06** von LDROBOT ist ein ultrakompakter DToF (Direct Time-of-Flight) 360°-Laserscanner:
* **Abtastrate:** ~4.500 Messpunkte pro Sekunde (4,5 kHz)
* **Rotationsfrequenz:** ca. 10 Hz (10 Umdrehungen / Sekunde)
* **Reichweite:** 0,02 m bis 12 m
* **Baudrate:** **230.400 Baud** (8N1)
* **Wellenlänge:** 905 nm (Laserklasse 1, augensicher)
* **Stromaufnahme:** ca. 180 mA im regulären Drehbetrieb (5V DC)

---

## 2. Steckerbelegung (4-Pin JST-ZH)

Der Sensor wird typischerweise über ein 4-poliges Flachbandkabel mit der kleinen USB-Adapterplatine verbunden:

| Pin | Farbe (typisch) | Signal | Beschreibung |
|:---:|:---:|:---:|:---|
| **1** | Rot | **VCC (+5V)** | Spannungsversorgung (4,5V – 5,5V) |
| **2** | Gelb | **PWM** | Motorgeschwindigkeitsregelung (offen lassen für konstante 10 Hz) |
| **3** | Schwarz | **GND** | Masse (0V) |
| **4** | Weiß / Blau | **TX** | Serieller Datenausgang (3.3V UART, 230.400 Baud) |

> [!WARNING]
> **Wackelkontakt-Gefahr:** Die JST-ZH-Stecker sind sehr filigran. Wenn beim Bewegen des Kabels Pins wackeln oder kurzschließen, bricht die 5V-Leitung des TXT sofort ein und schaltet ab. Achte auf festen, sauberen Sitz des Steckers.

---

## 3. Das "VBUS_ERROR in a_wait_bcon"-Phänomen auf dem TXT

### Warum schaltet der TXT den USB-Port ab?
Der fischertechnik ROBOTICS TXT Controller nutzt ein **Texas Instruments Sitara AM3359 SoC** (ARM Cortex-A8) mit einem MUSB-Host-Controller (`musb-hdrc.1`).

* **Einschaltstrom (Inrush Current):** Beim Anstecken des Sensors zieht der kleine DC-Motor des LiDARs sowie die Entkopplungskondensatoren für wenige Mikrosekunden eine Stromspitze.
* **Schutzschaltung des TI AM335x:** Fällt die USB-Spannung während des Einsteckens für einen Sekundenbruchteil unter $4,4\text{ V}$ (`<AValid`), interpretiert der MUSB-Controller dies als Kurzschluss (`VBUS_ERROR in a_wait_bcon`) und **schaltet die 5V-Spannung am USB-Port zum Eigenschutz dauerhaft ab** (`Vbus off`).
* **Die Software-Lösung:** 
  Über das Skript `reset_usb.sh` wird der MUSB-Controller per Sysfs kurz aus- und wieder eingebunden (`unbind` / `bind`). Dadurch schaltet der TXT die 5V-Spannung wieder frei. Unser Python-Treiber führt dies vollautomatisch im Hintergrund aus, sobald ein Ausfall erkannt wird.

---

## 4. Der fehlende CP210X-Treiber im TXT-Kernel

### Problem
Im Kernel der offiziellen **ftcommunity-TXT 1.1.4** (Linux 4.14.336 armv7l) sind zwar Treiber für CH341, FTDI und PL2303 kompiliert, **`CONFIG_USB_SERIAL_CP210X` ist jedoch nicht aktiviert**.

Wenn der CP2102-Adapter eingesteckt wird, greift der Kernel daher auf den Treiber `usbserial_generic` zurück. Dieser unterstützt aber keine hardwareseitige Baudrateneinstellung für den CP2102-Chip – der Chip verharrt im Standardmodus bei 9.600 Baud.

### Die Lösung unseres Treibers (`ld06.py`)
Unser Python-Treiber kommuniziert direkt über USB-Control-Transfers (`USBDEVFS_CONTROL = 0xc0105500`) mit dem USB-Gerät (`/dev/bus/usb/001/xxx`):
1. `0x00`: `IFC_ENABLE` (UART aktivieren)
2. `0x1E`: `SET_BAUDRATE` (Baudrate auf **230.400 Baud** einstellen)
3. `0x03`: `SET_LINE_CTL` (8 Datenbits, 1 Stopbit, keine Parität)
4. `0x07`: `SET_MHS` (DTR=1, RTS=1 setzen)
5. `0x12`: `PURGE` (FIFOs leeren)

Dadurch funktioniert der Silicon Labs CP2102 **ohne Neukompilierung des Kernels** sofort und absolut stabil mit vollen 4.500 Messpunkten pro Sekunde.
