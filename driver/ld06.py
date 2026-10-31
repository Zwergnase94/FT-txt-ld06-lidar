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

class LD06:
    def __init__(self, port='/dev/ttyUSB0', baudrate=230400):
        self.port = port
        self.baudrate = baudrate
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
                    # USB-Port kurz neu starten
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
        if not self.is_connected():
            return []
        try:
            b = self.ser.read(block_size)
            if b:
                self.buf.extend(b)
        except Exception:
            self.close()
            return []

        points = []
        while len(self.buf) >= 47:
            if self.buf[0] == 0x54 and self.buf[1] == 0x2C:
                pkt = self.buf[:47]
                del self.buf[:47]
                fsa = struct.unpack_from('<H', pkt, 4)[0] / 100.0
                lsa = struct.unpack_from('<H', pkt, 42)[0] / 100.0
                diff = (lsa + 360 - fsa) if lsa < fsa else (lsa - fsa)
                step = diff / 11.0
                for i in range(12):
                    dist = struct.unpack_from('<H', pkt, 6 + i * 3)[0]
                    conf = pkt[6 + i * 3 + 2]
                    angle = (fsa + i * step) % 360
                    if dist > 0:
                        points.append((angle, dist, conf))
            else:
                self.buf.pop(0)

        return points

    def close(self):
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None
