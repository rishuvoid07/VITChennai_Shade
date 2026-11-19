#!/usr/bin/env python3
"""
tests/test_formats.py - Format robustness test suite for Track 3 (Path Finder).

Generates variants from clean 7-col CSV:
  1. raw EuRoC imu0/data.csv (gyro-first with the ns header)
  2. no header
  3. ms (integer milliseconds)
  4. us (integer microseconds)
  5. float seconds
  6. accel in g (divided by 9.80665)
  7. semicolon delimiter
  8. whitespace delimiter
  9. CRLF + BOM + trailing blank lines
  10. zip input (streamed via zipfile)
  11. directory input (imu0/data.csv)
  12. 1-row file
  13. 2-row file
  14. 10-row file
  15. file with NaN and empty fields

Runs main.py + tools/validate_output.py on each:
  - Row count == input rows
  - 8 columns
  - Finite values (no NaN/Inf)
  - Monotonically non-decreasing timestamps
  - Unit quaternions (|norm - 1| <= 1e-4)
  - ATE matching reference run within 1% (for full-sequence variants)
Prints a comprehensive pass/fail table.
"""

import os
import sys
import math
import shutil
import zipfile
import subprocess
import numpy as np

def find_dataset(rel_p):
    for c in [rel_p, os.path.join("..", "pathfinder", rel_p), os.path.join("C:/pathfinder", rel_p)]:
        if os.path.exists(c):
            return c
    return rel_p

CLEAN_PATH = find_dataset("data/MH_01_easy/imu_clean_7col.csv")
GT_PATH = find_dataset("data/MH_01_easy/groundtruth_tum.txt")
TMP_DIR = "tests/test_variants_tmp"
G_GRAV = 9.80665
MAIN_PY = "src/main.py" if os.path.exists("src/main.py") else "main.py"


def run_cmd(cmd_list):
    res = subprocess.run(cmd_list, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return res.returncode, res.stdout, res.stderr


def eval_ate(est_path, gt_path):
    from evo.tools import file_interface
    from evo.core import sync, metrics
    import copy

    traj_ref = file_interface.read_tum_trajectory_file(gt_path)
    traj_est = file_interface.read_tum_trajectory_file(est_path)
    ref_sync, est_sync = sync.associate_trajectories(traj_ref, traj_est, max_diff=0.01)
    if len(ref_sync.timestamps) < 5:
        return math.nan
    est_aligned = copy.deepcopy(est_sync)
    est_aligned.align(ref_sync, correct_scale=False, correct_only_scale=False)
    ape = metrics.APE(metrics.PoseRelation.translation_part)
    ape.process_data((ref_sync, est_aligned))
    return float(ape.get_statistic(metrics.StatisticsType.rmse))


def create_variants(clean_rows, clean_header):
    os.makedirs(TMP_DIR, exist_ok=True)
    variants = {}

    # Parsed clean rows: (ts, ax, ay, az, gx, gy, gz)
    data = []
    for r in clean_rows:
        parts = r.strip().split(",")
        data.append((int(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]),
                     float(parts[4]), float(parts[5]), float(parts[6])))

    # 1. raw EuRoC (gyro-first with ns header)
    p1 = os.path.join(TMP_DIR, "raw_euroc.csv")
    with open(p1, "w", encoding="utf-8") as f:
        f.write("#timestamp [ns],w_RS_S_x [rad s^-1],w_RS_S_y [rad s^-1],w_RS_S_z [rad s^-1],a_RS_S_x [m s^-2],a_RS_S_y [m s^-2],a_RS_S_z [m s^-2]\n")
        for ts, ax, ay, az, gx, gy, gz in data:
            f.write(f"{ts},{gx},{gy},{gz},{ax},{ay},{az}\n")
    variants["1. Raw EuRoC (gyro-first, #ns header)"] = (p1, True)

    # 2. no header
    p2 = os.path.join(TMP_DIR, "no_header.csv")
    with open(p2, "w", encoding="utf-8") as f:
        for ts, ax, ay, az, gx, gy, gz in data:
            f.write(f"{ts},{ax},{ay},{az},{gx},{gy},{gz}\n")
    variants["2. No header (numeric first line)"] = (p2, True)

    # 3. ms timestamps
    p3 = os.path.join(TMP_DIR, "ts_ms.csv")
    with open(p3, "w", encoding="utf-8") as f:
        f.write("timestamp,ax,ay,az,gx,gy,gz\n")
        for ts, ax, ay, az, gx, gy, gz in data:
            f.write(f"{ts // 1000000},{ax},{ay},{az},{gx},{gy},{gz}\n")
    variants["3. Milliseconds timestamps (ms)"] = (p3, True)

    # 4. us timestamps
    p4 = os.path.join(TMP_DIR, "ts_us.csv")
    with open(p4, "w", encoding="utf-8") as f:
        f.write("timestamp,ax,ay,az,gx,gy,gz\n")
        for ts, ax, ay, az, gx, gy, gz in data:
            f.write(f"{ts // 1000},{ax},{ay},{az},{gx},{gy},{gz}\n")
    variants["4. Microseconds timestamps (us)"] = (p4, True)

    # 5. float seconds
    p5 = os.path.join(TMP_DIR, "ts_float_sec.csv")
    with open(p5, "w", encoding="utf-8") as f:
        f.write("timestamp,ax,ay,az,gx,gy,gz\n")
        for ts, ax, ay, az, gx, gy, gz in data:
            f.write(f"{ts * 1e-9:.9f},{ax},{ay},{az},{gx},{gy},{gz}\n")
    variants["5. Float seconds timestamps (s)"] = (p5, True)

    # 6. accel in g
    p6 = os.path.join(TMP_DIR, "accel_in_g.csv")
    with open(p6, "w", encoding="utf-8") as f:
        f.write("timestamp,ax,ay,az,gx,gy,gz\n")
        for ts, ax, ay, az, gx, gy, gz in data:
            f.write(f"{ts},{ax/G_GRAV:.6f},{ay/G_GRAV:.6f},{az/G_GRAV:.6f},{gx},{gy},{gz}\n")
    variants["6. Accel in g (auto-detected)"] = (p6, True)

    # 7. semicolon delimiter
    p7 = os.path.join(TMP_DIR, "semicolon.csv")
    with open(p7, "w", encoding="utf-8") as f:
        f.write("timestamp;ax;ay;az;gx;gy;gz\n")
        for ts, ax, ay, az, gx, gy, gz in data:
            f.write(f"{ts};{ax};{ay};{az};{gx};{gy};{gz}\n")
    variants["7. Semicolon delimiter (;)"] = (p7, True)

    # 8. whitespace delimiter
    p8 = os.path.join(TMP_DIR, "whitespace.txt")
    with open(p8, "w", encoding="utf-8") as f:
        f.write("timestamp ax ay az gx gy gz\n")
        for ts, ax, ay, az, gx, gy, gz in data:
            f.write(f"{ts} {ax} {ay} {az} {gx} {gy} {gz}\n")
    variants["8. Whitespace delimiter (spaces)"] = (p8, True)

    # 9. CRLF + BOM + trailing blank lines
    p9 = os.path.join(TMP_DIR, "crlf_bom_blanks.csv")
    with open(p9, "w", encoding="utf-8-sig", newline="") as f:
        f.write("timestamp,ax,ay,az,gx,gy,gz\r\n")
        for ts, ax, ay, az, gx, gy, gz in data:
            f.write(f"{ts},{ax},{ay},{az},{gx},{gy},{gz}\r\n")
        f.write("\r\n\r\n\r\n")
    variants["9. CRLF + BOM + trailing blank lines"] = (p9, True)

    # 10. zip input (contains imu0/data.csv)
    p10 = os.path.join(TMP_DIR, "imu_dataset.zip")
    with zipfile.ZipFile(p10, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("imu0/data.csv", "".join([clean_header] + clean_rows))
    variants["10. Zip archive (streaming imu0/data.csv)"] = (p10, True)

    # 11. directory input (contains imu0/data.csv)
    p11 = os.path.join(TMP_DIR, "imu_dir")
    imu0_dir = os.path.join(p11, "imu0")
    os.makedirs(imu0_dir, exist_ok=True)
    with open(os.path.join(imu0_dir, "data.csv"), "w", encoding="utf-8") as f:
        f.write(clean_header)
        f.writelines(clean_rows)
    variants["11. Directory input (imu0/data.csv)"] = (p11, True)

    # 12. 1-row file
    p12 = os.path.join(TMP_DIR, "one_row.csv")
    with open(p12, "w", encoding="utf-8") as f:
        f.write(clean_header)
        f.write(clean_rows[0])
    variants["12. 1-row file"] = (p12, False)

    # 13. 2-row file
    p13 = os.path.join(TMP_DIR, "two_rows.csv")
    with open(p13, "w", encoding="utf-8") as f:
        f.write(clean_header)
        f.writelines(clean_rows[:2])
    variants["13. 2-row file"] = (p13, False)

    # 14. 10-row file
    p14 = os.path.join(TMP_DIR, "ten_rows.csv")
    with open(p14, "w", encoding="utf-8") as f:
        f.write(clean_header)
        f.writelines(clean_rows[:10])
    variants["14. 10-row file"] = (p14, False)

    # 15. file with NaN / empty fields / unparsable fields
    p15 = os.path.join(TMP_DIR, "nan_empty_fields.csv")
    with open(p15, "w", encoding="utf-8") as f:
        f.write(clean_header)
        for idx, r in enumerate(clean_rows):
            if idx == 100:
                # empty fields
                f.write(f"{data[idx][0]},,,,,\n")
            elif idx == 200:
                # NaN fields
                f.write(f"{data[idx][0]},NaN,NaN,NaN,0.0,0.0,0.0\n")
            elif idx == 300:
                # unparsable strings
                f.write(f"{data[idx][0]},bad,row,corrupt,0.1,0.2,0.3\n")
            elif idx == 400:
                # duplicate timestamp
                f.write(f"{data[idx-1][0]},{data[idx][1]},{data[idx][2]},{data[idx][3]},{data[idx][4]},{data[idx][5]},{data[idx][6]}\n")
            elif idx == 500:
                # all zeros
                f.write(f"{data[idx][0]},0.0,0.0,0.0,0.0,0.0,0.0\n")
            else:
                f.write(r)
    variants["15. File with NaN/empty/duplicate rows"] = (p15, True)

    return variants


def main():
    print("=" * 80)
    print("  STAGE 3B-2: FORMAT & DEGRADATION ROBUSTNESS TEST SUITE")
    print("=" * 80)

    # 1. Run reference clean
    ref_traj = os.path.join(TMP_DIR, "ref_trajectory.txt")
    os.makedirs(TMP_DIR, exist_ok=True)
    code, out, err = run_cmd([sys.executable, MAIN_PY, CLEAN_PATH, ref_traj])
    if code != 0:
        sys.exit(f"Failed to run reference clean:\n{err}")

    ref_ate = eval_ate(ref_traj, GT_PATH)
    print(f"Reference Run Clean ATE: {ref_ate:.4f} m\n")

    # Read clean rows
    with open(CLEAN_PATH, "r", encoding="utf-8-sig") as f:
        clean_header = f.readline()
        clean_rows = f.readlines()

    variants = create_variants(clean_rows, clean_header)

    results = []
    print(f"Testing {len(variants)} format variants...\n")

    for name, (var_path, check_ate) in variants.items():
        var_traj = os.path.join(TMP_DIR, "traj_test.txt")
        if os.path.exists(var_traj):
            os.unlink(var_traj)

        # 1. Run main.py
        code_main, out_main, err_main = run_cmd([sys.executable, MAIN_PY, var_path, var_traj])
        main_ok = (code_main == 0 and os.path.exists(var_traj))

        # 2. Run validate_output.py
        code_val, out_val, err_val = run_cmd([sys.executable, "tools/validate_output.py", var_traj, var_path])
        val_ok = (code_val == 0)

        # 3. Evaluate ATE
        var_ate = math.nan
        ate_match = "N/A"
        ate_diff_pct = 0.0
        if val_ok and check_ate:
            var_ate = eval_ate(var_traj, GT_PATH)
            if not math.isnan(var_ate) and not math.isnan(ref_ate):
                ate_diff_pct = abs(var_ate - ref_ate) / ref_ate * 100.0
                ate_match = "PASS" if ate_diff_pct <= 1.0 else f"DIFF {ate_diff_pct:.2f}%"

        overall_pass = main_ok and val_ok and (ate_match in ("PASS", "N/A"))
        results.append({
            "name": name,
            "main_ok": "PASS" if main_ok else "FAIL",
            "val_ok": "PASS" if val_ok else "FAIL",
            "ate": f"{var_ate:.4f} m" if not math.isnan(var_ate) else "N/A",
            "ate_diff": f"{ate_diff_pct:.3f}%" if not math.isnan(var_ate) else "N/A",
            "ate_match": ate_match,
            "overall": "PASS" if overall_pass else "FAIL"
        })

    # Print markdown table
    print("\n" + "=" * 105)
    print("  FORMAT ROBUSTNESS TEST RESULTS TABLE")
    print("=" * 105)
    header_line = f"| {'Variant Name':<42} | {'main.py':<8} | {'Validate':<8} | {'ATE Aligned':<12} | {'ATE Diff %':<11} | {'Status':<6} |"
    sep_line    = f"|:{'-'*42}-|:{'-'*8}-|:{'-'*8}-|:{'-'*12}-|:{'-'*11}-|:{'-'*6}-|"
    print(header_line)
    print(sep_line)
    for r in results:
        line = f"| {r['name']:<42} | {r['main_ok']:<8} | {r['val_ok']:<8} | {r['ate']:<12} | {r['ate_diff']:<11} | **{r['overall']}** |"
        print(line)
    print("=" * 105)

    all_passed = all(r["overall"] == "PASS" for r in results)
    if all_passed:
        print("\nALL 15 FORMAT ROBUSTNESS TESTS PASSED (100% SUCCESS).\n")
    else:
        print("\nSOME TESTS FAILED. Check details above.\n")

    # Clean up temporary variants
    shutil.rmtree(TMP_DIR, ignore_errors=True)
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
