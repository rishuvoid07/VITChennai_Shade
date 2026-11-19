#!/usr/bin/env python3
"""
euroc_to_7col.py - Convert raw EuRoC datasets to Track 3 format.

Modes:
  1. IMU conversion:
     Convert EuRoC imu0/data.csv (gyro-first: ts, wx, wy, wz, ax, ay, az)
     into the Track 3 7-column format (accel-first: timestamp,ax,ay,az,gx,gy,gz).
     Preserves integer nanosecond timestamps and original units.
     Streams line-by-line.

  2. Ground-truth conversion:
     Convert EuRoC state_groundtruth_estimate0/data.csv (17 cols: ts, px, py, pz, qw, qx, qy, qz...)
     into TUM format (ts[s] tx ty tz qx qy qz qw).
     Streams line-by-line.

Usage:
  python tools/euroc_to_7col.py imu <raw_imu0.csv> <output_7col.csv>
  python tools/euroc_to_7col.py gt <state_groundtruth.csv> <output_groundtruth_tum.txt>
  # Or auto-detect based on input:
  python tools/euroc_to_7col.py <input.csv> <output> [--mode imu|gt]
"""

import sys
import argparse


def convert_imu(fin_path, fout_path):
    rows_in = 0
    rows_out = 0
    with open(fin_path, "r", encoding="utf-8") as fin, open(fout_path, "w", encoding="utf-8") as fout:
        fout.write("timestamp,ax,ay,az,gx,gy,gz\n")
        for line in fin:
            rows_in += 1
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 7:
                continue
            # EuRoC imu0: ts, wx, wy, wz, ax, ay, az
            # Track 3: timestamp, ax, ay, az, gx, gy, gz
            ts = parts[0]
            wx, wy, wz = parts[1], parts[2], parts[3]
            ax, ay, az = parts[4], parts[5], parts[6]
            fout.write(f"{ts},{ax},{ay},{az},{wx},{wy},{wz}\n")
            rows_out += 1
    print(f"IMU converted: {fin_path} -> {fout_path} ({rows_out} data rows, {rows_in} total lines)")


def convert_gt(fin_path, fout_path):
    rows_in = 0
    rows_out = 0
    with open(fin_path, "r", encoding="utf-8") as fin, open(fout_path, "w", encoding="utf-8") as fout:
        fout.write("# groundtruth converted from EuRoC - TUM format\n")
        fout.write("# timestamp tx ty tz qx qy qz qw\n")
        for line in fin:
            rows_in += 1
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 8:
                continue
            # EuRoC GT cols:
            # 0: ts (ns)
            # 1, 2, 3: px, py, pz
            # 4, 5, 6, 7: qw, qx, qy, qz
            ts_ns = int(parts[0])
            sec = ts_ns // 1000000000
            frac = ts_ns % 1000000000
            ts_str = f"{sec}.{frac:09d}"

            px, py, pz = parts[1], parts[2], parts[3]
            qw, qx, qy, qz = parts[4], parts[5], parts[6], parts[7]

            fout.write(f"{ts_str} {px} {py} {pz} {qx} {qy} {qz} {qw}\n")
            rows_out += 1
    print(f"Ground truth converted: {fin_path} -> {fout_path} ({rows_out} data rows, {rows_in} total lines)")


def detect_mode(fin_path):
    with open(fin_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",")
            if len(parts) >= 16:
                return "gt"
            elif len(parts) == 7:
                return "imu"
            break
    return "imu"


def main():
    parser = argparse.ArgumentParser(description="Convert EuRoC IMU or Ground Truth to Track 3 format.")
    parser.add_argument("args", nargs="*", help="[imu|gt] <input> <output> OR <input> <output>")
    parser.add_argument("--mode", choices=["imu", "gt", "auto"], default="auto")

    parsed = parser.parse_args()
    args = parsed.args

    if len(args) == 3 and args[0] in ("imu", "gt"):
        mode = args[0]
        fin_path = args[1]
        fout_path = args[2]
    elif len(args) == 2:
        fin_path = args[0]
        fout_path = args[1]
        mode = parsed.mode
        if mode == "auto":
            mode = detect_mode(fin_path)
    else:
        parser.print_help()
        sys.exit(1)

    if mode == "imu":
        convert_imu(fin_path, fout_path)
    elif mode == "gt":
        convert_gt(fin_path, fout_path)
    else:
        sys.exit(f"Unknown mode: {mode}")


if __name__ == "__main__":
    main()
