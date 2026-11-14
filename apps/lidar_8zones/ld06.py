#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Universal 360-degree LiDAR Driver for fischertechnik ROBOTICS TXT (ftcommunity-TXT).

Supports:
- LDROBOT LD06 / LD19 (0x54 0x2C protocol, CRC-8 poly 0x4D, CP2102 or standard UART)
- YDLIDAR 3-byte intensity protocol (e.g. T-mini Plus/Pro, 0xAA 0x55, XOR-16, CH340/UART)
- YDLIDAR 2-byte standard protocol (0xAA 0x55, XOR-16)
- Hardware-level CP2102 baudrate configuration via USB control transfers (0xc0105500)
- Automatic AM335x MUSB VBUS brownout recovery across Kernel 4.14 and 6.12+ sysfs paths
- Zero-allocation streaming routines (read_into_sectors, read_into_radar) for embedded performance
"""

import ctypes
import fcntl
import glob
import os
import struct
import subprocess
import time
import serial

USBDEVFS_CONTROL = 0xc0105500
RESET_SCRIPT = '/home/ftc/reset_usb.sh'
MUSB_DRIVER_DIR = '/sys/bus/platform/drivers/musb-hdrc'
MUSB_DEVICE_DIR = '/sys/bus/platform/drivers/musb-hdrc/musb-hdrc.1'
VBUS_PATHS = (
    '/sys/bus/platform/drivers/musb-hdrc/musb-hdrc.1/vbus',
    '/sys/devices/platform/ocp/47400000.target-module/47401c00.usb/musb-hdrc.1/vbus',
    '/sys/devices/platform/ocp/47400000.usb/47401c00.usb/musb-hdrc.1/vbus',
)
MUSB_MODE_PATHS = (
    '/sys/bus/platform/drivers/musb-hdrc/musb-hdrc.1/mode',
    '/sys/devices/platform/ocp/47400000.target-module/47401c00.usb/musb-hdrc.1/mode',
    '/sys/devices/platform/ocp/47400000.usb/47401c00.usb/musb-hdrc.1/mode',
)

# Vorberechnete CRC-8 Lookup-Tabelle (Polynom 0x4D) für LD06-Pakete
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

# Filtergrenzwerte gegen Messwert-Verfälschungen
MIN_DISTANCE_MM = 30   # Gehäuse-Nahbereich / Blindzone (< 30 mm) verwerfen
MIN_CONFIDENCE = 100   # Streulicht-Rauschen (< 100) verwerfen


def cal_crc8(data):
    """Berechnet die 8-Bit-CRC-Prüfsumme für ein LD06-Datenpaket."""
    crc = 0
    table = CRC_TABLE
    for b in data:
        crc = table[crc ^ b]
    return crc


def _read_first_existing(paths):
    """Liest den Inhalt des ersten existierenden sysfs-Pfads aus einer Liste."""
    for path in paths:
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    return f.read().lower()
            except Exception:
                pass
    return None


class LD06:
    def __init__(self, port='/dev/ttyUSB0', baudrate=230400, min_conf=MIN_CONFIDENCE):
        self.port = port
        self.baudrate = baudrate
        self.min_conf = min_conf
        self.ser = None
        self.buf = bytearray()
        self._proto = None  # Auto-erkannt: 'ld06', 'yd3' oder 'yd2'
        self.connect()

    def _resolve_port(self):
        """Findet das konfigurierte serielle Gerät (mit Fallback auf erstes /dev/ttyUSB*)."""
        if os.path.exists(self.port):
            return self.port
        if self.port == '/dev/ttyUSB0':
            candidates = sorted(glob.glob('/dev/ttyUSB*'))
            if candidates:
                return candidates[0]
        return None

    def _needs_usb_reset(self):
        """Prüft auf MUSB-VBUS-Abschaltung oder hängenden Controller-Zustand."""
        vbus = _read_first_existing(VBUS_PATHS)
        if vbus is not None and 'off' in vbus:
            return True
        mode = _read_first_existing(MUSB_MODE_PATHS)
        if mode is not None and 'b_idle' in mode:
            return True
        # Controller war entbunden (z.B. nach abgebrochenem Reset)
        if os.path.exists(MUSB_DRIVER_DIR) and not os.path.exists(MUSB_DEVICE_DIR):
            return True
        return False

    def connect(self):
        self.close()

        # Automatische Erkennung & Behebung eines VBUS-Spannungsausfalls (Kernel 4.14 & 6.12+)
        if os.path.exists(RESET_SCRIPT) and self._needs_usb_reset():
            try:
                subprocess.run(
                    ['sudo', '-n', RESET_SCRIPT],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                )
                for _ in range(30):
                    if self._resolve_port() is not None:
                        break
                    time.sleep(0.1)
            except Exception:
                pass

        dev_port = self._resolve_port()
        if not dev_port:
            return False

        self._init_cp2102()
        try:
            self.ser = serial.Serial(dev_port, self.baudrate, timeout=0.1)
            self.buf.clear()
            self._proto = None
            return True
        except Exception:
            self.ser = None
            return False

    def is_connected(self):
        return self.ser is not None and self.ser.is_open

    def _init_cp2102(self):
        """Konfiguriert einen Silicon Labs CP2102 auf Ziel-Baudrate über USB-Control-Transfers."""
        usb_nodes = glob.glob('/sys/bus/usb/devices/*')
        target_bus_dev = None
        for node in usb_nodes:
            idv = os.path.join(node, 'idVendor')
            idp = os.path.join(node, 'idProduct')
            if os.path.exists(idv) and os.path.exists(idp):
                try:
                    with open(idv) as f:
                        v = f.read().strip()
                    with open(idp) as f:
                        p = f.read().strip()
                    if v == '10c4' and p == 'ea60':
                        with open(os.path.join(node, 'busnum')) as f:
                            bus = int(f.read().strip())
                        with open(os.path.join(node, 'devnum')) as f:
                            dev = int(f.read().strip())
                        target_bus_dev = f'/dev/bus/usb/{bus:03d}/{dev:03d}'
                        break
                except Exception:
                    pass

        if not target_bus_dev or not os.path.exists(target_bus_dev):
            return

        try:
            fd = os.open(target_bus_dev, os.O_RDWR)
            try:
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
            finally:
                os.close(fd)
        except Exception:
            pass

    def fill_buffer(self, block_size=400):
        """Liest verfügbare Bytes in den internen Puffer (kann außerhalb von UI-Locks laufen)."""
        if not self.is_connected():
            return False
        try:
            n_avail = self.ser.in_waiting
            if block_size <= 0 and n_avail <= 0:
                return True
            to_read = max(block_size, min(n_avail, 2048)) if n_avail else block_size
            b = self.ser.read(to_read)
            if b:
                self.buf.extend(b)
                if len(self.buf) > 4096:
                    del self.buf[:-1024]
            return True
        except Exception:
            self.close()
            return False

    def _next_packet(self, pos, buf, n_buf):
        """
        Sucht und validiert das nächste Paket ab `pos` ohne bytearray-Verschiebung.
        Liefert `(next_pos, fmt, off_start, off_end, fsa, step)` oder `None` bei unvollständigem Paket.
        """
        proto = self._proto
        while True:
            if proto == 'ld06':
                idx = buf.find(b'\x54\x2c', pos)
                hdr_kind = 0
            elif proto in ('yd3', 'yd2'):
                idx = buf.find(b'\xaa\x55', pos)
                hdr_kind = 1
            else:
                idx_ld = buf.find(b'\x54\x2c', pos)
                idx_yd = buf.find(b'\xaa\x55', pos)
                if idx_ld == -1:
                    idx, hdr_kind = idx_yd, 1
                elif idx_yd == -1 or idx_ld < idx_yd:
                    idx, hdr_kind = idx_ld, 0
                else:
                    idx, hdr_kind = idx_yd, 1

            if idx == -1:
                return None, max(pos, n_buf - 1)

            if hdr_kind == 0:
                if idx + 47 > n_buf:
                    return None, idx
                end = idx + 47
                crc = 0
                table = CRC_TABLE
                for off_c in range(idx, end - 1):
                    crc = table[crc ^ buf[off_c]]
                if crc != buf[end - 1]:
                    pos = idx + 2
                    continue
                self._proto = 'ld06'
                fsa = (buf[idx + 4] | (buf[idx + 5] << 8)) * 0.01
                lsa = (buf[idx + 42] | (buf[idx + 43] << 8)) * 0.01
                diff = (lsa + 360.0 - fsa) if lsa < fsa else (lsa - fsa)
                return (end, 0, idx + 6, idx + 42, fsa, diff * (1.0 / 11.0)), end

            # YDLIDAR (0xAA 0x55)
            if idx + 10 > n_buf:
                return None, idx
            ct = buf[idx + 2]
            lsn = buf[idx + 3]
            if lsn == 0:
                pos = idx + 2
                continue

            fsa_raw = buf[idx + 4] | (buf[idx + 5] << 8)
            lsa_raw = buf[idx + 6] | (buf[idx + 7] << 8)
            cs = buf[idx + 8] | (buf[idx + 9] << 8)
            hdr_xor = 0x55AA ^ (ct | (lsn << 8)) ^ fsa_raw ^ lsa_raw

            fmt = -1
            end = 0
            plen3 = 10 + lsn * 3
            plen2 = 10 + lsn * 2

            if proto in (None, 'yd3'):
                if idx + plen3 <= n_buf:
                    end3 = idx + plen3
                    x = hdr_xor
                    for off in range(idx + 10, end3, 3):
                        x ^= buf[off] ^ (buf[off + 1] | (buf[off + 2] << 8))
                    if x == cs:
                        self._proto = proto = 'yd3'
                        fmt = 1
                        end = end3
                elif proto == 'yd3':
                    return None, idx

            if fmt == -1 and proto in (None, 'yd2'):
                need = plen2 + (2 if proto is None else 0)
                if idx + need > n_buf:
                    return None, idx
                end2 = idx + plen2
                if proto is not None or (buf[end2] == 0xAA and buf[end2 + 1] == 0x55):
                    x = hdr_xor
                    for off in range(idx + 10, end2, 2):
                        x ^= buf[off] | (buf[off + 1] << 8)
                    if x == cs:
                        self._proto = proto = 'yd2'
                        fmt = 2
                        end = end2

            if fmt == -1:
                if proto is None and idx + plen3 > n_buf:
                    return None, idx
                pos = idx + 2
                continue

            if ct & 0x01:
                pos = end
                continue

            fsa = (fsa_raw >> 1) * 0.015625
            lsa = (lsa_raw >> 1) * 0.015625
            diff = (lsa + 360.0 - fsa) if lsa < fsa else (lsa - fsa)
            step = (diff / (lsn - 1)) if lsn > 1 else 0.0
            return (end, fmt, idx + 10, end, fsa, step), end

    def _consume_stream(self, mode, out_points=None, sec_min=None, sec_sum=None,
                        sec_cnt=None, sec_time=None, scan_dist=None, scan_time=None,
                        now=0.0, block_size=400):
        """Liest (falls block_size > 0) und dekodiert alle vollständigen Pakete im Puffer."""
        if block_size > 0 and not self.fill_buffer(block_size):
            return 0

        buf = self.buf
        n_buf = len(buf)
        if n_buf < 12:
            return 0

        pos = 0
        pts_count = 0
        min_conf = self.min_conf

        while True:
            pkt_info, pos = self._next_packet(pos, buf, n_buf)
            if pkt_info is None:
                break
            _, fmt, start, end, ang, step = pkt_info
            stride = 2 if fmt == 2 else 3

            if mode == 2:
                # Schnellpfad: 360°-Radar-Array ohne Objektallokation
                ang += 0.5
                if fmt == 1:
                    for off in range(start, end, 3):
                        s1 = buf[off + 1]
                        dist = (s1 | (buf[off + 2] << 8)) >> 2
                        if dist >= MIN_DISTANCE_MM and (((s1 & 0x03) << 8) | buf[off]) >= min_conf:
                            pts_count += 1
                            deg = int(ang)
                            if deg >= 360:
                                deg %= 360
                            scan_dist[deg] = dist
                            scan_time[deg] = now
                        ang += step
                elif fmt == 0:
                    for off in range(start, end, 3):
                        dist = buf[off] | (buf[off + 1] << 8)
                        if dist >= MIN_DISTANCE_MM and buf[off + 2] >= min_conf:
                            pts_count += 1
                            deg = int(ang)
                            if deg >= 360:
                                deg %= 360
                            scan_dist[deg] = dist
                            scan_time[deg] = now
                        ang += step
                else:
                    for off in range(start, end, 2):
                        dist = (buf[off] | (buf[off + 1] << 8)) >> 2
                        if dist >= MIN_DISTANCE_MM and 200 >= min_conf:
                            pts_count += 1
                            deg = int(ang)
                            if deg >= 360:
                                deg %= 360
                            scan_dist[deg] = dist
                            scan_time[deg] = now
                        ang += step
            elif mode == 1:
                # Schnellpfad: 8-Sektoren-Auswertung ohne Objektallokation
                ang += 22.5
                if fmt == 1:
                    for off in range(start, end, 3):
                        s1 = buf[off + 1]
                        dist = (s1 | (buf[off + 2] << 8)) >> 2
                        if dist >= MIN_DISTANCE_MM and (((s1 & 0x03) << 8) | buf[off]) >= min_conf:
                            pts_count += 1
                            sec_idx = int(ang * 0.022222222222222223) & 7
                            if dist < sec_min[sec_idx]:
                                sec_min[sec_idx] = dist
                            sec_sum[sec_idx] += dist
                            sec_cnt[sec_idx] += 1
                            sec_time[sec_idx] = now
                        ang += step
                elif fmt == 0:
                    for off in range(start, end, 3):
                        dist = buf[off] | (buf[off + 1] << 8)
                        if dist >= MIN_DISTANCE_MM and buf[off + 2] >= min_conf:
                            pts_count += 1
                            sec_idx = int(ang * 0.022222222222222223) & 7
                            if dist < sec_min[sec_idx]:
                                sec_min[sec_idx] = dist
                            sec_sum[sec_idx] += dist
                            sec_cnt[sec_idx] += 1
                            sec_time[sec_idx] = now
                        ang += step
                else:
                    for off in range(start, end, 2):
                        dist = (buf[off] | (buf[off + 1] << 8)) >> 2
                        if dist >= MIN_DISTANCE_MM and 200 >= min_conf:
                            pts_count += 1
                            sec_idx = int(ang * 0.022222222222222223) & 7
                            if dist < sec_min[sec_idx]:
                                sec_min[sec_idx] = dist
                            sec_sum[sec_idx] += dist
                            sec_cnt[sec_idx] += 1
                            sec_time[sec_idx] = now
                        ang += step
            else:
                for off in range(start, end, stride):
                    if fmt == 1:
                        s1 = buf[off + 1]
                        dist = (s1 | (buf[off + 2] << 8)) >> 2
                        conf = ((s1 & 0x03) << 8) | buf[off]
                    elif fmt == 0:
                        dist = buf[off] | (buf[off + 1] << 8)
                        conf = buf[off + 2]
                    else:
                        dist = (buf[off] | (buf[off + 1] << 8)) >> 2
                        conf = 200
                    if dist >= MIN_DISTANCE_MM and conf >= min_conf:
                        out_points.append((ang % 360.0, dist, conf))
                    ang += step

        if pos > 0:
            del buf[:pos]
        return pts_count

    def read_points(self, block_size=400):
        """Liest Messpunkte mit Prüfsummen-Validierung und Signalstärke-Filterung aus."""
        points = []
        self._consume_stream(0, out_points=points, block_size=block_size)
        return points

    def read_into_sectors(self, sec_min, sec_sum, sec_cnt, sec_time, now, block_size=400):
        """Liest Messdaten direkt in 8 Sektoren mit Prüfsummen- und Confidence-Filterung."""
        return self._consume_stream(
            1,
            sec_min=sec_min,
            sec_sum=sec_sum,
            sec_cnt=sec_cnt,
            sec_time=sec_time,
            now=now,
            block_size=block_size,
        )

    def read_into_radar(self, scan_dist, scan_time, now, block_size=400):
        """Liest Messdaten direkt in ein 360-Grad-Radar-Array mit Filterung."""
        return self._consume_stream(
            2,
            scan_dist=scan_dist,
            scan_time=scan_time,
            now=now,
            block_size=block_size,
        )

    def close(self):
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None
        self._proto = None
