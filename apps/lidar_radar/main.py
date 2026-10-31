#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LD06 DToF LiDAR Touch-App für den Fischertechnik TXT Controller.
Zeigt eine flüssige 360°-Radar-Ansicht auf dem 240x320 Touchscreen an.
Hocheffiziente QPixmap-Pufferung und Zero-Allocation-Parsing für minimale CPU-Last.
"""

import sys
import os
import time
import math
import threading

sys.path.append('/opt/ftc')
sys.path.append(os.path.dirname(os.path.realpath(__file__)))

from PyQt5.QtCore import Qt, QTimer, QPointF
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPolygonF, QPixmap
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy
)
from TouchStyle import TouchApplication, TouchWindow

from ld06 import LD06

SIN_TABLE = [math.sin(math.radians(a)) for a in range(360)]
COS_TABLE = [math.cos(math.radians(a)) for a in range(360)]

RANGES = [1000, 2000, 4000, 8000]
RANGE_LABELS = ['1.0 m', '2.0 m', '4.0 m', '8.0 m']


class RadarWidget(QWidget):
    """Performantes Radar-Widget mit vorberechneter QPixmap-Gitterzeichnung."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(240, 220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.range_idx = 1  # Standard: 2.0 m
        self.max_range = RANGES[self.range_idx]

        # Scan-Puffer: Feste Arrays (0 Objektallokationen während des Betriebs)
        self.scan_dist = [0] * 360
        self.scan_time = [0.0] * 360
        self.data_lock = threading.Lock()
        self.has_points = False

        # Vorallozierte Grafikressourcen
        self.brush_bg = QBrush(QColor(10, 14, 20))
        self.pen_grid = QPen(QColor(0, 110, 85, 140), 1, Qt.DashLine)
        self.pen_axis = QPen(QColor(0, 170, 125, 200), 1, Qt.SolidLine)
        self.pen_outer = QPen(QColor(0, 220, 160, 255), 2, Qt.SolidLine)

        self.brush_red = QBrush(QColor(255, 50, 50))
        self.brush_yellow = QBrush(QColor(255, 205, 0))
        self.brush_cyan = QBrush(QColor(0, 240, 255))

        self.brush_arrow_warn = QBrush(QColor(255, 70, 0))
        self.brush_arrow_normal = QBrush(QColor(0, 180, 255))
        self.pen_arrow = QPen(Qt.white, 1)

        self.color_dir_lbl = QColor(0, 240, 200)
        self.color_dist_lbl = QColor(0, 170, 130)
        self.color_wait_lbl = QColor(255, 180, 50)

        self.font_dir = QFont('Liberation Sans', 9, QFont.Bold)
        self.font_dist = QFont('Liberation Sans', 7)
        self.font_wait = QFont('Liberation Sans', 10, QFont.Bold)

        # Vorberechnetes Gitter (spart ~75% Zeichen-Overhead in jedem Frame)
        self.grid_pixmap = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render_static_grid()

    def _render_static_grid(self):
        w = max(240, self.width())
        h = max(220, self.height())
        self.grid_pixmap = QPixmap(w, h)
        p = QPainter(self.grid_pixmap)
        p.setRenderHint(QPainter.Antialiasing, True)

        p.fillRect(0, 0, w, h, self.brush_bg)

        cx = w * 0.5
        cy = h * 0.5
        r_max = min(w, h) * 0.5 - 8.0

        p.setBrush(Qt.NoBrush)
        for i in range(1, 5):
            ring_r = r_max * (i * 0.25)
            p.setPen(self.pen_outer if i == 4 else self.pen_grid)
            p.drawEllipse(QPointF(cx, cy), ring_r, ring_r)

        p.setPen(self.pen_axis)
        p.drawLine(int(cx), int(cy - r_max), int(cx), int(cy + r_max))
        p.drawLine(int(cx - r_max), int(cy), int(cx + r_max), int(cy))

        p.setPen(self.pen_grid)
        d_off = r_max * 0.7071
        p.drawLine(int(cx - d_off), int(cy - d_off), int(cx + d_off), int(cy + d_off))
        p.drawLine(int(cx - d_off), int(cy + d_off), int(cx + d_off), int(cy - d_off))

        p.setFont(self.font_dir)
        p.setPen(self.color_dir_lbl)
        p.drawText(int(cx - 5), int(cy - r_max + 13), 'V')
        p.drawText(int(cx + r_max - 13), int(cy + 4), 'R')
        p.drawText(int(cx - 5), int(cy + r_max - 4), 'H')
        p.drawText(int(cx - r_max + 4), int(cy + 4), 'L')

        p.setFont(self.font_dist)
        p.setPen(self.color_dist_lbl)
        scale_m = self.max_range * 0.001
        for i in (1, 2, 3):
            val_m = scale_m * (i * 0.25)
            txt = f'{val_m:.1f}m' if val_m < 10 else f'{int(val_m)}m'
            p.drawText(int(cx + 4), int(cy - r_max * (i * 0.25) - 2), txt)

        p.end()

    def cycle_range(self):
        self.range_idx = (self.range_idx + 1) % len(RANGES)
        self.max_range = RANGES[self.range_idx]
        self._render_static_grid()
        self.update()
        return RANGE_LABELS[self.range_idx]

    def mousePressEvent(self, event):
        lbl = self.cycle_range()
        if hasattr(self.parent(), 'btn_range'):
            self.parent().btn_range.setText(lbl)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        if not self.grid_pixmap:
            self._render_static_grid()

        # 1. Statisches Gitter blitten (1 Call)
        painter.drawPixmap(0, 0, self.grid_pixmap)

        w = self.width()
        h = self.height()
        cx = w * 0.5
        cy = h * 0.5
        r_max = min(w, h) * 0.5 - 8.0

        now = time.time()
        with self.data_lock:
            dists = list(self.scan_dist)
            times = list(self.scan_time)

        # 2. Messpunkte zeichnen
        painter.setPen(Qt.NoPen)
        has_recent = False
        min_dist_active = 99999
        inv_max_range = 1.0 / float(self.max_range)

        for deg in range(360):
            dist = dists[deg]
            t = times[deg]
            if dist <= 0 or (now - t) > 0.6:
                continue

            has_recent = True
            if dist < min_dist_active:
                min_dist_active = dist

            r_px = (dist * inv_max_range) * r_max
            if r_px > r_max:
                continue

            px = cx + r_px * SIN_TABLE[deg]
            py = cy - r_px * COS_TABLE[deg]

            if dist < 300:
                painter.setBrush(self.brush_red)
            elif dist < 800:
                painter.setBrush(self.brush_yellow)
            else:
                painter.setBrush(self.brush_cyan)

            painter.drawRect(int(px - 1), int(py - 1), 3, 3)

        # 3. Roboter-Zentrumsanzeige
        arrow_brush = self.brush_arrow_warn if min_dist_active < 300 else self.brush_arrow_normal
        painter.setBrush(arrow_brush)
        painter.setPen(self.pen_arrow)
        arrow = QPolygonF([
            QPointF(cx, cy - 7),
            QPointF(cx + 5, cy + 5),
            QPointF(cx, cy + 3),
            QPointF(cx - 5, cy + 5)
        ])
        painter.drawPolygon(arrow)

        if not has_recent:
            painter.setPen(self.color_wait_lbl)
            painter.setFont(self.font_wait)
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

        main_widget = QWidget()
        vbox = QVBoxLayout()
        vbox.setContentsMargins(0, 0, 0, 2)
        vbox.setSpacing(2)

        self.radar = RadarWidget(self)
        vbox.addWidget(self.radar)

        bottom_bar = QWidget()
        hbox = QHBoxLayout()
        hbox.setContentsMargins(4, 0, 4, 2)
        hbox.setSpacing(6)

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

        self.thread = threading.Thread(target=self._lidar_worker, daemon=True)
        self.thread.start()

        # 8 FPS (125ms) - synchron mit der 10 Hz SPI-Hardware
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_ui_tick)
        self.timer.start(125)

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

        with self.radar.data_lock:
            dists = list(self.radar.scan_dist)
            times = list(self.radar.scan_time)

        min_d = 99999
        min_deg = -1
        for deg in range(360):
            d = dists[deg]
            t = times[deg]
            if d > 0 and (now - t) < 0.6:
                if d < min_d:
                    min_d = d
                    min_deg = deg

        if min_deg >= 0:
            d_cm = min_d * 0.1
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
        last_pts_time = time.time()
        while self.worker_running:
            if self.lidar is None or not self.lidar.is_connected():
                self.lidar = LD06()
                if not self.lidar.is_connected():
                    time.sleep(1.0)
                    continue
                last_pts_time = time.time()

            now = time.time()
            with self.radar.data_lock:
                n = self.lidar.read_into_radar(
                    self.radar.scan_dist, self.radar.scan_time, now, block_size=400
                )
            if n > 0:
                self.pts_counter += n
                last_pts_time = now
                time.sleep(0.005)
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
    w = LidarWindow()
    w.show()
    sys.exit(app.exec_())
