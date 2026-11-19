#!/usr/bin/env python3
"""
tests/test_zip_layouts.py - Zip layout and robustness tests for Track 3 (Path Finder).

Tests:
  (a) imu0/data.csv at root
  (b) mav0/imu0/data.csv
  (c) MH_01_easy/mav0/imu0/data.csv
  (d) top folder name with spaces ("My Space Dataset/mav0/imu0/data.csv")
  (e) extra entries: __MACOSX/._data.csv, cam0/data.csv, state_groundtruth_estimate0/data.csv, directory entries
  (f) file without a trailing newline
  (g) line longer than 64 KiB (garbage line in the middle)
  (h) zip with a single CSV named differently (imu.csv)
  (i) negative test: ambiguous multiple CSVs with no imu0/data.csv (must exit non-zero)
  (j) negative test: no CSV inside zip (must exit non-zero)
"""

import os
import sys
import shutil
import zipfile
import hashlib
import subprocess

def find_dataset(rel_p):
    for c in [rel_p, os.path.join("..", "pathfinder", rel_p), os.path.join("C:/pathfinder", rel_p)]:
        if os.path.exists(c):
            return c
    return rel_p

CLEAN_CSV = find_dataset("data/MH_01_easy/imu_clean_7col.csv")
TMP_DIR = "tests/test_zip_tmp"
MAIN_PY = "src/main.py" if os.path.exists("src/main.py") else "main.py"


def main():
    os.makedirs(TMP_DIR, exist_ok=True)
    with open(CLEAN_CSV, "r", encoding="utf-8") as f:
        clean_content = f.read()

    # Reference output from clean CSV
    ref_out = os.path.join(TMP_DIR, "ref_out.txt")
    subprocess.run(["py", "-3.12", MAIN_PY, CLEAN_CSV, ref_out], check=True, capture_output=True)
    ref_sha = hashlib.sha256(open(ref_out, "rb").read()).hexdigest()

    test_zips = {}

    # (a) imu0/data.csv at root
    pa = os.path.join(TMP_DIR, "layout_a_root.zip")
    with zipfile.ZipFile(pa, "w") as zf:
        zf.writestr("imu0/data.csv", clean_content)
    test_zips["(a) imu0/data.csv at root"] = (pa, True, ref_sha)

    # (b) mav0/imu0/data.csv
    pb = os.path.join(TMP_DIR, "layout_b_mav0.zip")
    with zipfile.ZipFile(pb, "w") as zf:
        zf.writestr("mav0/imu0/data.csv", clean_content)
    test_zips["(b) mav0/imu0/data.csv"] = (pb, True, ref_sha)

    # (c) MH_01_easy/mav0/imu0/data.csv
    pc = os.path.join(TMP_DIR, "layout_c_nested.zip")
    with zipfile.ZipFile(pc, "w") as zf:
        zf.writestr("MH_01_easy/mav0/imu0/data.csv", clean_content)
    test_zips["(c) MH_01_easy/mav0/imu0/data.csv"] = (pc, True, ref_sha)

    # (d) top folder name with spaces
    pd = os.path.join(TMP_DIR, "layout_d_spaces.zip")
    with zipfile.ZipFile(pd, "w") as zf:
        zf.writestr("My Dataset Folder With Spaces/mav0/imu0/data.csv", clean_content)
    test_zips["(d) Top folder name with spaces"] = (pd, True, ref_sha)

    # (e) extra entries: __MACOSX/._data.csv, other CSVs, directory entries
    pe = os.path.join(TMP_DIR, "layout_e_extra_entries.zip")
    with zipfile.ZipFile(pe, "w") as zf:
        zf.writestr("mav0/", "")
        zf.writestr("mav0/imu0/", "")
        zf.writestr("mav0/imu0/data.csv", clean_content)
        zf.writestr("__MACOSX/._data.csv", "mac binary metadata")
        zf.writestr("__MACOSX/mav0/._imu0", "mac binary metadata")
        zf.writestr("mav0/cam0/data.csv", "timestamp,filename\n100,cam0.png\n")
        zf.writestr("mav0/state_groundtruth_estimate0/data.csv", "timestamp,p_x,p_y,p_z\n100,0,0,0\n")
    test_zips["(e) Extra entries (__MACOSX, other CSVs)"] = (pe, True, ref_sha)

    # (f) file without trailing newline
    pf = os.path.join(TMP_DIR, "layout_f_no_trailing_newline.zip")
    clean_no_newline = clean_content.rstrip("\r\n")
    with zipfile.ZipFile(pf, "w") as zf:
        zf.writestr("imu0/data.csv", clean_no_newline)
    test_zips["(f) No trailing newline"] = (pf, True, ref_sha)

    # (g) line longer than 64 KiB (garbage line in the middle)
    pg = os.path.join(TMP_DIR, "layout_g_line_gt_64kb.zip")
    lines = clean_content.splitlines()
    # Insert a garbage line of 70,000 characters in the middle
    garbage_line = "GARBAGE_" + "X" * 70000
    mid = len(lines) // 2
    long_line_content = "\n".join(lines[:mid] + [garbage_line] + lines[mid:]) + "\n"
    with zipfile.ZipFile(pg, "w") as zf:
        zf.writestr("imu0/data.csv", long_line_content)
    # Reference for (g) computed by running frozen_py on the same content
    frozen_py = r"C:\pathfinder_frozen\main.py"
    g_raw = os.path.join(TMP_DIR, "g_raw.csv")
    with open(g_raw, "w", encoding="utf-8") as f:
        f.write(long_line_content)
    ref_g_out = os.path.join(TMP_DIR, "ref_g_out.txt")
    subprocess.run(["py", "-3.12", frozen_py, g_raw, ref_g_out], check=True, capture_output=True)
    ref_g_sha = hashlib.sha256(open(ref_g_out, "rb").read()).hexdigest()
    test_zips["(g) Line longer than 64 KiB (>70 KB)"] = (pg, True, ref_g_sha)

    # (h) single CSV named differently (imu.csv)
    ph = os.path.join(TMP_DIR, "layout_h_single_diff_name.zip")
    with zipfile.ZipFile(ph, "w") as zf:
        zf.writestr("sensor_readings/imu.csv", clean_content)
    test_zips["(h) Single CSV named differently (imu.csv)"] = (ph, True, ref_sha)

    # Negative tests:
    # (i) Ambiguous multiple CSVs with no imu0/data.csv
    pi = os.path.join(TMP_DIR, "layout_i_ambiguous.zip")
    with zipfile.ZipFile(pi, "w") as zf:
        zf.writestr("cam0/data.csv", "ts,val\n1,2\n")
        zf.writestr("cam1/data.csv", "ts,val\n1,2\n")
    test_zips["(i) Ambiguous CSVs without imu0/data.csv"] = (pi, False, None)

    # (j) No CSV inside zip
    pj = os.path.join(TMP_DIR, "layout_j_no_csv.zip")
    with zipfile.ZipFile(pj, "w") as zf:
        zf.writestr("info.txt", "just text\n")
    test_zips["(j) No CSV files inside zip"] = (pj, False, None)

    print("=" * 105)
    print("  STAGE 5B: ZIP LAYOUT ROBUSTNESS TEST SUITE")
    print("=" * 105)
    print(f"| {'Zip Layout Test Case':<45} | {'Expected':<10} | {'Return':<7} | {'SHA256 Match':<16} | {'Status':<6} |")
    print("|:" + "-"*45 + "|:" + "-"*10 + "|:" + "-"*7 + "|:" + "-"*16 + "|:" + "-"*6 + ":|")

    all_pass = True
    for name, (zpath, expect_success, expected_sha) in test_zips.items():
        out_p = os.path.join(TMP_DIR, "out.txt")
        if os.path.exists(out_p):
            os.remove(out_p)

        res = subprocess.run(["py", "-3.12", MAIN_PY, zpath, out_p], capture_output=True, text=True)

        if expect_success:
            if res.returncode != 0:
                print(f"| {name:<45} | Success    | {res.returncode:<7} | N/A              | FAIL   |")
                all_pass = False
            else:
                out_sha = hashlib.sha256(open(out_p, "rb").read()).hexdigest()
                match = (out_sha == expected_sha)
                if not match:
                    all_pass = False
                print(f"| {name:<45} | Success    | 0       | {'MATCH (' + out_sha[:6] + ')' if match else 'MISMATCH':<16} | {'PASS' if match else 'FAIL':<6} |")
        else:
            # Expect non-zero return code
            non_zero = (res.returncode != 0)
            if not non_zero:
                all_pass = False
            err_msg_printed = ("Error:" in res.stderr)
            status = "PASS" if (non_zero and err_msg_printed) else "FAIL"
            if status != "PASS":
                all_pass = False
            print(f"| {name:<45} | Non-Zero   | {res.returncode:<7} | {'ERROR LOGGED' if err_msg_printed else 'NO ERROR':<16} | {status:<6} |")

    shutil.rmtree(TMP_DIR, ignore_errors=True)

    print("=" * 105)
    print(f"OVERALL ZIP LAYOUT RESULT: {'ALL TESTS PASSED (100%)' if all_pass else 'FAILURES DETECTED'}")
    if not all_pass:
        sys.exit(1)


if __name__ == "__main__":
    main()
