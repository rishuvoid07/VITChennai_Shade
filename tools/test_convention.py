#!/usr/bin/env python3
"""
tools/test_convention.py - Unit test and convention verification for Stage 3C-2.
1a) Verify R_est * mean_accel_body == [0, 0, +G] on MH_01 and V1_01.
    Verify Hamilton quaternion convention and TUM pose format.
1b) Read imu0/sensor.yaml T_BS, construct GT_S: R_WS = R_WB * R_BS, write groundtruth_S_tum.txt.
1c) Evaluate APE rot (SE3 aligned) against GT_S and RPE rot (1s) against GT.
"""

import os
import sys
import math
import yaml
import copy
import numpy as np

sys.path.insert(0, os.path.abspath("src" if os.path.exists("src/main.py") else "."))
sys.path.insert(0, os.path.abspath("."))
from main import open_input_stream, parse_raw_row, auto_detect_and_init, qrot, quat_mult
from evo.tools import file_interface
from evo.core import sync, metrics


def test_quaternion_hamilton():
    # In Hamilton convention: i*j = k, j*k = i, k*i = j, i^2 = j^2 = k^2 = ijk = -1
    # q = (qx, qy, qz, qw)
    qi = (1.0, 0.0, 0.0, 0.0)
    qj = (0.0, 1.0, 0.0, 0.0)
    qk = (0.0, 0.0, 1.0, 0.0)
    
    # i * j should be k: (0, 0, 1, 0)
    prod_ij = quat_mult(qi, qj)
    assert np.allclose(prod_ij, qk), f"Expected k, got {prod_ij}"
    
    # j * k should be i: (1, 0, 0, 0)
    prod_jk = quat_mult(qj, qk)
    assert np.allclose(prod_jk, qi), f"Expected i, got {prod_jk}"
    
    # k * i should be j: (0, 1, 0, 0)
    prod_ki = quat_mult(qk, qi)
    assert np.allclose(prod_ki, qj), f"Expected j, got {prod_ki}"
    
    # i * i should be -1: (0, 0, 0, -1)
    prod_ii = quat_mult(qi, qi)
    assert np.allclose(prod_ii, (0.0, 0.0, 0.0, -1.0)), f"Expected -1, got {prod_ii}"
    print("  [PASS] Hamilton quaternion multiplication unit test.")


def test_body_to_world_leveling():
    datasets = [
        ("MH_01", "data/MH_01_easy/imu_clean_7col.csv"),
        ("V1_01", "data/V1_01_easy/imu_clean_7col.csv"),
    ]
    for name, path in datasets:
        stream, zf = open_input_stream(path)
        rows = []
        for line in stream:
            if line.startswith("#") or not line.strip():
                continue
            p = parse_raw_row(line, ",", None, 5000000, 0.005, True)
            if p:
                rows.append(p)
            if len(rows) >= 2000:
                break
        if zf:
            zf.close()
        cfg = auto_detect_and_init(rows, None)
        q_init = cfg["q_init"]
        mean_a = cfg["mean_init_a"]
        norm_a = math.sqrt(sum(x*x for x in mean_a))
        a_world = qrot(q_init, mean_a[0], mean_a[1], mean_a[2])
        
        print(f"\n--- {name} First Accepted Rows Leveling ---")
        print(f"  mean_accel_body: [{mean_a[0]:.4f}, {mean_a[1]:.4f}, {mean_a[2]:.4f}] m/s^2 (norm={norm_a:.4f})")
        print(f"  q_init (qx, qy, qz, qw): [{q_init[0]:.6f}, {q_init[1]:.6f}, {q_init[2]:.6f}, {q_init[3]:.6f}]")
        print(f"  R_est * mean_accel_body: [{a_world[0]:.6f}, {a_world[1]:.6f}, {a_world[2]:.6f}] m/s^2")
        
        assert abs(a_world[0]) < 1e-4, f"World X accel should be 0, got {a_world[0]}"
        assert abs(a_world[1]) < 1e-4, f"World Y accel should be 0, got {a_world[1]}"
        assert abs(a_world[2] - norm_a) < 1e-4, f"World Z accel should be {norm_a}, got {a_world[2]}"
        print(f"  [PASS] {name} body-to-world rotation levels gravity strictly to +Z.")


def parse_sensor_yaml_t_bs(yaml_path):
    if not os.path.exists(yaml_path):
        raise FileNotFoundError(f"Missing {yaml_path}")
    with open(yaml_path, "r", encoding="utf-8") as f:
        y = yaml.safe_load(f)
    t_bs_data = y["T_BS"]["data"]
    T_BS = np.array(t_bs_data, dtype=np.float64).reshape((4, 4))
    R_BS = T_BS[:3, :3]
    p_BS = T_BS[:3, 3]
    return T_BS, R_BS, p_BS


def rotmat_to_quat_xyzw(R):
    """Convert 3x3 rotation matrix to quaternion [qx, qy, qz, qw]."""
    tr = np.trace(R)
    if tr > 0.0:
        S = np.sqrt(tr + 1.0) * 2.0
        qw = 0.25 * S
        qx = (R[2, 1] - R[1, 2]) / S
        qy = (R[0, 2] - R[2, 0]) / S
        qz = (R[1, 0] - R[0, 1]) / S
    elif (R[0, 0] > R[1, 1]) and (R[0, 0] > R[2, 2]):
        S = np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2.0
        qw = (R[2, 1] - R[1, 2]) / S
        qx = 0.25 * S
        qy = (R[0, 1] + R[1, 0]) / S
        qz = (R[0, 2] + R[2, 0]) / S
    elif R[1, 1] > R[2, 2]:
        S = np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2.0
        qw = (R[0, 2] - R[2, 0]) / S
        qx = (R[0, 1] + R[1, 0]) / S
        qy = 0.25 * S
        qz = (R[1, 2] + R[2, 1]) / S
    else:
        S = np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2.0
        qw = (R[1, 0] - R[0, 1]) / S
        qx = (R[0, 2] + R[2, 0]) / S
        qy = (R[1, 2] + R[2, 1]) / S
        qz = 0.25 * S
    norm = np.sqrt(qx*qx + qy*qy + qz*qz + qw*qw)
    return np.array([qx/norm, qy/norm, qz/norm, qw/norm])


def quat_xyzw_to_rotmat(q):
    qx, qy, qz, qw = q
    return np.array([
        [1.0 - 2.0*(qy*qy + qz*qz), 2.0*(qx*qy - qz*qw), 2.0*(qx*qz + qy*qw)],
        [2.0*(qx*qy + qz*qw), 1.0 - 2.0*(qx*qx + qz*qz), 2.0*(qy*qz - qx*qw)],
        [2.0*(qx*qz - qy*qw), 2.0*(qy*qz + qx*qw), 1.0 - 2.0*(qx*qx + qy*qy)]
    ])


def build_gt_s(gt_path, sensor_yaml_path, out_gt_s_path):
    T_BS, R_BS, p_BS = parse_sensor_yaml_t_bs(sensor_yaml_path)
    print(f"\nBuilding GT_S from {gt_path} with {sensor_yaml_path}:")
    print(f"  T_BS:\n{T_BS}")
    
    rows_written = 0
    with open(gt_path, "r", encoding="utf-8") as fin, open(out_gt_s_path, "w", encoding="utf-8") as fout:
        fout.write("# ground truth in IMU S frame: R_WS = R_WB * R_BS\n")
        fout.write("# timestamp tx ty tz qx qy qz qw\n")
        for line in fin:
            line_s = line.strip()
            if not line_s or line_s.startswith("#"):
                continue
            parts = line_s.split()
            if len(parts) < 8:
                continue
            ts = parts[0]
            tx, ty, tz = parts[1], parts[2], parts[3]
            qx, qy, qz, qw = float(parts[4]), float(parts[5]), float(parts[6]), float(parts[7])
            
            # R_WB from GT
            R_WB = quat_xyzw_to_rotmat(np.array([qx, qy, qz, qw]))
            # R_WS = R_WB * R_BS
            R_WS = R_WB @ R_BS
            q_WS = rotmat_to_quat_xyzw(R_WS)
            
            fout.write(f"{ts} {tx} {ty} {tz} {q_WS[0]:.9f} {q_WS[1]:.9f} {q_WS[2]:.9f} {q_WS[3]:.9f}\n")
            rows_written += 1
    print(f"  Successfully wrote {rows_written} poses to {out_gt_s_path}")


def eval_rotations():
    from evo.core.trajectory import PoseTrajectory3D
    print("\n" + "=" * 80)
    print("  PART 1C: APE & RPE ROTATION EVALUATION (Estimator vs Constant-Orientation Null)")
    print("=" * 80)
    
    datasets = [
        ("MH_01 Clean", "data/MH_01_easy/estimated_trajectory_clean.txt", "data/MH_01_easy/groundtruth_tum.txt", "data/MH_01_easy/groundtruth_S_tum.txt"),
        ("V1_01 Clean", "data/V1_01_easy/estimated_trajectory_clean.txt", "data/V1_01_easy/groundtruth_tum.txt", "data/V1_01_easy/groundtruth_S_tum.txt"),
    ]
    
    results = {}
    
    for name, est_path, gt_path, gt_s_path in datasets:
        traj_gt = file_interface.read_tum_trajectory_file(gt_path)
        traj_gt_s = file_interface.read_tum_trajectory_file(gt_s_path)
        traj_est = file_interface.read_tum_trajectory_file(est_path)
        
        # 1. APE rotation against GT_S (SE3 aligned)
        ref_sync_s, est_sync_s = sync.associate_trajectories(traj_gt_s, traj_est, max_diff=0.01)
        est_aligned_s = copy.deepcopy(est_sync_s)
        est_aligned_s.align(ref_sync_s, correct_scale=False, correct_only_scale=False)
        
        ape_rot_est = metrics.APE(metrics.PoseRelation.rotation_angle_deg)
        ape_rot_est.process_data((ref_sync_s, est_aligned_s))
        est_ape_mean = float(ape_rot_est.get_statistic(metrics.StatisticsType.mean))
        est_ape_rmse = float(ape_rot_est.get_statistic(metrics.StatisticsType.rmse))
        
        # Null against GT_S
        n_poses = len(est_sync_s.timestamps)
        null_quat = np.zeros((n_poses, 4))
        null_quat[:, 0] = 1.0  # wxyz = [1, 0, 0, 0]
        null_traj_s = PoseTrajectory3D(est_sync_s.positions_xyz, null_quat, est_sync_s.timestamps)
        null_aligned_s = copy.deepcopy(null_traj_s)
        null_aligned_s.align(ref_sync_s, correct_scale=False, correct_only_scale=False)
        
        ape_rot_null = metrics.APE(metrics.PoseRelation.rotation_angle_deg)
        ape_rot_null.process_data((ref_sync_s, null_aligned_s))
        null_ape_mean = float(ape_rot_null.get_statistic(metrics.StatisticsType.mean))
        null_ape_rmse = float(ape_rot_null.get_statistic(metrics.StatisticsType.rmse))
        
        # 2. RPE rotation (delta 1s) against GT
        ref_sync, est_sync = sync.associate_trajectories(traj_gt, traj_est, max_diff=0.01)
        t_span = ref_sync.timestamps[-1] - ref_sync.timestamps[0]
        dt_s = t_span / (len(ref_sync.timestamps) - 1)
        delta_frames = int(round(1.0 / dt_s))
        
        rpe_rot_est = metrics.RPE(metrics.PoseRelation.rotation_angle_deg, delta=delta_frames, delta_unit=metrics.Unit.frames, all_pairs=False)
        rpe_rot_est.process_data((ref_sync, est_sync))
        est_rpe_mean = float(rpe_rot_est.get_statistic(metrics.StatisticsType.mean))
        est_rpe_rmse = float(rpe_rot_est.get_statistic(metrics.StatisticsType.rmse))
        
        # Null RPE rotation
        n_ref_poses = len(est_sync.timestamps)
        null_quat_rpe = np.zeros((n_ref_poses, 4))
        null_quat_rpe[:, 0] = 1.0
        null_traj_rpe = PoseTrajectory3D(est_sync.positions_xyz, null_quat_rpe, est_sync.timestamps)
        
        rpe_rot_null = metrics.RPE(metrics.PoseRelation.rotation_angle_deg, delta=delta_frames, delta_unit=metrics.Unit.frames, all_pairs=False)
        rpe_rot_null.process_data((ref_sync, null_traj_rpe))
        null_rpe_mean = float(rpe_rot_null.get_statistic(metrics.StatisticsType.mean))
        null_rpe_rmse = float(rpe_rot_null.get_statistic(metrics.StatisticsType.rmse))
        
        results[name] = {
            "est_ape_mean": est_ape_mean,
            "est_ape_rmse": est_ape_rmse,
            "null_ape_mean": null_ape_mean,
            "null_ape_rmse": null_ape_rmse,
            "est_rpe_mean": est_rpe_mean,
            "est_rpe_rmse": est_rpe_rmse,
            "null_rpe_mean": null_rpe_mean,
            "null_rpe_rmse": null_rpe_rmse,
        }
        
        print(f"\n--- {name} Rotation Results ---")
        print(f"  APE rot vs GT_S (SE3 aligned):")
        print(f"    Estimator: Mean = {est_ape_mean:.3f} deg, RMSE = {est_ape_rmse:.3f} deg")
        print(f"    Null:      Mean = {null_ape_mean:.3f} deg, RMSE = {null_ape_rmse:.3f} deg")
        print(f"  RPE rot 1s vs GT (Frame invariant):")
        print(f"    Estimator: Mean = {est_rpe_mean:.3f} deg, RMSE = {est_rpe_rmse:.3f} deg")
        print(f"    Null:      Mean = {null_rpe_mean:.3f} deg, RMSE = {null_rpe_rmse:.3f} deg")
    
    return results


if __name__ == "__main__":
    print("Running Stage 3C-2 Part 1 Convention & Rotation verification...")
    test_quaternion_hamilton()
    test_body_to_world_leveling()
    build_gt_s("data/MH_01_easy/groundtruth_tum.txt", "data/MH_01_easy/mav0/imu0/sensor.yaml", "data/MH_01_easy/groundtruth_S_tum.txt")
    build_gt_s("data/V1_01_easy/groundtruth_tum.txt", "data/V1_01_easy/mav0/imu0/sensor.yaml", "data/V1_01_easy/groundtruth_S_tum.txt")
    eval_rotations()
