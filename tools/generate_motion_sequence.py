#!/usr/bin/env python3
"""
generate_motion_sequence.py - Generate synthetic dynamic IMU data and TUM ground truth.

Specification:
  - Duration: 120 s at 200 Hz (dt = 0.005 s, 24001 samples).
  - Timestamps: integer nanoseconds starting at 1400000000000000000.
  - Position: p(t) = s(t) * [2.0*sin(0.30*t), 1.5*sin(0.23*t + 1.0), 0.5*sin(0.41*t)] m.
  - Orientation (ZYX Euler, world-from-body):
      roll  = s(t) * 0.20 * sin(0.50*t)
      pitch = s(t) * 0.15 * sin(0.37*t + 0.5)
      yaw   = s(t) * 0.60 * sin(0.10*t)
  - Smoothstep ramp s(t):
      0 for t <= 3.0 s
      1 for t >= 6.0 s
      u*u*(3 - 2*u) with u = (t - 3)/3 for 3 < t < 6
  - Ideal IMU:
      f_body = R^T * (p_ddot + [0, 0, 9.80665])
      omega_body = vee(R^T * dR/dt)
      with p_ddot and dR/dt from central finite differences (h = 1e-4 s).
  - Outputs:
      (a) data/synthetic_motion/imu_clean_7col.csv (header: timestamp,ax,ay,az,gx,gy,gz)
      (b) data/synthetic_motion/groundtruth_tum.txt (TUM: timestamp tx ty tz qx qy qz qw)
  - Self-test:
      Integrates the clean data from exact initial pose and verifies position error.
"""

import os
import sys
import math
import numpy as np
from scipy.spatial.transform import Rotation

G_VAL = 9.80665
G_VEC = np.array([0.0, 0.0, G_VAL])
H = 1e-4
START_TS_NS = 1400000000000000000
RATE_HZ = 200
DT_S = 1.0 / RATE_HZ
DT_NS = int(round(DT_S * 1e9))
TOTAL_SEC = 120
N_SAMPLES = TOTAL_SEC * RATE_HZ + 1  # 24001 samples for 0.0 to 120.0 inclusive


def smoothstep(t):
    if t <= 3.0:
        return 0.0
    if t >= 6.0:
        return 1.0
    u = (t - 3.0) / 3.0
    return u * u * (3.0 - 2.0 * u)


def pos_analytic(t):
    s = smoothstep(t)
    return np.array([
        s * 2.0 * math.sin(0.30 * t),
        s * 1.5 * math.sin(0.23 * t + 1.0),
        s * 0.5 * math.sin(0.41 * t)
    ], dtype=np.float64)


def rot_analytic(t):
    s = smoothstep(t)
    roll = s * 0.20 * math.sin(0.50 * t)
    pitch = s * 0.15 * math.sin(0.37 * t + 0.5)
    yaw = s * 0.60 * math.sin(0.10 * t)

    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)

    Rx = np.array([
        [1.0, 0.0, 0.0],
        [0.0, cr, -sr],
        [0.0, sr, cr]
    ], dtype=np.float64)

    Ry = np.array([
        [cp, 0.0, sp],
        [0.0, 1.0, 0.0],
        [-sp, 0.0, cp]
    ], dtype=np.float64)

    Rz = np.array([
        [cy, -sy, 0.0],
        [sy, cy, 0.0],
        [0.0, 0.0, 1.0]
    ], dtype=np.float64)

    # World-from-body rotation matrix: R = Rz @ Ry @ Rx
    return Rz @ Ry @ Rx


def rot_to_quat(R):
    """Returns unit quaternion [qx, qy, qz, qw] with qw >= 0."""
    q = Rotation.from_matrix(R).as_quat()  # [qx, qy, qz, qw]
    if q[3] < 0:
        q = -q
    norm = np.linalg.norm(q)
    return q / norm


def clean_zero(v, tol=1e-12):
    return 0.0 if abs(v) < tol else v


def format_ts(ns):
    sec = ns // 1000000000
    frac = ns % 1000000000
    return f"{sec}.{frac:09d}"


# Hamilton quaternion multiplication and vector rotation for self-test
def quat_mul(q1, q2):
    # [qx, qy, qz, qw]
    x1, y1, z1, w1 = q1
    x2, y2, z2, w2 = q2
    return np.array([
        w1*x2 + x1*w2 + y1*z2 - z1*y2,
        w1*y2 - x1*z2 + y1*w2 + z1*x2,
        w1*z2 + x1*y2 - y1*x2 + z1*w2,
        w1*w2 - x1*x2 - y1*y2 - z1*z2
    ], dtype=np.float64)


def quat_rot(q, v):
    # rotates v from body to world frame
    qx, qy, qz, qw = q
    tx = 2.0 * (qy*v[2] - qz*v[1])
    ty = 2.0 * (qz*v[0] - qx*v[2])
    tz = 2.0 * (qx*v[1] - qy*v[0])
    return np.array([
        v[0] + qw*tx + (qy*tz - qz*ty),
        v[1] + qw*ty + (qz*tx - qx*tz),
        v[2] + qw*tz + (qx*ty - qy*tx)
    ], dtype=np.float64)


def run_self_test(clean_imu_data, true_positions, true_quaternions, dt):
    """
    Self-test: integrate clean IMU data from exact initial pose [0,0,0], [0,0,0,1],
    and measure position error vs ground truth across the 120s sequence.
    """
    q = true_quaternions[0].copy()
    v = np.zeros(3, dtype=np.float64)
    p = true_positions[0].copy()

    errors = []
    n = len(clean_imu_data)

    for i in range(n):
        ts_ns, ax, ay, az, gx, gy, gz = clean_imu_data[i]
        f_b = np.array([ax, ay, az], dtype=np.float64)
        w_b = np.array([gx, gy, gz], dtype=np.float64)

        if i > 0:
            angle = np.linalg.norm(w_b) * dt
            if angle > 1e-14:
                ha = angle * 0.5
                sha = math.sin(ha)
                cha = math.cos(ha)
                inv_w = sha / np.linalg.norm(w_b)
                dq = np.array([w_b[0]*inv_w, w_b[1]*inv_w, w_b[2]*inv_w, cha], dtype=np.float64)
                q = quat_mul(q, dq)
                q = q / np.linalg.norm(q)

            a_w = quat_rot(q, f_b) - G_VEC
            # Double integrate
            p = p + v * dt + 0.5 * a_w * dt * dt
            v = v + a_w * dt

        err = np.linalg.norm(p - true_positions[i])
        errors.append(err)

    errors = np.array(errors)
    max_err = float(np.max(errors))
    final_err = float(errors[-1])
    rmse = float(np.sqrt(np.mean(errors**2)))
    return max_err, final_err, rmse


def main():
    out_dir = os.path.join("data", "synthetic_motion")
    os.makedirs(out_dir, exist_ok=True)

    imu_path = os.path.join(out_dir, "imu_clean_7col.csv")
    tum_path = os.path.join(out_dir, "groundtruth_tum.txt")

    clean_records = []
    true_positions = []
    true_quaternions = []

    print(f"Generating {N_SAMPLES} samples ({TOTAL_SEC} s at {RATE_HZ} Hz)...")
    with open(imu_path, "w", encoding="utf-8") as f_imu, \
         open(tum_path, "w", encoding="utf-8") as f_tum:

        # IMU CSV header
        f_imu.write("timestamp,ax,ay,az,gx,gy,gz\n")
        # TUM header
        f_tum.write("# groundtruth_tum.txt - TUM format\n")
        f_tum.write("# timestamp tx ty tz qx qy qz qw\n")

        for i in range(N_SAMPLES):
            t = i * DT_S
            ts_ns = START_TS_NS + i * DT_NS

            p = pos_analytic(t)
            R = rot_analytic(t)
            q = rot_to_quat(R)

            # Central finite differences for acceleration:
            p_plus = pos_analytic(t + H)
            p_minus = pos_analytic(t - H)
            p_ddot = (p_plus - 2.0 * p + p_minus) / (H * H)
            f_body = R.T @ (p_ddot + G_VEC)

            # Central finite differences for angular velocity:
            R_plus = rot_analytic(t + H)
            R_minus = rot_analytic(t - H)
            dR_dt = (R_plus - R_minus) / (2.0 * H)
            S = R.T @ dR_dt
            wx = 0.5 * (S[2, 1] - S[1, 2])
            wy = 0.5 * (S[0, 2] - S[2, 0])
            wz = 0.5 * (S[1, 0] - S[0, 1])

            # Store for self-test
            clean_records.append((ts_ns, f_body[0], f_body[1], f_body[2], wx, wy, wz))
            true_positions.append(p)
            true_quaternions.append(q)

            # Format outputs
            ax_c = clean_zero(f_body[0])
            ay_c = clean_zero(f_body[1])
            az_c = clean_zero(f_body[2])
            gx_c = clean_zero(wx)
            gy_c = clean_zero(wy)
            gz_c = clean_zero(wz)

            f_imu.write(f"{ts_ns},{ax_c:.9f},{ay_c:.9f},{az_c:.9f},{gx_c:.9f},{gy_c:.9f},{gz_c:.9f}\n")

            ts_str = format_ts(ts_ns)
            px_c = clean_zero(p[0])
            py_c = clean_zero(p[1])
            pz_c = clean_zero(p[2])
            qx_c = clean_zero(q[0])
            qy_c = clean_zero(q[1])
            qz_c = clean_zero(q[2])
            qw_c = clean_zero(q[3])
            f_tum.write(f"{ts_str} {px_c:.9f} {py_c:.9f} {pz_c:.9f} {qx_c:.9f} {qy_c:.9f} {qz_c:.9f} {qw_c:.9f}\n")

    print(f"Generated clean IMU: {imu_path} ({len(clean_records)} rows)")
    print(f"Generated ground truth: {tum_path} ({len(true_positions)} rows)")

    # Run self-test
    max_err, final_err, rmse = run_self_test(clean_records, true_positions, true_quaternions, DT_S)
    print("Self-test integration of clean data versus ground truth:")
    print(f"  Max position error:   {max_err:.5f} m ({max_err*100.0:.2f} cm)")
    print(f"  Final position error: {final_err:.5f} m ({final_err*100.0:.2f} cm)")
    print(f"  Position RMSE:        {rmse:.5f} m ({rmse*100.0:.2f} cm)")

    if max_err > 0.10:
        print(f"ERROR: Self-test max error ({max_err:.4f} m) exceeds 10 cm threshold!", file=sys.stderr)
        sys.exit(1)
    else:
        print("Self-test PASSED (consistency confirmed).")


if __name__ == "__main__":
    main()
