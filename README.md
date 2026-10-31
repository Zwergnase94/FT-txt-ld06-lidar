# LD06 DToF LiDAR für den fischertechnik ROBOTICS TXT (ftcommunity-TXT)

[![ftcommunity-TXT](https://img.shields.io/badge/Firmware-ftcommunity--TXT_1.1.4-blue.svg)](https://github.com/ftCommunity/ftcommunity-TXT)
[![Platform](https://img.shields.io/badge/Platform-TI_AM3359_ARM_Cortex--A8-green.svg)](https://www.ti.com/product/AM3359)
[![Python](https://img.shields.io/badge/Python-3.8+-yellow.svg)](https://www.python.org/)
[![UI](https://img.shields.io/badge/GUI-TouchStyle_%2F_PyQt5-orange.svg)](https://github.com/harbaum/TouchUI)
[![License: MIT](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)

Dieses Repository enthält den vollständigen **Python-Treiber**, die **System-Konfigurationen (udev / Auto-Reset)** sowie **zwei native Touchscreen-Apps** für den **Super Mini DTOF Prinzip LiDAR LD06** auf dem **fischertechnik ROBOTICS TXT Controller** mit der **Community-Firmware (ftcommunity-TXT)**.

---

## 📸 Screenshots vom TXT-Display (240x320 Pixel)

| App 1: 360° Live-Radar | App 2: 8-Zonen & Dashboard |
|:---:|:---:|
| ![Radar App](docs/screenshots/radar_app.png) | ![8 Zonen App](docs/screenshots/sectors_app.png) |
| *Punktwolke in Echtzeit (~4.500 Pkt/s)* | *Kollisionswarnung für alle 8 Richtungen* |

---

## 🚀 Die beiden enthaltenen Apps

### 1. App „LIDAR“ (360° Polar-Radar)
* **Hardwarenahes Rendering:** Nutzt `QPainter` und das offizielle `TouchStyle`-Framework (kein schwerfälliges `matplotlib` – flüssige 12,5 FPS bei nur ~25 % CPU-Last auf dem 600 MHz ARM-Prozessor).
* **Farbcodierte Punktwolke:**
  * 🔴 **Rot:** Sehr nah ($< 30\text{ cm}$) – unmittelbare Kollisionsgefahr.
  * 🟡 **Gelb:** Mittlerer Abstand ($30\text{ cm}$ bis $80\text{ cm}$).
  * 🔵 **Cyan:** Weiter entfernt ($> 80\text{ cm}$).
* **Touch-Zoom:** Durch Antippen des Bildschirms oder des Buttons kann zwischen $1.0\text{ m}$, $2.0\text{ m}$, $4.0\text{ m}$ und $8.0\text{ m}$ umgeschaltet werden.
* **Richtungsanzeige:** **V** (Vorne), **R** (Rechts), **H** (Hinten), **L** (Links) mit zentriertem Roboter-Pfeil.

### 2. App „8 Zonen“ (Hindernis-Dashboard)
* **Grafisches Sonar:** 8 kreisförmige Segmente um das Fahrzeugsymbol. Je näher ein Objekt kommt, desto größer wächst der Warnbalken auf den Roboter zu.
* **Genaue cm-Messwerte:** 8 übersichtliche Kacheln mit genauer Distanz in Zentimetern (Vorne, V-Rechts, Rechts, H-Rechts, Hinten, H-Links, Links, V-Links).
* **Live-Status:** Zeigt permanent das nächste Hindernis im Raum an (z. B. `Min: 6cm (Rechts)`).

Beide Apps liegen nach der Installation direkt auf der **obersten Ebene des TXT-Startbildschirms** und können mit einem Fingertippen gestartet werden.

---

## 💡 Technische Herausforderungen & Lösungen

Bei der Integration des LD06 auf dem klassischen TXT gab es drei knifflige Hürden, die in diesem Projekt vollständig gelöst wurden:

### 1. Fehlender CP210X-Treiber im Linux-Kernel
* **Problem:** Der TXT-Kernel (`4.14.336 armv7l`) hat Treiber für FTDI, CH341 und PL2303, aber **nicht** für den *Silicon Labs CP2102*. Beim Einstecken bindet Linux nur den rudimentären Treiber `usbserial_generic`, der die Baudrate von $230.400\text{ Baud}$ nicht setzen kann.
* **Lösung:** Unser Treiber [`driver/ld06.py`](driver/ld06.py) sendet hardwarenahe USB-Control-Transfers (`0xc0105500`) direkt an den USB-Knoten und konfiguriert den CP2102-Chip per Software auf $230.400\text{ Baud}$ (8N1, DTR=1, RTS=1). Ein Neukompilieren des Kernels ist **nicht** erforderlich!

### 2. USB-Spannungseinbruch & Abschaltung (`VBUS_ERROR`)
* **Problem:** Beim Anstecken des LiDARs zieht der integrierte Elektromotor einen kurzen Einschaltstrom (Inrush Current). Der USB-Host-Controller des Texas Instruments Sitara AM3359 registriert einen minimalen Spannungseinbruch (`VBUS_ERROR in a_wait_bcon`) und schaltet den USB-Port aus Schutzgründen komplett ab (`Vbus off`).
* **Lösung:** 
  1. Das Skript [`system/reset_usb.sh`](system/reset_usb.sh) führt einen Reset des MUSB-Controllers via Sysfs aus (`unbind` / `bind`).
  2. Der Treiber überwacht den Status des USB-Ports und führt diesen Reset bei Bedarf **vollautomatisch im Hintergrund** durch.

### 3. Zugriffsrechte & Hot-Plugging (udev)
* Die Regel [`system/90-cp2102.rules`](system/90-cp2102.rules) sorgt dafür, dass Linux dem Gerät bei jedem Einstecken automatisch die Schreibrechte (`0666`, Gruppe `dialout`) zuweist und den seriellen Treiber lädt.

---

## 📦 Schnelle 1-Klick-Installation

Verbinde dich per SSH mit deinem TXT und führe folgende Befehle aus:

```bash
# 1. Repository klonen oder auf den TXT kopieren
git clone https://github.com/Zwergnase94/FT-txt-ld06-lidar.git /home/ftc/ld06-lidar
cd /home/ftc/ld06-lidar

# 2. Installer ausführen
chmod +x install.sh
./install.sh
```

Das Skript richtet alles automatisch ein (udev-Regeln, Sudoers, Apps und Startbildschirm).

---

## 🛠 Manuelle Installation (Schritt für Schritt)

Falls du die Schritte einzeln durchführen möchtest:

### 1. USB-Reset-Skript & Berechtigung einrichten
```bash
# Skript kopieren und ausführbar machen
cp system/reset_usb.sh /home/ftc/reset_usb.sh
chmod +x /home/ftc/reset_usb.sh

# Passwortlose Ausführung für ftc erlauben
echo 'ftc ALL = (root) NOPASSWD: /home/ftc/reset_usb.sh' | sudo tee /etc/sudoers.d/usb
```

### 2. udev-Regel installieren
```bash
sudo cp system/90-cp2102.rules /etc/udev/rules.d/90-cp2102.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
sudo modprobe usbserial vendor=0x10c4 product=0xea60
```

### 3. Apps in das Benutzerverzeichnis kopieren
```bash
mkdir -p /home/ftc/apps/02eef5e0-981a-11ed-87cd-0800200c9a66
mkdir -p /home/ftc/apps/e8b5a1f0-4567-4f89-8d12-10d6800c9a88

cp -r apps/lidar_radar/* /home/ftc/apps/02eef5e0-981a-11ed-87cd-0800200c9a66/
cp -r apps/lidar_8zones/* /home/ftc/apps/e8b5a1f0-4567-4f89-8d12-10d6800c9a88/

chmod +x /home/ftc/apps/02eef5e0-981a-11ed-87cd-0800200c9a66/main.py
chmod +x /home/ftc/apps/e8b5a1f0-4567-4f89-8d12-10d6800c9a88/main.py
```

### 4. Apps auf dem Startbildschirm platzieren
Bearbeite `/home/ftc/.launcher.xml` und füge die beiden Pfade direkt unter `<apps>` ein:
```xml
<launcher>
  <apps>
    <app path="user/02eef5e0-981a-11ed-87cd-0800200c9a66" />
    <app path="user/e8b5a1f0-4567-4f89-8d12-10d6800c9a88" />
    ...
  </apps>
</launcher>
```
Anschließend den Launcher neu starten:
```bash
sudo /etc/init.d/S90launcher restart
```

---

## 🐍 Treiber in eigenen Python-Projekten nutzen

Du kannst den LiDAR-Treiber kinderleicht in deine eigenen Roboter-Steuerungsprogramme einbinden (z. B. für autonome Hindernisausweichung oder RoboCup):

```python
from ld06 import LD06
import time

lidar = LD06()

# Lese kontinuierlich Messpunkte aus
while True:
    points = lidar.read_points()
    for angle_deg, distance_mm, confidence in points:
        if distance_mm > 0:
            print(f"Winkel: {angle_deg:5.1f}° | Distanz: {distance_mm / 10.0:5.1f} cm (Konfidenz: {confidence})")
    time.sleep(0.01)
```

Ein vollständiges Terminal-Beispiel mit formatierter 8-Sektoren-Ausgabe findest du unter [`driver/example_cli.py`](driver/example_cli.py):
```bash
python3 driver/example_cli.py
```

---

## 🔌 Hardware-Verkabelung

| LD06 Pin | Signal | Verbindung am CP2102-Adapter |
|:---:|:---:|:---|
| **Pin 1 (Rot)** | 5V | `5V` |
| **Pin 2 (Gelb)** | PWM | *(offen lassen für Standard-Geschwindigkeit)* |
| **Pin 3 (Schwarz)** | GND | `GND` |
| **Pin 4 (Weiß/Blau)**| TX | `RXD` |

> [!TIP]
> **Praxistipp zum Einstecken:** 
> Falls der LiDAR beim Einstecken aus bleibt, einfach **2–3 Sekunden warten**. Der integrierte Watchdog erkennt die Abschaltung und reaktiviert den USB-Port automatisch. Für die stabilste Stromversorgung empfiehlt sich der Betrieb des TXT an einem **9V-Netzteil**.

---

## 📄 Lizenz & Autor

* **Autor:** Manuel Neumann (Zwergnase94)
* **Lizenz:** [MIT License](LICENSE)
* **Danksagung:** Danke an die [ft:community](https://ftcommunity.de/) für die großartige Community-Firmware und das `TouchStyle`-Framework!
