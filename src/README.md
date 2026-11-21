# \# Shade — Path Finder: IMU Trajectory Estimation Under Sensor Degradation

# 

# Demo video (2-3 min): https://youtu.be/UeS-C6DfX-I

# 

# Samsung PRISM XR Hackathon 2026, Track 3. Rishabh Jain, VIT Chennai.

# 

# A standalone, standard-library Python program that turns a degraded raw IMU stream into a 6-DoF trajectory (TUM format), one pose per input row, offline and single-threaded.

# 

# Shade.zip contains the minimal evaluation bundle. tools/, tests/, docs/ and presentation/ are in the GitHub repository.

# 

# \## Quick start

# 

# ```

# python src/main.py <input.csv | input.zip | folder> \[estimated\_trajectory.txt]

# ```

# 

# No third-party packages are needed to run `src/main.py` (tested with Python 3.12). Tools and tests need `pip install -r requirements-dev.txt`.

# 

# Output: `# timestamp tx ty tz qx qy qz qw`, seconds with 9 decimals, exactly one row per input row.

# 

# Input: a CSV, a zip or a folder. In a zip or folder, `imu0/data.csv` is found at any depth; if it is absent and the archive holds exactly one CSV, that file is used. Anything ambiguous or empty prints an error to stderr and exits with code 1.

# 

# \## Approach

# 

# 1\. \*\*Input handling.\*\* Header optional; comma, semicolon, tab or whitespace delimiters; timestamps in s/ms/us/ns detected from the data; accelerometer in m/s² or g; gyro and accel column order from header names, or from the gravity norm when there is no header. Timestamps are written with integer arithmetic so rows never collide. Files are streamed, never loaded whole.

# 2\. \*\*Degradation handling.\*\* Duplicate or non-increasing timestamps repeat the previous pose; gaps are integrated in nominal-dt sub-steps; spikes are rejected; stuck samples and all-zero rows (sensor blackout) are coasted without gravity subtraction.

# 3\. \*\*Estimator.\*\* A Mahony-style complementary filter keeps roll and pitch bounded using gravity (gated when the accelerometer norm is far from 1 g). Gyro bias is learned only in stillness-checked windows, with zero-velocity updates. Velocity leaks with a 1 s time constant, and position is weakly pulled toward its slow running mean (40 s).

# 4\. \*\*Why bounded drift.\*\* Plain strapdown double integration of a consumer IMU diverged to about 50 km ATE in 184 s on EuRoC MH\_01 in our tests, because small tilt and gyro-bias errors leak gravity into position. The leak and restoring terms trade long-term fidelity for bounded error.

# 

# \## Results

# 

# Development data: EuRoC MH\_01\_easy (tuned on) and V1\_01\_easy (validation, though the final position-restoring constant was chosen using both). Degraded files were made with the official `tools/degrade\_imu.py`, seed 42. ATE is RMSE after SE(3) Umeyama alignment. The baseline is a constant-position estimate, which is a strong baseline in a small room.

# 

# | Sequence | Full run ATE | Constant-position baseline | 60 s windows | baseline | 30 s windows | baseline |

# |---|---|---|---|---|---|---|

# | MH\_01 clean | 3.77 m | 4.31 m | 2.40 m | 2.80 m | 1.50 m | 1.69 m |

# | MH\_01 full-degraded | 3.85 m | 4.32 m | 2.42 m | 2.80 m | 1.50 m | 1.69 m |

# | V1\_01 clean | 1.88 m | 1.85 m | 1.45 m | 1.80 m | 1.22 m | 1.52 m |

# | V1\_01 full-degraded | 2.11 m | 1.85 m | 1.48 m | 1.80 m | 1.23 m | 1.52 m |

# 

# Plain strapdown (no filtering): about 50 km. RPE over 1 s is within 2–7% of the constant-position baseline (slightly worse). Relative rotation over 1 s is clearly better than a constant orientation (3.8° vs 6.0° on MH\_01, 3.7° vs 11.7° on V1\_01).

# 

# \## Budgets (Intel Core i5-13420H, Python 3.12, Windows 11)

# 

# \- Peak Python heap (tracemalloc): about 1.2 MB (limit 8 MB), the same on a 3-minute and a 21-minute input.

# \- Run time as a command-line process, interpreter start included, per 1 s of IMU: 3.1–3.6 ms on 3-minute files, 2.3–2.8 ms on a 21-minute file (limit 20 ms). Median of 5 runs. Full numbers are in `metadata.json` and `docs/RESULTS\_STAGE5B.md`.

# 

# \## Robustness

# 

# 15 input-format variants (raw EuRoC gyro-first, no header, ms/us/s timestamps, accel in g, delimiters, CRLF + BOM, zip, directory, 1/2/10-row files, NaN and empty fields) and 10 zip layouts (nested folders, spaces, extra entries, no trailing newline, a very long junk line, ambiguous or empty archives) behave as expected (`tests/`).

# 

# \## Limitations

# 

# \- IMU only, no absolute reference: heading is unobservable (yaw drifts about 1–2°/s from gyro bias), and absolute rotation after alignment is not reliable.

# \- The velocity leak and position restoring assume the aircraft stays in a bounded area; a long straight flight would be under-estimated.

# \- On the real EuRoC sequences the aircraft is moving at the start, so the stillness-based bias learning was exercised only on synthetic stationary segments. A synthetic oracle test showed that knowing the true gyro bias would not reduce ATE, because of the short velocity memory.

# \- Validated on two EuRoC sequences only.

# 

# \## Repository

# 

# `src/` the solution · `tools/` evaluation and data tools (`degrade\_imu.py` is the unmodified official script) · `tests/` · `docs/` results and development log · `metadata.json` measured specs.

# 

# License: MIT

