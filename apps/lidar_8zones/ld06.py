#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LD06 DToF LiDAR Driver for fischertechnik ROBOTICS TXT (ftcommunity-TXT).

Features:
- CRC-8 packet checksum validation (Polynomial 0x4D)
- Confidence threshold filtering (conf >= 100) to eliminate stray light noise spikes (6cm phantom obstacles)
- Blind-zone reflection rejection (dist >= 30mm)
- Hardware-level CP2102 baudrate configuration via USB control transfers (0xc0105500)
- Automatic MUSB VBUS brownout recovery via sysfs reset
- Zero-allocation streaming routines (read_into_sectors, read_into_radar) for embedded performance
"""

import fcntl
import struct
import os
import glob
import time
import serial
import ctypes

USBDEVFS_CONTROL = 0xc0105500
VBUS_PATH = '/sys/devices/platform/ocp/47400000.usb/47401c00.usb/musb-hdrc.1/vbus'
RESET_SCRIPT = '/home/ftc/reset_usb.sh'

# Vorberechnete CRC-8 Lookup-Tabelle (Polynom 0x4D)
CRC_TABLE = (
    0x00, 0x4d, 0x9a, 0xd7, 0x79, 0x34, 0xe3, 0xae, 0xf2, 0xbf, 0x68, 0x25, 0x8b, 0xc6, 0x11, 0x5c,
    0xa9, 0xe4, 0x33, 0x7e, 0xd0, 0x9d, 0x4a, 0x07, 0x5b, 0x16, 0xc1, 0x8c, 0x22, 0x6f, 0xb8, 0xf5,
    0x1f, 0x52, 0x85, 0xc8, 0x66, 0x2b, 0xfc, 0xb1, 0xed, 0xa0, 0x77, 0x3a, 0x94, 0xd9, 0x0e, 0x43,
    0xb6, 0xfb, 0x2c, 0x61, 0xcf, 0x82, 0x55, 0x18, 0x44, 0x09, 0xde, 0x93, 0x3d, 0x70, 0xa7, 0xea,
    0x3e, 0x73, 0xa4, 0xe9, 0x47, 0x0a, 0xdd, 0x90, 0xcc, 0x81, 0x56, 0x1b, 0xb5, 0xf8, 0x2f, 0x62,
    0x97, 0xda, 0x0d, 0x40, 0xee, 0xa3, 0x74, 0x39, 0x65, 0x28, 0xff, 0xb2, 0x1c, 0x51, 0x86, 0xcb,
    0x21, 0x6c, 0xbb, 0xf6, 0x58, 0x15, 0xc2, 0x8f, 0xd3, 0x9e, 0x49, 0x04, 0xaa, 0xe7, 0x30, 0x7d,
    0x88, 0xc5, 0x12, 0x5f, 0xf1, 0xbc, 0x6b, 0x26, 0x7a, 0x37, 0xe0, 0xad, 0x03, 0x4e, 0x99, 0xd4,
    0x7c, 0x31, 0xe6, 0xab, 0x05, 0x48, 0x9f, 0xd2, 0x8e, 0xc3, 0x14, 0x59, 0xf7, 0xba, 0x6d, 0x20,
    0xd5, 0x98, 0x4f, 0x02, 0xac, 0xe1, 0x36, 0x7b, 0x27, 0x6a, 0xbd, 0xf0, 0x5e, 0x13, 0xc4, 0x89,
    0x63, 0x2e, 0xf9, 0xb4, 0x1a, 0x57, 0x80, 0xcd, 0x91, 0xdc, 0x0b, 0x46, 0xe8, 0xa5, 0x72, 0x3f,
    0xca, 0x87, 0x50, 0x1d, 0xb3, 0xfe, 0x29, 0x64, 0x38, 0x75, 0xa2, 0xef, 0x41, 0x0c, 0xdb, 0x96,
    0x42, 0x0f, 0xd8, 0x95, 0x3b, 0x76, 0xa1, 0xec, 0xb0, 0xfd, 0x2a, 0x67, 0xc9, 0x84, 0x53, 0x1e,
    0xeb, 0xa6, 0x71, 0x3c, 0x92, 0xdf, 0x08, 0x45, 0x19, 0x54, 0x83, 0xce, 0x60, 0x2d, 0xfa, 0xb7,
    0x5d, 0x10, 0xc7, 0x8a, 0x24, 0x69, 0xbe, 0xf3, 0xaf, 0xe2, 0x35, 0x78, 0xd6, 0x9b, 0x4c, 0x01,
    0xf4, 0xb9, 0x6e, 0x23, 0x8d, 0xc0, 0x17, 0x5a, 0x06, 0x4b, 0x9c, 0xd1, 0x7f, 0x32, 0xe5, 0xa8
)

def cal_crc8(data):
    """Berechnet die 8-Bit-CRC-Prüfsumme für ein LD06-Datenpaket."""
    crc = 0
    for b in data:
        crc = CRC_TABLE[(crc ^ b) & 0xff]
    return crc

# Filtergrenzwerte gegen Messwert-Verfälschungen
MIN_DISTANCE_MM = 30   # Gehäuse-Nahbereich / Blindzone (< 30 mm) verwerfen
MIN_CONFIDENCE = 100   # Streulicht-Rauschen (< 100) verwerfen (echte Hindernisse liegen bei 150..250)


class LD06:
    def __init__(self, port='/dev/ttyUSB0', baudrate=230400, min_conf=MIN_CONFIDENCE):
        self.port = port
        self.baudrate = baudrate
        self.min_conf = min_conf
        self.ser = None
        self.buf = bytearray()
        self.connect()

    def connect(self):
        self.close()

        # Automatische Erkennung & Behebung eines VBUS-Spannungsausfalls
        if os.path.exists(VBUS_PATH):
            try:
                with open(VBUS_PATH, 'r') as f:
                    content = f.read().lower()
                if 'off' in content and os.path.exists(RESET_SCRIPT):
                    import subprocess
                    subprocess.run(['sudo', RESET_SCRIPT], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    time.sleep(1.5)
            except Exception:
                pass

        if not os.path.exists(self.port):
            return False

        self._init_cp2102()
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=0.1)
            self.buf.clear()
            return True
        except Exception:
            self.ser = None
            return False

    def is_connected(self):
        return self.ser is not None and self.ser.is_open

    def _init_cp2102(self):
        """Konfiguriert den Silicon Labs CP2102 auf 230400 Baud über direkte USB-Control-Transfers."""
        usb_nodes = glob.glob('/sys/bus/usb/devices/*')
        target_bus_dev = None
        for node in usb_nodes:
            idv = os.path.join(node, 'idVendor')
            idp = os.path.join(node, 'idProduct')
            if os.path.exists(idv) and os.path.exists(idp):
                try:
                    with open(idv) as f: v = f.read().strip()
                    with open(idp) as f: p = f.read().strip()
                    if v == '10c4' and p == 'ea60':
                        with open(os.path.join(node, 'busnum')) as f: bus = int(f.read().strip())
                        with open(os.path.join(node, 'devnum')) as f: dev = int(f.read().strip())
                        target_bus_dev = f'/dev/bus/usb/{bus:03d}/{dev:03d}'
                        break
                except Exception:
                    pass

        if not target_bus_dev or not os.path.exists(target_bus_dev):
            return

        try:
            fd = os.open(target_bus_dev, os.O_RDWR)
            def ctrl(req_type, req, val, idx, data=b''):
                buf = ctypes.create_string_buffer(data) if data else 0
                buf_ptr = ctypes.addressof(buf) if data else 0
                c = struct.pack('<BBHHHII', req_type, req, val, idx, len(data), 1000, buf_ptr)
                return fcntl.ioctl(fd, USBDEVFS_CONTROL, c)

            ctrl(0x41, 0x00, 1, 0)
            ctrl(0x41, 0x1E, 0, 0, struct.pack('<I', self.baudrate))
            ctrl(0x41, 0x03, 0x0800, 0)
            ctrl(0x41, 0x07, 0x0303, 0)
            ctrl(0x41, 0x12, 0x000F, 0)
            os.close(fd)
        except Exception:
            pass

    def read_points(self, block_size=400):
        """Liest Messpunkte mit CRC-8-Prüfung und Signalstärke-Filterung aus."""
        if not self.is_connected():
            return []
        try:
            b = self.ser.read(block_size)
            if b:
                self.buf.extend(b)
        except Exception:
            self.close()
            return []

        if len(self.buf) > 2048:
            del self.buf[:-512]

        points = []
        min_conf = self.min_conf

        while True:
            idx = self.buf.find(b'\x54\x2c')
            if idx == -1:
                if len(self.buf) > 1:
                    del self.buf[:-1]
                break
            if idx > 0:
                del self.buf[:idx]
            if len(self.buf) < 47:
                break

            pkt = self.buf[:47]
            del self.buf[:47]

            # 1. CRC-8 Prüfsummen-Validierung
            if cal_crc8(pkt[:46]) != pkt[46]:
                continue

            fsa = (pkt[4] | (pkt[5] << 8)) * 0.01
            lsa = (pkt[42] | (pkt[43] << 8)) * 0.01
            diff = (lsa + 360.0 - fsa) if lsa < fsa else (lsa - fsa)
            step = diff * (1.0 / 11.0)

            for i in range(12):
                byte_idx = 6 + i * 3
                dist = pkt[byte_idx] | (pkt[byte_idx + 1] << 8)
                conf = pkt[byte_idx + 2]

                # 2. Nahbereichs-Sanity und Streulicht-Filter (eliminiert 6 cm Geister-Spikes)
                if dist >= MIN_DISTANCE_MM and conf >= min_conf:
                    angle = (fsa + i * step) % 360.0
                    points.append((angle, dist, conf))

        return points

    def read_into_sectors(self, sec_min, sec_sum, sec_cnt, sec_time, now, block_size=400):
        """Liest Messdaten direkt in 8 Sektoren mit CRC-8 und Confidence-Filterung."""
        if not self.is_connected():
            return 0
        try:
            b = self.ser.read(block_size)
            if b:
                self.buf.extend(b)
        except Exception:
            self.close()
            return 0

        if len(self.buf) > 2048:
            del self.buf[:-512]

        pts_count = 0
        min_conf = self.min_conf

        while True:
            idx = self.buf.find(b'\x54\x2c')
            if idx == -1:
                if len(self.buf) > 1:
                    del self.buf[:-1]
                break
            if idx > 0:
                del self.buf[:idx]
            if len(self.buf) < 47:
                break

            pkt = self.buf[:47]
            del self.buf[:47]

            # 1. CRC-8 Prüfsummen-Validierung
            if cal_crc8(pkt[:46]) != pkt[46]:
                continue

            fsa = (pkt[4] | (pkt[5] << 8)) * 0.01
            lsa = (pkt[42] | (pkt[43] << 8)) * 0.01
            diff = (lsa + 360.0 - fsa) if lsa < fsa else (lsa - fsa)
            step = diff * (1.0 / 11.0)

            for i in range(12):
                byte_idx = 6 + i * 3
                dist = pkt[byte_idx] | (pkt[byte_idx + 1] << 8)
                conf = pkt[byte_idx + 2]

                # 2. Filterung gegen Rauschen & Nahbereich
                if dist >= MIN_DISTANCE_MM and conf >= min_conf:
                    pts_count += 1
                    angle = (fsa + i * step) % 360.0
                    sec_idx = int((angle + 22.5) * 0.02222222) % 8
                    if dist < sec_min[sec_idx]:
                        sec_min[sec_idx] = dist
                    sec_sum[sec_idx] += dist
                    sec_cnt[sec_idx] += 1
                    sec_time[sec_idx] = now

        return pts_count

    def read_into_radar(self, scan_dist, scan_time, now, block_size=400):
        """Liest Messdaten direkt in ein 360-Grad-Radar-Array mit CRC-8 und Confidence-Filterung."""
        if not self.is_connected():
            return 0
        try:
            b = self.ser.read(block_size)
            if b:
                self.buf.extend(b)
        except Exception:
            self.close()
            return 0

        if len(self.buf) > 2048:
            del self.buf[:-512]

        pts_count = 0
        min_conf = self.min_conf

        while True:
            idx = self.buf.find(b'\x54\x2c')
            if idx == -1:
                if len(self.buf) > 1:
                    del self.buf[:-1]
                break
            if idx > 0:
                del self.buf[:idx]
            if len(self.buf) < 47:
                break

            pkt = self.buf[:47]
            del self.buf[:47]

            # 1. CRC-8 Prüfsummen-Validierung
            if cal_crc8(pkt[:46]) != pkt[46]:
                continue

            fsa = (pkt[4] | (pkt[5] << 8)) * 0.01
            lsa = (pkt[42] | (pkt[43] << 8)) * 0.01
            diff = (lsa + 360.0 - fsa) if lsa < fsa else (lsa - fsa)
            step = diff * (1.0 / 11.0)

            for i in range(12):
                byte_idx = 6 + i * 3
                dist = pkt[byte_idx] | (pkt[byte_idx + 1] << 8)
                conf = pkt[byte_idx + 2]

                # 2. Filterung gegen Rauschen & Nahbereich
                if dist >= MIN_DISTANCE_MM and conf >= min_conf:
                    pts_count += 1
                    deg = int((fsa + i * step) + 0.5) % 360
                    scan_dist[deg] = dist
                    scan_time[deg] = now

        return pts_count

    def close(self):
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None
