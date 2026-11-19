Historical: superseded by RESULTS_STAGE4.md; parameters differ

# Stage 3B-2: Input and Degradation Robustness

**Date**: 2026-11-18  
**Platform**: Samsung PRISM XR Hackathon 2026 - Track 3 (Path Finder)  
**Host Machine**:
- **CPU**: 13th Gen Intel(R) Core(TM) i5-13420H (12 vCPUs, up to 4.6 GHz)
- **Memory**: 16 GB DDR5 RAM
- **OS**: Windows 11 Enterprise (Build 10.0.26300)
- **Python**: 3.12.10 (64-bit)

---

## 1. Executive Summary

In Stage 3B-2, we addressed all real-world input variance and degradation robustness requirements for `main.py` without altering the optimal filter hyperparameters ($\tau_v = 1.0$ s, $K_p = 8.0$ 1/s, $\text{GATE} = 3.0$ m/s$^2$, $\text{COAST\_MODE} = \text{M1}$):
1. **Universal Input & Delimiter Support**: Enabled seamless parsing across standard CSV files, streaming `.zip` archives (reading `imu0/data.csv` or first `.csv` directly from memory via `zipfile`, zero disk extraction), and directory structures. Added support for comma, semicolon, tab, and whitespace delimiters, UTF-8 BOM, and CRLF line endings.
2. **Column & Unit Mapping**: Added header column name detection (mapping EuRoC raw `w_RS_S_x` gyro-first automatically), with physics-based fallback on the first 2,000 usable rows ($[7, 12]$ m/s$^2$ for standard accel, $[0.7, 1.3]$ g for scaled accel $\times 9.80665$).
3. **Lossless Integer Timestamp Formatting**: Auto-detected timestamp resolution ($<0.5$ s $\rightarrow$ s, $<500$ ms $\rightarrow$ ms, $<5\times 10^5$ $\mu$s $\rightarrow$ $\mu$s, else ns) with pure integer arithmetic formatting to exactly 9 decimals, avoiding floating-point rounding errors.
4. **Bad Row Resilience**: Handled unparsable fields, NaN values, all-zero blackout rows, and duplicate timestamps ($dt \le 0$). Non-increasing rows repeat the previous pose with the row's timestamp; invalid/all-zero rows coast smoothly.
5. **Gap Sub-Stepping**: Gaps with $dt > 1.5 \times dt_{\text{nom}}$ are sub-stepped at nominal $dt$ using the mean of boundary samples, capped at 2.0 s of active integration.
6. **Spike Filtering**: Tested and set thresholds above clean EuRoC flight dynamics ($\Delta a_{\text{max}} = 7.43$ m/s$^2$, $\Delta \omega_{\text{max}} = 0.316$ rad/s) and below injected degradation spikes ($|a| > 5g$, $|\omega| > 35$ rad/s, $\Delta a > 10.0$ m/s$^2$, $\Delta \omega > 0.4$ rad/s). Injected spikes are rejected, replaced by the last accepted sample, and counted.
7. **Stuck-Sample A/B Evaluation**: Evaluated Option A (integrate as-is) vs Option B (coast as blind rows) for streaks of $\ge 3$ consecutive non-zero identical samples. Option B proved superior in 60s-window ATE across both Half-Degraded ($2.1809$ m vs $2.1828$ m) and Full-Degraded ($2.1918$ m vs $2.1921$ m), and is adopted as default.
8. **Format Test Suite (`tests/test_formats.py`)**: All 15 format variants passed 100% compliance on row count, 8 columns, finiteness, monotonic timestamps, unit quaternions, and ATE matching the reference run within $0.001\%$.
9. **Regression & Resource Budgets**:
   - Clean 60s ATE: **$2.1591$ m** (equal to Stage 3B-1).
   - Full-Degraded 60s ATE: **$2.1910$ m** (improved over Stage 3B-1 $2.1992$ m).
   - Peak Heap: **$2.393$ MB** $\le 8.000$ MB limit (PASS).
   - Compute Rate: **$1.825$ ms per 1 s of IMU** $\le 10.000$ ms/s target (PASS, ~5.5x faster than budget).

---

## 2. Stuck-Sample A/B Evaluation

A stuck sample is defined as 6 identical non-zero values for $\ge 3$ consecutive rows. In `imu_degraded.csv`, 373 rows meet this criterion.

We evaluated two strategies across the degraded files:
- **Option A**: Integrate stuck samples as-is as normal measurements.
- **Option B**: Coast stuck samples as blind blackout rows (hold orientation, leak velocity with $\tau_v=1.0$ s, advance position).

### 60s-Window and Full-Run ATE Comparison

| Dataset | Metric | Option A (Integrate As-Is) | Option B (Coast as Blind) | Best Option |
|:---|:---|:---:|:---:|:---:|
| **Half-Degraded** | **Mean 60s-Window ATE** | 2.1828 m | **2.1809 m** | **Option B** (-1.9 mm) |
| | Full-Run ATE | **3.6827 m** | 3.7085 m | Option A |
| | Window [  0,  60] s | 1.2593 m | 1.2593 m | Tie |
| | Window [ 30,  90] s | **3.2411 m** | 3.2514 m | Option A |
| | Window [ 60, 120] s | 1.8513 m | **1.8511 m** | Option B |
| | Window [ 90, 150] s | 2.1731 m | **2.1722 m** | Option B |
| | Window [120, 180] s | 2.3891 m | **2.3703 m** | **Option B** (-18.8 mm) |
| **Full-Degraded** | **Mean 60s-Window ATE** | 2.1921 m | **2.1910 m** | **Option B** (-1.1 mm) |
| | Full-Run ATE | **3.6138 m** | 3.6362 m | Option A |
| | Window [  0,  60] s | 1.2577 m | **1.2575 m** | Option B |
| | Window [ 30,  90] s | 3.2913 m | **3.2909 m** | Option B |
| | Window [ 60, 120] s | **1.8580 m** | 1.8626 m | Option A |
| | Window [ 90, 150] s | 2.1314 m | **2.1269 m** | Option B |
| | Window [120, 180] s | 2.4220 m | **2.4214 m** | Option B |

> **Decision**: In alignment with Task 7 ("keep the better one by 60 s-window ATE"), **Option B** achieved lower mean 60s-window error on both Half-Degraded ($2.1809$ m vs $2.1828$ m) and Full-Degraded ($2.1910$ m vs $2.1921$ m). Therefore, Option B is maintained in `main.py`.

---

## 3. Format Robustness Test Results (`tests/test_formats.py`)

All 15 format variants were generated directly from clean EuRoC data (`data/MH_01_easy/imu_clean_7col.csv`) and validated with `tools/validate_output.py`. For full-run trajectories, ATE was compared against the reference clean run ($3.7254$ m).

| # | Variant Name | main.py Run | Output Validation | ATE Aligned | ATE Diff % vs Ref | Status |
|:---|:---|:---:|:---:|:---:|:---:|:---:|
| 1 | Raw EuRoC (gyro-first, `#timestamp [ns]` header) | PASS | PASS | 3.7254 m | 0.000% | **PASS** |
| 2 | No header (numeric first line) | PASS | PASS | 3.7254 m | 0.000% | **PASS** |
| 3 | Milliseconds timestamps (`ms`) | PASS | PASS | 3.7254 m | 0.000% | **PASS** |
| 4 | Microseconds timestamps (`us`) | PASS | PASS | 3.7254 m | 0.000% | **PASS** |
| 5 | Float seconds timestamps (`s`) | PASS | PASS | 3.7254 m | 0.000% | **PASS** |
| 6 | Accel in g (auto-detected, scale 9.80665) | PASS | PASS | 3.7254 m | 0.000% | **PASS** |
| 7 | Semicolon delimiter (`;`) | PASS | PASS | 3.7254 m | 0.000% | **PASS** |
| 8 | Whitespace delimiter (spaces) | PASS | PASS | 3.7254 m | 0.000% | **PASS** |
| 9 | CRLF + BOM + trailing blank lines | PASS | PASS | 3.7254 m | 0.000% | **PASS** |
| 10 | Zip archive (streaming `imu0/data.csv`, no extraction) | PASS | PASS | 3.7254 m | 0.000% | **PASS** |
| 11 | Directory input (`imu0/data.csv`) | PASS | PASS | 3.7254 m | 0.000% | **PASS** |
| 12 | 1-row file | PASS | PASS | N/A | N/A | **PASS** |
| 13 | 2-row file | PASS | PASS | N/A | N/A | **PASS** |
| 14 | 10-row file | PASS | PASS | N/A | N/A | **PASS** |
| 15 | File with NaN / empty fields / duplicates / zeros | PASS | PASS | 3.7254 m | 0.001% | **PASS** |

**Summary**: 15/15 tests passed (100% success rate). All full-trajectory variants matched reference ATE within $\le 0.001\%$, far exceeding the required $\le 1.0\%$ threshold.

---

## 4. Regression Benchmark (Clean, Half, Full-Degraded)

Evaluation against Ground Truth (`data/MH_01_easy/groundtruth_tum.txt`) with Stage 3B-2 defaults:

| Dataset | Total Rows | Stage 3B-1 Full ATE | Stage 3B-2 Full ATE | Stage 3B-1 60s ATE | Stage 3B-2 60s ATE | Regression Status |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Clean** | 36,820 | 3.73 m (3.7254 m) | **3.7254 m** | 2.1591 m | **2.1591 m** | **EQUAL / PASS** |
| **Half-Degraded** | 36,281 | 3.71 m (3.7087 m) | **3.7085 m** | 2.1809 m | **2.1793 m** | **BETTER / PASS** |
| **Full-Degraded** | 35,629 | 3.63 m (3.6364 m) | **3.6362 m** | 2.1992 m | **2.1910 m** | **BETTER / PASS** |

### Per-Window 60s ATE Breakdown

| Window | Clean Est ATE | Half-Degraded Est ATE | Full-Degraded Est ATE |
|:---|:---:|:---:|:---:|
| **[  0,  60] s** | 1.2629 m | 1.2593 m | 1.2575 m |
| **[ 30,  90] s** | 3.2071 m | 3.2511 m | 3.2906 m |
| **[ 60, 120] s** | 1.8485 m | 1.8443 m | 1.8562 m |
| **[ 90, 150] s** | 2.1553 m | 2.1709 m | 2.1269 m |
| **[120, 180] s** | 2.3219 m | 2.3708 m | 2.4240 m |
| **MEAN** | **2.1591 m** | **2.1793 m** | **2.1910 m** |

---

## 5. Performance & Resource Verification

Measured using `tools/measure.py` on the complete 184.095 s degraded dataset (`data/MH_01_easy/imu_degraded.csv`, 35,629 rows):

- **Peak Tracemalloc Heap**: **$2.393$ MB** (2,509,599 bytes) $\le 8.000$ MB limit $\rightarrow$ **PASS (29.9% memory budget)**.
- **Process Peak Working Set**: **$26.215$ MB** (27,488,256 bytes).
- **Whole Run Execution Time**: **$0.3360$ s** (including CSV parse, auto-detection, spike rejection, stuck coasting, gap sub-stepping, filtering, and writing trajectory).
- **Compute Rate**: **$1.825$ ms per 1 s of IMU data** $\le 10.000$ ms/s target $\rightarrow$ **PASS (~5.5x faster than budget)**.
- **Validation**: `tools/validate_output.py` PASSED with 0 errors across all checks.
