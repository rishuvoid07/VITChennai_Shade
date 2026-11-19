Historical: superseded by RESULTS_STAGE4.md; parameters differ

# Track 3 Python Baseline Benchmark Results

This document records the empirical results of the Python 3.12 streaming baseline (`main.py`) evaluated across three reference datasets under the official Track 3 (Path Finder) measurement and validation harnesses.

---

## Machine Description

- **Processor**: 13th Gen Intel(R) Core(TM) i5-13420H (8 physical cores: 4 P-cores + 4 E-cores, 12 logical processors, base clock ~2.10 GHz, boost up to 4.60 GHz)
- **RAM**: 16.0 GB DDR5 Physical RAM
- **Operating System**: Microsoft Windows 11 Home Single Language (Build 10.0.26300, 64-bit)
- **Python Environment**: Python 3.12.10 (64-bit), numpy 2.5.4, pandas 3.1.1, psutil 7.2.2, evo v1.38.1

---

## Exact Execution Commands

### 1. Dataset 1: Clean Synthetic Motion (120 s dynamic 3D motion)
```bash
# Integrator execution
py -3.12 main.py data/synthetic_motion/imu_clean_7col.csv data/synthetic_motion/estimated_trajectory_clean.txt

# Format & contract validation
py -3.12 tools/validate_output.py data/synthetic_motion/estimated_trajectory_clean.txt data/synthetic_motion/imu_clean_7col.csv

# Trajectory accuracy evaluation (evo ATE & RPE)
py -3.12 tools/eval.py data/synthetic_motion/estimated_trajectory_clean.txt data/synthetic_motion/groundtruth_tum.txt

# Heap & runtime benchmark
py -3.12 tools/measure.py data/synthetic_motion/imu_clean_7col.csv data/synthetic_motion/estimated_trajectory_clean.txt
```

### 2. Dataset 2: Degraded Synthetic Motion (120 s official degradation)
```bash
# Generate degraded copy with official script
py -3.12 tools/degrade_imu.py data/synthetic_motion/imu_clean_7col.csv data/synthetic_motion/imu_degraded_7col.csv --meta data/synthetic_motion/degrade_stats.json

# Integrator execution
py -3.12 main.py data/synthetic_motion/imu_degraded_7col.csv data/synthetic_motion/estimated_trajectory_degraded.txt

# Format & contract validation
py -3.12 tools/validate_output.py data/synthetic_motion/estimated_trajectory_degraded.txt data/synthetic_motion/imu_degraded_7col.csv

# Trajectory accuracy evaluation (evo ATE & RPE)
py -3.12 tools/eval.py data/synthetic_motion/estimated_trajectory_degraded.txt data/synthetic_motion/groundtruth_tum.txt

# Heap & runtime benchmark
py -3.12 tools/measure.py data/synthetic_motion/imu_degraded_7col.csv data/synthetic_motion/estimated_trajectory_degraded.txt
```

### 3. Dataset 3: Stationary Synthetic (1.0 s static IMU sanity check)
```bash
# Convert to Track 3 format
py -3.12 tools/euroc_to_7col.py imu data/synthetic/imu0_data.csv data/synthetic/imu_stationary_7col.csv
py -3.12 tools/euroc_to_7col.py gt data/synthetic/state_groundtruth.csv data/synthetic/groundtruth_stationary_tum.txt

# Integrator execution
py -3.12 main.py data/synthetic/imu_stationary_7col.csv data/synthetic/estimated_trajectory_stationary.txt

# Format & contract validation
py -3.12 tools/validate_output.py data/synthetic/estimated_trajectory_stationary.txt data/synthetic/imu_stationary_7col.csv

# Trajectory accuracy evaluation (evo ATE & RPE)
py -3.12 tools/eval.py data/synthetic/estimated_trajectory_stationary.txt data/synthetic/groundtruth_stationary_tum.txt

# Heap & runtime benchmark
py -3.12 tools/measure.py data/synthetic/imu_stationary_7col.csv data/synthetic/estimated_trajectory_stationary.txt
```

---

## Benchmark Results Table

| Metric / Parameter | Clean Synthetic (`imu_clean_7col.csv`) | Degraded Synthetic (`imu_degraded_7col.csv`) | Stationary (`imu_stationary_7col.csv`) | Limit / Target |
|:---|:---:|:---:|:---:|:---:|
| **Duration (s)** | 120.000 s | 120.000 s | 0.995 s | — |
| **Input Rows** | 24,001 | 23,142 | 200 | — |
| **Output Rows** | 24,001 | 23,142 | 200 | Exact 1:1 match |
| **Validation Status** | **PASSED** (0 errors) | **PASSED** (0 errors) | **PASSED** (0 errors) | 100% Valid TUM |
| **Tracemalloc Peak Heap** | **1.191 MB** (1,248,996 B) | **1.191 MB** (1,248,996 B) | **1.191 MB** (1,248,996 B) | **≤ 8.000 MB (PASS)** |
| **Process Working Set** | 21.90 MB | 21.98 MB | 21.17 MB | Reference |
| **Native Compute Time** | 0.1542 s | 0.1938 s | 0.0140 s | — |
| **Compute Rate (ms / 1s IMU)** | **1.285 ms/s** | **1.615 ms/s** | 14.088 ms/s (startup-dominated) | **≤ 20.000 ms/s (PASS)** |
| **ATE RMSE (SE(3) Aligned)** | **0.013481 m (1.35 cm)** | **147.189344 m (147.19 m)** | 0.000744 m (0.07 cm)* | Lower is better |
| **ATE RMSE (Unaligned)** | 0.023142 m (2.31 cm) | 169.508699 m (169.51 m) | 0.000744 m (0.07 cm) | Reference |
| **RPE RMSE (SE(3) Aligned, $\Delta=1$ s)** | **0.004100 m (0.41 cm)** | **9.448211 m (9.45 m)** | 0.001658 m (0.17 cm)* | Lower is better |
| **RPE RMSE (Unaligned, $\Delta=1$ s)** | 0.004100 m (0.41 cm) | 9.448211 m (9.45 m) | 0.001658 m (0.17 cm) | Reference |
| **Aligned Pos Error @ t = 10 s** | **0.016404 m (1.64 cm)** | **83.115935 m (83.12 m)** | N/A (< 10 s) | Reference |
| **Aligned Pos Error @ t = 30 s** | **0.007975 m (0.80 cm)** | **85.510643 m (85.51 m)** | N/A (< 10 s) | Reference |
| **Aligned Pos Error @ t = 60 s** | **0.010740 m (1.07 cm)** | **75.286745 m (75.29 m)** | N/A (< 10 s) | Reference |
| **Aligned Pos Error @ t = 90 s** | **0.004361 m (0.44 cm)** | **32.052138 m (32.05 m)** | N/A (< 10 s) | Reference |
| **Aligned Pos Error @ t = 115 s** | **0.014217 m (1.42 cm)** | **398.084424 m (398.08 m)** | N/A (< 10 s) | Reference |
| **Aligned Pos Error @ Final Frame**| **0.022455 m (2.25 cm)** | **527.925434 m (527.93 m)** | 0.001658 m (0.17 cm) | Reference |

*\*Note: On the stationary test, all ground truth coordinates are identical at (0, 0, 0). As documented by `evo`, Umeyama SE(3) alignment is degenerate on a zero-variance point, so alignment falls back to unaligned evaluation.*

---

## Degradation Statistics (Official Script Output)

From `data/synthetic_motion/degrade_stats.json`:
- **Input / Output Rows**: 24,001 in $\rightarrow$ 23,142 out (886 dropped total: 479 single drops + 18 burst drops; 27 duplicated rows).
- **Spikes Added**: 29 spikes.
- **Stuck Samples**: 262 stuck samples across sequences.
- **Sensor Failure**: 1,001 frames (last 5.0 seconds set to exactly 0.0 accel & gyro).
- **Final Accumulated Sensor Drift**:
  - Gyro bias: `[0.00325, -0.00623, 0.00699]` rad/s
  - Accel bias: `[-0.0423, 0.0165, 0.0915]` m/s²

## Analysis of Results

1. **Clean Synthetic Consistency**:
   - The strapdown baseline tracks the 120-second dynamic sinusoidal trajectory with an ATE RMSE of **1.35 cm** (aligned) and **2.31 cm** (unaligned). This verifies that coordinate frame transformations (world-from-body, gravity removal, quaternion conventions) are mathematically consistent between the generator and the estimator.
2. **Degraded Baseline Behavior**:
   - As expected for an uncompensated double-integrator without filtering or sensor fusion, random-walk bias, unmitigated spikes, and stuck readings cause open-loop divergence ($t^2$ drift), reaching 147.19 m ATE RMSE.
   - Crucially, the invalid-row handler prevents catastrophic gravitational collapse during the final 5.0 s sensor blackout (without constant-velocity dead reckoning, gravity removal on 0 accel would drop the estimate by over 120 m in 5 s).
3. **Resource Compliance**:
   - Peak traced heap is **1.191 MB** across all runs, well below the 8.0 MB ceiling.
   - Native compute rate is **1.285 ms/s** on clean data and **1.615 ms/s** on degraded data, ~12–15x faster than the 20 ms/s limit.
