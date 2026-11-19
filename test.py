#!/usr/bin/env python3
"""Diagnostic for VL6180X ambient light (ALS) always reading 0.

Usage: python3 vl6180x_als_test.py [--bus 2]
Paste the full output back.
"""
import argparse
import fcntl
import os
import time

ADDR = 0x29
I2C_SLAVE = 0x0703

ap = argparse.ArgumentParser()
ap.add_argument("--bus", type=int, default=2)
args = ap.parse_args()

fd = os.open(f"/dev/i2c-{args.bus}", os.O_RDWR)
fcntl.ioctl(fd, I2C_SLAVE, ADDR)


def w8(reg, val):
    os.write(fd, bytes([reg >> 8, reg & 0xFF, val & 0xFF]))


def r8(reg):
    os.write(fd, bytes([reg >> 8, reg & 0xFF]))
    return os.read(fd, 1)[0]


def r16(reg):
    os.write(fd, bytes([reg >> 8, reg & 0xFF]))
    hi, lo = os.read(fd, 2)
    return (hi << 8) | lo


print("--- Identification ---")
print(f"Model ID        0x000: 0x{r8(0x000):02X}  (VL6180X = 0xB4)")
print(f"Model rev major 0x001: 0x{r8(0x001):02X}")
print(f"Model rev minor 0x002: 0x{r8(0x002):02X}")
print(f"Module rev maj  0x003: 0x{r8(0x003):02X}")
print(f"Module rev min  0x004: 0x{r8(0x004):02X}")
print(f"Fresh-out-of-reset   : {r8(0x016)}")

print("\n--- ALS config ---")
print(f"ALS gain     0x03F: 0x{r8(0x03F):02X}")
print(f"ALS int time 0x040: {r16(0x040)} (+1 = ms)")
print(f"INT config   0x014: 0x{r8(0x014):02X}")
print(f"ALS status   0x04E: 0x{r8(0x04E):02X}  (bit0 = ready, bits7:4 = error)")

GAINS = [(0x46, 1.01, "x1"), (0x45, 1.67, "x1.67"), (0x44, 2.5, "x2.5"),
         (0x43, 5.0, "x5"), (0x42, 10.0, "x10"), (0x41, 20.0, "x20"),
         (0x47, 40.0, "x40")]

w8(0x015, 0x07)  # clear any old interrupts
w8(0x040, 0x00)
w8(0x041, 0x63)  # 100 ms integration
w8(0x014, 0x24)  # new-sample-ready interrupts for range and ALS

print("\n--- ALS readings (no ranging) ---")
for reg, gain, name in GAINS:
    w8(0x03F, reg)
    w8(0x038, 0x01)  # start single ALS measurement
    t0 = time.time()
    timed_out = False
    while ((r8(0x04F) >> 3) & 0x07) != 0x04:
        if time.time() - t0 > 1.0:
            timed_out = True
            break
        time.sleep(0.005)
    status = r8(0x04F)
    raw = r16(0x050)
    als_status = r8(0x04E)
    err = r8(0x04D)
    w8(0x015, 0x07)
    lux = 0.32 * raw / gain
    print(f"gain {name:>5}: raw={raw:5d}  lux={lux:8.2f}  int_status=0x{status:02X}  "
          f"als_status=0x{als_status:02X}  range_status=0x{err:02X}"
          f"{'  TIMEOUT' if timed_out else ''}")
    time.sleep(0.05)

w8(0x03F, 0x46)  # back to gain 1
os.close(fd)
print("\nTry once in normal light and once with a torch shining on the sensor.")
