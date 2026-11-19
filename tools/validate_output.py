#!/usr/bin/env python3
"""
validate_output.py - Validate an estimated_trajectory.txt against the Track 3 spec and input IMU.

Checks:
  1. Every non-comment line has exactly 8 space-separated columns.
  2. Timestamps are monotonically non-decreasing (dt >= 0).
  3. Quaternion (qx, qy, qz, qw) has unit norm (tolerance 1e-4).
  4. No NaN or Inf in any column.
  5. Row count (excluding comments) EXACTLY matches input IMU data row count.
  6. Output timestamps match expected seconds conversion from the input file.

Usage:
  python validate_output.py <estimated_trajectory.txt> <input>
"""

import sys
import os
import io
import math
import zipfile


def die(msg):
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def detect_ts_scale(timestamps):
    dt_list = []
    for i in range(1, len(timestamps)):
        t_prev = timestamps[i-1]
        t_curr = timestamps[i]
        if t_curr > t_prev:
            dt_list.append(t_curr - t_prev)
    if not dt_list:
        if timestamps and timestamps[0] > 1e14:
            return 1e-9, "ns"
        elif timestamps and timestamps[0] > 1e11:
            return 1e-6, "us"
        elif timestamps and timestamps[0] > 1e8:
            return 1e-3, "ms"
        else:
            return 1.0, "s"
    s = sorted(dt_list)
    mid = len(s) // 2
    median_dt = s[mid] if len(s) % 2 == 1 else (s[mid - 1] + s[mid]) * 0.5

    if median_dt < 0.5:
        return 1.0, "s"
    elif median_dt < 500.0:
        return 1e-3, "ms"
    elif median_dt < 5e5:
        return 1e-6, "us"
    else:
        return 1e-9, "ns"


def format_expected_ts(raw_ts_str, ts_unit):
    ts_str = raw_ts_str.strip()
    if "." in ts_str:
        try:
            val = float(ts_str)
            return f"{val:.9f}"
        except ValueError:
            return None
    else:
        try:
            val = int(ts_str)
        except ValueError:
            return None
        sign = "-" if val < 0 else ""
        abs_val = abs(val)
        if ts_unit == "ns":
            sec = abs_val // 1000000000
            frac = abs_val % 1000000000
            return f"{sign}{sec}.{frac:09d}"
        elif ts_unit == "us":
            sec = abs_val // 1000000
            frac = (abs_val % 1000000) * 1000
            return f"{sign}{sec}.{frac:09d}"
        elif ts_unit == "ms":
            sec = abs_val // 1000
            frac = (abs_val % 1000) * 1000000
            return f"{sign}{sec}.{frac:09d}"
        else:
            return f"{sign}{abs_val}.000000000"


def open_input_stream(path):
    if zipfile.is_zipfile(path) or path.lower().endswith(".zip"):
        zf = zipfile.ZipFile(path, "r")
        target = None
        for n in zf.namelist():
            if n == "imu0/data.csv" or n.endswith("/imu0/data.csv"):
                target = n
                break
        if target is None:
            for n in zf.namelist():
                if n.lower().endswith(".csv") and not n.startswith("__MACOSX"):
                    target = n
                    break
        if target is None:
            zf.close()
            raise FileNotFoundError(f"No CSV inside {path}")
        bio = zf.open(target, "r")
        return io.TextIOWrapper(bio, encoding="utf-8-sig", newline=""), zf
    elif os.path.isdir(path):
        target = os.path.join(path, "imu0", "data.csv")
        if not os.path.exists(target):
            for root, _, files in os.walk(path):
                for f in files:
                    if f.lower().endswith(".csv"):
                        target = os.path.join(root, f)
                        break
                if target and os.path.exists(target):
                    break
        if not target or not os.path.exists(target):
            raise FileNotFoundError(f"No CSV inside directory {path}")
        return open(target, "r", encoding="utf-8-sig", newline=""), None
    else:
        return open(path, "r", encoding="utf-8-sig", newline=""), None


def read_input_imu(path):
    """
    Parses input CSV/zip/dir, tolerating optional header, comments (#), delimiters, CRLF.
    Returns list of (raw_ts_str, ts_num).
    """
    stream, zf_obj = open_input_stream(path)
    imu_rows = []
    first_data_line = True
    delim = None

    try:
        for line in stream:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if delim is None:
                if "," in line:
                    delim = ","
                elif ";" in line:
                    delim = ";"
                elif "\t" in line:
                    delim = "\t"
                else:
                    delim = None

            if delim is None:
                parts = line.split()
            else:
                parts = [p.strip() for p in line.split(delim)]

            if not parts:
                continue

            ts_token = parts[0]
            if first_data_line:
                first_data_line = False
                try:
                    float(ts_token)
                except ValueError:
                    continue  # skip header

            try:
                if "." in ts_token:
                    ts_num = float(ts_token)
                else:
                    ts_num = int(ts_token)
            except ValueError:
                ts_num = (imu_rows[-1][1] + 1) if imu_rows else 0

            imu_rows.append((ts_token, ts_num))
    finally:
        stream.close()
        if zf_obj:
            zf_obj.close()

    return imu_rows


def main():
    if len(sys.argv) != 3:
        die(f"Usage: {sys.argv[0]} <estimated_trajectory.txt> <input>")

    traj_path = sys.argv[1]
    imu_path = sys.argv[2]

    imu_rows = read_input_imu(imu_path)
    expected_rows = len(imu_rows)
    if expected_rows == 0:
        die(f"No valid data rows found in input {imu_path}")

    _, ts_unit = detect_ts_scale([r[1] for r in imu_rows])

    # Parse trajectory
    rows = []
    prev_ts = None
    errors = []

    with open(traj_path, "r", encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            cols = line.split()
            # Check 1: exactly 8 columns
            if len(cols) != 8:
                errors.append(f"Line {line_no}: expected 8 columns, got {len(cols)}")
                continue

            # Check 4: no NaN/Inf
            vals = []
            for i, c in enumerate(cols):
                try:
                    v = float(c)
                except ValueError:
                    errors.append(f"Line {line_no}, col {i}: cannot parse '{c}'")
                    continue
                if math.isnan(v) or math.isinf(v):
                    errors.append(f"Line {line_no}, col {i}: NaN/Inf value '{c}'")
                vals.append(v)

            if len(vals) != 8:
                continue

            ts = vals[0]
            qx, qy, qz, qw = vals[4], vals[5], vals[6], vals[7]

            # Check 2: monotonic timestamps (dt >= 0)
            if prev_ts is not None and ts < prev_ts:
                errors.append(f"Line {line_no}: timestamp {ts} < previous {prev_ts}")
            prev_ts = ts

            # Check 3: quaternion norm
            qnorm = math.sqrt(qx*qx + qy*qy + qz*qz + qw*qw)
            if abs(qnorm - 1.0) > 1e-4:
                errors.append(f"Line {line_no}: quat norm = {qnorm:.6f} (expected 1.0)")

            rows.append((ts, cols[0]))

    # Check 5: row count
    if len(rows) != expected_rows:
        errors.append(
            f"Row count mismatch: output trajectory has {len(rows)} rows, "
            f"input IMU CSV has {expected_rows} data rows"
        )

    # Check 6: timestamp values match expected format
    n_check = min(len(rows), len(imu_rows))
    for i in range(n_check):
        expected_str = format_expected_ts(imu_rows[i][0], ts_unit)
        if expected_str is not None:
            actual_str = rows[i][1]
            if actual_str != expected_str:
                errors.append(
                    f"Row {i+1}: timestamp mismatch: got '{actual_str}', expected '{expected_str}'"
                )
                if len(errors) > 10:
                    errors.append("  (stopping timestamp checks after 10 mismatches)")
                    break

    # Report
    if errors:
        print(f"VALIDATION FAILED ({len(errors)} error(s)):")
        for e in errors[:20]:
            print(f"  {e}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more errors.")
        sys.exit(1)
    else:
        print(f"VALIDATION PASSED: {len(rows)} rows, all checks OK.")
        sys.exit(0)


if __name__ == "__main__":
    main()
