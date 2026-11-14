#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Omni 8-Zonen App für den fischertechnik TXT Controller (ftcommunity-TXT).
Baut auf der 8-Zonen LiDAR-App auf und steuert einen 4-Rad Omniwheel-Roboter (M1-M4):
  - Linker Joystick (alle 8 Richtungen: V, VR, R, HR, H, HL, L, VL):
    Fährt in die gewählte Richtung, reduziert ab 30 cm (300 mm) schrittweise
    die Geschwindigkeit bis auf 18 cm (180 mm) und bleibt bei <= 18 cm komplett stehen.
  - Rechter Joystick (Links / Rechts):
    Dreht den Roboter auf der Stelle um die eigene Achse.
Kompatibel mit alter Firmware (1.1.4 / Kernel 4.14 / Python 3.8) und
neuer Firmware (Kernel 6.12 / Python 3.14), inkl. BT Control Set & IR-Fernbedienung.
"""

import sys
import os
import time
import math
import struct
import signal
import atexit
import threading
import subprocess

sys.path.append('/opt/ftc')
sys.path.append(os.path.dirname(os.path.realpath(__file__)))

from PyQt5.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPolygonF, QPixmap
from PyQt5.QtWidgets import QWidget
from TouchStyle import TouchApplication, TouchWindow

try:
    import ftrobopy
except Exception:
    ftrobopy = None

from ld06 import LD06

# Sicherheits- & Bremsabstände:
# Ab 30 cm (300 mm) wird die Geschwindigkeit schrittweise reduziert,
# bei <= 18 cm (180 mm) wird komplett gestoppt!
STOP_DIST_MM = 180       # 18.0 cm Stopp-Schwelle
RELEASE_DIST_MM = 185    # 18.5 cm Freigabe-Hysterese gegen Ruckeln an der Stopp-Grenze
SLOW_DIST_MM = 300       # 30.0 cm Beginn der schrittweisen Geschwindigkeitsreduzierung
WARN_DIST_CM = 30.0      # Gelbe Brems-/Warnzone unter 30 cm (18..30 cm)

# Motor- & Joystick-Parameter
MAX_SPEED = 512
MIN_SPEED = 160
DEADZONE = 0.16          # 16 % Joystick-Totzone

# Definition der 8 Sektoren (passend zu LD06.read_into_sectors)
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

# 4-Rad Omniwheel Kinematik (M1..M4 Vorzeichen für Sektor 0..7):
# +1 = CCW (Vorwärts), -1 = CW (Rückwärts), 0 = Stopp
# Diagonale 1: (M1, M4), Diagonale 2: (M2, M3)
SECTOR_MOTOR_SIGNS = [
    (+1, +1, +1, +1),  # 0: Vorne (0°)
    ( 0, +1, +1,  0),  # 1: V-Rechts (45°)
    (-1, +1, +1, -1),  # 2: Rechts (90°)
    (-1,  0,  0, -1),  # 3: H-Rechts (135°)
    (-1, -1, -1, -1),  # 4: Hinten (180°)
    ( 0, -1, -1,  0),  # 5: H-Links (225°)
    (+1, -1, -1, +1),  # 6: Links (270°)
    (+1,  0,  0, +1),  # 7: V-Links (315°)
]

# Drehung um die eigene Achse (Linke Seite M1/M3 gegen Rechte Seite M2/M4):
ROTATE_RIGHT_SIGNS = (+1, -1, +1, -1)  # Rechts drehen (im Uhrzeigersinn)
ROTATE_LEFT_SIGNS  = (-1, +1, -1, +1)  # Links drehen (gegen den Uhrzeigersinn)


class DualJoystickReader(object):
    """
    Liest verzögerungsfrei sowohl die blaue fischertechnik Bluetooth-Fernbedienung
    (/dev/input/js0 via ft_bt_remote_server) als auch die rote IR-Fernbedienung
    (über ftrobopy) auf alter (Kernel 4.14) und neuer (Kernel 6.12) Firmware aus.
    """

    def __init__(self, txt=None):
        self.txt = txt
        self.js_fd = None
        self.last_open_try = 0.0
        self.bt_server_started = False

        # Normierte Achsenwerte (-1.0 .. +1.0) für BT (/dev/input/js0)
        self.bt_lx = 0.0
        self.bt_ly = 0.0
        self.bt_rx = 0.0
        self.bt_ry = 0.0

        # IR-Joysticks über ftrobopy (falls verfügbar)
        self.ir_left = None
        self.ir_right = None
        if self.txt is not None:
            try:
                self.ir_left = self.txt.joystick(0, 0, 0)
                self.ir_right = self.txt.joystick(1, 0, 0)
            except Exception:
                self.ir_left = None
                self.ir_right = None

        self._ensure_bt_server()
        self._try_open_js0()

    def _ensure_bt_server(self):
        """Startet ft_bt_remote_start.sh automatisch im Hintergrund, falls noch nicht aktiv."""
        if self.bt_server_started:
            return
        self.bt_server_started = True
        if os.path.exists('/dev/input/js0'):
            return
        if os.path.exists('/usr/bin/ft_bt_remote_start.sh'):
            try:
                res = subprocess.run(
                    ['pidof', 'ft_bt_remote_server'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if res.returncode != 0:
                    subprocess.Popen(
                        ['sudo', '-n', '/usr/bin/ft_bt_remote_start.sh'],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
            except Exception:
                pass

    def restart_bt_server(self):
        self.close()
        self.bt_server_started = False
        self._ensure_bt_server()

    def _try_open_js0(self):
        if self.js_fd is not None:
            return True
        now = time.time()
        if (now - self.last_open_try) < 1.0:
            return False
        self.last_open_try = now
        if not os.path.exists('/dev/input/js0'):
            return False
        try:
            self.js_fd = os.open('/dev/input/js0', os.O_RDONLY | os.O_NONBLOCK)
            return True
        except Exception:
            self.js_fd = None
            return False

    @staticmethod
    def _norm_js_axis(val, invert=False):
        if invert:
            val = -val
        if val < 0:
            res = val / 32767.0
        else:
            res = val / 32512.0
        return max(-1.0, min(1.0, res))

    def poll(self):
        """
        Gibt (lx, ly, rx, ry) im Bereich [-1.0 .. +1.0] zurück:
          lx: Links (-1.0) .. Rechts (+1.0)
          ly: Hinten (-1.0) .. Vorne (+1.0)
          rx: Links drehen (-1.0) .. Rechts drehen (+1.0)
          ry: Unten (-1.0) .. Oben (+1.0)
        """
        if self.js_fd is None:
            self._try_open_js0()

        if self.js_fd is not None:
            while True:
                try:
                    buf = os.read(self.js_fd, 8)
                    if not buf or len(buf) < 8:
                        break
                    _, val, evt_type, axis_num = struct.unpack('IhBB', buf)
                    if evt_type & 0x02:  # JS_EVENT_AXIS
                        if axis_num == 0:
                            self.bt_lx = self._norm_js_axis(val, invert=False)
                        elif axis_num == 1:
                            # Bei ft_bt_remote_server ist Oben (Vorne) negativ
                            self.bt_ly = self._norm_js_axis(val, invert=True)
                        elif axis_num == 2:
                            self.bt_rx = self._norm_js_axis(val, invert=False)
                        elif axis_num == 3:
                            self.bt_ry = self._norm_js_axis(val, invert=True)
                except BlockingIOError:
                    break
                except OSError:
                    try:
                        os.close(self.js_fd)
                    except Exception:
                        pass
                    self.js_fd = None
                    self.bt_lx = 0.0
                    self.bt_ly = 0.0
                    self.bt_rx = 0.0
                    self.bt_ry = 0.0
                    break

        ir_lx = 0.0
        ir_ly = 0.0
        ir_rx = 0.0
        ir_ry = 0.0
        if self.ir_left is not None and self.ir_right is not None:
            try:
                ir_lx = float(self.ir_left.leftright())
                ir_ly = float(self.ir_left.updown())
                ir_rx = float(self.ir_right.leftright())
                ir_ry = float(self.ir_right.updown())
            except Exception:
                pass

        # Kombiniere BT- und IR-Joystick (stärkerer Ausschlag gewinnt)
        lx = self.bt_lx if abs(self.bt_lx) >= abs(ir_lx) else ir_lx
        ly = self.bt_ly if abs(self.bt_ly) >= abs(ir_ly) else ir_ly
        rx = self.bt_rx if abs(self.bt_rx) >= abs(ir_rx) else ir_rx
        ry = self.bt_ry if abs(self.bt_ry) >= abs(ir_ry) else ir_ry
        return lx, ly, rx, ry

    def close(self):
        if self.js_fd is not None:
            try:
                os.close(self.js_fd)
            except Exception:
                pass
            self.js_fd = None


class OmniSectorDashboardWidget(QWidget):
    """
    Zeichnet die 8-Zonen-Ansicht, die 18cm-Stopp-Grenze (Bremszone ab 30 cm), die aktiven
    Joystick-Befehle (8 Fahrtrichtungen + Drehung um die eigene Achse) und die 8 Distanz-Badges.
    """

    def __init__(self, parent=None, on_center_tap=None):
        super().__init__(parent)
        self.setFixedSize(240, 280)
        self.on_center_tap = on_center_tap

        self.sector_data = [(0, 0, 0.0)] * 8
        self.pts_per_sec = 0

        # Steuerstatus für Visualisierung
        self.cmd_sector = None       # 0..7 wenn linker Stick aktiv, sonst None
        self.cmd_blocked = False     # True wenn Richtung durch <= 18 cm blockiert
        self.cmd_rotate = 0          # -1 = Links drehen, +1 = Rechts drehen, 0 = keine Drehung
        self.drive_enabled = True
        self.status_text = 'BEREIT'
        self.status_mode = 'IDLE'    # 'DRIVE', 'SLOW', 'BLOCKED', 'ROTATE', 'PAUSED', 'IDLE'
        self._last_ui_key = None

        # Vorallozierte Grafik-Ressourcen
        self.pen_grid = QPen(QColor(0, 140, 110, 130), 1, Qt.DashLine)
        self.pen_stop_ring = QPen(QColor(255, 60, 60, 190), 1, Qt.DotLine)
        self.pen_card_border = QPen(QColor(30, 50, 75), 1)
        self.pen_card_drive = QPen(QColor(0, 240, 220), 2)
        self.pen_card_block = QPen(QColor(255, 50, 50), 2)
        self.pen_robot_body = QPen(QColor(100, 160, 220), 1)
        self.pen_rot_arc = QPen(QColor(0, 230, 255), 2)
        self.pen_sel_drive = QPen(QColor(0, 255, 220), 2)
        self.pen_sel_block = QPen(QColor(255, 60, 60), 2)

        self.brush_bg = QBrush(QColor(10, 14, 20))
        self.brush_card_bg = QBrush(QColor(16, 26, 38))
        self.brush_card_drive = QBrush(QColor(14, 48, 58))
        self.brush_card_block = QBrush(QColor(60, 18, 22))
        self.brush_robot_body = QBrush(QColor(20, 45, 75))
        self.brush_robot_paused = QBrush(QColor(55, 40, 25))
        self.brush_robot_wheel = QBrush(QColor(220, 165, 20))
        self.brush_robot_arrow = QBrush(QColor(0, 220, 255))
        self.brush_arrow_drive = QBrush(QColor(0, 255, 180))
        self.brush_arrow_block = QBrush(QColor(255, 55, 55))

        self.brush_badge_red = QBrush(QColor(220, 45, 45))
        self.brush_badge_yellow = QBrush(QColor(240, 180, 0))
        self.brush_badge_green = QBrush(QColor(0, 160, 120))
        self.brush_badge_inactive = QBrush(QColor(35, 45, 55))

        self.brush_pie_red = QBrush(QColor(255, 40, 40, 220))
        self.brush_pie_yellow = QBrush(QColor(255, 190, 0, 185))
        self.brush_pie_green = QBrush(QColor(0, 225, 200, 165))

        self.color_fg_white = QColor(255, 255, 255)
        self.color_fg_black = QColor(0, 0, 0)
        self.color_fg_dim = QColor(100, 115, 130)
        self.color_dir_lbl = QColor(0, 230, 200)
        self.color_name_lbl = QColor(180, 205, 225)
        self.color_status_drive = QColor(0, 255, 180)
        self.color_status_block = QColor(255, 75, 75)
        self.color_status_rotate = QColor(0, 225, 255)
        self.color_status_idle = QColor(150, 180, 205)

        self.font_bold_8 = QFont('Liberation Sans', 8, QFont.Bold)
        self.font_status_7 = QFont('Liberation Sans', 7, QFont.Bold)

        # Vorberechnete Karten- und Badge-Rechtecke
        self._card_rects = []
        self._badge_rects = []
        card_w = 110.0
        card_h = 24.0
        start_y = 153.0
        spacing_y = 27.0
        badge_w = 42.0
        badge_h = 18.0
        for col in range(2):
            bx = 8.0 if col == 0 else 122.0
            for row in range(4):
                by = start_y + row * spacing_y
                self._card_rects.append(QRectF(bx, by, card_w, card_h))
                self._badge_rects.append(QRectF(
                    bx + card_w - badge_w - 4.0,
                    by + (card_h - badge_h) * 0.5,
                    badge_w,
                    badge_h,
                ))

        self._rect_inner = QRectF(120.0 - 23.0, 74.0 - 23.0, 46.0, 46.0)
        self._rect_status = QRectF(8, 280 - 17, 138, 15)
        self._rect_min = QRectF(146, 280 - 17, 86, 15)

        # Statischer Hintergrund (nur 1x rendern für minimale CPU-Last)
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
        # 18 cm Stopp-Ring (bei näherem Abstand = größerer Warnbalken nahe r_stop)
        r_stop = r_inner + (1.0 - (18.0 / 160.0)) * (r_outer - r_inner)

        p.setPen(self.pen_grid)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r_outer, r_outer)
        p.drawEllipse(QPointF(cx, cy), r_inner, r_inner)

        p.setPen(self.pen_stop_ring)
        p.drawEllipse(QPointF(cx, cy), r_stop, r_stop)

        p.setPen(self.pen_grid)
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

        # 8 Karten-Rahmen & Beschriftungen im statischen Hintergrund
        card_w = 110.0
        card_h = 24.0
        start_y = 153.0
        spacing_y = 27.0
        for col in range(2):
            for row in range(4):
                idx = col * 4 + row
                name, _ = SECTOR_NAMES[idx]
                bx = 8.0 if col == 0 else 122.0
                by = start_y + row * spacing_y

                p.setPen(self.pen_card_border)
                p.setBrush(self.brush_card_bg)
                p.drawRoundedRect(QRectF(bx, by, card_w, card_h), 4, 4)

                p.setFont(self.font_bold_8)
                p.setPen(self.color_name_lbl)
                p.drawText(QRectF(bx + 6, by, 58, card_h), Qt.AlignVCenter | Qt.AlignLeft, name)

        p.end()

    def mousePressEvent(self, event):
        # Tippen auf das Roboter-Symbol in der Mitte schaltet Fahren AN/AUS um
        dx = event.x() - 120.0
        dy = event.y() - 74.0
        if (dx * dx + dy * dy) <= (28.0 * 28.0) and self.on_center_tap is not None:
            self.on_center_tap()
        super().mousePressEvent(event)

    def update_state(self, sector_values, pts_rate, cmd_sector, cmd_blocked,
                     cmd_rotate, drive_enabled, status_text, status_mode):
        self.sector_data = sector_values
        self.pts_per_sec = pts_rate
        self.cmd_sector = cmd_sector
        self.cmd_blocked = cmd_blocked
        self.cmd_rotate = cmd_rotate
        self.drive_enabled = drive_enabled
        self.status_text = status_text
        self.status_mode = status_mode

        now = time.time()
        ui_key = (
            tuple((d // 10) if (d > 0 and (now - t) < 1.0) else -1 for d, _, t in sector_values),
            cmd_sector,
            cmd_blocked,
            cmd_rotate,
            drive_enabled,
            status_text,
        )
        if ui_key != self._last_ui_key:
            self._last_ui_key = ui_key
            self.update()

    def _draw_robot_center(self, painter, cx, cy):
        # Roboter-Chassis
        painter.setPen(self.pen_robot_body)
        painter.setBrush(self.brush_robot_body if self.drive_enabled else self.brush_robot_paused)
        painter.drawRoundedRect(QRectF(cx - 10, cy - 14, 20, 28), 3, 3)

        # 4 Omniwheels
        painter.setBrush(self.brush_robot_wheel)
        painter.drawRect(int(cx - 13), int(cy - 12), 3, 8)
        painter.drawRect(int(cx - 13), int(cy + 4), 3, 8)
        painter.drawRect(int(cx + 10), int(cy - 12), 3, 8)
        painter.drawRect(int(cx + 10), int(cy + 4), 3, 8)

        # Richtungspfeil oder Drehpfeil in der Mitte
        if self.cmd_rotate != 0:
            painter.setPen(self.pen_rot_arc)
            painter.setBrush(Qt.NoBrush)
            rect_rot = QRectF(cx - 17, cy - 17, 34, 34)
            painter.drawArc(rect_rot, 30 * 16, 300 * 16)
            painter.setFont(self.font_bold_8)
            painter.setPen(self.color_status_rotate)
            rot_sym = 'R' if self.cmd_rotate > 0 else 'L'
            painter.drawText(QRectF(cx - 10, cy - 8, 20, 16), Qt.AlignCenter, rot_sym)
        elif self.cmd_sector is not None:
            ang = DIR_ANGLES_RAD[self.cmd_sector]
            sin_a = math.sin(ang)
            cos_a = math.cos(ang)
            # Gedrehter Richtungspfeil in Joystick-Richtung
            tip = QPointF(cx + 13.0 * sin_a, cy - 13.0 * cos_a)
            left_pt = QPointF(cx - 4.0 * sin_a - 5.5 * cos_a, cy + 4.0 * cos_a - 5.5 * sin_a)
            back_pt = QPointF(cx - 1.5 * sin_a, cy + 1.5 * cos_a)
            right_pt = QPointF(cx - 4.0 * sin_a + 5.5 * cos_a, cy + 4.0 * cos_a + 5.5 * sin_a)
            painter.setPen(Qt.NoPen)
            painter.setBrush(self.brush_arrow_block if self.cmd_blocked else self.brush_arrow_drive)
            painter.drawPolygon(QPolygonF([tip, right_pt, back_pt, left_pt]))
        else:
            painter.setPen(Qt.NoPen)
            painter.setBrush(self.brush_robot_arrow)
            arrow = QPolygonF([
                QPointF(cx, cy - 11),
                QPointF(cx + 5, cy - 2),
                QPointF(cx, cy - 5),
                QPointF(cx - 5, cy - 2),
            ])
            painter.drawPolygon(arrow)

    def paintEvent(self, event):
        painter = QPainter(self)

        # 1. Vorberechneten Hintergrund blitten
        painter.drawPixmap(0, 0, self.bg_pixmap)

        now = time.time()
        cutoff = now - 1.0
        sectors = self.sector_data

        cx = 120.0
        cy = 74.0
        r_outer = 64.0
        r_inner = 23.0

        # 2. Dynamische Sektor-Warnbögen (Rot <= 18 cm Stopp, Gelb <= 30 cm Bremszone)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        has_pie = False
        for i in range(8):
            dist_mm, _, t = sectors[i]
            if dist_mm > 0 and t > cutoff:
                has_pie = True
                d_cm = dist_mm * 0.1
                if dist_mm <= STOP_DIST_MM:
                    pie_brush = self.brush_pie_red
                elif dist_mm <= SLOW_DIST_MM:
                    pie_brush = self.brush_pie_yellow
                else:
                    pie_brush = self.brush_pie_green

                ratio = max(0.25, min(1.0, 1.0 - (d_cm / 160.0)))
                r_bar = r_inner + ratio * (r_outer - r_inner)
                start_angle = int((90 - i * 45 - 22.5) * 16)
                rect_bar = QRectF(cx - r_bar, cy - r_bar, r_bar * 2, r_bar * 2)

                painter.setBrush(pie_brush)
                painter.drawPie(rect_bar, start_angle, 720)

        # Aktiven Joystick-Sektor im Radar hervorheben
        if self.cmd_sector is not None:
            painter.setPen(self.pen_sel_block if self.cmd_blocked else self.pen_sel_drive)
            painter.setBrush(Qt.NoBrush)
            start_angle = int((90 - self.cmd_sector * 45 - 22.5) * 16)
            rect_sel = QRectF(cx - r_outer, cy - r_outer, r_outer * 2, r_outer * 2)
            painter.drawPie(rect_sel, start_angle, 720)

        if has_pie or self.cmd_sector is not None:
            painter.setPen(Qt.NoPen)
            painter.setBrush(self.brush_bg)
            painter.drawEllipse(self._rect_inner)

        self._draw_robot_center(painter, cx, cy)
        painter.setRenderHint(QPainter.Antialiasing, False)

        # 3. Dynamische Messwert-Badges & Hervorhebung der aktiven Richtungskarte
        min_overall_d = 99999
        min_overall_short = ''

        painter.setFont(self.font_bold_8)
        for idx in range(8):
            dist_mm, _, t = sectors[idx]
            is_active = dist_mm > 0 and t > cutoff
            rect_card = self._card_rects[idx]
            rect_badge = self._badge_rects[idx]

            # Falls dieser Sektor vom linken Joystick gewählt ist, Kartenrahmen hervorheben
            if idx == self.cmd_sector:
                painter.setPen(self.pen_card_block if self.cmd_blocked else self.pen_card_drive)
                painter.setBrush(self.brush_card_block if self.cmd_blocked else self.brush_card_drive)
                painter.drawRoundedRect(rect_card, 4, 4)
                painter.setPen(self.color_fg_white)
                painter.drawText(
                    QRectF(rect_card.x() + 6, rect_card.y(), 58, rect_card.height()),
                    Qt.AlignVCenter | Qt.AlignLeft,
                    SECTOR_NAMES[idx][0],
                )

            if is_active:
                d_cm = dist_mm * 0.1
                if dist_mm < min_overall_d:
                    min_overall_d = dist_mm
                    min_overall_short = DIR_LABELS[idx]

                if dist_mm <= STOP_DIST_MM:
                    badge_bg = self.brush_badge_red
                    badge_fg = self.color_fg_white
                elif dist_mm <= SLOW_DIST_MM:
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
            painter.drawRoundedRect(rect_badge, 3, 3)

            painter.setPen(badge_fg)
            painter.drawText(rect_badge, Qt.AlignCenter, txt_val)

        # 4. Statuszeile ganz unten (Fahr-/Brems-/Blockierstatus links, Minimalabstand rechts)
        painter.setFont(self.font_status_7)
        if self.status_mode == 'BLOCKED':
            st_col = self.color_status_block
        elif self.status_mode == 'SLOW':
            st_col = self.brush_badge_yellow.color()
        elif self.status_mode == 'DRIVE':
            st_col = self.color_status_drive
        elif self.status_mode == 'ROTATE':
            st_col = self.color_status_rotate
        elif self.status_mode == 'PAUSED':
            st_col = self.brush_badge_yellow.color()
        else:
            st_col = self.color_status_idle

        painter.setPen(st_col)
        painter.drawText(self._rect_status, Qt.AlignVCenter | Qt.AlignLeft, self.status_text)

        if min_overall_d < 99999:
            min_cm = min_overall_d * 0.1
            warn_col = self.brush_badge_red.color() if min_overall_d <= STOP_DIST_MM else (
                self.brush_badge_yellow.color() if min_overall_d <= SLOW_DIST_MM else self.color_dir_lbl
            )
            painter.setPen(warn_col)
            painter.drawText(
                self._rect_min, Qt.AlignVCenter | Qt.AlignRight,
                f'Min:{min_cm:.0f}cm({min_overall_short})',
            )
        else:
            painter.setPen(self.brush_badge_yellow.color())
            painter.drawText(self._rect_min, Qt.AlignVCenter | Qt.AlignRight, 'Warte LiDAR')

        painter.end()


class LidarOmniWindow(TouchWindow):
    """
    Hauptfenster für die Omni 8-Zonen App:
    Kombiniert den 8-Zonen LiDAR-Scanner mit der 8-Wege Joystick-Steuerung (Linker Stick),
    der 30->18cm Bremsrampe mit Kollisionsstopp und der Drehung um die eigene Achse (Rechter Stick).
    """

    def __init__(self):
        super().__init__('Omni 8-Zonen')

        self.lidar = None
        self.worker_running = True
        self.pts_per_sec = 0
        self.pts_counter = 0
        self.pts_timer_t0 = time.time()
        self.last_any_pts_time = 0.0

        # 8 Sektor-Slots (0 Speicherallokation im LiDAR-Thread)
        self.sec_min = [99999] * 8
        self.sec_sum = [0] * 8
        self.sec_cnt = [0] * 8
        self.sec_time = [0.0] * 8
        self.last_display_min = [0] * 8
        self.sector_lock = threading.Lock()

        # Fahr- & Motor-Zustand
        self.drive_enabled = True
        self.invert_rotation = False
        self.blocked_sectors = [False] * 8
        self.last_motor_speeds = (0, 0, 0, 0)

        self.cmd_sector = None
        self.cmd_blocked = False
        self.cmd_rotate = 0
        self.status_text = 'BEREIT (>18cm frei)'
        self.status_mode = 'IDLE'

        # TXT Hardware & Motoren M1..M4 initialisieren
        self.txt = None
        self.motors = []
        self._init_txt_hardware()

        # Joystick-Leser (BT /dev/input/js0 + IR-Fernbedienung)
        self.joy = DualJoystickReader(self.txt)

        # Touch-Menü oben links
        try:
            menu = self.addMenu()
            self.act_toggle_drive = menu.addAction('Motoren: AN/AUS')
            self.act_toggle_drive.triggered.connect(self.toggle_drive_enabled)
            self.act_inv_rot = menu.addAction('Drehrichtung umkehren')
            self.act_inv_rot.triggered.connect(self.toggle_invert_rotation)
            self.act_bt = menu.addAction('BT-Fernbedienung verbinden')
            self.act_bt.triggered.connect(self.joy.restart_bt_server)
        except Exception:
            pass

        self.dashboard = OmniSectorDashboardWidget(self, on_center_tap=self.toggle_drive_enabled)
        self.setCentralWidget(self.dashboard)

        atexit.register(self.stop_motors)

        # Hintergrund-Thread für LiDAR-Daten
        self.thread = threading.Thread(target=self._lidar_worker, daemon=True)
        self.thread.start()

        # Schneller Regel-Timer für Joystick & 30->18cm Kollisionsschutz: 25 Hz (40 ms)
        self.ctrl_timer = QTimer(self)
        self.ctrl_timer.timeout.connect(self.on_control_tick)
        self.ctrl_timer.start(40)

        # UI-Darstellungs-Timer: 5 FPS (200 ms) für minimale CPU-Last
        self.ui_timer = QTimer(self)
        self.ui_timer.timeout.connect(self.on_ui_tick)
        self.ui_timer.start(200)

    def _init_txt_hardware(self):
        if ftrobopy is None:
            return
        try:
            # 25 Hz (0.04s) passend zur 25 Hz Regelschleife spart ~70 % ftrobopy-Thread-CPU & GIL-Wechsel
            self.txt = ftrobopy.ftrobopy('auto', update_interval=0.04)
            self.motors = [
                self.txt.motor(1),
                self.txt.motor(2),
                self.txt.motor(3),
                self.txt.motor(4),
            ]
            self.stop_motors()
        except Exception:
            self.txt = None
            self.motors = []

    def set_motor_speeds(self, s1, s2, s3, s4):
        target = (int(s1), int(s2), int(s3), int(s4))
        if target == self.last_motor_speeds:
            return
        self.last_motor_speeds = target
        if not self.motors or self.txt is None:
            return
        try:
            self.txt.SyncDataBegin()
            self.motors[0].setSpeed(target[0])
            self.motors[1].setSpeed(target[1])
            self.motors[2].setSpeed(target[2])
            self.motors[3].setSpeed(target[3])
            self.txt.SyncDataEnd()
        except Exception:
            for i, m in enumerate(self.motors):
                try:
                    m.setSpeed(target[i])
                except Exception:
                    pass

    def stop_motors(self):
        self.set_motor_speeds(0, 0, 0, 0)

    def toggle_drive_enabled(self):
        self.drive_enabled = not self.drive_enabled
        if not self.drive_enabled:
            self.stop_motors()

    def toggle_invert_rotation(self):
        self.invert_rotation = not self.invert_rotation

    def _get_live_sector_dist_mm(self, idx, now):
        """
        Liefert den aktuellsten Minimalabstand (in mm) für Sektor idx (0..7).
        Kombiniert das laufende Scan-Intervall (für sofortige <25ms Stopp-Reaktion)
        mit dem letzten vollständigen 360°-Scan-Fenster (lock-frei unter GIL).
        """
        cnt = self.sec_cnt[idx]
        cur_min = self.sec_min[idx] if cnt > 0 else 99999
        last_min = self.last_display_min[idx]
        last_t = self.sec_time[idx]

        if (now - last_t) >= 1.0:
            return 0
        if cnt > 0 and last_min > 0:
            return min(cur_min, last_min)
        if cnt > 0:
            return cur_min
        return last_min

    def _is_sector_blocked(self, idx, dist_mm):
        """Prüft mit kleiner Hysterese (18.0 cm Stopp / 18.5 cm Freigabe), ob <= 18 cm blockiert ist."""
        if dist_mm <= 0:
            self.blocked_sectors[idx] = False
            return False
        if self.blocked_sectors[idx]:
            if dist_mm > RELEASE_DIST_MM:
                self.blocked_sectors[idx] = False
        else:
            if dist_mm <= STOP_DIST_MM:
                self.blocked_sectors[idx] = True
        return self.blocked_sectors[idx]

    @staticmethod
    def _calc_motor_pwm(mag):
        """Skaliert den Joystick-Ausschlag (DEADZONE..1.0) auf Motortempo (MIN_SPEED..MAX_SPEED)."""
        norm = max(0.0, min(1.0, (mag - DEADZONE) / (1.0 - DEADZONE)))
        raw_speed = MIN_SPEED + norm * (MAX_SPEED - MIN_SPEED)
        return min(MAX_SPEED, int(round(raw_speed / 16.0) * 16))

    def on_control_tick(self):
        """25 Hz Echtzeit-Regelschleife für Joystick-Abfrage, 30->18cm Bremsrampe und Motorsteuerung."""
        now = time.time()
        lx, ly, rx, _ = self.joy.poll()

        if not self.drive_enabled:
            self.stop_motors()
            self.cmd_sector = None
            self.cmd_blocked = False
            self.cmd_rotate = 0
            self.status_mode = 'PAUSED'
            self.status_text = 'PAUSE (Mitte tippen)'
            return

        mag_left = min(1.0, math.hypot(lx, ly))
        abs_rx = min(1.0, abs(rx))

        # 1. Rechter Joystick: Drehung um die eigene Achse
        if abs_rx >= DEADZONE and abs_rx >= mag_left:
            rot_dir = 1 if rx > 0 else -1
            if self.invert_rotation:
                rot_dir = -rot_dir
            pwm = self._calc_motor_pwm(abs_rx)
            signs = ROTATE_RIGHT_SIGNS if rot_dir > 0 else ROTATE_LEFT_SIGNS
            self.set_motor_speeds(
                signs[0] * pwm,
                signs[1] * pwm,
                signs[2] * pwm,
                signs[3] * pwm,
            )
            self.cmd_sector = None
            self.cmd_blocked = False
            self.cmd_rotate = 1 if rx > 0 else -1
            self.status_mode = 'ROTATE'
            rot_lbl = 'Rechts' if rx > 0 else 'Links'
            self.status_text = f'DREHEN: {rot_lbl} ({int(abs_rx * 100)}%)'
            return

        self.cmd_rotate = 0

        # 2. Linker Joystick: Alle 8 Richtungen erkennen + 30->18cm Bremsrampe & 18cm Stopp
        if mag_left >= DEADZONE:
            angle_deg = math.degrees(math.atan2(lx, ly)) % 360.0
            sec_idx = int((angle_deg + 22.5) % 360.0 // 45.0)
            sec_name = SECTOR_NAMES[sec_idx][0]
            self.cmd_sector = sec_idx

            lidar_ready = (now - self.last_any_pts_time) < 1.5
            dist_mm = self._get_live_sector_dist_mm(sec_idx, now)

            if not lidar_ready:
                self.stop_motors()
                self.cmd_blocked = True
                self.status_mode = 'BLOCKED'
                self.status_text = 'STOPP (Warte LiDAR)'
                return

            if self._is_sector_blocked(sec_idx, dist_mm):
                # <= 18 cm (180 mm) -> komplett stehen bleiben!
                self.stop_motors()
                self.cmd_blocked = True
                self.status_mode = 'BLOCKED'
                d_cm = dist_mm * 0.1
                self.status_text = f'STOPP {sec_name} ({d_cm:.0f}cm<=18)'
                return

            # Mehr als 18 cm frei -> Fahrt in diese Richtung (ggf. ab 30 cm schrittweise gebremst)
            self.cmd_blocked = False
            joy_pwm = self._calc_motor_pwm(mag_left)

            if 0 < dist_mm <= SLOW_DIST_MM:
                # Schrittweise Geschwindigkeitsreduzierung zwischen 30 cm (300 mm) und 18 cm (180 mm)
                ratio = max(0.0, min(1.0, (dist_mm - STOP_DIST_MM) / float(SLOW_DIST_MM - STOP_DIST_MM)))
                raw_pwm = MIN_SPEED + ratio * (joy_pwm - MIN_SPEED)
                pwm = max(MIN_SPEED, min(joy_pwm, int(round(raw_pwm / 16.0) * 16)))
                self.status_mode = 'SLOW'
                d_cm = dist_mm * 0.1
                pct = int(round(pwm * 100.0 / MAX_SPEED))
                self.status_text = f'BREMSE {sec_name} ({d_cm:.0f}cm|{pct}%)'
            else:
                pwm = joy_pwm
                self.status_mode = 'DRIVE'
                if dist_mm > 0:
                    self.status_text = f'{sec_name} ({dist_mm * 0.1:.0f}cm frei)'
                else:
                    self.status_text = f'FAHRT: {sec_name} ({int(mag_left * 100)}%)'

            signs = SECTOR_MOTOR_SIGNS[sec_idx]
            self.set_motor_speeds(
                signs[0] * pwm,
                signs[1] * pwm,
                signs[2] * pwm,
                signs[3] * pwm,
            )
            return

        # 3. Beide Joysticks in Mittelstellung -> Stopp
        self.stop_motors()
        self.cmd_sector = None
        self.cmd_blocked = False
        self.status_mode = 'IDLE'
        self.status_text = 'BEREIT (>18cm frei)'

    def on_ui_tick(self):
        now = time.time()
        dt = now - self.pts_timer_t0
        if dt >= 1.0:
            self.pts_per_sec = int(self.pts_counter / dt)
            self.pts_counter = 0
            self.pts_timer_t0 = now

        sec_snapshot = []
        with self.sector_lock:
            for i in range(8):
                cnt = self.sec_cnt[i]
                if cnt > 0:
                    min_d = self.sec_min[i]
                    avg_d = self.sec_sum[i] // cnt
                    t = self.sec_time[i]
                    self.last_display_min[i] = min_d
                    sec_snapshot.append((min_d, avg_d, t))
                else:
                    prev_t = self.sec_time[i]
                    if prev_t > 0 and (now - prev_t) < 1.0:
                        sec_snapshot.append((self.last_display_min[i], 0, prev_t))
                    else:
                        sec_snapshot.append((0, 0, 0.0))

                self.sec_min[i] = 99999
                self.sec_sum[i] = 0
                self.sec_cnt[i] = 0

        self.dashboard.update_state(
            sec_snapshot,
            self.pts_per_sec,
            self.cmd_sector,
            self.cmd_blocked,
            self.cmd_rotate,
            self.drive_enabled,
            self.status_text,
            self.status_mode,
        )

    def _lidar_worker(self):
        last_pts_time = time.time()
        w_min = [99999] * 8
        w_sum = [0] * 8
        w_cnt = [0] * 8
        w_time = [0.0] * 8

        while self.worker_running:
            if self.lidar is None or not self.lidar.is_connected():
                self.lidar = LD06()
                if not self.lidar.is_connected():
                    time.sleep(1.0)
                    continue
                last_pts_time = time.time()

            if not self.lidar.fill_buffer(block_size=400):
                time.sleep(0.2)
                continue

            now = time.time()
            for i in range(8):
                w_min[i] = 99999
                w_sum[i] = 0
                w_cnt[i] = 0

            # Paket-Dekodierung komplett außerhalb von sector_lock (verhindert GIL/Lock-Stau)
            n = self.lidar.read_into_sectors(
                w_min, w_sum, w_cnt, w_time, now, block_size=0
            )
            if n > 0:
                with self.sector_lock:
                    for i in range(8):
                        c = w_cnt[i]
                        if c > 0:
                            if w_min[i] < self.sec_min[i]:
                                self.sec_min[i] = w_min[i]
                            self.sec_sum[i] += w_sum[i]
                            self.sec_cnt[i] += c
                            self.sec_time[i] = now
                self.pts_counter += n
                last_pts_time = now
                self.last_any_pts_time = now
                time.sleep(0.025)
            else:
                if (now - last_pts_time) > 2.0:
                    self.lidar.close()
                    time.sleep(0.5)
                    self.lidar = LD06()
                    last_pts_time = now
                else:
                    time.sleep(0.025)

    def closeEvent(self, event):
        self.worker_running = False
        self.stop_motors()
        self.joy.close()
        if self.lidar:
            self.lidar.close()
        if self.txt is not None:
            try:
                self.txt.stopOnline()
            except Exception:
                pass
        event.accept()


if __name__ == '__main__':
    app = TouchApplication(sys.argv)
    w = LidarOmniWindow()
    signal.signal(signal.SIGTERM, lambda *_a: w.close())
    signal.signal(signal.SIGINT, lambda *_a: w.close())
    w.show()
    sys.exit(app.exec_())
