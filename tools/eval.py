#!/usr/bin/env python3
"""
eval.py - Evaluate estimated trajectory against ground truth using evo.

Track 3 Evaluation Spec:
  - Primary metrics:
      * ATE RMSE (Absolute Trajectory Error, translation part) with SE(3) Umeyama alignment (evo -a)
      * ATE RMSE unaligned
      * RPE RMSE (Relative Pose Error, translation part, delta = 1 s) with SE(3) alignment
      * RPE RMSE unaligned
  - Checkpoint errors:
      * Aligned position error at t = 10, 30, 60, 90, 115 s and at the last frame
  - Input compatibility:
      * Works directly with TUM-format ground truth (e.g. groundtruth_tum.txt)
      * Works with raw EuRoC ground truth (state_groundtruth_estimate0/data.csv) by auto-converting

Usage:
  python tools/eval.py <estimated_trajectory.txt> <groundtruth_tum.txt | state_groundtruth.csv>
"""

import sys
import os
import copy
import tempfile
import numpy as np

try:
    from evo.tools import file_interface
    from evo.core import sync, metrics
except ImportError:
    print("ERROR: 'evo' package not found. Install with: pip install evo", file=sys.stderr)
    sys.exit(1)


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def is_euroc_groundtruth(path):
    """Checks if the file is a 17-column EuRoC ground truth CSV."""
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",")
            return len(parts) >= 16
    return False


def convert_euroc_gt_to_tum(fin_path, fout_path):
    """Converts 17-column EuRoC ground truth CSV to TUM format."""
    count = 0
    with open(fin_path, "r", encoding="utf-8-sig") as fin, open(fout_path, "w", encoding="utf-8") as fout:
        fout.write("# ground truth converted from EuRoC format\n")
        fout.write("# timestamp tx ty tz qx qy qz qw\n")
        for line in fin:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 8:
                continue
            ts_ns = int(parts[0])
            sec = ts_ns // 1000000000
            frac = ts_ns % 1000000000
            ts_str = f"{sec}.{frac:09d}"
            px, py, pz = parts[1], parts[2], parts[3]
            qw, qx, qy, qz = parts[4], parts[5], parts[6], parts[7]
            fout.write(f"{ts_str} {px} {py} {pz} {qx} {qy} {qz} {qw}\n")
            count += 1
    return count


def main():
    if len(sys.argv) != 3:
        die(f"Usage: python {sys.argv[0]} <estimated_trajectory.txt> <groundtruth.txt/.csv>")

    est_path = sys.argv[1]
    gt_path = sys.argv[2]

    if not os.path.isfile(est_path):
        die(f"Estimated trajectory not found: {est_path}")
    if not os.path.isfile(gt_path):
        die(f"Ground truth file not found: {gt_path}")

    temp_gt_tum = None
    if is_euroc_groundtruth(gt_path):
        fd, temp_gt_tum = tempfile.mkstemp(suffix="_gt.tum")
        os.close(fd)
        n = convert_euroc_gt_to_tum(gt_path, temp_gt_tum)
        print(f"[eval.py] Detected EuRoC ground truth CSV; converted {n} rows to {temp_gt_tum}")
        tum_gt_path = temp_gt_tum
    else:
        tum_gt_path = gt_path

    try:
        traj_ref = file_interface.read_tum_trajectory_file(tum_gt_path)
        traj_est = file_interface.read_tum_trajectory_file(est_path)
    except Exception as e:
        die(f"Failed to load trajectories: {e}")
    finally:
        if temp_gt_tum and os.path.exists(temp_gt_tum):
            try:
                os.unlink(temp_gt_tum)
            except OSError:
                pass

    # Synchronize and associate poses
    traj_ref_sync, traj_est_sync = sync.associate_trajectories(traj_ref, traj_est, max_diff=0.01)
    n_associated = len(traj_ref_sync.timestamps)
    if n_associated == 0:
        die("Zero poses could be associated between trajectory and ground truth (check timestamp units).")

    # Unaligned data tuple
    data_unaligned = (traj_ref_sync, traj_est_sync)

    # 1. Unaligned ATE
    ape_metric_unaligned = metrics.APE(metrics.PoseRelation.translation_part)
    ape_metric_unaligned.process_data(data_unaligned)
    stats_ate_unaligned = ape_metric_unaligned.get_all_statistics()

    # 2. SE(3) Umeyama aligned
    traj_est_aligned = copy.deepcopy(traj_est_sync)
    has_alignment = True
    try:
        traj_est_aligned.align(traj_ref_sync, correct_scale=False)
        data_aligned = (traj_ref_sync, traj_est_aligned)
        ape_metric_aligned = metrics.APE(metrics.PoseRelation.translation_part)
        ape_metric_aligned.process_data(data_aligned)
        stats_ate_aligned = ape_metric_aligned.get_all_statistics()
    except Exception as e:
        print(f"[WARN] SE(3) alignment failed ({e}); falling back to unaligned.")
        traj_est_aligned = copy.deepcopy(traj_est_sync)
        data_aligned = data_unaligned
        stats_ate_aligned = stats_ate_unaligned
        has_alignment = False

    # 3. RPE (delta = 1 s or capped to trajectory length)
    t_span = traj_ref_sync.timestamps[-1] - traj_ref_sync.timestamps[0]
    dt_s = t_span / (n_associated - 1) if n_associated > 1 else 0.005
    nominal_delta_frames = max(1, int(round(1.0 / dt_s)))
    delta_frames = min(nominal_delta_frames, max(1, n_associated - 1))

    try:
        rpe_metric_unaligned = metrics.RPE(
            metrics.PoseRelation.translation_part,
            delta=delta_frames,
            delta_unit=metrics.Unit.frames,
            all_pairs=False
        )
        rpe_metric_unaligned.process_data(data_unaligned)
        stats_rpe_unaligned = rpe_metric_unaligned.get_all_statistics()
    except Exception as e:
        stats_rpe_unaligned = {"rmse": 0.0}

    try:
        rpe_metric_aligned = metrics.RPE(
            metrics.PoseRelation.translation_part,
            delta=delta_frames,
            delta_unit=metrics.Unit.frames,
            all_pairs=False
        )
        rpe_metric_aligned.process_data(data_aligned)
        stats_rpe_aligned = rpe_metric_aligned.get_all_statistics()
    except Exception as e:
        stats_rpe_aligned = {"rmse": 0.0}

    # 4. Checkpoint Position Errors
    t_start = traj_ref_sync.timestamps[0]
    checkpoint_times = [10.0, 30.0, 60.0, 90.0, 115.0, 120.0, 150.0, 170.0]
    checkpoint_results = []

    for tt in checkpoint_times:
        target_ts = t_start + tt
        if target_ts > traj_ref_sync.timestamps[-1]:
            continue
        idx = int((np.abs(traj_ref_sync.timestamps - target_ts)).argmin())
        actual_t = traj_ref_sync.timestamps[idx] - t_start
        err_vec_al = traj_est_aligned.positions_xyz[idx] - traj_ref_sync.positions_xyz[idx]
        err_mag_al = float(np.linalg.norm(err_vec_al))
        err_vec_un = traj_est_sync.positions_xyz[idx] - traj_ref_sync.positions_xyz[idx]
        err_mag_un = float(np.linalg.norm(err_vec_un))
        checkpoint_results.append((tt, actual_t, err_mag_al, err_mag_un))

    # Last frame error
    err_last_vec_al = traj_est_aligned.positions_xyz[-1] - traj_ref_sync.positions_xyz[-1]
    last_err_mag_al = float(np.linalg.norm(err_last_vec_al))
    err_last_vec_un = traj_est_sync.positions_xyz[-1] - traj_ref_sync.positions_xyz[-1]
    last_err_mag_un = float(np.linalg.norm(err_last_vec_un))
    last_actual_t = traj_ref_sync.timestamps[-1] - t_start

    # Final 5-second blind window (T - 5.0s to T)
    blind_results = None
    if t_span >= 7.0:
        ts_blind_start = traj_ref_sync.timestamps[-1] - 5.0
        idx_b_start = int((np.abs(traj_ref_sync.timestamps - ts_blind_start)).argmin())
        actual_t_b_start = traj_ref_sync.timestamps[idx_b_start] - t_start
        err_b_start = float(np.linalg.norm(traj_est_aligned.positions_xyz[idx_b_start] - traj_ref_sync.positions_xyz[idx_b_start]))
        blind_results = (actual_t_b_start, err_b_start, last_actual_t, last_err_mag_al)

    # Report
    print("\n" + "="*65)
    print("  TRACK 3 TRAJECTORY EVALUATION REPORT (evo)")
    print("="*65)
    print(f"Estimated Trajectory:  {est_path}")
    print(f"Ground Truth File:     {gt_path}")
    print(f"Associated Samples:    {n_associated} across {t_span:.3f} s")
    print(f"RPE Delta:             {delta_frames} frames (~{delta_frames*dt_s:.3f} s)")
    print("-" * 65)
    print("PRIMARY METRICS:")
    align_label = "SE(3) aligned" if has_alignment else "SE(3) fallback to unaligned"
    print(f"  ATE RMSE ({align_label}):  {stats_ate_aligned['rmse']:.6f} m  ({stats_ate_aligned['rmse']*100.0:.2f} cm)")
    print(f"  ATE RMSE (unaligned):      {stats_ate_unaligned['rmse']:.6f} m  ({stats_ate_unaligned['rmse']*100.0:.2f} cm)")
    print(f"  RPE RMSE ({align_label}):  {stats_rpe_aligned['rmse']:.6f} m  ({stats_rpe_aligned['rmse']*100.0:.2f} cm)")
    print(f"  RPE RMSE (unaligned):      {stats_rpe_unaligned['rmse']:.6f} m  ({stats_rpe_unaligned['rmse']*100.0:.2f} cm)")
    print("-" * 65)
    print("POSITION ERROR AT KEY CHECKPOINTS [Aligned | Unaligned]:")
    if checkpoint_results:
        for tt, actual_t, err_al, err_un in checkpoint_results:
            print(f"  t = {tt:5.1f} s (act {actual_t:6.3f} s):  Aligned: {err_al:9.4f} m | Unaligned: {err_un:9.4f} m")
    else:
        print("  (Sequence duration < 10 s; no 10-170 s checkpoints available)")
    print(f"  Last frame (act {last_actual_t:6.3f} s):  Aligned: {last_err_mag_al:9.4f} m | Unaligned: {last_err_mag_un:9.4f} m")
    if blind_results:
        print("-" * 65)
        print("FINAL 5-SECOND BLIND WINDOW (SENSOR FAILURE):")
        print(f"  Blind start (t = {blind_results[0]:6.3f} s): {blind_results[1]:.6f} m  ({blind_results[1]*100.0:.2f} cm)")
        print(f"  Blind end   (t = {blind_results[2]:6.3f} s): {blind_results[3]:.6f} m  ({blind_results[3]*100.0:.2f} cm)")
    print("="*65 + "\n")


if __name__ == "__main__":
    main()
