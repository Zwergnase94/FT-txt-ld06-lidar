#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LD06 DToF LiDAR Touch-App für den Fischertechnik TXT Controller.
Zeigt eine flüssige 360°-Radar-Ansicht auf dem 240x320 Touchscreen an.
Inklusive automatischer Hotplug-/Wiederverbindungs-Erkennung bei USB-Trennung.
"""

import sys
import os
import time
import math
import threading

sys.path.append('/opt/ftc')
sys.path.append(os.path.dirname(os.path.realpath(__file__)))

from PyQt5.QtCore import Qt, QTimer, QPointF
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPolygonF
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy
)
from TouchStyle import TouchApplication, TouchWindow

from ld06 import LD06

# Vorberechnete Sinus- und Kosinus-Tabellen (0..359 Grad) für maximale ARM-Performance
SIN_TABLE = [math.sin(math.radians(a)) for a in range(360)]
COS_TABLE = [math.cos(math.radians(a)) for a in range(360)]

# Zoom-Bereiche (in mm) und Beschriftungen
RANGES = [1000, 2000, 4000, 8000]
RANGE_LABELS = ['1.0 m', '2.0 m', '4.0 m', '8.0 m']


class RadarWidget(QWidget):
    """Performantes Radar-Widget mit QPainter-Zeichnung."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(240, 220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.range_idx = 1  # Standard: 2.0 m
        self.max_range = RANGES[self.range_idx]

        # Scan-Puffer: 360 Winkelschritte mit (Distanz_mm, Konfidenz, Zeitstempel)
        self.scan_data = [(0, 0, 0.0)] * 360
        self.data_lock = threading.Lock()
        self.has_points = False

    def cycle_range(self):
        self.range_idx = (self.range_idx + 1) % len(RANGES)
        self.max_range = RANGES[self.range_idx]
        self.update()
        return RANGE_LABELS[self.range_idx]

    def mousePressEvent(self, event):
        # Berührung des Radars schaltet die Reichweite um
        lbl = self.cycle_range()
        if hasattr(self.parent(), 'btn_range'):
            self.parent().btn_range.setText(lbl)

    def update_points(self, points):
        now = time.time()
        with self.data_lock:
            for angle, dist, conf in points:
                deg = int(round(angle)) % 360
                self.scan_data[deg] = (dist, conf, now)
            self.has_points = True

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        w = self.width()
        h = self.height()
        cx = w / 2.0
        cy = h / 2.0
        r_max = min(w, h) / 2.0 - 8.0

        # Tiefschwarzer Radar-Hintergrund
        painter.fillRect(0, 0, w, h, QColor(10, 14, 20))

        # Stifte für Gitter & Achsen
        pen_grid = QPen(QColor(0, 110, 85, 140), 1, Qt.DashLine)
        pen_axis = QPen(QColor(0, 170, 125, 200), 1, Qt.SolidLine)
        pen_outer = QPen(QColor(0, 220, 160, 255), 2, Qt.SolidLine)

        # 4 Konzentrische Kreise
        painter.setBrush(Qt.NoBrush)
        for i in range(1, 5):
            ring_r = r_max * (i / 4.0)
            if i == 4:
                painter.setPen(pen_outer)
            else:
                painter.setPen(pen_grid)
            painter.drawEllipse(QPointF(cx, cy), ring_r, ring_r)

        # Fadenkreuz (Vorne/Hinten 0°/180° und Rechts/Links 90°/270°)
        painter.setPen(pen_axis)
        painter.drawLine(int(cx), int(cy - r_max), int(cx), int(cy + r_max))
        painter.drawLine(int(cx - r_max), int(cy), int(cx + r_max), int(cy))

        # Diagonale 45°-Hilfslinien
        painter.setPen(pen_grid)
        d_off = r_max * 0.7071
        painter.drawLine(int(cx - d_off), int(cy - d_off), int(cx + d_off), int(cy + d_off))
        painter.drawLine(int(cx - d_off), int(cy + d_off), int(cx + d_off), int(cy - d_off))

        # Richtungs-Beschriftung (V = Vorne, R = Rechts, H = Hinten, L = Links)
        font_dir = QFont('Liberation Sans', 9, QFont.Bold)
        painter.setFont(font_dir)
        painter.setPen(QColor(0, 240, 200))
        painter.drawText(int(cx - 5), int(cy - r_max + 13), 'V')
        painter.drawText(int(cx + r_max - 13), int(cy + 4), 'R')
        painter.drawText(int(cx - 5), int(cy + r_max - 4), 'H')
        painter.drawText(int(cx - r_max + 4), int(cy + 4), 'L')

        # Distanz-Beschriftungen der Ringe
        font_dist = QFont('Liberation Sans', 7)
        painter.setFont(font_dist)
        painter.setPen(QColor(0, 170, 130))
        scale_m = self.max_range / 1000.0
        for i in (1, 2, 3):
            val_m = scale_m * (i / 4.0)
            txt = f'{val_m:.1f}m' if val_m < 10 else f'{int(val_m)}m'
            painter.drawText(int(cx + 4), int(cy - r_max * (i / 4.0) - 2), txt)

        # Scan-Snapshot holen
        now = time.time()
        with self.data_lock:
            pts_snapshot = list(self.scan_data)

        # Messpunkte zeichnen
        painter.setPen(Qt.NoPen)
        has_recent = False
        min_dist_active = 99999
        min_deg_active = -1

        for deg in range(360):
            dist, conf, t = pts_snapshot[deg]
            # Nur Punkte der letzten 0.45s berücksichtigen
            if dist <= 0 or (now - t) > 0.45:
                continue

            has_recent = True
            if dist < min_dist_active:
                min_dist_active = dist
                min_deg_active = deg

            r_px = (dist / float(self.max_range)) * r_max
            if r_px > r_max:
                continue

            px = cx + r_px * SIN_TABLE[deg]
            py = cy - r_px * COS_TABLE[deg]

            # Farbkodierung: Rot = nah (<30cm), Gelb = mittel (<80cm), Cyan = fern
            if dist < 300:
                painter.setBrush(QBrush(QColor(255, 50, 50)))
            elif dist < 800:
                painter.setBrush(QBrush(QColor(255, 205, 0)))
            else:
                painter.setBrush(QBrush(QColor(0, 240, 255)))

            painter.drawRect(int(px - 1), int(py - 1), 3, 3)

        # Roboter-Zentrumsanzeige (Pfeil nach Vorne)
        arrow_color = QColor(255, 70, 0) if min_dist_active < 300 else QColor(0, 180, 255)
        painter.setBrush(QBrush(arrow_color))
        painter.setPen(QPen(Qt.white, 1))
        arrow = QPolygonF([
            QPointF(cx, cy - 7),
            QPointF(cx + 5, cy + 5),
            QPointF(cx, cy + 3),
            QPointF(cx - 5, cy + 5)
        ])
        painter.drawPolygon(arrow)

        # Falls keine aktuellen Punkte vorliegen
        if not has_recent:
            painter.setPen(QColor(255, 180, 50))
            painter.setFont(QFont('Liberation Sans', 10, QFont.Bold))
            painter.drawText(self.rect(), Qt.AlignCenter, 'Warte auf LiDAR...')


class LidarWindow(TouchWindow):
    """Hauptfenster der App für das Fischertechnik TouchStyle UI."""

    def __init__(self):
        super().__init__('LIDAR')

        self.lidar = None
        self.worker_running = True
        self.pts_per_sec = 0
        self.pts_counter = 0
        self.pts_timer_t0 = time.time()

        # Layout aufbauen
        main_widget = QWidget()
        vbox = QVBoxLayout()
        vbox.setContentsMargins(0, 0, 0, 2)
        vbox.setSpacing(2)

        # Radar-Bereich
        self.radar = RadarWidget(self)
        vbox.addWidget(self.radar)

        # Untere Steuerungs- und Informationsleiste
        bottom_bar = QWidget()
        hbox = QHBoxLayout()
        hbox.setContentsMargins(4, 0, 4, 2)
        hbox.setSpacing(6)

        # Zoom-Taste
        self.btn_range = QPushButton(RANGE_LABELS[self.radar.range_idx])
        self.btn_range.setObjectName('smallerlabel')
        self.btn_range.setFixedSize(72, 34)
        self.btn_range.setStyleSheet(
            'QPushButton {'
            ' background-color: #1a4060;'
            ' border: 2px solid #2a6590;'
            ' border-radius: 6px;'
            ' font-size: 13px;'
            ' font-weight: bold;'
            ' color: #00e0ff;'
            '}'
            'QPushButton:pressed {'
            ' background-color: #0c2538;'
            '}'
        )
        self.btn_range.clicked.connect(self.on_range_clicked)
        hbox.addWidget(self.btn_range)

        # Statuszeile (Min-Distanz & Messrate)
        self.lbl_status = QLabel('Verbinde...')
        self.lbl_status.setStyleSheet(
            'QLabel {'
            ' font-size: 11px;'
            ' font-weight: bold;'
            ' color: #cccccc;'
            ' background: transparent;'
            '}'
        )
        self.lbl_status.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        hbox.addWidget(self.lbl_status, stretch=1)

        bottom_bar.setLayout(hbox)
        vbox.addWidget(bottom_bar)

        main_widget.setLayout(vbox)
        self.setCentralWidget(main_widget)

        # Hintergrund-Thread für serielle Daten
        self.thread = threading.Thread(target=self._lidar_worker, daemon=True)
        self.thread.start()

        # UI-Timer: 12.5 FPS (80ms)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_ui_tick)
        self.timer.start(80)

    def on_range_clicked(self):
        label = self.radar.cycle_range()
        self.btn_range.setText(label)

    def on_ui_tick(self):
        now = time.time()
        dt = now - self.pts_timer_t0
        if dt >= 1.0:
            self.pts_per_sec = int(self.pts_counter / dt)
            self.pts_counter = 0
            self.pts_timer_t0 = now

        # Nächstgelegenes Hindernis ermitteln
        with self.radar.data_lock:
            pts = list(self.radar.scan_data)

        min_d = 99999
        min_deg = -1
        for deg in range(360):
            d, conf, t = pts[deg]
            if d > 0 and (now - t) < 0.45:
                if d < min_d:
                    min_d = d
                    min_deg = deg

        if min_deg >= 0:
            d_cm = min_d / 10.0
            if d_cm < 30:
                color = '#ff4444'
            elif d_cm < 80:
                color = '#ffcc00'
            else:
                color = '#00ffcc'
            self.lbl_status.setText(
                f'<span style="color:{color};">Min: {d_cm:.0f}cm ({min_deg}°)</span><br>'
                f'<span style="color:#8899aa;">{self.pts_per_sec} Pkt/s</span>'
            )
        else:
            self.lbl_status.setText(
                '<span style="color:#ffaa00;">Warte auf Signal...</span><br>'
                f'<span style="color:#8899aa;">{self.pts_per_sec} Pkt/s</span>'
            )

        self.radar.update()

    def _lidar_worker(self):
        """Liest Datenpakete mit automatischem Reconnect bei USB-Trennung."""
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
                self.radar.update_points(pts)
                last_pts_time = now
                time.sleep(0.002)
            else:
                # Watchdog: Wenn länger als 2s keine Punkte eintreffen (z.B. nach USB Re-Plug)
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
    w = LidarWindow()
    w.show()
    sys.exit(app.exec_())
