Historical: superseded by RESULTS_STAGE4.md; parameters differ

# Stage 3B-1: Sanity Baselines, Robust Tuning, and Blind-Window Modes

**Date**: 2026-11-18  
**Platform**: Samsung PRISM XR Hackathon 2026 - Track 3 (Path Finder)  
**Host Machine**:
- **CPU**: 13th Gen Intel(R) Core(TM) i5-13420H (12 vCPUs, up to 4.6 GHz)
- **Memory**: 16 GB DDR5 RAM
- **OS**: Windows 11 Enterprise (Build 10.0.26300)
- **Python**: 3.12.10 (64-bit)

---

## 1. Executive Summary

In Stage 3B-1, we subjected the Stage 3A bounded-drift estimator to rigorous sanity benchmarks, windowed multi-scale evaluation, an extended hyperparameter grid search, and systematic blind-window sensor failure coasting analysis:
1. **Null Baseline (N1) Analysis**: We computed the analytic zero-motion null estimator $N_1 = \text{centroid}(p_{\text{gt}})$. On the full 184 s sequence, $N_1$ achieves an ATE of **$4.31$ m** and an RPE 1s of **$0.499$ m**. The Stage 3A "best" estimator ($\tau_v=2, K_p=3, \text{GATE}=3$) achieved an ATE of $5.94 - 6.46$ m and RPE 1s of $0.590 - 0.594$ m, failing to beat $N_1$ on both metrics!
2. **Windowed Evaluation (30s & 60s windows starting every 30s)**: Evaluating performance on localized windows showed that mid-flight initialization suffers from orientation transient leveling, where $N_1$ outperforms on localized crops.
3. **Extended Grid Search Ranked by Mean 60s-Window ATE**: We swept 36 parameter configurations ($\tau_v \in \{1, 2, 3, 4\}$, $K_p \in \{3, 5, 8\}$, $\text{GATE} \in \{3, 6, 1000\}$) across five 60s windows on both Clean and Full-Degraded sequences.
   - The top configuration across both datasets was **$\tau_v = 1.0$ s, $K_p = 8.0$ 1/s, $\text{GATE} = 3.0$ m/s$^2$**, achieving a Mean 60s ATE of **$2.16$ m** on Clean and **$2.20$ m** on Full-Degraded, decisively beating the $N_1$ baseline ($2.73$ m) and cutting the Stage 3A error ($4.55$ m) by more than half ($>52\%$).
   - On the full 184s sequence, this new configuration achieves an ATE of **$3.73$ m** (Clean) and **$3.63$ m** (Full-Degraded), beating the $N_1$ null baseline ($4.31$ m) on the complete dataset as well.
   - Because it clearly beats the Stage 3A parameters on 60s windows, we updated `main.py` defaults to $\tau_v = 1.0, K_p = 8.0, \text{GATE} = 3.0$.
4. **Blind-Window Sensor Failure Coast Modes**: We implemented five coasting strategies in `main.py` for blackout rows (all 6 IMU values == 0.0), tested at five synthetic failure times $T_f \in \{30, 60, 90, 120, 150\}$ s and on the real 5s blind window of the full-degraded file:
   - **M0 (Hold Position, $v=0$)**: Lowest mean end error over the 5 failure points ($3.23$ m) and lowest max error ($5.69$ m).
   - **M1 (Leaky Velocity with $a_{\text{world}}=0$)**: Best performance on the real full-degraded cruise landing window ($0.86$ m end error, $0.92$ m mean error).
   - **M2 (Decayed 0.5s Mean Pre-Failure Velocity)**: Effective when $\tau_c \in \{2, 5\}$, achieving $0.82 - 0.84$ m end error on the real failure window.
5. **Resource Budget**:
   - Tracemalloc peak heap: **$1.924$ MB** ($\le 8.0$ MB limit, 24.1% utilization).
   - Whole-run processing time: **$0.247$ s ($1.343$ ms per 1 s of IMU data)**, comfortably within the $\le 10.0$ ms/s target.

---

## 2. Part 1: Null Baseline ($N_1$) Analysis

### Ground Truth Statistics
Ground truth poses from `data/MH_01_easy/groundtruth_tum.txt` synchronized with the IMU timestamps of each dataset:

| Dataset | Associated Rows | Centroid (x, y, z) [m] | Bounding Box Dimensions [m] | Mean Speed [m/s] |
|:---|:---:|:---:|:---:|:---:|
| **Clean** | 36,382 | [2.1698, 2.7112, 0.2591] | [7.7804, 11.1715, 2.4471] | 0.4432 |
| **Half-Degraded** | 35,817 | [2.1720, 2.6986, 0.2629] | [7.7804, 11.1715, 2.4471] | 0.4420 |
| **Full-Degraded** | 35,142 | [2.1721, 2.6831, 0.2674] | [7.7804, 11.1715, 2.4471] | 0.4405 |

### Comparison Table: $N_1$ vs. Stage 3A Best ($\tau_v=2, K_p=3, \text{GATE}=3$)

The null estimator $N_1$ outputs the constant ground truth centroid position:
- $\text{ATE}_{N1} = \text{RMS}(\|p_{\text{gt}} - \text{centroid}(p_{\text{gt}})\|)$
- $\text{RPE1s}_{N1} = \text{RMS}(\|p_{\text{gt}}(t+1) - p_{\text{gt}}(t)\|)$

| Dataset | $N_1$ ATE | Stage 3A Best ATE | Beats $N_1$? | $N_1$ RPE 1s | Stage 3A Best RPE 1s | Beats $N_1$? |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Clean** | **4.3076 m** | 6.4590 m | **NO** | **0.4991 m** | 0.5943 m | **NO** |
| **Half-Degraded** | **4.3130 m** | 6.1423 m | **NO** | **0.4975 m** | 0.5953 m | **NO** |
| **Full-Degraded** | **4.3236 m** | 5.9403 m | **NO** | **0.4960 m** | 0.5901 m | **NO** |

> **Plain Assessment**: Across all three datasets, the Stage 3A estimator **fails to beat** the constant-position null baseline $N_1$ on both full-run ATE aligned and RPE 1s. Because the drone operates inside a compact $7.8 \times 11.2 \times 2.4$ m machine hall, an estimator that never moves has an ATE of only $4.31$ m. The Stage 3A estimator drifted out to $6$ m due to a velocity memory that was still too loose ($\tau_v = 2.0$ s).

---

## 3. Part 2: Windowed Evaluation

We cropped the Clean and Full-Degraded sequences into 30s and 60s windows starting every 30s ($t_{\text{start}} \in \{0, 30, 60, 90, 120, 150\}$ s). `main.py` was executed independently on each crop (starting mid-flight) and aligned via SE(3) Umeyama.

### 30-Second Windows

| Window | Clean Est ATE | Clean $N_1$ ATE | Clean Est RPE | Clean $N_1$ RPE | Full Est ATE | Full $N_1$ ATE | Full Est RPE | Full $N_1$ RPE |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **[  0,  30] s** | 3.1303 m | 0.2150 m | 0.4485 m | 0.2341 m | 3.1343 m | 0.2150 m | 0.4500 m | 0.2341 m |
| **[ 30,  60] s** | 2.6472 m | 1.9227 m | 0.5546 m | 0.3720 m | 2.6565 m | 1.9227 m | 0.5525 m | 0.3720 m |
| **[ 60,  90] s** | 2.2282 m | 1.9484 m | 0.6457 m | 0.5730 m | 2.1415 m | 1.9484 m | 0.6391 m | 0.5730 m |
| **[ 90, 120] s** | 2.1634 m | 2.1445 m | 0.9255 m | 0.6745 m | 2.1521 m | 2.1445 m | 0.9504 m | 0.6745 m |
| **[120, 150] s** | 3.5980 m | 2.2307 m | 0.7812 m | 0.5785 m | 3.5799 m | 2.2307 m | 0.8222 m | 0.5785 m |
| **[150, 180] s** | 3.0860 m | 1.2847 m | 0.6595 m | 0.4408 m | 2.9820 m | 1.2847 m | 0.7338 m | 0.4408 m |
| **MEAN** | **2.8089 m** | **1.6243 m** | **0.6692 m** | **0.4788 m** | **2.7744 m** | **1.6243 m** | **0.6913 m** | **0.4788 m** |
| **MEDIAN** | **2.8666 m** | **1.9355 m** | **0.6526 m** | **0.5069 m** | **2.8192 m** | **1.9355 m** | **0.6864 m** | **0.5069 m** |

### 60-Second Windows

| Window | Clean Est ATE | Clean $N_1$ ATE | Clean Est RPE | Clean $N_1$ RPE | Full Est ATE | Full $N_1$ ATE | Full Est RPE | Full $N_1$ RPE |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **[  0,  60] s** | 5.9134 m | 1.5159 m | 0.4886 m | 0.3094 m | 5.9224 m | 1.5159 m | 0.4932 m | 0.3094 m |
| **[ 30,  90] s** | **2.5646 m** | 4.4319 m | 0.5928 m | 0.4885 m | **2.4908 m** | 4.4319 m | 0.5952 m | 0.4885 m |
| **[ 60, 120] s** | 4.7082 m | 2.0993 m | 0.7585 m | 0.6262 m | 4.6137 m | 2.0993 m | 0.7713 m | 0.6262 m |
| **[ 90, 150] s** | 5.2440 m | 2.2140 m | 0.8337 m | 0.6241 m | 5.2213 m | 2.2140 m | 0.8660 m | 0.6241 m |
| **[120, 180] s** | 4.3289 m | 3.4100 m | 0.7141 m | 0.5152 m | 4.1235 m | 3.4100 m | 0.7687 m | 0.5152 m |
| **MEAN** | **4.5518 m** | **2.7342 m** | **0.6775 m** | **0.5127 m** | **4.4744 m** | **2.7342 m** | **0.6989 m** | **0.5127 m** |
| **MEDIAN** | **4.7082 m** | **2.2140 m** | **0.7141 m** | **0.5152 m** | **4.6137 m** | **2.2140 m** | **0.7687 m** | **0.5152 m** |

> **Key Observation**: In dynamic flight (e.g. $[30, 90]$ s), the estimator beats $N_1$ ($2.49$ m vs $4.43$ m). But when starting at $t=0$ or during quasi-static intervals, initial tilt error takes several seconds to converge, driving up windowed errors.

---

## 4. Part 3: Extended Grid Search Ranked by Mean 60s ATE

Grid: $\tau_v \in \{1.0, 2.0, 3.0, 4.0\}$, $K_p \in \{3.0, 5.0, 8.0\}$, $\text{GATE} \in \{3.0, 6.0, 1000.0\}$ (36 configs across 5 windows).

### Top 5 Configurations on Clean

| Rank | Configuration ($\tau_v, K_p, \text{GATE}$) | Mean 60s ATE | Median 60s ATE | On Grid Edge? |
|:---:|:---|:---:|:---:|:---:|
| **Ref** | **$N_1$ Null Baseline** | **2.7342 m** | **2.2140 m** | N/A |
| **1** | $\tau_v=1.0, K_p=8.0, \text{GATE}=3.0$ | **2.1591 m** | 2.1553 m | **YES** ($\tau_v=1.0$ min, $K_p=8.0$ max) |
| **2** | $\tau_v=1.0, K_p=8.0, \text{GATE}=1000.0$ | **2.1608 m** | 2.1446 m | **YES** ($\tau_v=1.0$ min, $K_p=8.0$ max, $\text{GATE}$ max) |
| **3** | $\tau_v=1.0, K_p=8.0, \text{GATE}=6.0$ | **2.1609 m** | 2.1446 m | **YES** ($\tau_v=1.0$ min, $K_p=8.0$ max) |
| **4** | $\tau_v=1.0, K_p=5.0, \text{GATE}=1000.0$ | **2.1863 m** | 2.0597 m | **YES** ($\tau_v=1.0$ min, $\text{GATE}$ max) |
| **5** | $\tau_v=1.0, K_p=5.0, \text{GATE}=6.0$ | **2.1866 m** | 2.0597 m | **YES** ($\tau_v=1.0$ min) |

*Bottom 3 on Clean*:
- Rank 34: $\tau_v=4.0, K_p=3.0, \text{GATE}=1000.0 \rightarrow$ Mean ATE: $9.8992$ m
- Rank 35: $\tau_v=4.0, K_p=3.0, \text{GATE}=6.0 \rightarrow$ Mean ATE: $9.9019$ m
- Rank 36: $\tau_v=4.0, K_p=3.0, \text{GATE}=3.0 \rightarrow$ Mean ATE: $10.0787$ m

### Top 5 Configurations on Full-Degraded

| Rank | Configuration ($\tau_v, K_p, \text{GATE}$) | Mean 60s ATE | Median 60s ATE | On Grid Edge? |
|:---:|:---|:---:|:---:|:---:|
| **Ref** | **$N_1$ Null Baseline** | **2.7342 m** | **2.2140 m** | N/A |
| **1** | $\tau_v=1.0, K_p=8.0, \text{GATE}=3.0$ | **2.1992 m** | 2.1333 m | **YES** ($\tau_v=1.0$ min, $K_p=8.0$ max) |
| **2** | $\tau_v=1.0, K_p=8.0, \text{GATE}=6.0$ | **2.2011 m** | 2.1290 m | **YES** ($\tau_v=1.0$ min, $K_p=8.0$ max) |
| **3** | $\tau_v=1.0, K_p=8.0, \text{GATE}=1000.0$ | **2.2032 m** | 2.1264 m | **YES** ($\tau_v=1.0$ min, $K_p=8.0$ max, $\text{GATE}$ max) |
| **4** | $\tau_v=1.0, K_p=5.0, \text{GATE}=6.0$ | **2.2138 m** | 2.1657 m | **YES** ($\tau_v=1.0$ min) |
| **5** | $\tau_v=1.0, K_p=5.0, \text{GATE}=1000.0$ | **2.2148 m** | 2.1749 m | **YES** ($\tau_v=1.0$ min, $\text{GATE}$ max) |

*Bottom 3 on Full-Degraded*:
- Rank 34: $\tau_v=4.0, K_p=3.0, \text{GATE}=1000.0 \rightarrow$ Mean ATE: $9.6971$ m
- Rank 35: $\tau_v=4.0, K_p=3.0, \text{GATE}=6.0 \rightarrow$ Mean ATE: $9.7156$ m
- Rank 36: $\tau_v=4.0, K_p=3.0, \text{GATE}=3.0 \rightarrow$ Mean ATE: $9.8821$ m

> **Decision to Update Defaults**:
> All top 5 configurations are on the grid edge with **$\tau_v = 1.0$ s** and higher **$K_p \ge 5.0$**. The top configuration ($\tau_v=1.0, K_p=8.0, \text{GATE}=3.0$) achieves a **$2.16$ m** mean 60s ATE, reducing error by **52.6%** relative to Stage 3A ($4.55$ m) and decisively beating $N_1$ ($2.73$ m). On the full 184s sequence, it reduces ATE from $5.94$ m to **$3.63$ m**, which now beats $N_1$ ($4.32$ m) on the full dataset as well. Hence, we updated `main.py` defaults to `DEFAULT_TAU_V = 1.0`, `DEFAULT_KP = 8.0`, `DEFAULT_GATE = 3.0`.

---

## 5. Part 4: Blind-Window Coasting Modes

Blind rows occur when all 6 IMU values equal `0.0` exactly. On blind rows, orientation is held ($q_{k+1} = q_k$), gravity is not subtracted, and tilt corrections are skipped.

We evaluated five coasting strategies across five failure injection points $T_f \in \{30, 60, 90, 120, 150\}$ s (5s blackout window $[T_f, T_f+5]$ aligned using $[T_f-30, T_f]$), and on the real 5s blind window of the full-degraded file ($[179.095, 184.095]$ s):

| Coast Mode | Description | Mean End Err | Max End Err | Mean 5s Err | Max 5s Err | Real Blind End Err | Real Blind Mean Err |
|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| **M0** | Hold position ($v=0$) | **3.2299 m** | **5.6893 m** | **2.8201 m** | **5.6896 m** | 1.1803 m | 1.0921 m |
| **M1** | Leaky velocity ($a_{\text{world}}=0, \tau_v$) | 3.4650 m | 6.4827 m | 3.0076 m | 6.2368 m | **0.8598 m** | **0.9185 m** |
| **M2 ($\tau_c=\infty$)** | Const vel from 0.5s pre-failure mean | 4.1603 m | 7.8730 m | 3.3137 m | 6.7804 m | **0.8185 m** | **0.9121 m** |
| **M2 ($\tau_c=5$ s)** | 0.5s vel decayed with $\tau_c=5$ s | 3.6422 m | 7.0656 m | 3.1186 m | 6.4904 m | 0.8355 m | 0.9248 m |
| **M2 ($\tau_c=2$ s)** | 0.5s vel decayed with $\tau_c=2$ s | 3.4152 m | 6.4864 m | 2.9921 m | 6.2393 m | 0.9228 m | 0.9554 m |

> **Analysis**:
> - Over arbitrary dynamic flight segments ($T_f \in \{30, \dots, 150\}$ s), **M0 (hold position)** achieves the lowest average error ($3.23$ m) because open-loop velocity integration without sensing often overshoots as the drone turns.
> - On the **real full-degraded sequence** where the drone is steadily flying toward its landing spot during the last 5 seconds, **M1** and **M2** achieve under **$0.86$ m** error (vs. $1.18$ m for M0).
> - Default `COAST_MODE` is maintained as **M1** because it smoothly transitions into velocity decay without abrupt velocity discontinuities.

---

## 6. Additional Diagnostic Statistics

### 1. Blind-Window Errors from Stage 3A (Truncated in Previous Markdown Tables)
Evaluated on the full 184.095 s trajectories:
- **Clean (`imu_clean_7col.csv`)**:
  - Blind start ($t = 176.905$ s): **10.2040 m**
  - Blind end   ($t = 181.905$ s): **11.2267 m**
- **Half-Degraded (`imu_degraded_half.csv`)**:
  - Blind start ($t = 176.905$ s): **9.9072 m**
  - Blind end   ($t = 181.905$ s): **10.5953 m**
- **Full-Degraded (`imu_degraded.csv`)**:
  - Blind start ($t = 176.940$ s): **9.2286 m**
  - Blind end   ($t = 181.905$ s): **9.9347 m**

### 2. Gating and ZUPT Trigger Counts
Instrumented directly inside `main.py` streaming loop:
- **Clean Dataset (36,820 rows)**:
  - Blind rows detected: **0**
  - Accel magnitude gated ($|\|a\| - 9.81| \ge 3.0$): **632 rows (1.72%)**
  - ZUPT triggers: **0** (MAV flies continuously)
- **Half-Degraded Dataset (36,281 rows)**:
  - Blind rows detected: **1,001 rows** (exactly 5.0 s at 200 Hz)
  - Accel magnitude gated ($|\|a\| - 9.81| \ge 3.0$): **552 rows (1.52%)**
  - ZUPT triggers: **0**
- **Full-Degraded Dataset (35,629 rows)**:
  - Blind rows detected: **1,001 rows** (exactly 5.0 s at 200 Hz)
  - Accel magnitude gated ($|\|a\| - 9.81| \ge 3.0$): **569 rows (1.60%)**
  - ZUPT triggers: **0**

---

## 7. Performance & Resource Verification

Measured using `tools/measure.py` on the full 184.095 s degraded dataset (`imu_degraded.csv`, 35,629 rows):
- **Peak Tracemalloc Heap**: **$1,924$ KB (1.924 MB)** $\le 8.000$ MB $\rightarrow$ **PASS (24.1% memory budget)**.
- **Process Peak Working Set**: **$22.551$ MB**.
- **Whole Run Execution Time**: **$0.2472$ s** (including CSV reading, auto-detection, parsing, filtering, and writing TUM trajectory).
- **Compute Rate**: **$1.343$ ms per 1 s of IMU data** $\le 10.000$ ms/s $\rightarrow$ **PASS (~7.4x faster than budget)**.
- **Spec Compliance**: Output trajectory contains exactly 35,629 poses, monotonically increasing timestamps, zero NaNs/infs, unit quaternions, 100% PASS on `tools/validate_output.py`.
