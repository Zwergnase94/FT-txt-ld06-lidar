#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LD06 8-Zonen LiDAR Dashboard App für den Fischertechnik TXT Controller.
Zeigt die Mindestabstände in 8 Richtungen (Vorne, V-Rechts, Rechts, H-Rechts,
Hinten, H-Links, Links, V-Links) in Echtzeit auf dem 240x320 Touchscreen an.
Hocheffiziente QPixmap-Pufferung und Zero-Allocation-Parsing für minimale CPU-Last.
"""

import sys
import os
import time
import math
import threading

sys.path.append('/opt/ftc')
sys.path.append(os.path.dirname(os.path.realpath(__file__)))

from PyQt5.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPolygonF, QPixmap
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
DIR_LABELS = ['V', 'VR', 'R', 'HR', 'H', 'HL', 'L', 'VL']

DIR_ANGLES_RAD = [math.radians(i * 45) for i in range(8)]
DIV_ANGLES_RAD = [math.radians(i * 45 + 22.5) for i in range(8)]


class SectorDashboardWidget(QWidget):
    """Zeichnet die grafische 8-Zonen-Ansicht und die Messwert-Tabelle mit vorberechnetem Hintergrund."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(240, 280)
        self.sector_data = [(0, 0, 0.0)] * 8
        self.data_lock = threading.Lock()
        self.pts_per_sec = 0

        # Vorallozierte Grafik-Ressourcen
        self.pen_grid = QPen(QColor(0, 140, 110, 130), 1, Qt.DashLine)
        self.pen_card_border = QPen(QColor(30, 50, 75), 1)
        self.pen_robot_body = QPen(QColor(100, 160, 220), 1)

        self.brush_bg = QBrush(QColor(10, 14, 20))
        self.brush_card_bg = QBrush(QColor(16, 26, 38))
        self.brush_robot_body = QBrush(QColor(20, 45, 75))
        self.brush_robot_wheel = QBrush(QColor(50, 65, 80))
        self.brush_robot_arrow = QBrush(QColor(0, 220, 255))

        self.brush_badge_red = QBrush(QColor(220, 45, 45))
        self.brush_badge_yellow = QBrush(QColor(240, 180, 0))
        self.brush_badge_green = QBrush(QColor(0, 160, 120))
        self.brush_badge_inactive = QBrush(QColor(35, 45, 55))

        self.color_pie_red = QColor(255, 45, 45, 210)
        self.color_pie_yellow = QColor(255, 190, 0, 190)
        self.color_pie_green = QColor(0, 225, 200, 170)

        self.color_fg_white = QColor(255, 255, 255)
        self.color_fg_black = QColor(0, 0, 0)
        self.color_fg_dim = QColor(100, 115, 130)
        self.color_dir_lbl = QColor(0, 230, 200)
        self.color_name_lbl = QColor(180, 205, 225)
        self.color_pts_lbl = QColor(120, 150, 175)

        self.font_bold_8 = QFont('Liberation Sans', 8, QFont.Bold)
        self.font_status_7 = QFont('Liberation Sans', 7)

        # Statischer Hintergrund (nur 1x rendern -> spart ~80 % Rendering-CPU)
        self.bg_pixmap = QPixmap(240, 280)
        self._render_static_background()

    def _render_static_background(self):
        p = QPainter(self.bg_pixmap)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(0, 0, 240, 280, self.brush_bg)

        cx = 120.0
        cy = 74.0
        r_outer = 64.0
        r_inner = 23.0

        p.setPen(self.pen_grid)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r_outer, r_outer)
        p.drawEllipse(QPointF(cx, cy), r_inner, r_inner)

        for i in range(8):
            sin_a = math.sin(DIV_ANGLES_RAD[i])
            cos_a = math.cos(DIV_ANGLES_RAD[i])
            p.drawLine(int(cx + r_inner * sin_a), int(cy - r_inner * cos_a),
                       int(cx + r_outer * sin_a), int(cy - r_outer * cos_a))

        p.setFont(self.font_bold_8)
        p.setPen(self.color_dir_lbl)
        for i in range(8):
            lx = cx + (r_outer + 9) * math.sin(DIR_ANGLES_RAD[i])
            ly = cy - (r_outer + 9) * math.cos(DIR_ANGLES_RAD[i])
            p.drawText(QRectF(lx - 12, ly - 7, 24, 14), Qt.AlignCenter, DIR_LABELS[i])

        # Roboter-Fahrzeugsymbol in der Mitte
        p.setPen(self.pen_robot_body)
        p.setBrush(self.brush_robot_body)
        p.drawRoundedRect(QRectF(cx - 10, cy - 14, 20, 28), 3, 3)

        p.setBrush(self.brush_robot_wheel)
        p.drawRect(int(cx - 13), int(cy - 12), 3, 8)
        p.drawRect(int(cx - 13), int(cy + 4), 3, 8)
        p.drawRect(int(cx + 10), int(cy - 12), 3, 8)
        p.drawRect(int(cx + 10), int(cy + 4), 3, 8)

        p.setPen(Qt.NoPen)
        p.setBrush(self.brush_robot_arrow)
        arrow = QPolygonF([
            QPointF(cx, cy - 11),
            QPointF(cx + 5, cy - 2),
            QPointF(cx, cy - 5),
            QPointF(cx - 5, cy - 2)
        ])
        p.drawPolygon(arrow)

        # 8 Karten-Rahmen & Beschriftungen
        card_w = 110.0
        card_h = 24.0
        start_y = 153.0
        spacing_y = 27.0
        for col in range(2):
            for row in range(4):
                idx = col * 4 + row
                name, deg_str = SECTOR_NAMES[idx]
                bx = 8.0 if col == 0 else 122.0
                by = start_y + row * spacing_y

                p.setPen(self.pen_card_border)
                p.setBrush(self.brush_card_bg)
                p.drawRoundedRect(QRectF(bx, by, card_w, card_h), 4, 4)

                p.setFont(self.font_bold_8)
                p.setPen(self.color_name_lbl)
                p.drawText(QRectF(bx + 6, by, 58, card_h), Qt.AlignVCenter | Qt.AlignLeft, name)

        p.end()

    def update_sectors(self, sector_values, pts_rate):
        with self.data_lock:
            self.sector_data = list(sector_values)
            self.pts_per_sec = pts_rate
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        # 1. Vorberechneten Hintergrund blitzschnell blitten (1 Draw Call)
        painter.drawPixmap(0, 0, self.bg_pixmap)

        now = time.time()
        with self.data_lock:
            sectors = list(self.sector_data)
            pts_rate = self.pts_per_sec

        cx = 120.0
        cy = 74.0
        r_outer = 64.0
        r_inner = 23.0

        # 2. Nur die dynamischen Warnbögen zeichnen
        for i in range(8):
            dist_mm, avg_mm, t = sectors[i]
            if dist_mm > 0 and (now - t < 1.0):
                d_cm = dist_mm * 0.1
                if d_cm < 30:
                    fill_col = self.color_pie_red
                elif d_cm < 80:
                    fill_col = self.color_pie_yellow
                else:
                    fill_col = self.color_pie_green

                ratio = max(0.25, min(1.0, 1.0 - (d_cm / 160.0)))
                r_bar = r_inner + ratio * (r_outer - r_inner)

                start_angle = int((90 - i * 45 - 22.5) * 16)
                span_angle = int(45 * 16)

                rect_bar = QRectF(cx - r_bar, cy - r_bar, r_bar * 2, r_bar * 2)
                rect_in = QRectF(cx - r_inner, cy - r_inner, r_inner * 2, r_inner * 2)

                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(fill_col))
                painter.drawPie(rect_bar, start_angle, span_angle)

                painter.setBrush(self.brush_bg)
                painter.drawEllipse(rect_in)

        # 3. Dynamische Messwert-Badges
        card_w = 110.0
        card_h = 24.0
        start_y = 153.0
        spacing_y = 27.0
        badge_w = 42.0
        badge_h = 18.0

        min_overall_d = 99999
        min_overall_name = ''

        painter.setFont(self.font_bold_8)
        for col in range(2):
            for row in range(4):
                idx = col * 4 + row
                dist_mm, avg_mm, t = sectors[idx]
                is_active = (dist_mm > 0) and (now - t < 1.0)

                bx = 8.0 if col == 0 else 122.0
                by = start_y + row * spacing_y
                badge_x = bx + card_w - badge_w - 4.0
                badge_y = by + (card_h - badge_h) * 0.5

                if is_active:
                    d_cm = dist_mm * 0.1
                    if dist_mm < min_overall_d:
                        min_overall_d = dist_mm
                        min_overall_name = SECTOR_NAMES[idx][0]

                    if d_cm < 30:
                        badge_bg = self.brush_badge_red
                        badge_fg = self.color_fg_white
                    elif d_cm < 80:
                        badge_bg = self.brush_badge_yellow
                        badge_fg = self.color_fg_black
                    else:
                        badge_bg = self.brush_badge_green
                        badge_fg = self.color_fg_white

                    txt_val = f'{d_cm:.0f} cm' if d_cm < 100 else f'{int(d_cm)} cm'
                else:
                    badge_bg = self.brush_badge_inactive
                    badge_fg = self.color_fg_dim
                    txt_val = '---'

                painter.setPen(Qt.NoPen)
                painter.setBrush(badge_bg)
                painter.drawRoundedRect(QRectF(badge_x, badge_y, badge_w, badge_h), 3, 3)

                painter.setPen(badge_fg)
                painter.drawText(QRectF(badge_x, badge_y, badge_w, badge_h), Qt.AlignCenter, txt_val)

        # 4. Statuszeile ganz unten
        painter.setFont(self.font_status_7)
        painter.setPen(self.color_pts_lbl)
        h = self.height()
        painter.drawText(QRectF(8, h - 16, 100, 14), Qt.AlignVCenter | Qt.AlignLeft, f'{pts_rate} Pkt/s')

        if min_overall_d < 99999:
            min_cm = min_overall_d * 0.1
            warn_col = self.brush_badge_red.color() if min_cm < 30 else (self.brush_badge_yellow.color() if min_cm < 80 else self.color_dir_lbl)
            painter.setPen(warn_col)
            painter.drawText(QRectF(108, h - 16, 124, 14), Qt.AlignVCenter | Qt.AlignRight, f'Min: {min_cm:.0f}cm ({min_overall_name})')
        else:
            painter.setPen(self.brush_badge_yellow.color())
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

        # 8 Sektor-Slots direkt als skalare Werte (0 Speicherallokation im Worker)
        self.sec_min = [99999] * 8
        self.sec_sum = [0] * 8
        self.sec_cnt = [0] * 8
        self.sec_time = [0.0] * 8
        self.sector_lock = threading.Lock()

        self.dashboard = SectorDashboardWidget(self)
        self.setCentralWidget(self.dashboard)

        # Hintergrund-Thread für serielle Daten
        self.thread = threading.Thread(target=self._lidar_worker, daemon=True)
        self.thread.start()

        # UI-Timer: 5 FPS (200ms) - vollkommen flüssig und extrem ressourcenschonend für 600 MHz ARM
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_ui_tick)
        self.timer.start(200)

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
                if self.sec_cnt[i] > 0:
                    min_d = self.sec_min[i]
                    avg_d = self.sec_sum[i] // self.sec_cnt[i]
                    t = self.sec_time[i]
                    sec_snapshot.append((min_d, avg_d, t))
                else:
                    prev_t = self.sec_time[i]
                    if prev_t > 0 and (now - prev_t) < 1.0:
                        sec_snapshot.append((self.sec_min[i], 0, prev_t))
                    else:
                        sec_snapshot.append((0, 0, 0.0))

            self.sec_min = [99999] * 8
            self.sec_sum = [0] * 8
            self.sec_cnt = [0] * 8

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

            now = time.time()
            with self.sector_lock:
                n = self.lidar.read_into_sectors(
                    self.sec_min, self.sec_sum, self.sec_cnt, self.sec_time, now, block_size=400
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
    w = LidarSectorsWindow()
    w.show()
    sys.exit(app.exec_())
