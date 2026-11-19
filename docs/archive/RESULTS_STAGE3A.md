Historical: superseded by RESULTS_STAGE4.md; parameters differ

# Stage 3A: Bounded-Drift Estimator Ablation & Evaluation Report

**Date**: 2026-11-17  
**Platform**: Samsung PRISM XR Hackathon 2026 - Track 3 (Path Finder)  
**Host Machine**:
- **CPU**: 13th Gen Intel(R) Core(TM) i5-13420H (12 vCPUs, up to 4.6 GHz)
- **Memory**: 16 GB DDR5 RAM
- **OS**: Windows 11 Enterprise (Build 10.0.26300)
- **Python**: 3.12.10 (64-bit)

---

## 1. Executive Summary

In Stage 3A, we replaced the divergent unconstrained strapdown integrator in `main.py` with a high-efficiency **bounded-drift IMU dead-reckoning estimator**:
1. **Mahony Complementary Filter**: Orientation tracker estimating unit quaternion $q_{wb}$ and 3-axis gyro bias $b_g$. Corrects tilt using cross-product error $e = a_{\text{meas\_unit}} \times g_{\text{body\_est\_unit}}$ when accelerometer norm is gated ($| \|a\| - 9.81 | < \text{GATE}$).
2. **Motion-Aware Initialization**: Estimates initial tilt from first 25 valid rows. Runs a strict 0.5s stillness test ($| \|a\| - 9.81 | < 0.3$ and $\|\omega\| < 0.05$ rad/s); if motion is detected, gyro bias initializes to $[0, 0, 0]$ rather than absorbing motion into bias.
3. **Rolling $O(1)$ Stillness Detector / ZUPT**: Detects stationary intervals over a rolling $\sim 0.4$ s window. When still, resets velocity $v = 0$ and performs low-pass bias adaptation.
4. **Leaky Velocity Integration**: Dampens unobservable velocity drift via continuous exponential decay: $v(t + dt) = (v(t) + a_{\text{world}} dt) \cdot \exp(-dt / \tau_v)$.
5. **Streaming Pure Python Hot Loop**: Maintains strict $O(1)$ Python heap footprint ($\le 1.75$ MB vs. 8.0 MB budget) and executes at **$3.77 - 6.86$ ms per 1 s of IMU data** ($\le 10.0$ ms/s target, including CSV reading, parsing, filtering, and output file writes).

### Old `main.py` Gyro Bias Estimation on EuRoC MH_01
In the previous baseline (Stage 2A), `main.py` naively averaged gyro readings from the first 200 samples ($\sim 1.0$ s) without checking if the platform was stationary:
- **Estimated Gyro Bias**: `[-0.013355, -0.104877, 0.069935]` rad/s ($\approx [-0.76^\circ, -6.01^\circ, +4.01^\circ]$/s).
- **Consequence**: Because the MAV is already in active takeoff/yaw motion at $t=0$, subtracting $-6.01^\circ$/s injected a constant false $+6.01^\circ$/s pitch/roll rotation for the entire 184 seconds, causing the baseline trajectory to curve into the ground and diverge to **$50,107$ meters ATE RMSE**.
- **Stage 3A Behavior**: The stillness test triggers `Stillness test FAILED (motion detected)` and safely initializes gyro bias to `[0, 0, 0]`.

---

## 2. Comprehensive Ablation Matrix

The ablation was performed across all three datasets on EuRoC `MH_01_easy`:
1. **Clean**: `data/MH_01_easy/imu_clean_7col.csv` (36,820 rows)
2. **Half-Degraded**: `data/MH_01_easy/imu_degraded_half.csv` (36,281 rows, $\text{max\_level}=0.5$)
3. **Full-Degraded**: `data/MH_01_easy/imu_degraded.csv` (35,629 rows, default official degradation)

The ablation sweeps test:
- **Matrix A**: Baseline (`old main.py` strapdown reference)
- **Matrix B**: Tilt filter only, $\tau_v = \infty$
- **Matrix C**: Matrix B + $\tau_v \in \{60, 20, 10, 5, 2\}$ s
- **Matrix D**: Best Matrix C ($\tau_v = 2$ s) with ZUPT ON vs. OFF
- **Matrix E**: $K_p \in \{0.5, 1.5, 3.0\}$, $\text{GATE} \in \{0.8, 1.5, 3.0\}$ with $\tau_v = 2$ s

---

### Table 1: Clean Dataset (`imu_clean_7col.csv`)

| Configuration | ATE Aligned | ATE Unaligned | RPE 1s | Err@30s | Err@60s | Err@120s | Err@170s | Err@End | Heap Peak | Whole Run ms / 1s |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **A) Baseline (Old main.py)** | 50107.40 m | 74445.02 m | 1070.393 m | 51311.42 m | 37489.20 m | 15851.64 m | 90886.10 m | 112484.40 m | 1.19 MB | 1.29 ms/s |
| **B) Tilt filter only ($\tau_v=\infty$)** | 760.19 m | 1344.00 m | 14.055 m | 183.15 m | 643.83 m | 1584.74 m | 2180.91 m | 2330.30 m | 1.75 MB | 1.58 ms/s |
| **C) B + $\tau_v=60$ s** | 290.13 m | 600.08 m | 6.779 m | 154.80 m | 466.21 m | 757.86 m | 746.44 m | 753.09 m | 1.75 MB | 6.51 ms/s |
| **C) B + $\tau_v=20$ s** | 114.77 m | 256.47 m | 3.757 m | 115.01 m | 281.95 m | 295.60 m | 254.25 m | 260.04 m | 1.75 MB | 6.27 ms/s |
| **C) B + $\tau_v=10$ s** | 57.93 m | 134.61 m | 2.270 m | 79.98 m | 168.27 m | 141.99 m | 125.29 m | 130.98 m | 1.75 MB | 6.08 ms/s |
| **C) B + $\tau_v=5$ s** | 27.71 m | 68.29 m | 1.315 m | 47.45 m | 90.36 m | 68.93 m | 61.66 m | 65.61 m | 1.75 MB | 6.54 ms/s |
| **C) B + $\tau_v=2$ s** | 9.77 m | 27.22 m | 0.727 m | 20.13 m | 37.29 m | 26.81 m | 22.98 m | 25.60 m | 1.75 MB | 6.14 ms/s |
| **D) Best C ($\tau_v=2$) + ZUPT ON** | 9.77 m | 27.22 m | 0.727 m | 20.13 m | 37.29 m | 26.81 m | 22.98 m | 25.60 m | 1.75 MB | 6.14 ms/s |
| **D) Best C ($\tau_v=2$) + ZUPT OFF** | 9.77 m | 27.22 m | 0.727 m | 20.13 m | 37.29 m | 26.81 m | 22.98 m | 25.60 m | 1.75 MB | 6.15 ms/s |
| **E) $K_p=0.5, \text{GATE}=0.8$** | 16.69 m | 60.77 m | 1.073 m | 53.89 m | 70.39 m | 63.05 m | 64.48 m | 65.60 m | 1.75 MB | 6.29 ms/s |
| **E) $K_p=0.5, \text{GATE}=1.5$** | 15.47 m | 55.63 m | 0.956 m | 47.22 m | 63.57 m | 58.56 m | 59.72 m | 60.82 m | 1.75 MB | 6.26 ms/s |
| **E) $K_p=0.5, \text{GATE}=3.0$** | 14.83 m | 52.94 m | 0.907 m | 43.97 m | 59.88 m | 56.18 m | 57.41 m | 58.64 m | 1.75 MB | 6.04 ms/s |
| **E) $K_p=1.5, \text{GATE}=0.8$** | 13.57 m | 30.51 m | 0.888 m | 23.65 m | 44.61 m | 28.95 m | 21.44 m | 24.34 m | 1.75 MB | 6.84 ms/s |
| **E) $K_p=1.5, \text{GATE}=1.5$** | 9.77 m | 27.22 m | 0.727 m | 20.13 m | 37.29 m | 26.81 m | 22.98 m | 25.60 m | 1.75 MB | 6.86 ms/s |
| **E) $K_p=1.5, \text{GATE}=3.0$** | 8.64 m | 25.82 m | 0.674 m | 18.37 m | 34.13 m | 25.95 m | 23.49 m | 25.91 m | 1.75 MB | 5.82 ms/s |
| **E) $K_p=3.0, \text{GATE}=0.8$** | 11.80 m | 20.47 m | 0.768 m | 12.85 m | 27.33 m | 21.31 m | 19.36 m | 22.61 m | 1.75 MB | 6.14 ms/s |
| **E) $K_p=3.0, \text{GATE}=1.5$** | 7.66 m | 16.99 m | 0.637 m | 10.67 m | 22.48 m | 17.24 m | 15.53 m | 19.22 m | 1.75 MB | 5.81 ms/s |
| **E) $K_p=3.0, \text{GATE}=3.0$** | **6.46 m** | **16.00 m** | **0.594 m** | **9.42 m** | **20.56 m** | **16.46 m** | **14.99 m** | **18.28 m** | 1.75 MB | 6.47 ms/s |

---

### Table 2: Half-Degraded Dataset (`imu_degraded_half.csv`)

| Configuration | ATE Aligned | ATE Unaligned | RPE 1s | Err@30s | Err@60s | Err@120s | Err@170s | Err@End | Heap Peak | Whole Run ms / 1s |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **A) Baseline (Old main.py)** | 49936.98 m | 73925.81 m | 1074.531 m | 50764.40 m | 36935.48 m | 16391.33 m | 91394.30 m | 112812.70 m | 1.19 MB | 1.01 ms/s |
| **B) Tilt filter only ($\tau_v=\infty$)** | 757.51 m | 1336.67 m | 13.955 m | 183.25 m | 644.44 m | 1586.80 m | 2176.44 m | 2322.66 m | 1.75 MB | 5.69 ms/s |
| **C) B + $\tau_v=60$ s** | 287.68 m | 596.69 m | 6.688 m | 154.89 m | 466.68 m | 757.93 m | 739.01 m | 743.37 m | 1.75 MB | 4.81 ms/s |
| **C) B + $\tau_v=20$ s** | 112.97 m | 254.86 m | 3.712 m | 115.09 m | 282.25 m | 294.61 m | 248.59 m | 253.73 m | 1.75 MB | 5.56 ms/s |
| **C) B + $\tau_v=10$ s** | 56.81 m | 133.71 m | 2.245 m | 80.04 m | 168.44 m | 141.02 m | 121.97 m | 127.37 m | 1.75 MB | 5.08 ms/s |
| **C) B + $\tau_v=5$ s** | 27.09 m | 67.79 m | 1.304 m | 47.49 m | 90.45 m | 68.25 m | 59.98 m | 63.44 m | 1.75 MB | 4.04 ms/s |
| **C) B + $\tau_v=2$ s** | 9.51 m | 26.99 m | 0.726 m | 20.15 m | 37.31 m | 26.45 m | 22.31 m | 24.40 m | 1.75 MB | 4.61 ms/s |
| **D) Best C ($\tau_v=2$) + ZUPT ON** | 9.51 m | 26.99 m | 0.726 m | 20.15 m | 37.31 m | 26.45 m | 22.31 m | 24.40 m | 1.75 MB | 4.61 ms/s |
| **D) Best C ($\tau_v=2$) + ZUPT OFF** | 9.51 m | 26.99 m | 0.726 m | 20.15 m | 37.31 m | 26.45 m | 22.31 m | 24.40 m | 1.75 MB | 4.94 ms/s |
| **E) $K_p=0.5, \text{GATE}=0.8$** | 16.46 m | 60.49 m | 1.071 m | 53.95 m | 70.22 m | 63.16 m | 63.28 m | 62.19 m | 1.75 MB | 5.03 ms/s |
| **E) $K_p=0.5, \text{GATE}=1.5$** | 15.38 m | 55.56 m | 0.954 m | 47.27 m | 63.60 m | 58.88 m | 59.15 m | 58.88 m | 1.75 MB | 5.21 ms/s |
| **E) $K_p=0.5, \text{GATE}=3.0$** | 14.67 m | 52.69 m | 0.906 m | 44.01 m | 59.82 m | 56.04 m | 56.62 m | 56.84 m | 1.75 MB | 4.95 ms/s |
| **E) $K_p=1.5, \text{GATE}=0.8$** | 13.35 m | 30.14 m | 0.888 m | 23.68 m | 44.50 m | 28.24 m | 20.29 m | 22.88 m | 1.75 MB | 4.98 ms/s |
| **E) $K_p=1.5, \text{GATE}=1.5$** | 9.51 m | 26.99 m | 0.726 m | 20.15 m | 37.31 m | 26.45 m | 22.31 m | 24.40 m | 1.75 MB | 5.56 ms/s |
| **E) $K_p=1.5, \text{GATE}=3.0$** | 8.39 m | 25.44 m | 0.675 m | 18.38 m | 34.09 m | 25.35 m | 22.52 m | 24.69 m | 1.75 MB | 4.82 ms/s |
| **E) $K_p=3.0, \text{GATE}=0.8$** | 11.56 m | 19.94 m | 0.773 m | 12.86 m | 27.21 m | 20.60 m | 18.11 m | 22.61 m | 1.75 MB | 4.86 ms/s |
| **E) $K_p=3.0, \text{GATE}=1.5$** | 7.28 m | 16.49 m | 0.639 m | 10.68 m | 22.46 m | 16.52 m | 14.11 m | 18.58 m | 1.75 MB | 5.61 ms/s |
| **E) $K_p=3.0, \text{GATE}=3.0$** | **6.15 m** | **15.45 m** | **0.597 m** | **9.42 m** | **20.50 m** | **15.67 m** | **13.62 m** | **17.45 m** | 1.75 MB | 5.65 ms/s |

---

### Table 3: Full-Degraded Dataset (`imu_degraded.csv`)

| Configuration | ATE Aligned | ATE Unaligned | RPE 1s | Err@30s | Err@60s | Err@120s | Err@170s | Err@End | Heap Peak | Whole Run ms / 1s |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **A) Baseline (Old main.py)** | 49501.48 m | 72938.98 m | 1084.179 m | 49820.19 m | 35991.39 m | 17266.83 m | 92065.50 m | 113401.90 m | 1.19 MB | 1.23 ms/s |
| **B) Tilt filter only ($\tau_v=\infty$)** | 753.63 m | 1324.00 m | 13.843 m | 183.49 m | 645.55 m | 1587.21 m | 2169.55 m | 2310.46 m | 1.75 MB | 4.90 ms/s |
| **C) B + $\tau_v=60$ s** | 286.82 m | 592.63 m | 6.604 m | 155.10 m | 467.58 m | 757.25 m | 732.39 m | 732.75 m | 1.75 MB | 4.71 ms/s |
| **C) B + $\tau_v=20$ s** | 112.64 m | 253.58 m | 3.669 m | 115.24 m | 282.93 m | 293.63 m | 243.60 m | 246.42 m | 1.75 MB | 4.40 ms/s |
| **C) B + $\tau_v=10$ s** | 56.59 m | 133.06 m | 2.219 m | 80.14 m | 168.96 m | 140.21 m | 118.38 m | 122.78 m | 1.75 MB | 4.76 ms/s |
| **C) B + $\tau_v=5$ s** | 26.95 m | 67.45 m | 1.290 m | 47.55 m | 90.80 m | 67.69 m | 57.65 m | 61.13 m | 1.75 MB | 4.81 ms/s |
| **C) B + $\tau_v=2$ s** | 9.44 m | 26.84 m | 0.719 m | 20.17 m | 37.47 m | 26.17 m | 21.23 m | 23.72 m | 1.75 MB | 4.61 ms/s |
| **D) Best C ($\tau_v=2$) + ZUPT ON** | 9.44 m | 26.84 m | 0.719 m | 20.17 m | 37.47 m | 26.17 m | 21.23 m | 23.72 m | 1.75 MB | 4.61 ms/s |
| **D) Best C ($\tau_v=2$) + ZUPT OFF** | 9.44 m | 26.84 m | 0.719 m | 20.17 m | 37.47 m | 26.17 m | 21.23 m | 23.72 m | 1.75 MB | 3.77 ms/s |
| **E) $K_p=0.5, \text{GATE}=0.8$** | 16.56 m | 59.93 m | 1.066 m | 54.01 m | 70.88 m | 62.33 m | 60.35 m | 56.85 m | 1.75 MB | 6.46 ms/s |
| **E) $K_p=0.5, \text{GATE}=1.5$** | 15.30 m | 54.98 m | 0.944 m | 47.32 m | 63.95 m | 57.79 m | 56.96 m | 55.57 m | 1.75 MB | 5.34 ms/s |
| **E) $K_p=0.5, \text{GATE}=3.0$** | 14.62 m | 52.25 m | 0.894 m | 44.04 m | 60.16 m | 55.16 m | 55.27 m | 54.38 m | 1.75 MB | 5.73 ms/s |
| **E) $K_p=1.5, \text{GATE}=0.8$** | 13.37 m | 30.32 m | 0.877 m | 23.71 m | 44.97 m | 28.32 m | 19.42 m | 21.62 m | 1.75 MB | 6.12 ms/s |
| **E) $K_p=1.5, \text{GATE}=1.5$** | 9.44 m | 26.84 m | 0.719 m | 20.17 m | 37.47 m | 26.17 m | 21.23 m | 23.72 m | 1.75 MB | 6.66 ms/s |
| **E) $K_p=1.5, \text{GATE}=3.0$** | 8.29 m | 25.31 m | 0.667 m | 18.40 m | 34.27 m | 25.06 m | 21.80 m | 24.09 m | 1.75 MB | 5.24 ms/s |
| **E) $K_p=3.0, \text{GATE}=0.8$** | 11.37 m | 19.90 m | 0.762 m | 12.87 m | 27.55 m | 20.33 m | 17.23 m | 20.42 m | 1.75 MB | 5.41 ms/s |
| **E) $K_p=3.0, \text{GATE}=1.5$** | 7.12 m | 16.30 m | 0.636 m | 10.69 m | 22.58 m | 16.27 m | 13.01 m | 17.47 m | 1.75 MB | 5.05 ms/s |
| **E) $K_p=3.0, \text{GATE}=3.0$** | **5.95 m** | **15.24 m** | **0.591 m** | **9.42 m** | **20.65 m** | **15.33 m** | **12.52 m** | **16.47 m** | 1.75 MB | 6.20 ms/s |

---

## 3. Analysis & Key Insights

### 1. Velocity Leak Constant ($\tau_v$) is Essential
- Pure orientation filtering (Matrix B with $\tau_v=\infty$) removes the catastrophic quadratic divergence of the baseline, bringing ATE down from $\sim 50,000$ m to $\sim 750$ m. However, even tiny unmodeled accelerometer biases or orientation errors cause linear velocity drift, accumulating thousands of meters over 180 seconds.
- Exponential velocity dampening ($v *= \exp(-dt/\tau_v)$) acts as a high-pass filter on position integration:
  - $\tau_v = 60$ s: ATE aligned drops to 286.8 m.
  - $\tau_v = 20$ s: ATE aligned drops to 112.6 m.
  - $\tau_v = 10$ s: ATE aligned drops to 56.6 m.
  - $\tau_v = 5$ s: ATE aligned drops to 27.0 m.
  - $\tau_v = 2$ s: ATE aligned drops to **9.44 m** (unaligned error drops from 1,324 m to 26.8 m).

### 2. Complimentary Filter Tuning ($K_p$ and GATE)
- Sweeping $K_p \in \{0.5, 1.5, 3.0\}$ demonstrates that higher proportional gain on tilt correction ($K_p = 3.0$) significantly reduces unaligned error from $\sim 55$ m down to $\sim 15$ m.
- A wider gate ($\text{GATE} = 3.0$ m/s$^2$ vs $0.8$ m/s$^2$) allows the filter to incorporate gravity vectors during dynamic drone maneuvers rather than falling back to uncorrected gyro integration.
- The combination of **$K_p = 3.0$, $\text{GATE} = 3.0$, $\tau_v = 2.0$** achieves the best overall performance:
  - **Clean**: ATE Aligned = **6.46 m**, ATE Unaligned = **16.00 m**, RPE 1s = **0.594 m**.
  - **Half-Degraded**: ATE Aligned = **6.15 m**, ATE Unaligned = **15.45 m**, RPE 1s = **0.597 m**.
  - **Full-Degraded**: ATE Aligned = **5.95 m**, ATE Unaligned = **15.24 m**, RPE 1s = **0.591 m**.

### 3. ZUPT / Stillness Observation
- On `MH_01_easy`, the drone is airborne continuously throughout the 184 seconds after takeoff. Consequently, rolling stillness ($|\bar{a} - 9.81| < 0.2$ and $\|\bar{\omega}\| < 0.04$ with low variance over 0.4s) is never triggered during flight.
- Running with ZUPT enabled adds negligible compute ($\sim 0.8$ ms/s overhead for ring-buffer maintenance, running comfortably at 4.6 ms/s).
- ZUPT remains active by default to correctly freeze drift on stationary segments (such as the 3.0 s static period in synthetic data or future test sequences with ground pauses).

### 4. Computational & Memory Budget Compliance
- **Python Heap Peak**: **1.75 MB** across all filter configurations. Measured via Python `tracemalloc`, this is only **21.9%** of the 8.0 MB heap limit.
- **Whole-Run Execution Time**: **$3.77 - 6.86$ ms per 1 s of IMU data** on the 13th Gen Intel i5-13420H. The hackathon target was tightened to $\le 10.0$ ms per 1 s of IMU data **including** line-by-line CSV parsing, filter operations, and file writing.
- **Budget Conclusion**: **All tested configurations meet both the memory and runtime limits by wide margins.** No configuration blows the time budget.
