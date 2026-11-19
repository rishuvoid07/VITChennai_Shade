Historical: superseded by RESULTS_STAGE4.md; parameters differ

# Stage 2A: Python Baseline Benchmark on Real EuRoC MH_01_easy

This document records the empirical results of running the Track 3 Python streaming baseline (`main.py`) on the real EuRoC MAV `MH_01_easy` dataset (clean, official degraded default, and official degraded half).

---

## Machine Description

- **Processor**: 13th Gen Intel(R) Core(TM) i5-13420H (8 physical cores: 4 Performance cores + 4 Efficient cores, 12 logical processors, base frequency ~2.10 GHz, max boost ~4.60 GHz)
- **RAM**: 16.0 GB DDR5 Physical RAM
- **Operating System**: Microsoft Windows 11 Home Single Language (Version 10.0.26300, 64-bit)
- **Python Environment**: Python 3.12.10 (64-bit), numpy 2.5.4, pandas 3.1.1, psutil 7.2.2, evo v1.38.1

---

## Start-of-Sequence Analysis (First 10 Seconds)

To assess whether the MAV starts stationary or in motion, 1-second window statistics were computed from the first 10 seconds of IMU data ($t_0 = 1403636579758555392$ ns) and the synchronized ground truth state:

| Window (s) | Median Accel Norm (m/s²) | Mean Accel Vector $[a_x, a_y, a_z]$ (m/s²) | Mean Gyro Mag (rad/s) | Mean Speed (m/s) |
|:---:|:---:|:---:|:---:|:---:|
| **[0 s – 1 s)** | 10.5249 | [ 9.9013, -0.4120, -4.0482] | 0.1975 | *No GT yet (starts at +1.08 s)* |
| **[1 s – 2 s)** | 8.5916 | [ 7.8934, -0.0010, -2.8695] | 0.2868 | **0.5277** |
| **[2 s – 3 s)** | 10.7203 | [10.2673, -0.1022, -4.1786] | 0.2373 | **0.5147** |
| **[3 s – 4 s)** | 8.6170 | [ 8.0492, -0.0424, -2.7152] | 0.2477 | **0.5143** |
| **[4 s – 5 s)** | 11.0072 | [10.0380,  0.0020, -4.4067] | 0.2439 | **0.4969** |
| **[5 s – 6 s)** | 9.0024 | [ 8.4590,  0.1868, -2.9530] | 0.2475 | **0.3923** |
| **[6 s – 7 s)** | 9.9121 | [ 8.2676, -0.1529, -5.4270] | 0.3739 | **0.1000** |
| **[7 s – 8 s)** | 9.7678 | [ 7.4164, -0.0454, -6.3009] | 0.1550 | **0.1825** |
| **[8 s – 9 s)** | 9.7624 | [ 7.1519, -1.0142, -6.5201] | 0.1598 | **0.2126** |
| **[9 s – 10 s)**| 9.7175 | [ 7.2867, -0.6408, -6.3467] | 0.1101 | **0.4411** |

### Start-of-Sequence Findings
1. **Dynamic State**: The MAV is **ALREADY IN MOTION** at sequence start.
   - Ground truth begins at $t = +1.08$ s with velocity vector $v = [-0.0279, 0.0332, 0.8000]$ m/s (speed $\approx 0.801$ m/s), indicating vertical ascent/takeoff.
   - In window $[0\text{ s} - 1\text{ s})$, the accelerometer norm fluctuates between $8.5$ and $11.0\text{ m/s}^2$ (median $10.52\text{ m/s}^2 \neq 9.807\text{ m/s}^2$) and mean gyroscope magnitude is $0.198\text{ rad/s}$ ($> 11^\circ/\text{s}$).
2. **Impact on Initial Roll / Pitch Estimation**:
   - `main.py` derives initial attitude by assuming the mean accelerometer reading in the first $N$ rows represents static reaction to gravity ($\mathbf{f} \approx R^T [0, 0, g]$).
   - Comparing $N = 50$ rows ($\approx 0.25$ s) versus $N = 200$ rows ($\approx 1.00$ s):
     - **First 50 rows**: Mean accel = `[8.2038, -0.4563, -2.9541]` m/s² (norm = 8.7313 m/s²), unit vector $\mathbf{u} = [0.939575, -0.052264, -0.338331]$, derived Roll = $-171.219^\circ$, Pitch = $-69.980^\circ$.
     - **First 200 rows**: Mean accel = `[9.9013, -0.4120, -4.0482]` m/s² (norm = 10.7048 m/s²), unit vector $\mathbf{u} = [0.924938, -0.038491, -0.378165]$, derived Roll = $-174.188^\circ$, Pitch = $-67.659^\circ$.
   - **Angular difference**: $2.49^\circ$. Because linear takeoff acceleration is coupled into the gravity estimate, the initial orientation has an unavoidable $\approx 2.5^\circ - 5^\circ$ initial tilt error under simple static leveling.

---

## Degradation Statistics (Official Degradation Script)

Generated using `tools/degrade_imu.py` (seed = 42):

| Metric | Clean Input | Default Degradation (`--max-level 1.0`) | Half Degradation (`--max-level 0.5`) |
|:---|:---:|:---:|:---:|
| **Duration (s)** | 184.095 s | 184.095 s | 184.095 s |
| **Input Rows** | 36,820 | 36,820 | 36,820 |
| **Output Rows** | 36,820 | 35,629 | 36,281 |
| **Dropped Rows (Single)** | 0 | 796 | 430 |
| **Dropped Burst Gaps** | 0 | 26 gaps | 12 gaps |
| **Total Dropped Rows** | 0 | 1,240 rows | 565 rows |
| **Duplicated Rows** | 0 | 49 | 26 |
| **Spikes Injected** | 0 | 38 | 20 |
| **Stuck Samples** | 0 | 525 | 203 |
| **Sensor Blackout Frames** | 0 | 1,001 (last 5.0 s) | 1,001 (last 5.0 s) |
| **Accumulated Final Gyro Bias (rad/s)** | [0, 0, 0] | `[-0.00443, -0.00188, -0.00451]` | `[-0.00222, -0.00098, -0.00224]` |
| **Accumulated Final Accel Bias (m/s²)** | [0, 0, 0] | `[-0.0136, -0.0648, 0.0364]` | `[-0.0063, -0.0334, 0.0194]` |

---

## Exact Execution Commands

```bash
# 1. Format Conversion from EuRoC MAV format
py -3.12 tools/euroc_to_7col.py imu data/MH_01_easy/mav0/imu0/data.csv data/MH_01_easy/imu_clean_7col.csv
py -3.12 tools/euroc_to_7col.py gt data/MH_01_easy/mav0/state_groundtruth_estimate0/data.csv data/MH_01_easy/groundtruth_tum.txt

# 2. Degradation
py -3.12 tools/degrade_imu.py data/MH_01_easy/imu_clean_7col.csv data/MH_01_easy/imu_degraded.csv --meta data/MH_01_easy/degraded_stats.json
py -3.12 tools/degrade_imu.py data/MH_01_easy/imu_clean_7col.csv data/MH_01_easy/imu_degraded_half.csv --max-level 0.5 --meta data/MH_01_easy/degraded_half_stats.json

# 3. Clean Run
py -3.12 main.py data/MH_01_easy/imu_clean_7col.csv data/MH_01_easy/estimated_trajectory_clean.txt
py -3.12 tools/validate_output.py data/MH_01_easy/estimated_trajectory_clean.txt data/MH_01_easy/imu_clean_7col.csv
py -3.12 tools/eval.py data/MH_01_easy/estimated_trajectory_clean.txt data/MH_01_easy/groundtruth_tum.txt

# 4. Degraded Default Run
py -3.12 main.py data/MH_01_easy/imu_degraded.csv data/MH_01_easy/estimated_trajectory_degraded.txt
py -3.12 tools/validate_output.py data/MH_01_easy/estimated_trajectory_degraded.txt data/MH_01_easy/imu_degraded.csv
py -3.12 tools/eval.py data/MH_01_easy/estimated_trajectory_degraded.txt data/MH_01_easy/groundtruth_tum.txt

# 5. Degraded Half Run
py -3.12 main.py data/MH_01_easy/imu_degraded_half.csv data/MH_01_easy/estimated_trajectory_degraded_half.txt
py -3.12 tools/validate_output.py data/MH_01_easy/estimated_trajectory_degraded_half.txt data/MH_01_easy/imu_degraded_half.csv
py -3.12 tools/eval.py data/MH_01_easy/estimated_trajectory_degraded_half.txt data/MH_01_easy/groundtruth_tum.txt

# 6. Performance Measurement (on 184s Degraded sequence)
py -3.12 tools/measure.py data/MH_01_easy/imu_degraded.csv data/MH_01_easy/estimated_trajectory_degraded.txt
```

---

## Empirical Benchmark Results Table

| Metric / Parameter | Clean (`imu_clean_7col.csv`) | Degraded Default (`imu_degraded.csv`) | Degraded Half (`imu_degraded_half.csv`) | Contest Target | Status |
|:---|:---:|:---:|:---:|:---:|:---:|
| **Duration (s)** | 184.095 s | 184.095 s | 184.095 s | — | — |
| **Input Rows** | 36,820 | 35,629 | 36,281 | — | — |
| **Output Rows** | 36,820 | 35,629 | 36,281 | Exact 1:1 match | **PASS** |
| **Validation Status** | **PASSED** (0 errors) | **PASSED** (0 errors) | **PASSED** (0 errors) | Valid TUM format | **PASS** |
| **Associated GT Poses**| 36,382 (across 181.905 s)| 35,195 (across 181.905 s)| 35,847 (across 181.905 s)| — | — |
| **Tracemalloc Peak Heap**| 1.191 MB | **1.191 MB** (1,248,996 B) | 1.191 MB | **$\le$ 8.000 MB** | **PASS** |
| **Process Working Set** | 21.90 MB | 21.98 MB | 21.95 MB | Reference only | — |
| **Native Compute Time** | 0.178 s | **0.2254 s** | 0.185 s | — | — |
| **Compute Rate (ms / 1s IMU)** | 0.967 ms/s | **1.225 ms/s** | 1.005 ms/s | **$\le$ 20.000 ms/s** | **PASS** |
| **ATE RMSE (SE(3) Aligned)**| **50,107.40 m** | **49,501.48 m** | **49,936.98 m** | Lower is better | Reference |
| **ATE RMSE (Unaligned)** | 74,445.02 m | 72,938.98 m | 73,925.81 m | Reference | Reference |
| **RPE RMSE (SE(3) Aligned, $\Delta=1$ s)**| **1,070.39 m** | **1,084.18 m** | **1,074.53 m** | Lower is better | Reference |
| **RPE RMSE (Unaligned, $\Delta=1$ s)** | 1,070.39 m | 1,084.18 m | 1,074.53 m | Reference | Reference |
| **Aligned Error @ t = 10 s** | 54,949.83 m | 53,461.46 m | 54,402.24 m | Reference | Reference |
| **Aligned Error @ t = 30 s** | 51,311.42 m | 49,820.19 m | 50,764.40 m | Reference | Reference |
| **Aligned Error @ t = 60 s** | 37,489.20 m | 35,991.39 m | 36,935.48 m | Reference | Reference |
| **Aligned Error @ t = 90 s** | 15,585.69 m | 14,141.86 m | 15,067.13 m | Reference | Reference |
| **Aligned Error @ t = 120 s**| 15,851.64 m | 17,266.83 m | 16,391.33 m | Reference | Reference |
| **Aligned Error @ t = 150 s**| 59,129.43 m | 60,440.27 m | 59,685.23 m | Reference | Reference |
| **Aligned Error @ t = 170 s**| 90,886.10 m | 92,065.50 m | 91,394.30 m | Reference | Reference |
| **Aligned Error @ Final Frame**| 112,484.43 m | 113,401.91 m | 112,812.74 m | Reference | Reference |
| **Blind Window Start Error** | 103,099.00 m (t=176.91s) | **104,262.16 m** (t=176.94s) | 103,572.17 m (t=176.91s) | Reference | Reference |
| **Blind Window End Error**   | 112,484.43 m (t=181.91s) | **113,401.91 m** (t=181.91s) | 112,812.74 m (t=181.91s) | Reference | Reference |

---

## Detailed Analysis & Engineering Diagnostics

1. **Why Baseline Diverges on Real Data**:
   - The open-loop strapdown baseline double-integrates raw specific force without feedback correction or state-covariance estimation.
   - On synthetic data, initial attitude and sensor bias were mathematically zero. On real EuRoC data:
     - Real uncalibrated MEMS gyroscope bias ($\sim 0.01 - 0.1\text{ rad/s}$) causes orientation estimate $\hat{R}_{WB}$ to rotate away from true gravity at a rate of several degrees per second.
     - When gravity $[0, 0, 9.80665]$ is rotated by an incorrect orientation, a spurious horizontal acceleration component of magnitude $g \cdot \sin(\theta)$ appears.
     - In 180 seconds, integrating a few degrees of tilt error yields quadratic position growth $\sim \frac{1}{2} a t^2 \sim 10^4 - 10^5\text{ m}$.
   - This large divergence is not a bug; it is the fundamental mathematical motivation for the Stage 3 Error-State Kalman Filter (ESKF).
2. **Behavior Across Degradation Levels**:
   - Notice that the clean, half-degraded, and fully-degraded errors are remarkably similar ($\approx 50\text{ km}$ ATE RMSE).
   - This confirms that on real IMU data over a 184-second window, the primary source of error is the **uncompensated low-frequency gyro drift and initial dynamic leveling tilt**, which dwarfs the additive high-frequency white noise and spikes added by `degrade_imu.py`.
3. **Blackout Window Resilience**:
   - During the final 5.0 seconds ($t = 176.9$ s to $181.9$ s), sensor readings drop to $(0, 0, 0)$.
   - `main.py`'s invalid-row rule detects this norm-zero condition and transitions to constant-velocity dead reckoning ($\mathbf{p} \leftarrow \mathbf{p} + \mathbf{v} \cdot dt$).
   - This prevented spurious downward gravity acceleration ($a_z = -9.81\text{ m/s}^2$) which would otherwise cause an additional uncontrolled $-122\text{ m}$ parabolic vertical plunge.
4. **Budget Compliance**:
   - **Heap Limit**: $1.191\text{ MB} \le 8.0\text{ MB}$ (**PASS**). Memory remains strictly bounded regardless of sequence duration due to generator streaming.
   - **Compute Rate**: $1.225\text{ ms per 1 s of IMU data} \le 20.0\text{ ms/s}$ (**PASS**). The algorithm executes at $\approx 816\times$ real-time speed.
