#!/bin/sh
#
# Automatisches Installationsskript für den LD06 LiDAR auf dem fischertechnik TXT
# Community Firmware (ftcommunity-TXT)
#

set -e

echo "=========================================================="
echo "  fischertechnik TXT - LD06 LiDAR Treiber & Apps Installer"
echo "=========================================================="

if [ ! -f /etc/fw-ver.txt ]; then
    echo "Warnung: /etc/fw-ver.txt nicht gefunden. Läuft dieses Skript auf einem TXT?"
fi

BASE_DIR=$(cd "$(dirname "$0")" && pwd)

# 1. USB Auto-Reset Skript installieren
echo "[1/6] Installiere USB-Reset-Skript unter /home/ftc/reset_usb.sh..."
cp "$BASE_DIR/system/reset_usb.sh" /home/ftc/reset_usb.sh
chmod +x /home/ftc/reset_usb.sh

# 2. Sudoers-Berechtigung für USB-Reset hinterlegen
echo "[2/6] Richte passwortlose Sudoers-Regel für USB-Reset ein..."
echo 'ftc ALL = (root) NOPASSWD: /home/ftc/reset_usb.sh' | sudo tee /etc/sudoers.d/usb >/dev/null

# 3. udev-Regeln einrichten (automatische Berechtigung & Modulladung)
echo "[3/6] Installiere udev-Regel für CP2102..."
sudo cp "$BASE_DIR/system/90-cp2102.rules" /etc/udev/rules.d/90-cp2102.rules
sudo udevadm control --reload-rules || true
sudo udevadm trigger || true

# Kernelmodul sofort laden
sudo modprobe usbserial vendor=0x10c4 product=0xea60 2>/dev/null || true

# 4. Apps kopieren
echo "[4/6] Installiere Apps nach /home/ftc/apps/..."
mkdir -p /home/ftc/apps/02eef5e0-981a-11ed-87cd-0800200c9a66
mkdir -p /home/ftc/apps/e8b5a1f0-4567-4f89-8d12-10d6800c9a88

cp -r "$BASE_DIR/apps/lidar_radar/"* /home/ftc/apps/02eef5e0-981a-11ed-87cd-0800200c9a66/
cp -r "$BASE_DIR/apps/lidar_8zones/"* /home/ftc/apps/e8b5a1f0-4567-4f89-8d12-10d6800c9a88/

chmod +x /home/ftc/apps/02eef5e0-981a-11ed-87cd-0800200c9a66/main.py
chmod +x /home/ftc/apps/e8b5a1f0-4567-4f89-8d12-10d6800c9a88/main.py

# 5. Launcher Startbildschirm aktualisieren
echo "[5/6] Platziere Apps auf dem Startbildschirm..."
if [ -f /home/ftc/.launcher.xml ]; then
    python3 -c "
import xml.etree.ElementTree as ET
try:
    tree = ET.parse('/home/ftc/.launcher.xml')
    root = tree.getroot()
    apps = root.find('apps')
    if apps is not None:
        existing = [el.attrib.get('path') for el in apps.findall('app')]
        p1 = 'user/02eef5e0-981a-11ed-87cd-0800200c9a66'
        p2 = 'user/e8b5a1f0-4567-4f89-8d12-10d6800c9a88'
        if p1 not in existing:
            el = ET.Element('app', {'path': p1})
            apps.insert(0, el)
        if p2 not in existing:
            el = ET.Element('app', {'path': p2})
            apps.insert(1, el)
        tree.write('/home/ftc/.launcher.xml')
except Exception as e:
    pass
"
fi

# 6. Launcher neu starten
echo "[6/6] Starte Launcher neu..."
sudo /etc/init.d/S90launcher restart || true

echo ""
echo "=========================================================="
echo "  Installation erfolgreich abgeschlossen!"
echo "  Die Apps 'LIDAR' und '8 Zonen' sind jetzt auf dem TXT!"
echo "=========================================================="
