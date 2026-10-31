#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LD06 8-Zonen LiDAR Dashboard App für den Fischertechnik TXT Controller.
Zeigt die Mindestabstände in 8 Richtungen (Vorne, V-Rechts, Rechts, H-Rechts,
Hinten, H-Links, Links, V-Links) in Echtzeit auf dem 240x320 Touchscreen an.
"""

import sys
import os
import time
import math
import threading

sys.path.append('/opt/ftc')
sys.path.append(os.path.dirname(os.path.realpath(__file__)))

from PyQt5.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPolygonF
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QSizePolicy
from TouchStyle import TouchApplication, TouchWindow

from ld06 import LD06

# Definition der 8 Sektoren
SECTOR_NAMES = [
    ('Vorne', '0°'),
    ('V-Rechts', '45°'),
    ('Rechts', '90°'),
    ('H-Rechts', '135°'),
    ('Hinten', '180°'),
    ('H-Links', '225°'),
    ('Links', '270°'),
    ('V-Links', '315°'),
]


class SectorDashboardWidget(QWidget):
    """Zeichnet die grafische 8-Zonen-Ansicht und die Messwert-Tabelle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(240, 280)
        self.sector_data = [(0, 0, 0.0)] * 8
        self.data_lock = threading.Lock()
        self.pts_per_sec = 0

    def update_sectors(self, sector_values, pts_rate):
        with self.data_lock:
            self.sector_data = list(sector_values)
            self.pts_per_sec = pts_rate
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        w = self.width()
        h = self.height()

        # Dunkler Hintergrund
        painter.fillRect(0, 0, w, h, QColor(10, 14, 20))

        now = time.time()
        with self.data_lock:
            sectors = list(self.sector_data)
            pts_rate = self.pts_per_sec

        # ========================================================
        # 1. OBERER GRAFISCHER 8-ZONEN-RADAR-KREIS
        # ========================================================
        cx = 120.0
        cy = 74.0
        r_outer = 64.0
        r_inner = 23.0

        # Äußere & innere Begrenzungslinien
        painter.setPen(QPen(QColor(0, 140, 110, 130), 1, Qt.DashLine))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), r_outer, r_outer)
        painter.drawEllipse(QPointF(cx, cy), r_inner, r_inner)

        # Trennlinien der 8 Sektoren
        for i in range(8):
            ang = math.radians(i * 45 + 22.5)
            x1 = cx + r_inner * math.sin(ang)
            y1 = cy - r_inner * math.cos(ang)
            x2 = cx + r_outer * math.sin(ang)
            y2 = cy - r_outer * math.cos(ang)
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))

        # Die 8 Zonen-Füllungen zeichnen
        for i in range(8):
            dist_mm, avg_mm, t = sectors[i]
            is_active = (dist_mm > 0) and (now - t < 0.6)

            start_angle = int((90 - i * 45 - 22.5) * 16)
            span_angle = int(45 * 16)

            if is_active:
                d_cm = dist_mm / 10.0
                if d_cm < 30:
                    color_fill = QColor(255, 45, 45, 210)
                elif d_cm < 80:
                    color_fill = QColor(255, 190, 0, 190)
                else:
                    color_fill = QColor(0, 225, 200, 170)

                # Dynamische Balkenlänge: Je näher das Hindernis, desto größer der Bogen
                ratio = max(0.25, min(1.0, 1.0 - (d_cm / 160.0)))
                r_bar = r_inner + ratio * (r_outer - r_inner)

                rect_bar = QRectF(cx - r_bar, cy - r_bar, r_bar * 2, r_bar * 2)
                rect_in = QRectF(cx - r_inner, cy - r_inner, r_inner * 2, r_inner * 2)

                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(color_fill))
                painter.drawPie(rect_bar, start_angle, span_angle)

                # Innenkreis freistellen
                painter.setBrush(QBrush(QColor(10, 14, 20)))
                painter.drawEllipse(rect_in)
            else:
                painter.setPen(QPen(QColor(40, 55, 70, 90), 1))
                rect_out = QRectF(cx - r_outer, cy - r_outer, r_outer * 2, r_outer * 2)
                painter.drawPie(rect_out, start_angle, span_angle)

        # Richtungs-Beschriftung (V, VR, R, HR, H, HL, L, VL)
        dir_labels = ['V', 'VR', 'R', 'HR', 'H', 'HL', 'L', 'VL']
        painter.setFont(QFont('Liberation Sans', 8, QFont.Bold))
        for i in range(8):
            ang = math.radians(i * 45)
            lx = cx + (r_outer + 9) * math.sin(ang)
            ly = cy - (r_outer + 9) * math.cos(ang)
            painter.setPen(QColor(0, 230, 200))
            painter.drawText(QRectF(lx - 12, ly - 7, 24, 14), Qt.AlignCenter, dir_labels[i])

        # Roboter-Fahrzeugsymbol in der Mitte
        painter.setPen(QPen(QColor(100, 160, 220), 1))
        painter.setBrush(QBrush(QColor(20, 45, 75)))
        painter.drawRoundedRect(QRectF(cx - 10, cy - 14, 20, 28), 3, 3)

        # Räder links & rechts
        painter.setBrush(QBrush(QColor(50, 65, 80)))
        painter.drawRect(int(cx - 13), int(cy - 12), 3, 8)
        painter.drawRect(int(cx - 13), int(cy + 4), 3, 8)
        painter.drawRect(int(cx + 10), int(cy - 12), 3, 8)
        painter.drawRect(int(cx + 10), int(cy + 4), 3, 8)

        # Vorwärts-Pfeil
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(0, 220, 255)))
        arrow = QPolygonF([
            QPointF(cx, cy - 11),
            QPointF(cx + 5, cy - 2),
            QPointF(cx, cy - 5),
            QPointF(cx - 5, cy - 2)
        ])
        painter.drawPolygon(arrow)

        # ========================================================
        # 2. UNTERE TABELLE / KARTEN DER 8 SEKTOREN
        # ========================================================
        card_w = 110.0
        card_h = 24.0
        start_y = 153.0
        spacing_y = 27.0

        min_overall_d = 99999
        min_overall_name = ''

        for col in range(2):
            for row in range(4):
                idx = col * 4 + row
                name, deg_str = SECTOR_NAMES[idx]
                dist_mm, avg_mm, t = sectors[idx]
                is_active = (dist_mm > 0) and (now - t < 0.6)

                bx = 8.0 if col == 0 else 122.0
                by = start_y + row * spacing_y

                # Hintergrund-Karte
                painter.setPen(QPen(QColor(30, 50, 75), 1))
                painter.setBrush(QBrush(QColor(16, 26, 38)))
                painter.drawRoundedRect(QRectF(bx, by, card_w, card_h), 4, 4)

                # Name
                painter.setFont(QFont('Liberation Sans', 8, QFont.Bold))
                painter.setPen(QColor(180, 205, 225))
                painter.drawText(QRectF(bx + 6, by, 58, card_h), Qt.AlignVCenter | Qt.AlignLeft, name)

                # Messwert-Badge
                badge_w = 42.0
                badge_h = 18.0
                badge_x = bx + card_w - badge_w - 4.0
                badge_y = by + (card_h - badge_h) / 2.0

                if is_active:
                    d_cm = dist_mm / 10.0
                    if dist_mm < min_overall_d:
                        min_overall_d = dist_mm
                        min_overall_name = name

                    if d_cm < 30:
                        badge_bg = QColor(220, 45, 45)
                        badge_fg = QColor(255, 255, 255)
                    elif d_cm < 80:
                        badge_bg = QColor(240, 180, 0)
                        badge_fg = QColor(0, 0, 0)
                    else:
                        badge_bg = QColor(0, 160, 120)
                        badge_fg = QColor(255, 255, 255)

                    txt_val = f'{d_cm:.0f} cm' if d_cm < 100 else f'{int(d_cm)} cm'
                else:
                    badge_bg = QColor(35, 45, 55)
                    badge_fg = QColor(100, 115, 130)
                    txt_val = '---'

                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(badge_bg))
                painter.drawRoundedRect(QRectF(badge_x, badge_y, badge_w, badge_h), 3, 3)

                painter.setFont(QFont('Liberation Sans', 8, QFont.Bold))
                painter.setPen(badge_fg)
                painter.drawText(QRectF(badge_x, badge_y, badge_w, badge_h), Qt.AlignCenter, txt_val)

        # ========================================================
        # 3. STATUSLEISTE GANZ UNTEN
        # ========================================================
        painter.setFont(QFont('Liberation Sans', 7))
        painter.setPen(QColor(120, 150, 175))
        painter.drawText(QRectF(8, h - 16, 100, 14), Qt.AlignVCenter | Qt.AlignLeft, f'{pts_rate} Pkt/s')

        if min_overall_d < 99999:
            min_cm = min_overall_d / 10.0
            warn_col = QColor(255, 60, 60) if min_cm < 30 else (QColor(255, 200, 0) if min_cm < 80 else QColor(0, 220, 200))
            painter.setPen(warn_col)
            painter.drawText(QRectF(108, h - 16, 124, 14), Qt.AlignVCenter | Qt.AlignRight, f'Min: {min_cm:.0f}cm ({min_overall_name})')
        else:
            painter.setPen(QColor(255, 180, 50))
            painter.drawText(QRectF(108, h - 16, 124, 14), Qt.AlignVCenter | Qt.AlignRight, 'Warte auf LiDAR...')


class LidarSectorsWindow(TouchWindow):
    """Hauptfenster für die 8-Zonen-Dashboard-App."""

    def __init__(self):
        super().__init__('8 Zonen')

        self.lidar = None
        self.worker_running = True
        self.pts_per_sec = 0
        self.pts_counter = 0
        self.pts_timer_t0 = time.time()

        self.sector_pts = [[] for _ in range(8)]
        self.sector_lock = threading.Lock()

        self.dashboard = SectorDashboardWidget(self)
        self.setCentralWidget(self.dashboard)

        # Hintergrund-Thread für serielle Daten
        self.thread = threading.Thread(target=self._lidar_worker, daemon=True)
        self.thread.start()

        # UI-Timer: 10 FPS (100ms) - perfekt für Zahlenanzeige und minimale CPU-Last
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_ui_tick)
        self.timer.start(100)

    def on_ui_tick(self):
        now = time.time()
        dt = now - self.pts_timer_t0
        if dt >= 1.0:
            self.pts_per_sec = int(self.pts_counter / dt)
            self.pts_counter = 0
            self.pts_timer_t0 = now

        with self.sector_lock:
            sec_snapshot = []
            for i in range(8):
                # Nur Punkte der letzten 0.45s berücksichtigen
                valid = [(d, t) for d, t in self.sector_pts[i] if (now - t) < 0.45 and d > 0]
                self.sector_pts[i] = valid
                if valid:
                    min_d = min(d for d, t in valid)
                    avg_d = sum(d for d, t in valid) // len(valid)
                    sec_snapshot.append((min_d, avg_d, now))
                else:
                    sec_snapshot.append((0, 0, 0.0))

        self.dashboard.update_sectors(sec_snapshot, self.pts_per_sec)

    def _lidar_worker(self):
        last_pts_time = time.time()
        while self.worker_running:
            if self.lidar is None or not self.lidar.is_connected():
                self.lidar = LD06()
                if not self.lidar.is_connected():
                    time.sleep(1.0)
                    continue
                last_pts_time = time.time()

            pts = self.lidar.read_points(block_size=400)
            now = time.time()
            if pts:
                self.pts_counter += len(pts)
                with self.sector_lock:
                    for angle, dist, conf in pts:
                        sec_idx = int((angle + 22.5) % 360 / 45)
                        self.sector_pts[sec_idx].append((dist, now))
                last_pts_time = now
                time.sleep(0.002)
            else:
                if (now - last_pts_time) > 2.0:
                    self.lidar.close()
                    time.sleep(0.5)
                    self.lidar = LD06()
                    last_pts_time = now
                else:
                    time.sleep(0.02)

    def closeEvent(self, event):
        self.worker_running = False
        if self.lidar:
            self.lidar.close()
        event.accept()


if __name__ == '__main__':
    app = TouchApplication(sys.argv)
    w = LidarSectorsWindow()
    w.show()
    sys.exit(app.exec_())
