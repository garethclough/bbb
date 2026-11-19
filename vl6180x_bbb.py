#!/usr/bin/env python3
"""Read distance from a VL6180X time-of-flight sensor on a BeagleBone Black.

Wiring (I2C2, default): VIN->P9_3, GND->P9_1, SCL->P9_19, SDA->P9_20
No extra libraries needed: talks to /dev/i2c-N directly (Python 3 standard library only).
"""
import argparse
import fcntl
import os
import time

ADDR = 0x29
I2C_SLAVE = 0x0703  # ioctl from <linux/i2c-dev.h>

# Mandatory private settings from ST application note AN4545
PRIVATE_INIT = [
    (0x0207, 0x01), (0x0208, 0x01), (0x0096, 0x00), (0x0097, 0xFD),
    (0x00E3, 0x00), (0x00E4, 0x04), (0x00E5, 0x02), (0x00E6, 0x01),
    (0x00E7, 0x03), (0x00F5, 0x02), (0x00D9, 0x05), (0x00DB, 0xCE),
    (0x00DC, 0x03), (0x00DD, 0xF8), (0x009F, 0x00), (0x00A3, 0x3C),
    (0x00B7, 0x00), (0x00BB, 0x3C), (0x00B2, 0x09), (0x00CA, 0x09),
    (0x0198, 0x01), (0x01B0, 0x17), (0x01AD, 0x00), (0x00FF, 0x05),
    (0x0100, 0x05), (0x0199, 0x05), (0x01A6, 0x1B), (0x01AC, 0x3E),
    (0x01A7, 0x1F), (0x0030, 0x00),
]

# Recommended public settings
PUBLIC_INIT = [
    (0x0011, 0x10),  # GPIO1 interrupt: active low
    (0x010A, 0x30),  # averaging period
    (0x003F, 0x46),  # ALS analogue gain
    (0x0031, 0xFF),  # auto-calibration period
    (0x0041, 0x63),  # ALS integration time 100 ms
    (0x002E, 0x01),  # perform temperature calibration
    (0x001B, 0x09),  # ranging inter-measurement period
    (0x003E, 0x31),  # ALS inter-measurement period
    (0x0014, 0x24),  # interrupt on new sample ready
]

RANGE_ERRORS = {
    1: "VCSEL continuity fail", 2: "VCSEL watchdog fail",
    3: "VCSEL watchdog", 4: "PLL1 lock fail", 5: "PLL2 lock fail",
    6: "early convergence estimate", 7: "max convergence (no target)",
    8: "range ignore", 11: "low SNR", 12: "raw underflow",
    13: "raw overflow", 14: "range underflow", 15: "range overflow",
}


class VL6180X:
    def __init__(self, bus_num=2, addr=ADDR):
        self.fd = os.open(f"/dev/i2c-{bus_num}", os.O_RDWR)
        fcntl.ioctl(self.fd, I2C_SLAVE, addr)

    def write8(self, reg, val):
        os.write(self.fd, bytes([reg >> 8, reg & 0xFF, val & 0xFF]))

    def read8(self, reg):
        os.write(self.fd, bytes([reg >> 8, reg & 0xFF]))  # set register pointer
        return os.read(self.fd, 1)[0]

    def read16(self, reg):
        os.write(self.fd, bytes([reg >> 8, reg & 0xFF]))
        hi, lo = os.read(self.fd, 2)
        return (hi << 8) | lo

    def init(self):
        model = self.read8(0x0000)
        if model != 0xB4:
            raise RuntimeError(f"Unexpected model ID 0x{model:02X} (expected 0xB4)")
        if self.read8(0x0016) == 1:  # SYSTEM__FRESH_OUT_OF_RESET
            for reg, val in PRIVATE_INIT + PUBLIC_INIT:
                self.write8(reg, val)
            self.write8(0x0016, 0x00)

    def range_mm(self, timeout=1.0):
        self.write8(0x0018, 0x01)  # SYSRANGE__START single-shot
        start = time.time()
        while (self.read8(0x004F) & 0x07) != 0x04:  # wait for new sample
            if time.time() - start > timeout:
                raise TimeoutError("Range measurement timed out")
            time.sleep(0.001)
        dist = self.read8(0x0062)           # RESULT__RANGE_VAL
        status = self.read8(0x004D) >> 4    # RESULT__RANGE_STATUS
        self.write8(0x0015, 0x07)           # clear interrupts
        return dist, status

    def lux(self, timeout=1.0):
        """Ambient light in lux (gain 1.01, 100 ms integration as set in PUBLIC_INIT)."""
        self.write8(0x0038, 0x01)  # SYSALS__START single-shot
        start = time.time()
        while ((self.read8(0x004F) >> 3) & 0x07) != 0x04:  # wait for ALS sample
            if time.time() - start > timeout:
                raise TimeoutError("ALS measurement timed out")
            time.sleep(0.005)
        raw = self.read16(0x0050)           # RESULT__ALS_VAL
        self.write8(0x0015, 0x07)           # clear interrupts
        gain = 1.01
        integration_ms = 100
        return 0.32 * raw / gain * (100.0 / integration_ms)

    def close(self):
        os.close(self.fd)


def main():
    ap = argparse.ArgumentParser(description="VL6180X range reader")
    ap.add_argument("--bus", type=int, default=2, help="I2C bus number (default 2)")
    ap.add_argument("--interval", type=float, default=0.1, help="seconds between reads")
    args = ap.parse_args()

    sensor = VL6180X(args.bus)
    sensor.init()
    print("VL6180X ready. Ctrl+C to stop.")
    try:
        while True:
            dist, status = sensor.range_mm()
            light = sensor.lux()
            if status == 0:
                rng = f"Range: {dist:3d} mm"
            else:
                rng = f"Range error: {RANGE_ERRORS.get(status, status)}"
            print(f"{rng:<40} Light: {light:8.1f} lux")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        sensor.close()


if __name__ == "__main__":
    main()