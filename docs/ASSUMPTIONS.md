# Track 3 (Path Finder) Assumptions & Specifications

This document records the official organizer FAQ rules and all implementation assumptions in the Python codebase (`main.py` and `tools/`).

---

## 1. Official Organizer FAQ Rules (Confirmed)

1. **Submission Format**:
   - The submission **MUST** be a standalone Python script named `main.py`.
   - C++ is **NOT** accepted for the final submission. Our earlier C++ prototype is archived under `archive_cpp_reference/` as reference only.
2. **Input CSV Specification**:
   - Exactly 7 columns in this order: `timestamp, accel_x, accel_y, accel_z, gyro_x, gyro_y, gyro_z`.
   - **ACCEL-FIRST**: Note that this differs from raw EuRoC `imu0/data.csv` which is gyro-first (`timestamp, w_x, w_y, w_z, a_x, a_y, a_z`).
   - Header row is optional.
   - Timestamp units may be `s`, `ms`, `us`, or `ns`.
   - Accelerometer units may be `m/s^2` or `g`.
   - Gyroscope is assumed `rad/s`.
3. **Output Trajectory Specification**:
   - Output file named `estimated_trajectory.txt` in standard TUM format:
     `timestamp tx ty tz qx qy qz qw`
   - Timestamp in **SECONDS** with 9 decimal places.
   - **EXACTLY one pose per input row**, preserving input row count and order, including duplicate-timestamp rows and invalid rows.
   - No `NaN` or `inf` values.
   - Unit quaternions ($\|q\| = 1.0 \pm 10^{-4}$).
4. **Degradation Characteristics (`tools/degrade_imu.py`)**:
   - Fixed RNG seed (`SEED = 42`).
   - First ~2 seconds are almost clean (`protect_seconds = 2.0`, `floor = 0.02`).
   - Degradation ramp grows via power curve ($\gamma = 1.7$).
   - Adds Gaussian white noise, bias random walk, scale factor random walk, random spikes, stuck sample bursts, single and burst dropped rows (physical timestamp gaps), and duplicated rows ($dt = 0$).
   - **Sensor Failure Blackout**: For the final 5.0 seconds of the sequence, accel and gyro values are set to exactly `0.0`. Timestamps are still present; one pose must still be written per row.
5. **Scoring Metric**:
   - `evo ATE` (Absolute Trajectory Error, translation part) after SE(3) (Umeyama) alignment against hidden ground truth (`evo_ape tum ref est -a`).
   - Offline processing is permitted.
6. **Resource Limits**:
   - **Memory Limit**: 8 MB measured at the **Python HEAP** level (via `tracemalloc.get_traced_memory()`), reflecting algorithmic buffers and data structures, not the process RSS / OS working set.
   - **Runtime Target**: At most **20 ms of compute per 1 s of IMU data** (~200 Hz sampling rate). Measured on sequences $\ge 60$ s to amortize one-off interpreter startup.

---

## 2. Implementation Assumptions & Heuristics (`main.py`)

### A. Auto-Detection Heuristics (First $\le 1000$ Rows)
- **Timestamp Unit**:
  - Sample positive successive differences $dt_i = t_i - t_{i-1} > 0$.
  - Median $dt < 1.0 \implies \text{seconds}$ (`s`, scale $= 1.0$).
  - Median $dt < 10^3 \implies \text{milliseconds}$ (`ms`, scale $= 10^{-3}$).
  - Median $dt < 10^6 \implies \text{microseconds}$ (`us`, scale $= 10^{-6}$).
  - Median $dt \ge 10^6 \implies \text{nanoseconds}$ (`ns`, scale $= 10^{-9}$).
- **Column Order Detection**:
  - Compute median vector norm of triple 1 (`cols[1:4]`) and triple 2 (`cols[4:7]`).
  - If triple 2 is close to earth gravity ($0.5 < \|\mathbf{v}\| < 2.0$ for $g$, or $7.0 < \|\mathbf{v}\| < 12.0$ for m/s²) and triple 1 is not, columns are identified as gyro-first (EuRoC raw format) and swapped to accel-first with a stderr warning.
- **Accelerometer Unit**:
  - If the median norm of the accel triple is in $(0.5, 2.0)$, unit is assumed `g` and scaled by standard gravity $g = 9.80665\text{ m/s}^2$. Otherwise, unit is assumed $\text{m/s}^2$ (scale $= 1.0$).
- **Gyroscope Unit**:
  - Always assumed `rad/s` per competition FAQ.

### B. Lossless Integer Timestamp Formatting
- Timestamps that are integral are parsed directly as Python `int` without passing through standard 64-bit float (`double`).
- When formatting to TUM seconds with 9 decimals:
  - For nanoseconds: integer quotient `ts // 10**9` and 9-digit zero-padded remainder `ts % 10**9`.
  - For microseconds: `ts // 10**6` and remainder `(ts % 10**6) * 1000`.
  - For milliseconds: `ts // 1000` and remainder `(ts % 1000) * 1000000`.
  - For seconds (integral): `{ts}.000000000`.
- Float timestamps use standard `f"{ts:.9f}"`.

### C. Initial Orientation & Gyro Debiasing
- The sensor is assumed approximately static for the initial phase.
- Initial orientation is derived from the mean accelerometer vector over the first up to 200 valid rows:
  - Unit gravity vector $\mathbf{u} = \bar{\mathbf{a}} / \|\bar{\mathbf{a}}\|$.
  - Half-angle quaternion rotation aligning $\mathbf{u}$ with world $+z$ `[0, 0, 1]` with zero yaw.
- Gyroscope bias is estimated as the mean angular velocity over the same initial window and subtracted from subsequent readings.

### D. Row Rules (Mandatory 1-to-1 Mapping)
1. **Invalid Rows**:
   - A row is invalid if any column contains non-finite values (`NaN`, `inf`), or if accelerometer norm is exactly 0.0 AND gyroscope norm is exactly 0.0.
   - **Handling**: Sensor measurements are ignored. The estimator propagates state under constant velocity ($\mathbf{p} \leftarrow \mathbf{p} + \mathbf{v} \cdot dt$) and constant orientation ($\mathbf{q} \leftarrow \mathbf{q}$).
   - **Rationale**: Prevents gravitational runaway during sensor blackout (e.g., the last 5 seconds of the degraded file).
2. **Duplicate or Non-Increasing Timestamps ($dt \le 0$)**:
   - If $t_k \le t_{prev}$, state is not integrated. The previous pose is output verbatim with the current timestamp.
3. **Time Gaps ($dt > 1.5 \times dt_{median}$)**:
   - When dropped rows create a time gap, the estimator integrates across $dt$ holding the last valid debiased measurement constant.
4. **Outlier Filtering**:
   - In this Stage 1 baseline, spikes and stuck samples are passed through to the integrator without Kalman filtering (outlier rejection will be implemented in Stage 2/3).

### E. Memory & Heap Discipline
- Processing streams line-by-line using a generator.
- Memory during auto-detection buffers at most 1000 parsed tuples (~60 KB), which are cleared immediately after init.
- Per-row operations use scalar floats and math functions. No numpy or pandas in the processing loop.
- Output is written in buffered chunks of 1000 strings, maintaining traced heap usage below 1.2 MB.
