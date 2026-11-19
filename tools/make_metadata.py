#!/usr/bin/env python3
"""
tools/make_metadata.py - Generate metadata.json from standardized real system measurements.

Records:
  - heap_peak_mb_tracemalloc: pure runtime heap from tracemalloc-ON run
  - in_process_ms_per_s_median5: median of 5 in-process runs with tracemalloc OFF
  - cli_ms_per_s_median5: median of 5 CLI subprocess runs (includes interpreter startup/teardown)
  - cli_peak_rss_mb: OS process peak resident set size (diagnostic only)
Covers:
  - MH_01 full-degraded (CSV and ZIP)
  - V1_01 full-degraded (CSV and ZIP)
  - 21-minute flight (CSV and ZIP)
"""

import os
import sys
import json
import time
import math
import gc
import hashlib
import zipfile
import statistics
import datetime
import platform
import subprocess
import tracemalloc
import psutil

# Ensure main is importable
sys.path.insert(0, os.path.abspath("src" if os.path.exists("src/main.py") else "."))
import main as app_main


def get_cpu_name():
    try:
        res = subprocess.run(
            ["powershell", "-Command", "(Get-CimInstance Win32_Processor).Name"],
            capture_output=True, text=True, timeout=5
        )
        name = res.stdout.strip()
        if name:
            return name
    except Exception:
        pass
    return platform.processor() or platform.machine()


def find_dataset(rel_path):
    candidates = [
        rel_path,
        os.path.join("..", "pathfinder", rel_path),
        os.path.join("C:/pathfinder", rel_path),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    raise FileNotFoundError(f"Could not locate dataset: {rel_path}")


def detect_imu_duration(imu_path):
    first_ts = None
    last_ts = None
    dt_list = []
    prev_ts = None

    if zipfile.is_zipfile(imu_path) or imu_path.lower().endswith(".zip"):
        with zipfile.ZipFile(imu_path, "r") as zf:
            target = None
            for n in zf.namelist():
                norm = n.replace("\\", "/").strip()
                if norm == "imu0/data.csv" or norm.endswith("/imu0/data.csv"):
                    target = n
                    break
            if target is None:
                for n in zf.namelist():
                    if n.lower().endswith(".csv") and not n.startswith("__MACOSX"):
                        target = n
                        break
            with zf.open(target, "r") as bio:
                import io
                with io.TextIOWrapper(bio, encoding="utf-8-sig") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        parts = line.split(",") if "," in line else line.split()
                        try:
                            ts = float(parts[0]) if "." in parts[0] else int(parts[0])
                        except Exception:
                            continue
                        if first_ts is None:
                            first_ts = ts
                        last_ts = ts
                        if prev_ts is not None and ts > prev_ts and len(dt_list) < 500:
                            dt_list.append(ts - prev_ts)
                        prev_ts = ts
    else:
        with open(imu_path, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(",") if "," in line else line.split()
                try:
                    ts = float(parts[0]) if "." in parts[0] else int(parts[0])
                except Exception:
                    continue
                if first_ts is None:
                    first_ts = ts
                last_ts = ts
                if prev_ts is not None and ts > prev_ts and len(dt_list) < 500:
                    dt_list.append(ts - prev_ts)
                prev_ts = ts

    if first_ts is None or last_ts is None:
        return 1.0

    med_dt = statistics.median(dt_list) if dt_list else 0.005
    scale = 1.0 if med_dt < 1.0 else (1e-3 if med_dt < 1e3 else (1e-6 if med_dt < 1e6 else 1e-9))
    return (last_ts - first_ts) * scale


def measure_target(imu_path, runs=5):
    main_py = os.path.abspath("src/main.py" if os.path.exists("src/main.py") else "main.py")
    tmp_out = os.path.abspath("tests/test_variants_tmp/tmp_meta_meas.txt")
    os.makedirs(os.path.dirname(tmp_out), exist_ok=True)

    dur = detect_imu_duration(imu_path)

    # 1. Tracemalloc Peak Heap (one in-process run, module imported outside)
    orig_argv = list(sys.argv)
    sys.argv = [main_py, imu_path, tmp_out]
    gc.collect()
    tracemalloc.start()
    app_main.main()
    curr_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peak_heap_mb = peak_bytes / (1024.0 * 1024.0)

    # 2. In-Process Compute Time (median of 5 runs, tracemalloc OFF)
    in_times = []
    for _ in range(runs):
        if os.path.exists(tmp_out):
            os.remove(tmp_out)
        gc.collect()
        sys.argv = [main_py, imu_path, tmp_out]
        t0_in = time.perf_counter()
        app_main.main()
        t1_in = time.perf_counter()
        in_times.append(t1_in - t0_in)
    sys.argv = orig_argv

    median_in_time = statistics.median(in_times)
    in_ms_per_s = (median_in_time * 1000.0) / dur if dur > 0 else float("inf")

    # 3. Subprocess CLI (median of 5 runs)
    sub_times = []
    peak_rss = 0
    for _ in range(runs):
        if os.path.exists(tmp_out):
            os.remove(tmp_out)
        t0_sub = time.perf_counter()
        p = subprocess.Popen(
            [sys.executable, main_py, imu_path, tmp_out],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        proc = psutil.Process(p.pid)
        while p.poll() is None:
            try:
                rss = proc.memory_info().rss
                if rss > peak_rss:
                    peak_rss = rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            time.sleep(0.005)
        p.communicate()
        t1_sub = time.perf_counter()
        sub_times.append(t1_sub - t0_sub)

    median_sub_time = statistics.median(sub_times)
    sub_ms_per_s = (median_sub_time * 1000.0) / dur if dur > 0 else float("inf")
    peak_rss_mb = peak_rss / (1024.0 * 1024.0)

    if os.path.exists(tmp_out):
        os.remove(tmp_out)

    return {
        "dataset_duration_seconds": round(dur, 3),
        "heap_peak_mb_tracemalloc": round(peak_heap_mb, 3),
        "in_process_ms_per_s_median5": round(in_ms_per_s, 3),
        "cli_ms_per_s_median5": round(sub_ms_per_s, 3),
        "cli_peak_rss_mb": round(peak_rss_mb, 3),
        "heap_budget_status": "PASS" if peak_heap_mb <= 8.0 else "FAIL",
        "speed_budget_status": "PASS" if sub_ms_per_s <= 10.0 else "FAIL",
    }


def main():
    print("Generating metadata.json from standardized real system measurements...")
    main_py_path = os.path.abspath("src/main.py" if os.path.exists("src/main.py") else "main.py")
    with open(main_py_path, "rb") as f:
        main_py_sha256 = hashlib.sha256(f.read()).hexdigest()

    targets = [
        ("MH_01_full_degraded_csv", find_dataset("data/MH_01_easy/imu_degraded.csv")),
        ("MH_01_full_degraded_zip", find_dataset("data/MH_01_easy/imu_degraded.zip")),
        ("V1_01_full_degraded_csv", find_dataset("data/V1_01_easy/imu_degraded.csv")),
        ("V1_01_full_degraded_zip", find_dataset("data/V1_01_easy/imu_degraded.zip")),
        ("21_minute_flight_csv", r"C:\pathfinder\temp_long_21m.csv"),
        ("21_minute_flight_zip", r"C:\pathfinder\temp_long_21m.zip"),
    ]

    perf_data = {}
    for key, path in targets:
        print(f"Measuring {key} ({path})...")
        perf_data[key] = measure_target(path, runs=5)

    metadata = {
        "project": "Samsung PRISM XR Hackathon - Track 3 (Path Finder)",
        "language": "Python",
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "cpu": get_cpu_name(),
        "src_main_sha256": main_py_sha256,
        "algorithm_summary": (
            "Bounded-drift Mahony complementary filter with gate-controlled tilt correction, "
            "stillness-detected initial bias calibration, exponential velocity leak, and slow exponential moving average position restoring."
        ),
        "parameters": {
            "TAU_V": 1.0,
            "KP": 8.0,
            "KI": 0.02,
            "KP_BOOST": 10.0,
            "GATE": 3.0,
            "TAU_P": 40.0,
            "COAST_MODE": "M1",
            "TAU_C": "inf",
            "USE_ZUPT": True,
        },
        "performance": perf_data,
        "timing_primary": "cli_ms_per_s_median5",
        "notes": {
            "cli_peak_rss_mb": (
                "Includes the Python interpreter and runtime libraries; this is NOT the algorithm heap. "
                "The algorithm heap is heap_peak_mb_tracemalloc."
            ),
            "in_process_timing": (
                "In-process repeated-run timing is higher than CLI on the test laptop. "
                "The first in-process run was 2.09 ms per 1 s, matching the CLI rate; "
                "later repeated runs in the same process were 4-8 ms per 1 s. Cause not verified."
            ),
        },
        "input_formats_accepted": [
            "CSV (standard 7-column: timestamp, ax, ay, az, gx, gy, gz)",
            "Raw EuRoC CSV (imu0/data.csv: ts, wx, wy, wz, ax, ay, az with #ns header)",
            "ZIP archive (streaming imu0/data.csv or first CSV in-memory with zero disk extraction)",
            "Directory path (locating imu0/data.csv or first CSV)",
            "Delimiters: comma, semicolon, tab, whitespace",
            "Timestamps: integer or float nanoseconds, microseconds, milliseconds, seconds",
            "Acceleration units: m/s^2 (nominal norm in [7, 12]), g (nominal norm in [0.7, 1.3], auto-scaled by 9.80665)",
            "Robustness: NaN/empty/duplicate rows repeat or coast without crashing",
        ],
        "output_format": "TUM trajectory (timestamp tx ty tz qx qy qz qw, seconds formatted with 9 decimal digits)",
        "timestamp_generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    out_file = "metadata.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print(f"\nSuccessfully generated {out_file} (SHA256 of main.py: {main_py_sha256})")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
