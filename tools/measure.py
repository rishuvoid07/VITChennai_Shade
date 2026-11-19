#!/usr/bin/env python3
"""
tools/measure.py - Consistent measurement harness for Track 3 (Path Finder).

Methodology:
  - Heap: One in-process run with tracemalloc ON (measuring true runtime Python heap peak,
          excluding module compilation and AST setup).
  - Time: In-process runs with tracemalloc OFF, perf_counter, median of 5 runs
          (including parse + filter step + output formatting + disk writing).
  - Subprocess Wall Time: CLI subprocess runs (python src/main.py in out), median of 5 runs
          (including Python VM startup, imports, OS file buffer allocation, and teardown).

Datasets:
  1. MH_01 full-degraded CSV
  2. MH_01 full-degraded ZIP
  3. V1_01 full-degraded CSV
  4. V1_01 full-degraded ZIP
  5. 21-minute CSV
  6. 21-minute ZIP
"""

import os
import sys
import time
import zipfile
import statistics
import tracemalloc
import subprocess
import gc
import psutil

# Ensure src/main.py is importable
sys.path.insert(0, os.path.abspath("src" if os.path.exists("src/main.py") else "."))
import main as app_main


def find_dataset(rel_p):
    for c in [rel_p, os.path.join("..", "pathfinder", rel_p), os.path.join("C:/pathfinder", rel_p)]:
        if os.path.exists(c):
            return c
    return rel_p


def detect_imu_duration(imu_path):
    """Detects duration in seconds from CSV or ZIP archive."""
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


def measure_dataset(name, input_path, runs=5):
    main_script = os.path.abspath("src/main.py" if os.path.exists("src/main.py") else "main.py")
    tmp_out = os.path.abspath("tests/test_variants_tmp/measure_tmp_out.txt")
    os.makedirs(os.path.dirname(tmp_out), exist_ok=True)

    duration_s = detect_imu_duration(input_path)

    # 1. In-process Peak Heap (one run with tracemalloc ON)
    orig_argv = list(sys.argv)
    sys.argv = [main_script, input_path, tmp_out]
    gc.collect()
    tracemalloc.start()
    app_main.main()
    cur_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peak_heap_mb = peak_bytes / (1024.0 * 1024.0)

    # 2. In-process Compute Time (median of 5 runs, tracemalloc OFF)
    in_times = []
    for _ in range(runs):
        if os.path.exists(tmp_out):
            os.remove(tmp_out)
        gc.collect()
        sys.argv = [main_script, input_path, tmp_out]
        t0 = time.perf_counter()
        app_main.main()
        t1 = time.perf_counter()
        in_times.append(t1 - t0)
    sys.argv = orig_argv

    median_in_time = statistics.median(in_times)
    in_ms_per_s = (median_in_time * 1000.0) / duration_s

    # 3. Subprocess Wall Time (median of 5 runs)
    sub_times = []
    peak_rss = 0
    for _ in range(runs):
        if os.path.exists(tmp_out):
            os.remove(tmp_out)
        t0 = time.perf_counter()
        p = subprocess.Popen(
            [sys.executable, main_script, input_path, tmp_out],
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
        t1 = time.perf_counter()
        sub_times.append(t1 - t0)

    median_sub_time = statistics.median(sub_times)
    sub_ms_per_s = (median_sub_time * 1000.0) / duration_s
    peak_rss_mb = peak_rss / (1024.0 * 1024.0)

    if os.path.exists(tmp_out):
        os.remove(tmp_out)

    return {
        "name": name,
        "duration_s": duration_s,
        "peak_heap_mb": peak_heap_mb,
        "peak_heap_bytes": peak_bytes,
        "median_in_time_s": median_in_time,
        "in_ms_per_s": in_ms_per_s,
        "median_sub_time_s": median_sub_time,
        "sub_ms_per_s": sub_ms_per_s,
        "peak_rss_mb": peak_rss_mb,
    }


def main():
    print("=" * 110)
    print("  STAGE 5B: STANDARDIZED CONSISTENT MEASUREMENT HARNESS")
    print("=" * 110)

    targets = [
        ("MH_01 Full-Degraded CSV", find_dataset("data/MH_01_easy/imu_degraded.csv")),
        ("MH_01 Full-Degraded ZIP", find_dataset("data/MH_01_easy/imu_degraded.zip")),
        ("V1_01 Full-Degraded CSV", find_dataset("data/V1_01_easy/imu_degraded.csv")),
        ("V1_01 Full-Degraded ZIP", find_dataset("data/V1_01_easy/imu_degraded.zip")),
        ("21-minute Flight CSV", r"C:\pathfinder\temp_long_21m.csv"),
        ("21-minute Flight ZIP", r"C:\pathfinder\temp_long_21m.zip"),
    ]

    results = []
    for name, p in targets:
        print(f"Measuring {name} ({p})...")
        res = measure_dataset(name, p, runs=5)
        results.append(res)

    print("\n" + "=" * 125)
    print("  MEASUREMENT RESULTS TABLE (Median of 5 Runs)")
    print("=" * 125)
    print(f"| {'Dataset Input Target':<26} | {'Duration (s)':<12} | {'Peak Heap (MB)':<14} | {'In-Proc Time (s)':<16} | {'In-Proc ms/s':<13} | {'Subproc Wall (s)':<16} | {'Subproc ms/s':<13} |")
    print("|:" + "-"*26 + "|:" + "-"*12 + "|:" + "-"*14 + "|:" + "-"*16 + "|:" + "-"*13 + "|:" + "-"*16 + "|:" + "-"*13 + ":|")

    for r in results:
        print(
            f"| {r['name']:<26} | {r['duration_s']:<12.2f} | {r['peak_heap_mb']:<14.3f} | "
            f"{r['median_in_time_s']:<16.4f} | {r['in_ms_per_s']:<13.3f} | "
            f"{r['median_sub_time_s']:<16.4f} | {r['sub_ms_per_s']:<13.3f} |"
        )
    print("=" * 125)

    print("\nColumn Definitions:")
    print("  1. Dataset Input Target: The specific test sequence and container format (plain CSV vs streaming ZIP).")
    print("  2. Duration (s): Total physical flight time represented in the dataset based on timestamps.")
    print("  3. Peak Heap (MB): Peak memory tracked by tracemalloc inside an in-process execution of main() (target <= 8.0 MB).")
    print("  4. In-Proc Time (s): Median wall time across 5 in-process runs of main() with tracemalloc OFF (perf_counter).")
    print("  5. In-Proc ms/s: Native compute cost per 1 second of IMU input (In-Proc Time * 1000 / Duration) (target <= 10.0 ms/s).")
    print("  6. Subproc Wall (s): Median wall time across 5 CLI subprocess runs (python src/main.py in out) including interpreter init.")
    print("  7. Subproc ms/s: Total system throughput cost per 1 second of IMU input at OS CLI level.")

    print("\nHeap Difference Explanation:")
    print("  The Stage 5 3-minute heap (2.66 MB) was measured by invoking `runpy.run_path`, which traced the memory allocated")
    print("  by Python's compiler, AST generator, and module namespace initialization inside tracemalloc, whereas the 21-minute")
    print("  test imported `main` before starting tracemalloc and thus measured only the true estimator runtime heap (~1.1 MB).")


if __name__ == "__main__":
    main()
