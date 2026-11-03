# Hardware, Pinbelegung & Technische Hintergründe

## 1. Übersicht: LDROBOT LD06 LiDAR

Der **LD06** ist ein kompakter 360°-Laserscanner nach dem Direct-Time-of-Flight-Prinzip (DToF):
* **Abtastrate:** ca. 4.500 Messpunkte pro Sekunde (4,5 kHz)
* **Rotationsfrequenz:** ca. 10–13 Hz
* **Reichweite:** 0,02 m bis 12 m
* **Schnittstelle:** UART mit **230.400 Baud** (8N1, 3,3 V Pegel)
* **Wellenlänge:** 905 nm (Laserklasse 1, augensicher)
* **Stromaufnahme:** ca. 180 mA im Betrieb (5 V DC)

---

## 2. Steckerbelegung (4-Pin JST-ZH)

Der Sensor wird über ein 4-poliges Kabel mit der USB-Adapterplatine verbunden:

| Pin | Farbe (typisch) | Signal | Beschreibung |
|:---:|:---:|:---:|:---|
| **1** | Rot | **VCC (+5 V)** | Spannungsversorgung (4,5 V – 5,5 V) |
| **2** | Gelb | **PWM** | Drehzahlregelung (offen lassen für Standard-Drehzahl ~10 Hz) |
| **3** | Schwarz | **GND** | Masse (0 V) |
| **4** | Weiß / Blau | **TX** | Serieller Datenausgang (3,3 V UART, 230.400 Baud) |

> [!WARNING]
> **Wackelkontakte vermeiden:** Die JST-ZH-Stecker sind sehr fein. Wackelnde Kontakte oder Kurzschlüsse lösen am TXT sofort die USB-Schutzabschaltung aus. Auf festen, geraden Sitz des Steckers achten.

---

## 3. USB-Abschaltung (`VBUS_ERROR in a_wait_bcon`) auf dem TXT

### Ursache
Der fischertechnik ROBOTICS TXT nutzt ein **TI Sitara AM3359 SoC** mit MUSB-Host-Controller (`musb-hdrc.1`):
* Beim Einstecken ziehen Motor und Kondensatoren des Sensors kurzzeitig einen erhöhten Einschaltstrom.
* Fällt die USB-Spannung dabei kurz unter 4,4 V (`< AValid`), meldet der Controller `VBUS_ERROR in a_wait_bcon` und schaltet die 5-V-Versorgung am USB-Port dauerhaft ab (`Vbus off`).

### Software-Lösung
Das Skript [`system/reset_usb.sh`](../system/reset_usb.sh) bindet den MUSB-Controller per Sysfs kurz aus und wieder ein (`unbind` / `bind`), wodurch die 5-V-Spannung wieder eingeschaltet wird. Der Python-Treiber prüft den VBUS-Status beim Verbinden und führt diesen Reset bei Bedarf automatisch aus.

---

## 4. Fehlender CP210X-Treiber im Kernel

### Ursache
Im Kernel von **ftcommunity-TXT 1.1.4** (`Linux 4.14.336 armv7l`) sind Treiber für CH341, FTDI und PL2303 enthalten, `CONFIG_USB_SERIAL_CP210X` ist jedoch nicht aktiviert. Der Fallback-Treiber `usbserial_generic` kann die Baudrate des CP2102 nicht umschalten, sodass der Chip auf 9.600 Baud stehen bleibt.

### Lösung in `ld06.py`
Der Treiber sendet beim Öffnen direkte USB-Control-Transfers (`USBDEVFS_CONTROL = 0xc0105500`) an `/dev/bus/usb/001/xxx`:
1. `0x00` (`IFC_ENABLE`): UART aktivieren
2. `0x1E` (`SET_BAUDRATE`): Baudrate auf **230.400 Baud** setzen
3. `0x03` (`SET_LINE_CTL`): 8N1 konfigurieren
4. `0x07` (`SET_MHS`): DTR=1, RTS=1 setzen
5. `0x12` (`PURGE`): Puffer leeren

Damit arbeitet der CP2102 ohne Kernel-Anpassung mit der vollen Datenrate.
