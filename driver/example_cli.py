#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Beispiel-Skript: LD06 LiDAR im Terminal / für autonome fischertechnik Roboter
Liest den Sensor aus und gibt die Mindestabstände in 8 Himmelsrichtungen aus.
"""

import sys
import time
from ld06 import LD06

SECTOR_NAMES = [
    ("Vorne (0°)", 0),
    ("Vorne-Rechts (45°)", 45),
    ("Rechts (90°)", 90),
    ("Hinten-Rechts (135°)", 135),
    ("Hinten (180°)", 180),
    ("Hinten-Links (225°)", 225),
    ("Links (270°)", 270),
    ("Vorne-Links (315°)", 315)
]

def main():
    print("Verbinde mit LD06 LiDAR...")
    lidar = LD06()
    if not lidar.is_connected():
        print("Fehler: Sensor nicht gefunden oder USB-Port blockiert!")
        sys.exit(1)

    print("LiDAR verbunden! Drücke Strg+C zum Beenden.\n")
    try:
        while True:
            # Puffer für Messpunkte der nächsten 0.5 Sekunden
            sector_points = [[] for _ in range(8)]
            total_points = 0
            t_start = time.time()

            while (time.time() - t_start) < 0.5:
                points = lidar.read_points(block_size=400)
                if points:
                    total_points += len(points)
                    for angle, dist, conf in points:
                        # Berechne Sektor 0..7
                        sec_idx = int((angle + 22.5) % 360 / 45)
                        sector_points[sec_idx].append(dist)
                else:
                    time.sleep(0.005)

            # Ausgabe formatieren
            rate = int(total_points / (time.time() - t_start))
            print(f"\033[H\033[J=== LD06 LiDAR 360° Übersicht ({rate} Pkt/s) ===")
            for i in range(8):
                name, deg = SECTOR_NAMES[i]
                dists = sector_points[i]
                if dists:
                    min_cm = min(dists) / 10.0
                    avg_cm = sum(dists) / len(dists) / 10.0
                    
                    # Farbige Markierung je nach Abstand
                    if min_cm < 30:
                        color = "\033[91m" # Rot
                    elif min_cm < 80:
                        color = "\033[93m" # Gelb
                    else:
                        color = "\033[92m" # Grün
                    
                    bar = "█" * int(min(20, min_cm / 5))
                    print(f" {name:<22}: {color}{min_cm:5.1f} cm\033[0m (Schnitt: {avg_cm:5.1f} cm)  |{bar}")
                else:
                    print(f" {name:<22}: Keine Reflexion")

            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\nBeendet.")
    finally:
        lidar.close()

if __name__ == '__main__':
    main()
