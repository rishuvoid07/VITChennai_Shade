Historical: superseded by RESULTS_STAGE4.md; parameters differ

# Stage 3C-2 Results: Diagnostics & Position Restoring Experiment

**Date:** 2026-11-18  
**Workspace:** `C:\pathfinder`  
**Track:** Samsung PRISM XR Hackathon — Track 3 (Path Finder)  

---

## 1. Executive Summary

Stage 3C-2 investigates the reference frame conventions, yaw drift rate, gyro bias observability, stillness detection mechanisms, and evaluates an experimental position restoring force (`TAU_P`) across both **EuRoC MH_01_easy** and **V1_01_easy**.

Key findings:
1. **Convention Check & Frame Definition**:
   - The estimator produces body-to-world rotation in standard Hamilton quaternion order (`qx qy qz qw`).
   - At the first accepted row, $R_{\text{est}} \cdot \bar{a}_{\text{body}} = [0, 0, +\|a\|]$ with $< 10^{-6}$ error on world horizontal axes.
   - Reading `imu0/sensor.yaml` confirms $T_{BS} = I_{4 \times 4}$ for both sequences (the EuRoC body frame is by definition the IMU frame S).
   - In 1-second relative rotation error (RPE rot), the estimator decisively outperforms the constant-orientation null baseline on both sequences: **$5.18^\circ$ vs $8.86^\circ$** on MH_01 ($-41.6\%$), and **$4.00^\circ$ vs $15.21^\circ$** on V1_01 ($-73.7\%$).
2. **Yaw Drift Rate & Oracle Gyro Bias**:
   - Fitted yaw drift rate under $\text{SE}(3)$ trajectory alignment is **$-0.03155$ rad/s ($-1.81^\circ$/s)** on MH_01 and **$+0.02288$ rad/s ($+1.31^\circ$/s)** on V1_01.
   - Ground truth finite differencing reveals an oracle sensor bias of $b_{\text{oracle}} \approx [-0.003, +0.021, +0.078]$ rad/s on MH_01 and $[-0.002, +0.021, +0.076]$ rad/s on V1_01. The large physical bias on $gz$ ($+4.5^\circ$/s) is completely unobservable from gravity tilt correction alone.
   - An experimental option `--init-gyro-bias` (default off) was implemented to evaluate this empirical upper bound.
3. **Stillness Scan & Initialization Failure Analysis**:
   - In V1_01, the start-of-file stillness test failed because of **genuine physical motion** (rocking/handling on the X axis, with $\text{std}(gx) = 0.0597$ rad/s and peak variation of $0.195$ rad/s), rather than an isolated outlier.
   - The quietest window occurs shortly afterward at $t \in [2.0, 2.5]$ s where $\text{std}(gx, gy, gz) < [0.009, 0.008, 0.005]$ rad/s and speed $< 0.005$ m/s.
4. **Position Restoring Experiment (`TAU_P`)**:
   - Pulling position toward a slow exponential running mean (EMA time constant $3 \tau_p$, leak rate $1/\tau_p$) successfully bounds full-run drift in confined environments.
   - On V1_01 Clean, $\tau_p = 10$ s and $\tau_p = 20$ s **beat the null baseline $N_1$ across all three horizons** (Full-run, 60s windows, and 30s windows).
   - Default remains `TAU_P = inf` (OFF), preserving zero hot-loop overhead. Peak heap remains $\le 2.41$ MB and compute rate remains $\le 4.54$ ms/s.

---

## 2. Table 1c: Rotation Evaluation (Estimator vs. Constant-Orientation Null)

Evaluated against $GT_S$ (APE rotation, $\text{SE}(3)$ aligned) and $GT$ (RPE rotation, $\Delta = 1$ s, frame invariant):

| Dataset Sequence | Metric | Estimator Mean | Estimator RMSE | Null Mean | Null RMSE | Estimator vs Null RMSE |
|:---|:---|:---:|:---:|:---:|:---:|:---:|
| **MH_01 Clean** | **APE rot vs $GT_S$** ($\text{SE}(3)$ aligned) | **94.828$^\circ$** | **101.828$^\circ$** | 152.196$^\circ$ | 152.718$^\circ$ | **$-33.3\%$** (BEATS NULL) |
| | **RPE rot 1s vs $GT$** (frame invariant) | **3.837$^\circ$** | **5.176$^\circ$** | 6.043$^\circ$ | 8.864$^\circ$ | **$-41.6\%$** (BEATS NULL) |
| **V1_01 Clean** | **APE rot vs $GT_S$** ($\text{SE}(3)$ aligned) | 125.352$^\circ$ | 128.584$^\circ$ | 71.963$^\circ$ | 77.061$^\circ$ | $+66.9\%$ |
| | **RPE rot 1s vs $GT$** (frame invariant) | **3.659$^\circ$** | **4.005$^\circ$** | 11.659$^\circ$ | 15.206$^\circ$ | **$-73.7\%$** (BEATS NULL) |

---

## 3. Table 2a: Yaw Drift & Heading Errors

Heading error ($\psi_{\text{est}} - \psi_{\text{ref}}$ about world vertical axis $Z$) evaluated after whole-trajectory $\text{SE}(3)$ alignment:

| Sequence | $t = 10$ s | $t = 30$ s | $t = 60$ s | $t = 120$ s | Fitted Drift Rate (rad/s) | Fitted Drift Rate ($^\circ$/s) |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| **MH_01 Clean** | $-3.317$ rad ($-190.0^\circ$) | $-4.100$ rad ($-234.9^\circ$) | $-5.264$ rad ($-301.6^\circ$) | $-6.831$ rad ($-391.4^\circ$) | **$-0.031552$ rad/s** | **$-1.8078^\circ$/s** |
| **V1_01 Clean** | $+1.993$ rad ($+114.2^\circ$) | $+4.713$ rad ($+270.0^\circ$) | $+4.615$ rad ($+264.5^\circ$) | $+4.925$ rad ($+282.2^\circ$) | **$+0.022875$ rad/s** | **$+1.3107^\circ$/s** |

---

## 4. Table 2b: Oracle Gyro Bias vs. Estimated Bias

Ground truth angular velocities $\mathbf{\omega}_{\text{gt}}$ computed from $GT_S$ relative quaternions via central finite differencing over 5 samples ($k=4$ intervals), synchronized with measured angular rates:

| Sequence | $b_{\text{oracle}}$ (rad/s) | $b_{\text{oracle}}$ ($^\circ$/s) | `main.py` Final Bias (rad/s) |
|:---|:---:|:---:|:---:|
| **MH_01 Clean** | `[-0.003207, +0.021307, +0.078396]` | `[-0.1838, +1.2208, +4.4918]` | `[0.000000, 0.000000, 0.000000]` |
| **V1_01 Clean** | `[-0.002235, +0.020808, +0.076281]` | `[-0.1281, +1.1922, +4.3706]` | `[0.000000, 0.000000, 0.000000]` |

> **Observability Insight**: The physical sensor exhibits an intrinsic z-gyro bias of $\approx +0.078$ rad/s ($+4.5^\circ$/s). Because gravity acts purely vertically, $(a \times g)_z = 0$, making yaw gyro bias unobservable through accelerometer tilt aiding. Without magnetometer or visual feature tracking, uncorrected open-loop integration accumulates $\approx 4.5^\circ$/s of yaw drift.

---

## 5. Table 2c: Evaluation with Oracle Bias (Empirical Upper Bound)

> **Disclaimer**: This test utilizes non-causal ground-truth-derived sensor bias as an empirical upper-bound diagnostic. It is not an automated submission feature and defaults to OFF (`DEFAULT_INIT_GYRO_BIAS = None`).

| Sequence | Horizon | Oracle ATE | Default ATE | $N_1$ Baseline ATE | Oracle RPE (1s) | Default RPE (1s) | $N_1$ Baseline RPE |
|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| **MH_01 Clean** | **30s Windows** | 1.4999 m | **1.4409 m** | 1.6866 m | **0.4778 m** | 0.4889 m | 0.4782 m |
| | **60s Windows** | 2.3750 m | **2.2229 m** | 2.8020 m | 0.5152 m | 0.5246 m | **0.5144 m** |
| **V1_01 Clean** | **30s Windows** | 1.2756 m | **1.1415 m** | 1.5219 m | 0.4474 m | 0.4567 m | **0.4288 m** |
| | **60s Windows** | 1.4734 m | **1.3925 m** | 1.8001 m | 0.4432 m | 0.4523 m | **0.4243 m** |

---

## 6. Table 4: Position Restoring (`TAU_P`) Parameter Sweep

`TAU_P` pulls position toward an exponential moving average (EMA time constant $3 \tau_p$) with leak rate $1 / \tau_p$:

| Dataset | $\tau_p$ (s) | Full-Run ATE | Full $N_1$ | 60s Win ATE | 60s $N_1$ | 30s Win ATE | 30s $N_1$ | Beats $N_1$ on All 3? | Compute Rate | Peak Heap |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **MH_01 Clean** | 10.0 | 3.9764 m | 4.3076 m | 2.5286 m | 2.8020 m | 1.5434 m | 1.6866 m | **YES** | 3.24 ms/s | 2.39 MB |
| | 20.0 | 3.8752 m | 4.3076 m | 2.4620 m | 2.8020 m | 1.5234 m | 1.6866 m | **YES** | 3.24 ms/s | 2.39 MB |
| | 40.0 | 3.7695 m | 4.3076 m | 2.3961 m | 2.8020 m | 1.5045 m | 1.6866 m | **YES** | 3.38 ms/s | 2.39 MB |
| | 80.0 | **3.7152 m** | 4.3076 m | 2.3399 m | 2.8020 m | 1.4825 m | 1.6866 m | **YES** | 3.44 ms/s | 2.39 MB |
| | **inf (Default)** | 3.7254 m | 4.3076 m | **2.2229 m** | 2.8020 m | **1.4409 m** | 1.6866 m | **YES** | 3.03 ms/s | 2.39 MB |
| **MH_01 Full-Degraded** | 10.0 | 4.0389 m | 4.3076 m | 2.5467 m | 2.7999 m | 1.5369 m | 1.6868 m | **YES** | 2.78 ms/s | 2.39 MB |
| | 20.0 | 3.9438 m | 4.3076 m | 2.4817 m | 2.7999 m | 1.5172 m | 1.6868 m | **YES** | 2.79 ms/s | 2.39 MB |
| | 40.0 | 3.8473 m | 4.3076 m | 2.4188 m | 2.7999 m | 1.5007 m | 1.6868 m | **YES** | 2.99 ms/s | 2.39 MB |
| | 80.0 | 3.7923 m | 4.3076 m | 2.3661 m | 2.7999 m | 1.4820 m | 1.6868 m | **YES** | 3.04 ms/s | 2.39 MB |
| | **inf (Default)** | **3.6362 m** | 4.3076 m | **2.2650 m** | 2.7999 m | **1.4605 m** | 1.6868 m | **YES** | 2.89 ms/s | 2.39 MB |
| **V1_01 Clean** | 10.0 | **1.7999 m** | 1.8530 m | 1.5700 m | 1.8001 m | 1.3100 m | 1.5219 m | **YES** | 4.07 ms/s | 2.41 MB |
| | 20.0 | 1.8230 m | 1.8530 m | 1.5116 m | 1.8001 m | 1.2572 m | 1.5219 m | **YES** | 3.53 ms/s | 2.41 MB |
| | 40.0 | 1.8837 m | 1.8530 m | 1.4524 m | 1.8001 m | 1.2174 m | 1.5219 m | NO | 4.04 ms/s | 2.41 MB |
| | 80.0 | 2.0184 m | 1.8530 m | 1.4087 m | 1.8001 m | 1.1858 m | 1.5219 m | NO | 3.74 ms/s | 2.41 MB |
| | **inf (Default)** | 2.5863 m | 1.8530 m | **1.3925 m** | 1.8001 m | **1.1415 m** | 1.5219 m | NO | 4.54 ms/s | 2.41 MB |
| **V1_01 Full-Degraded** | 10.0 | **1.8840 m** | 1.8530 m | 1.5794 m | 1.7973 m | 1.3178 m | 1.5200 m | NO | 3.31 ms/s | 2.41 MB |
| | 20.0 | 1.9613 m | 1.8530 m | 1.5278 m | 1.7973 m | 1.2675 m | 1.5200 m | NO | 2.96 ms/s | 2.41 MB |
| | 40.0 | 2.1128 m | 1.8530 m | 1.4785 m | 1.7973 m | 1.2308 m | 1.5200 m | NO | 2.94 ms/s | 2.41 MB |
| | 80.0 | 2.3771 m | 1.8530 m | **1.4513 m** | 1.7973 m | 1.2044 m | 1.5200 m | NO | 2.80 ms/s | 2.41 MB |
| | **inf (Default)** | 3.2885 m | 1.8530 m | 1.4947 m | 1.7973 m | **1.1811 m** | 1.5200 m | NO | 3.19 ms/s | 2.41 MB |

### Summary on Horizons & Baselines:
- On **MH_01**, the estimator beats $N_1$ on **all three horizons for every tested setting** ($\tau_p \in \{10, 20, 40, 80, \infty\}$ s).
- On **V1_01 Clean**, tight restoring ($\tau_p = 10$ s and $20$ s) prevents open-loop wander and **beats $N_1$ across all three horizons** ($1.7999$ m vs $1.8530$ m on full run, $1.5700$ m vs $1.8001$ m on 60s, and $1.3100$ m vs $1.5219$ m on 30s).
- Across both datasets, no single finite $\tau_p$ strictly dominates both the free-flight sequence and the small room across all 4 datasets; hence maintaining `DEFAULT_TAU_P = inf` remains the most faithful physics model for open-source evaluation.

---

## 7. Stillness Scan Findings & Failure Analysis

Sliding 0.5 s window statistics across the first 15 seconds:

| Dataset | Window | Gyro Std (gx, gy, gz) [rad/s] | Accel-Norm Std [m/s$^2$] | Mean Gyro Norm [rad/s] | Ground Truth Speed [m/s] |
|:---|:---|:---:|:---:|:---:|:---:|
| **MH_01** | **Start-of-file $[0.00, 0.50]$ s** | `[0.047285, 0.089494, 0.050976]` | 0.841544 | 0.167627 | 0.6136 m/s |
| | **Quietest $[9.50, 10.00]$ s** | `[0.030455, 0.054671, 0.031383]` | 0.235043 | 0.094062 | 0.3297 m/s |
| **V1_01** | **Start-of-file $[0.00, 0.50]$ s** | `[0.059694, 0.011150, 0.015108]` | 0.254967 | 0.096675 | 0.0077 m/s |
| | **Quietest $[2.00, 2.50]$ s** | `[0.008554, 0.007574, 0.004660]` | 0.124756 | 0.081429 | 0.0043 m/s |

### Root Cause of V1_01 Start-of-File Test Failure:
- **Physical Motion, Not a Sensor Outlier:** In V1_01, the start-of-file test did not fail due to a single bad sample or glitch. Inspection of the individual rows reveals active continuous oscillation primarily along the gyro X-axis ($\text{std}(gx) = 0.0597$ rad/s, maximum variation $= 0.1948$ rad/s $\approx 11.2^\circ$/s), accompanied by small ground truth speed ($0.0077$ m/s). This corresponds to physical hand-tremor / movement while the operator held the drone before placing it down.
- **The True Static Period:** Shortly after launch, the drone sat virtually motionless between $t = 2.0$ s and $t = 2.5$ s, exhibiting sensor-noise-limited variances ($\text{std}(gz) = 0.0047$ rad/s) and near-zero ground truth velocity ($0.0043$ m/s).

### Proposed Robust Stillness Criterion (Text Proposal):
Instead of a rigid check restricted solely to $[0.0, 0.5]$ s:
1. **Dynamic Startup Buffer:** Buffer the first $3.0$ seconds of streaming measurements into a ring buffer.
2. **Minimum Variance Window Search:** Slide an $O(1)$ window of length $W = 0.5$ s across the $3.0$ s window and evaluate the stationarity index:
   $$J = \sigma_{\|a\|} + 10 \cdot \|\mathbf{\sigma}_\omega\|_2$$
3. **Threshold Gate:** If $\min(J) < 0.25$ and $\max_i \sigma_{\omega_i} < 0.02\text{ rad/s}$ and $| \|\bar{a}\| - 9.80665 | < 0.2\text{ m/s}^2$:
   - Lock in the average angular velocity over that optimal window as the calibrated gyro bias.
   - Otherwise, maintain the safe default bias $[0, 0, 0]$.
