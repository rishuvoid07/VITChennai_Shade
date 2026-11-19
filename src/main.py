#!/usr/bin/env python3
"""
main.py - Standalone Track 3 (Path Finder) Trajectory Estimator.

Stage 3B-2: Input and Degradation Robustness
  - CLI: python main.py <input> [output]; default output estimated_trajectory.txt
  - Input types: CSV, .zip (streaming via zipfile, never extracted), or directory
  - Robust parsing: optional header, delimiters (comma, semicolon, tab, whitespace),
    BOM and CRLF, first 7 columns used
  - Header or physics column mapping (gyro-first vs accel-first, m/s^2 vs g)
  - Lossless integer timestamp formatting with exact 9 decimals
  - Bad rows: duplicates repeat previous pose; unparsable/NaN/all-zero coast like blind rows
  - Gaps (dt > 1.5x nominal): integrated in nominal-dt sub-steps using mean of both sides, capped at 2s
  - Spikes: rejected if |a| > 5g or |gyro| > 35 rad/s or per-sample jump > threshold, replaced by last accepted
  - Stuck samples (streak >= 3): coasted as blind rows (Option B)
  - Pure Python floats & math in per-sample loop (no numpy/pandas)
  - Strict O(1) memory heap discipline (<= 8 MB)
  - Execution speed <= 10 ms per 1 s of IMU data
"""

import sys
import os
import io
import math
import zipfile

G_VAL = 9.81
G_GRAV = 9.80665
N_AUTO_DETECT_MAX = 2000
N_INIT_TILT_ROWS = 25
OUT_CHUNK_SIZE = 1000

# Tuned parameters from Stage 3B-1
DEFAULT_KP = 8.0
DEFAULT_KI = 0.02
DEFAULT_KP_BOOST = 10.0
DEFAULT_GATE = 3.0
DEFAULT_TAU_V = 1.0
DEFAULT_USE_ZUPT = True
DEFAULT_COAST_MODE = "M1"
DEFAULT_TAU_C = math.inf
DEFAULT_TAU_P = 40.0
DEFAULT_INIT_GYRO_BIAS = None

# Degradation robustness thresholds (Task 6)
MAX_A_MAG = 5.0 * G_GRAV      # 49.03325 m/s^2
MAX_G_MAG = 35.0             # 35 rad/s
MAX_DELTA_A = 10.0           # m/s^2 per sample jump
MAX_DELTA_G = 0.4            # rad/s per sample jump


def clean_zero(v, tol=1e-12):
    return 0.0 if abs(v) < tol else v


def format_timestamp(ts, is_integral, ts_unit):
    """
    Lossless timestamp formatting using integer arithmetic where possible.
    Outputs seconds with 9 decimal digits.
    """
    if is_integral:
        sign = ""
        val = ts
        if val < 0:
            sign = "-"
            val = -val

        if ts_unit == "ns":
            sec = val // 1000000000
            frac = val % 1000000000
            return f"{sign}{sec}.{frac:09d}"
        elif ts_unit == "us":
            sec = val // 1000000
            frac = (val % 1000000) * 1000
            return f"{sign}{sec}.{frac:09d}"
        elif ts_unit == "ms":
            sec = val // 1000
            frac = (val % 1000) * 1000000
            return f"{sign}{sec}.{frac:09d}"
        else:  # "s"
            return f"{sign}{val}.000000000"
    else:
        return f"{ts:.9f}"


def is_finite(x):
    return not (math.isnan(x) or math.isinf(x))


def quat_mult(q1, q2):
    # Hamiltonian product: [qx, qy, qz, qw]
    x1, y1, z1, w1 = q1
    x2, y2, z2, w2 = q2
    return (
        w1*x2 + x1*w2 + y1*z2 - z1*y2,
        w1*y2 - x1*z2 + y1*w2 + z1*x2,
        w1*z2 + x1*y2 - y1*x2 + z1*w2,
        w1*w2 - x1*x2 - y1*y2 - z1*z2
    )


def qrot(q, vx, vy, vz):
    # Rotates vector (vx, vy, vz) by quaternion q: q * v * q^*
    qx, qy, qz, qw = q
    tx = 2.0 * (qy*vz - qz*vy)
    ty = 2.0 * (qz*vx - qx*vz)
    tz = 2.0 * (qx*vy - qy*vx)
    return (
        vx + qw*tx + (qy*tz - qz*ty),
        vy + qw*ty + (qz*tx - qx*tz),
        vz + qw*tz + (qx*ty - qy*tx)
    )


def compute_median(vals):
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    else:
        return float(s[mid - 1] + s[mid]) * 0.5


def detect_delimiter(line):
    """Detect delimiter: comma, semicolon, tab, or whitespace."""
    if "," in line:
        return ","
    elif ";" in line:
        return ";"
    elif "\t" in line:
        return "\t"
    else:
        return None  # whitespace


def split_line(line, delim):
    line = line.strip()
    if delim is None:
        return line.split()
    return [p.strip() for p in line.split(delim)]


def is_gyro_col(name):
    name = name.lower()
    return any(k in name for k in ("w_", "gyro", "gx", "gy", "gz", "omega", "ang_vel", "rad"))


def is_accel_col(name):
    name = name.lower()
    return any(k in name for k in ("a_", "acc", "ax", "ay", "az", "lin_acc", "m s", "m/s"))


def open_input_stream(input_path):
    """
    Opens an input stream from a CSV file, .zip archive (streaming, no extraction),
    or directory. Returns (stream, zip_obj_or_None).
    """
    if zipfile.is_zipfile(input_path) or input_path.lower().endswith(".zip"):
        zf = zipfile.ZipFile(input_path, "r")
        candidates = []
        for n in zf.namelist():
            norm = n.replace("\\", "/").strip()
            if norm.endswith("/"):
                continue
            parts = norm.split("/")
            if any(p.startswith("__MACOSX") or p.startswith("._") for p in parts):
                continue
            if norm.lower().endswith(".csv"):
                candidates.append(n)

        target = None
        for c in candidates:
            c_norm = c.replace("\\", "/").strip()
            if c_norm == "imu0/data.csv" or c_norm.endswith("/imu0/data.csv"):
                target = c
                break

        if target is None:
            if len(candidates) == 1:
                target = candidates[0]

        if target is None:
            zf.close()
            sys.stderr.write(f"Error: Ambiguous or missing CSV inside zip archive: {input_path}\n")
            sys.exit(1)

        bio = zf.open(target, "r")
        buf = io.BufferedReader(bio, buffer_size=65536)
        stream = io.TextIOWrapper(buf, encoding="utf-8-sig", newline="")
        return stream, zf
    elif os.path.isdir(input_path):
        target = None
        candidates = []
        for root, dirs, files in os.walk(input_path):
            for f in files:
                norm = os.path.join(root, f).replace("\\", "/")
                parts = norm.split("/")
                if any(p.startswith("__MACOSX") or p.startswith("._") for p in parts):
                    continue
                if f.lower().endswith(".csv"):
                    candidates.append(os.path.join(root, f))
        for c in candidates:
            c_norm = c.replace("\\", "/")
            if c_norm.endswith("imu0/data.csv"):
                target = c
                break
        if target is None and len(candidates) == 1:
            target = candidates[0]
        if target is None:
            sys.stderr.write(f"Error: Ambiguous or missing CSV inside directory: {input_path}\n")
            sys.exit(1)
        stream = open(target, "r", encoding="utf-8-sig", newline="", buffering=65536)
        return stream, None
    else:
        stream = open(input_path, "r", encoding="utf-8-sig", newline="", buffering=65536)
        return stream, None


def parse_raw_row(line, delim, prev_ts_raw, median_dt_int, median_dt_s, is_integral_mode):
    """
    Parses a single row into:
      (ts_raw, is_integral, c1, c2, c3, c4, c5, c6, is_valid_numbers)
    Returns None if line is blank or comment line.
    """
    line = line.strip()
    if not line:
        return None
    if line.startswith("#"):
        return None

    parts = split_line(line, delim)
    if not parts:
        return None

    # Parse timestamp
    ts_str = parts[0]
    ts_raw = None
    is_integral = is_integral_mode
    try:
        if "." in ts_str:
            ts_raw = float(ts_str)
            is_integral = False
        else:
            ts_raw = int(ts_str)
            is_integral = True
    except (ValueError, TypeError):
        pass

    if ts_raw is None or not is_finite(ts_raw):
        if prev_ts_raw is not None:
            ts_raw = prev_ts_raw + (median_dt_int if is_integral_mode else median_dt_s)
            is_integral = is_integral_mode
        else:
            ts_raw = 0
            is_integral = True

    # Parse sensor values (use first 7 columns: parts[1:7])
    c = [float("nan")] * 6
    for i in range(6):
        col_idx = i + 1
        if col_idx < len(parts):
            try:
                val = float(parts[col_idx])
                if is_finite(val):
                    c[i] = val
            except (ValueError, TypeError):
                pass

    is_valid_numbers = all(is_finite(v) for v in c)
    return (ts_raw, is_integral, c[0], c[1], c[2], c[3], c[4], c[5], is_valid_numbers)


def auto_detect_and_init(buffered_rows, header_mapping=None):
    """
    Analyzes initial rows for:
      1. Timestamp unit (s, ms, us, ns) based on median positive dt
      2. Column order (gyro-first vs accel-first) and accel unit (m/s^2 vs g)
      3. Initial tilt quaternion from first 25 valid rows
      4. Initial gyro bias (0 unless 0.5s stillness test passes)
    """
    # 1. Timestamp unit
    dt_list = []
    for i in range(1, len(buffered_rows)):
        t_prev = buffered_rows[i-1][0]
        t_curr = buffered_rows[i][0]
        if t_curr > t_prev:
            dt_list.append(t_curr - t_prev)

    if dt_list:
        median_dt = compute_median(dt_list)
        if median_dt < 0.5:
            ts_unit = "s"
            ts_scale = 1.0
        elif median_dt < 500.0:
            ts_unit = "ms"
            ts_scale = 1e-3
        elif median_dt < 5e5:
            ts_unit = "us"
            ts_scale = 1e-6
        else:
            ts_unit = "ns"
            ts_scale = 1e-9
    else:
        # Fallback for single-row files based on magnitude
        first_ts = buffered_rows[0][0] if buffered_rows else 0
        if first_ts > 1e14:
            ts_unit = "ns"
            ts_scale = 1e-9
            median_dt = 5000000.0
        elif first_ts > 1e11:
            ts_unit = "us"
            ts_scale = 1e-6
            median_dt = 5000.0
        elif first_ts > 1e8:
            ts_unit = "ms"
            ts_scale = 1e-3
            median_dt = 5.0
        else:
            ts_unit = "s"
            ts_scale = 1.0
            median_dt = 0.005

    median_dt_s = median_dt * ts_scale

    # 2. Column mapping and accel unit
    # Compute triplet norms
    norm1_list = []
    norm2_list = []
    for row in buffered_rows:
        _, _, c1, c2, c3, c4, c5, c6, is_valid = row
        if is_valid:
            if not (c1 == 0.0 and c2 == 0.0 and c3 == 0.0 and c4 == 0.0 and c5 == 0.0 and c6 == 0.0):
                norm1_list.append(math.sqrt(c1*c1 + c2*c2 + c3*c3))
                norm2_list.append(math.sqrt(c4*c4 + c5*c5 + c6*c6))

    median_norm1 = compute_median(norm1_list) if norm1_list else 9.81
    median_norm2 = compute_median(norm2_list) if norm2_list else 0.0

    swap_cols = False
    accel_unit = "m/s^2"
    accel_scale = 1.0

    if header_mapping is not None:
        swap_cols = (header_mapping == "gyro_first")
        acc_norm = median_norm2 if swap_cols else median_norm1
        if 0.7 <= acc_norm <= 1.3:
            accel_unit = "g"
            accel_scale = G_GRAV
        else:
            accel_unit = "m/s^2"
            accel_scale = 1.0
    else:
        # Detect by physics on first up to 2000 usable rows
        trip1_ms2 = (7.0 <= median_norm1 <= 12.0)
        trip1_g   = (0.7 <= median_norm1 <= 1.3)
        trip2_ms2 = (7.0 <= median_norm2 <= 12.0)
        trip2_g   = (0.7 <= median_norm2 <= 1.3)

        if (trip2_ms2 or trip2_g) and not (trip1_ms2 or trip1_g):
            swap_cols = True
            accel_unit = "g" if trip2_g else "m/s^2"
            accel_scale = G_GRAV if trip2_g else 1.0
        elif (trip1_ms2 or trip1_g) and not (trip2_ms2 or trip2_g):
            swap_cols = False
            accel_unit = "g" if trip1_g else "m/s^2"
            accel_scale = G_GRAV if trip1_g else 1.0
        else:
            # Ambiguous: default order timestamp, accel xyz, gyro xyz
            swap_cols = False
            accel_unit = "m/s^2"
            accel_scale = 1.0

    sys.stderr.write(
        f"[Column Mapping] Mapping: {'gyro-first (swapped)' if swap_cols else 'accel-first'}, "
        f"Accel unit: {accel_unit} (scale={accel_scale:.5f}), "
        f"Timestamp unit: {ts_unit} (median_dt={median_dt_s*1000:.3f} ms)\n"
    )

    # 3. Filter valid rows for initial tilt & stillness
    valid_rows = []
    for row in buffered_rows:
        _, _, c1, c2, c3, c4, c5, c6, is_valid = row
        if not is_valid:
            continue
        if swap_cols:
            ax, ay, az = c4 * accel_scale, c5 * accel_scale, c6 * accel_scale
            gx, gy, gz = c1, c2, c3
        else:
            ax, ay, az = c1 * accel_scale, c2 * accel_scale, c3 * accel_scale
            gx, gy, gz = c4, c5, c6

        if ax == 0.0 and ay == 0.0 and az == 0.0 and gx == 0.0 and gy == 0.0 and gz == 0.0:
            continue
        valid_rows.append((ax, ay, az, gx, gy, gz))

    n_tilt = min(len(valid_rows), N_INIT_TILT_ROWS)
    if n_tilt == 0:
        mean_ax, mean_ay, mean_az = 0.0, 0.0, G_VAL
        q_init = (0.0, 0.0, 0.0, 1.0)
    else:
        mean_ax = sum(r[0] for r in valid_rows[:n_tilt]) / n_tilt
        mean_ay = sum(r[1] for r in valid_rows[:n_tilt]) / n_tilt
        mean_az = sum(r[2] for r in valid_rows[:n_tilt]) / n_tilt
        norm_a = math.sqrt(mean_ax*mean_ax + mean_ay*mean_ay + mean_az*mean_az)
        if norm_a < 1e-6:
            norm_a = 1e-6
        ux = mean_ax / norm_a
        uy = mean_ay / norm_a
        uz = mean_az / norm_a

        dot_uz = uz
        if dot_uz < -0.999999:
            q_init = (1.0, 0.0, 0.0, 0.0)
        else:
            qw = 1.0 + dot_uz
            qx = uy
            qy = -ux
            qz = 0.0
            nq = math.sqrt(qx*qx + qy*qy + qz*qz + qw*qw)
            q_init = (qx/nq, qy/nq, qz/nq, qw/nq)

    # 4. Stillness test over first 0.5s for initial gyro bias
    n_05s = max(5, int(round(0.5 / median_dt_s)))
    check_rows = valid_rows[:n_05s]
    still_init = (len(check_rows) >= 5)

    for r in check_rows:
        an = math.sqrt(r[0]*r[0] + r[1]*r[1] + r[2]*r[2])
        gn = math.sqrt(r[3]*r[3] + r[4]*r[4] + r[5]*r[5])
        if abs(an - G_GRAV) >= 0.3 or gn >= 0.05:
            still_init = False
            break

    if still_init:
        bgx = sum(r[3] for r in check_rows) / len(check_rows)
        bgy = sum(r[4] for r in check_rows) / len(check_rows)
        bgz = sum(r[5] for r in check_rows) / len(check_rows)
        gyro_bias = [bgx, bgy, bgz]
        sys.stderr.write(f"[Init] Stillness test PASSED (0.5s): gyro_bias=[{bgx:.6f}, {bgy:.6f}, {bgz:.6f}] rad/s\n")
    else:
        gyro_bias = [0.0, 0.0, 0.0]
        sys.stderr.write(f"[Init] Stillness test FAILED (motion detected): gyro_bias=[0, 0, 0]\n")

    return {
        "ts_unit": ts_unit,
        "ts_scale": ts_scale,
        "median_dt": median_dt,
        "median_dt_s": median_dt_s,
        "accel_scale": accel_scale,
        "accel_unit": accel_unit,
        "swap_cols": swap_cols,
        "gyro_bias": gyro_bias,
        "q_init": q_init,
        "mean_init_a": (mean_ax, mean_ay, mean_az),
    }


def step_filter(q, vx, vy, vz, px, py, pz, bias, ax, ay, az, gx, gy, gz, dt, kp, ki, kp_boost, gate, tau_v, is_boost, tau_p=DEFAULT_TAU_P, p_mean=None):
    anorm = math.sqrt(ax*ax + ay*ay + az*az)
    qx, qy, qz, qw = q

    # Estimated gravity reaction vector in body frame: R(q)^T * [0, 0, 1]
    gbx = 2.0 * (qx*qz - qy*qw)
    gby = 2.0 * (qy*qz + qx*qw)
    gbz = 1.0 - 2.0 * (qx*qx + qy*qy)

    if anorm > 1e-4:
        amx = ax / anorm
        amy = ay / anorm
        amz = az / anorm
    else:
        amx, amy, amz = 0.0, 0.0, 1.0

    # Error vector: e = cross(a_meas_unit, g_body_est_unit)
    ex = amy * gbz - amz * gby
    ey = amz * gbx - amx * gbz
    ez = amx * gby - amy * gbx

    if abs(anorm - G_VAL) < gate:
        kp_eff = (kp * kp_boost) if is_boost else kp
        ki_eff = ki
    else:
        kp_eff = 0.0
        ki_eff = 0.0

    corr_gx = gx - bias[0] + kp_eff * ex
    corr_gy = gy - bias[1] + kp_eff * ey
    corr_gz = gz - bias[2] + kp_eff * ez

    bias[0] -= ki_eff * ex * dt
    bias[1] -= ki_eff * ey * dt
    bias[2] -= ki_eff * ez * dt

    w_norm = math.sqrt(corr_gx*corr_gx + corr_gy*corr_gy + corr_gz*corr_gz)
    if w_norm > 1e-12:
        ha = 0.5 * w_norm * dt
        sha = math.sin(ha)
        cha = math.cos(ha)
        inv_w = sha / w_norm
        dq = (corr_gx * inv_w, corr_gy * inv_w, corr_gz * inv_w, cha)
        q_new = quat_mult(q, dq)
        nq = math.sqrt(q_new[0]*q_new[0] + q_new[1]*q_new[1] + q_new[2]*q_new[2] + q_new[3]*q_new[3])
        inv_nq = 1.0 / nq
        q = (q_new[0]*inv_nq, q_new[1]*inv_nq, q_new[2]*inv_nq, q_new[3]*inv_nq)

    awx, awy, awz = qrot(q, ax, ay, az)
    awz -= G_VAL

    if not math.isinf(tau_v) and tau_v > 0.0:
        leak = math.exp(-dt / tau_v)
        vx = (vx + awx * dt) * leak
        vy = (vy + awy * dt) * leak
        vz = (vz + awz * dt) * leak
    else:
        vx += awx * dt
        vy += awy * dt
        vz += awz * dt

    px += vx * dt
    py += vy * dt
    pz += vz * dt

    if not math.isinf(tau_p) and tau_p > 0.0 and p_mean is not None:
        alpha_ema = 1.0 - math.exp(-dt / (3.0 * tau_p))
        p_mean[0] += alpha_ema * (px - p_mean[0])
        p_mean[1] += alpha_ema * (py - p_mean[1])
        p_mean[2] += alpha_ema * (pz - p_mean[2])
        leak_p = math.exp(-dt / tau_p)
        px = p_mean[0] + (px - p_mean[0]) * leak_p
        py = p_mean[1] + (py - p_mean[1]) * leak_p
        pz = p_mean[2] + (pz - p_mean[2]) * leak_p

    return q, vx, vy, vz, px, py, pz


def main():
    args = sys.argv[1:]
    if len(args) < 1 or args[0] in ("-h", "--help"):
        help_msg = (
            "Usage: python main.py <input> [output] [options]\n\n"
            "Options:\n"
            "  --tau-v VAL         Velocity leaky integrator time constant [s] (default: 1.0)\n"
            "  --tau-p VAL         Position restoring EMA time constant [s] (default: 40.0, inf=off)\n"
            "  --kp VAL            Mahony proportional gain (default: 8.0)\n"
            "  --ki VAL            Mahony integral gain (default: 0.02)\n"
            "  --kp-boost VAL      Initial tilt leveling boost factor (default: 10.0)\n"
            "  --gate VAL          Accelerometer gating threshold [m/s^2] (default: 3.0)\n"
            "  --coast-mode MODE   Blackout coasting mode: M0, M1, M2 (default: M1)\n"
            "  --tau-c VAL         Coasting time constant [s] (default: inf)\n"
            "  --no-zupt           Disable Zero Velocity Updates (ZUPT)\n"
            "  --init-gyro-bias B  Initial gyro bias bx,by,bz [rad/s] (default: None, auto-detected)\n"
            "  -h, --help          Show this help message and exit\n"
        )
        if len(args) >= 1 and args[0] in ("-h", "--help"):
            sys.stdout.write(help_msg)
            sys.exit(0)
        else:
            sys.stderr.write(help_msg)
            sys.exit(1)

    input_path = args[0]
    output_path = "estimated_trajectory.txt"
    if len(args) >= 2 and not args[1].startswith("--"):
        output_path = args[1]

    def parse_float_opt(flag, env_name, default_val):
        for i in range(1, len(args)):
            if args[i] == flag and i + 1 < len(args):
                val_str = args[i + 1]
                return math.inf if val_str.lower() in ("inf", "none") else float(val_str)
        if env_name in os.environ:
            val_str = os.environ[env_name]
            return math.inf if val_str.lower() in ("inf", "none") else float(val_str)
        return default_val

    kp = parse_float_opt("--kp", "KP", DEFAULT_KP)
    ki = parse_float_opt("--ki", "KI", DEFAULT_KI)
    kp_boost = parse_float_opt("--kp-boost", "KP_BOOST", DEFAULT_KP_BOOST)
    gate = parse_float_opt("--gate", "GATE", DEFAULT_GATE)
    tau_v = parse_float_opt("--tau-v", "TAU_V", DEFAULT_TAU_V)
    tau_p = parse_float_opt("--tau-p", "TAU_P", DEFAULT_TAU_P)

    init_gyro_bias = DEFAULT_INIT_GYRO_BIAS
    for i in range(1, len(args)):
        if args[i] == "--init-gyro-bias" and i + 1 < len(args):
            parts = [float(x.strip()) for x in args[i + 1].split(",")]
            if len(parts) == 3:
                init_gyro_bias = parts
    if init_gyro_bias is None and "INIT_GYRO_BIAS" in os.environ:
        parts = [float(x.strip()) for x in os.environ["INIT_GYRO_BIAS"].split(",")]
        if len(parts) == 3:
            init_gyro_bias = parts

    def parse_str_opt(flag, env_name, default_val):
        for i in range(1, len(args)):
            if args[i] == flag and i + 1 < len(args):
                return args[i + 1].strip().upper()
        if env_name in os.environ:
            return os.environ[env_name].strip().upper()
        return default_val

    coast_mode = parse_str_opt("--coast-mode", "COAST_MODE", DEFAULT_COAST_MODE)
    tau_c = parse_float_opt("--tau-c", "TAU_C", DEFAULT_TAU_C)
    if coast_mode == "M2_INF":
        coast_mode = "M2"; tau_c = math.inf
    elif coast_mode == "M2_5":
        coast_mode = "M2"; tau_c = 5.0
    elif coast_mode == "M2_2":
        coast_mode = "M2"; tau_c = 2.0

    use_zupt = DEFAULT_USE_ZUPT
    if "--no-zupt" in args or os.environ.get("USE_ZUPT", "").lower() in ("0", "false", "no"):
        use_zupt = False

    # Open input stream
    stream, zf_obj = open_input_stream(input_path)

    # Detect delimiter and header
    header_mapping = None
    first_non_empty_line = None
    header_line = None
    first_data_line = None
    delim = None

    # Read until first non-empty line
    for raw_line in stream:
        line = raw_line.strip()
        if not line:
            continue
        first_non_empty_line = raw_line
        break

    if first_non_empty_line is None:
        sys.stderr.write("Error: input is empty.\n")
        if zf_obj: zf_obj.close()
        sys.exit(1)

    clean_first = first_non_empty_line.strip()

    # Determine if first_non_empty_line is a header or data line
    if clean_first.startswith("#"):
        header_line = clean_first
        # Scan forward for first non-comment line (the first data line)
        for raw_line in stream:
            c = raw_line.strip()
            if not c or c.startswith("#"):
                continue
            first_data_line = raw_line
            break
    else:
        # Check if first token is non-numeric (un-prefixed header)
        is_num = False
        for d in (",", ";", "\t", None):
            parts = clean_first.split() if d is None else [p.strip() for p in clean_first.split(d)]
            if parts:
                try:
                    float(parts[0])
                    is_num = True
                    break
                except ValueError:
                    pass
        if not is_num:
            header_line = clean_first
            for raw_line in stream:
                c = raw_line.strip()
                if not c or c.startswith("#"):
                    continue
                first_data_line = raw_line
                break
        else:
            first_data_line = first_non_empty_line

    # Parse header for column-mapping (using header's own delimiter)
    if header_line is not None:
        header_text = header_line.lstrip("#").strip()
        h_delim = detect_delimiter(header_line)
        cols = split_line(header_text, h_delim)
        if len(cols) >= 7:
            if all(is_gyro_col(cols[i]) for i in (1, 2, 3)) and all(is_accel_col(cols[i]) for i in (4, 5, 6)):
                header_mapping = "gyro_first"
            elif all(is_accel_col(cols[i]) for i in (1, 2, 3)) and all(is_gyro_col(cols[i]) for i in (4, 5, 6)):
                header_mapping = "accel_first"

    # Decide delimiter from first numeric data line, not header line; use header only if no numeric line exists
    if first_data_line is not None:
        delim = detect_delimiter(first_data_line)
    elif header_line is not None:
        delim = detect_delimiter(header_line)
    else:
        delim = None

    # Collect up to N_AUTO_DETECT_MAX raw data lines
    raw_data_lines = []
    if first_data_line is not None:
        raw_data_lines.append(first_data_line)

    for raw_line in stream:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        raw_data_lines.append(raw_line)
        if len(raw_data_lines) >= N_AUTO_DETECT_MAX:
            break

    if not raw_data_lines:
        sys.stderr.write("Error: no data rows found in input.\n")
        if zf_obj: zf_obj.close()
        sys.exit(1)

    # Function to parse raw_data_lines with a given delimiter
    def try_parse_lines(lines, d):
        rows = []
        integral_mode = True
        for l in lines:
            line_str = l.strip()
            if not line_str or line_str.startswith("#"):
                continue
            p = parse_raw_row(line_str, d, rows[-1][0] if rows else None, 5000000, 0.005, integral_mode)
            if p is not None:
                rows.append(p)
                if not p[1]:
                    integral_mode = False
        return rows, integral_mode

    # Parse with chosen delim
    buffered_rows, is_integral_mode = try_parse_lines(raw_data_lines, delim)

    # If parsing with chosen delimiter yields zero valid rows, retry with other delimiters
    if not any(r[8] for r in buffered_rows):
        for trial_d in (",", ";", "\t", None):
            if trial_d == delim:
                continue
            trial_rows, trial_integral = try_parse_lines(raw_data_lines, trial_d)
            if any(r[8] for r in trial_rows):
                delim = trial_d
                buffered_rows = trial_rows
                is_integral_mode = trial_integral
                break

    if not buffered_rows:
        sys.stderr.write("Error: no data rows found in input.\n")
        if zf_obj: zf_obj.close()
        sys.exit(1)

    # Auto detect
    cfg = auto_detect_and_init(buffered_rows, header_mapping)
    ts_unit = cfg["ts_unit"]
    ts_scale = cfg["ts_scale"]
    median_dt = cfg["median_dt"]
    median_dt_s = cfg["median_dt_s"]
    median_dt_int = int(round(median_dt))
    accel_scale = cfg["accel_scale"]
    swap_cols = cfg["swap_cols"]

    # Initialize filter state
    px, py, pz = 0.0, 0.0, 0.0
    p_mean = [0.0, 0.0, 0.0]
    vx, vy, vz = 0.0, 0.0, 0.0
    q = cfg["q_init"]
    if init_gyro_bias is not None:
        bias = list(init_gyro_bias)
        sys.stderr.write(f"[Init] Overriding gyro_bias with oracle: {bias}\n")
    else:
        bias = list(cfg["gyro_bias"])

    # Stillness rolling window (~0.4s)
    n_still_window = max(5, int(round(0.4 / median_dt_s)))
    ring_gx = [0.0] * n_still_window
    ring_gy = [0.0] * n_still_window
    ring_gz = [0.0] * n_still_window
    ring_still = [0] * n_still_window
    sum_gx = sum_gy = sum_gz = 0.0
    count_still = 0
    ring_idx = 0
    ring_filled = 0

    # Diagnostics counters
    count_blind = 0
    count_accel_gated = 0
    count_zupt_triggered = 0
    count_spikes = 0
    count_stuck = 0
    count_duplicates = 0
    count_bad_rows = 0
    count_gap_steps = 0

    t_start_sec = None
    prev_ts_raw = None
    prev_pose_str = None
    total_poses_written = 0

    # Last accepted measurements for spike rejection and gaps
    init_a = cfg["mean_init_a"]
    last_accepted_ax = init_a[0]
    last_accepted_ay = init_a[1]
    last_accepted_az = init_a[2]
    last_accepted_gx = bias[0]
    last_accepted_gy = bias[1]
    last_accepted_gz = bias[2]

    # Stuck sample tracker (raw values streak)
    prev_raw_ax = None
    prev_raw_ay = None
    prev_raw_az = None
    prev_raw_gx = None
    prev_raw_gy = None
    prev_raw_gz = None
    stuck_streak = 0

    out_buffer = []

    with open(output_path, "w", encoding="utf-8") as fout:
        fout.write("# estimated_trajectory.txt - TUM format\n")
        fout.write("# timestamp tx ty tz qx qy qz qw\n")

        # Generator that streams buffered rows first, then continues reading stream
        def row_stream():
            for r in buffered_rows:
                yield r
            buffered_rows.clear()

            for line in stream:
                line_str = line.strip()
                if not line_str or line_str.startswith("#"):
                    continue
                p = parse_raw_row(line, delim, prev_ts_raw, median_dt_int, median_dt_s, is_integral_mode)
                if p is not None:
                    yield p

        for row in row_stream():
            ts_raw, is_integral, c1, c2, c3, c4, c5, c6, is_valid_numbers = row

            if swap_cols:
                ax_raw, ay_raw, az_raw = c4 * accel_scale, c5 * accel_scale, c6 * accel_scale
                gx_raw, gy_raw, gz_raw = c1, c2, c3
            else:
                ax_raw, ay_raw, az_raw = c1 * accel_scale, c2 * accel_scale, c3 * accel_scale
                gx_raw, gy_raw, gz_raw = c4, c5, c6

            # Duplicate timestamp check: dt <= 0 (Task 4)
            if prev_ts_raw is not None:
                dt_raw = ts_raw - prev_ts_raw
                if dt_raw <= 0:
                    count_duplicates += 1
                    ts_s = format_timestamp(ts_raw, is_integral, ts_unit)
                    if prev_pose_str is not None:
                        out_buffer.append(f"{ts_s} {prev_pose_str}\n")
                    else:
                        qx_c = clean_zero(q[0]); qy_c = clean_zero(q[1]); qz_c = clean_zero(q[2]); qw_c = clean_zero(q[3])
                        out_buffer.append(f"{ts_s} 0.000000000 0.000000000 0.000000000 {qx_c:.9f} {qy_c:.9f} {qz_c:.9f} {qw_c:.9f}\n")
                    total_poses_written += 1
                    if len(out_buffer) >= OUT_CHUNK_SIZE:
                        fout.writelines(out_buffer)
                        out_buffer.clear()
                    continue

                dt = dt_raw * ts_scale
            else:
                dt = 0.0

            prev_ts_raw = ts_raw
            curr_t_sec = ts_raw * ts_scale
            if t_start_sec is None:
                t_start_sec = curr_t_sec

            # Check for blind row / all-zero or unparsable/NaN row (Task 4)
            is_zero_row = (
                is_valid_numbers and
                ax_raw == 0.0 and ay_raw == 0.0 and az_raw == 0.0 and
                gx_raw == 0.0 and gy_raw == 0.0 and gz_raw == 0.0
            )
            is_bad_row = (not is_valid_numbers) or is_zero_row

            if is_bad_row:
                if is_zero_row:
                    count_blind += 1
                else:
                    count_bad_rows += 1
                stuck_streak = 0
                # Coast like blind rows: hold orientation, leaky velocity, advance position
                if dt > 0.0:
                    if not math.isinf(tau_v) and tau_v > 0.0:
                        leak = math.exp(-dt / tau_v)
                        vx *= leak
                        vy *= leak
                        vz *= leak
                    px += vx * dt
                    py += vy * dt
                    pz += vz * dt
                    if not math.isinf(tau_p) and tau_p > 0.0:
                        alpha_ema = 1.0 - math.exp(-dt / (3.0 * tau_p))
                        p_mean[0] += alpha_ema * (px - p_mean[0])
                        p_mean[1] += alpha_ema * (py - p_mean[1])
                        p_mean[2] += alpha_ema * (pz - p_mean[2])
                        leak_p = math.exp(-dt / tau_p)
                        px = p_mean[0] + (px - p_mean[0]) * leak_p
                        py = p_mean[1] + (py - p_mean[1]) * leak_p
                        pz = p_mean[2] + (pz - p_mean[2]) * leak_p
            else:
                # Check stuck samples (Task 7): 6 identical non-zero values for >= 3 consecutive rows
                if (prev_raw_ax is not None and
                    ax_raw == prev_raw_ax and ay_raw == prev_raw_ay and az_raw == prev_raw_az and
                    gx_raw == prev_raw_gx and gy_raw == prev_raw_gy and gz_raw == prev_raw_gz):
                    stuck_streak += 1
                else:
                    stuck_streak = 1
                    prev_raw_ax = ax_raw; prev_raw_ay = ay_raw; prev_raw_az = az_raw
                    prev_raw_gx = gx_raw; prev_raw_gy = gy_raw; prev_raw_gz = gz_raw

                is_stuck = (stuck_streak >= 3)
                if is_stuck:
                    count_stuck += 1
                    # Option B (verified superior on 60s windows): coast as blind rows
                    if dt > 0.0:
                        if not math.isinf(tau_v) and tau_v > 0.0:
                            leak = math.exp(-dt / tau_v)
                            vx *= leak
                            vy *= leak
                            vz *= leak
                        px += vx * dt
                        py += vy * dt
                        pz += vz * dt
                        if not math.isinf(tau_p) and tau_p > 0.0:
                            alpha_ema = 1.0 - math.exp(-dt / (3.0 * tau_p))
                            p_mean[0] += alpha_ema * (px - p_mean[0])
                            p_mean[1] += alpha_ema * (py - p_mean[1])
                            p_mean[2] += alpha_ema * (pz - p_mean[2])
                            leak_p = math.exp(-dt / tau_p)
                            px = p_mean[0] + (px - p_mean[0]) * leak_p
                            py = p_mean[1] + (py - p_mean[1]) * leak_p
                            pz = p_mean[2] + (pz - p_mean[2]) * leak_p
                else:
                    # Spike detection (Task 6):
                    # Reject if |a| > 5g or |gyro| > 35 rad/s or per-sample jump exceeds thresholds
                    anorm = math.sqrt(ax_raw*ax_raw + ay_raw*ay_raw + az_raw*az_raw)
                    gnorm = math.sqrt(gx_raw*gx_raw + gy_raw*gy_raw + gz_raw*gz_raw)
                    da = max(abs(ax_raw - last_accepted_ax), abs(ay_raw - last_accepted_ay), abs(az_raw - last_accepted_az))
                    dg = max(abs(gx_raw - last_accepted_gx), abs(gy_raw - last_accepted_gy), abs(gz_raw - last_accepted_gz))

                    is_spike = (anorm > MAX_A_MAG) or (gnorm > MAX_G_MAG) or (da > MAX_DELTA_A) or (dg > MAX_DELTA_G)
                    if is_spike:
                        count_spikes += 1
                        use_ax = last_accepted_ax
                        use_ay = last_accepted_ay
                        use_az = last_accepted_az
                        use_gx = last_accepted_gx
                        use_gy = last_accepted_gy
                        use_gz = last_accepted_gz
                    else:
                        use_ax = ax_raw
                        use_ay = ay_raw
                        use_az = az_raw
                        use_gx = gx_raw
                        use_gy = gy_raw
                        use_gz = gz_raw
                        last_accepted_ax = use_ax
                        last_accepted_ay = use_ay
                        last_accepted_az = use_az
                        last_accepted_gx = use_gx
                        last_accepted_gy = use_gy
                        last_accepted_gz = use_gz

                    # Stillness / ZUPT tracking (O(1) rolling window)
                    is_sample_still = 1 if (abs(anorm - G_VAL) < 0.3 and gnorm < 0.05) else 0
                    sum_gx += use_gx - ring_gx[ring_idx]
                    sum_gy += use_gy - ring_gy[ring_idx]
                    sum_gz += use_gz - ring_gz[ring_idx]
                    count_still += is_sample_still - ring_still[ring_idx]
                    ring_gx[ring_idx] = use_gx
                    ring_gy[ring_idx] = use_gy
                    ring_gz[ring_idx] = use_gz
                    ring_still[ring_idx] = is_sample_still
                    ring_idx = (ring_idx + 1) % n_still_window
                    if ring_filled < n_still_window:
                        ring_filled += 1

                    is_window_still = (ring_filled == n_still_window and count_still == n_still_window) and use_zupt
                    if is_window_still:
                        count_zupt_triggered += 1
                        vx, vy, vz = 0.0, 0.0, 0.0
                        bias[0] += 0.01 * (sum_gx / n_still_window - bias[0])
                        bias[1] += 0.01 * (sum_gy / n_still_window - bias[1])
                        bias[2] += 0.01 * (sum_gz / n_still_window - bias[2])

                    if dt > 0.0:
                        t_elapsed = curr_t_sec - t_start_sec
                        is_boost = (t_elapsed < 2.0)

                        # Gap integration (Task 5): dt > 1.5 * nominal_dt
                        if dt > 1.5 * median_dt_s:
                            count_gap_steps += 1
                            dt_gap = min(dt, 2.0)
                            n_sub = max(1, int(round(dt_gap / median_dt_s)))
                            dt_sub = dt_gap / n_sub
                            mean_ax = 0.5 * (last_accepted_ax + use_ax)
                            mean_ay = 0.5 * (last_accepted_ay + use_ay)
                            mean_az = 0.5 * (last_accepted_az + use_az)
                            mean_gx = 0.5 * (last_accepted_gx + use_gx)
                            mean_gy = 0.5 * (last_accepted_gy + use_gy)
                            mean_gz = 0.5 * (last_accepted_gz + use_gz)

                            for _ in range(n_sub):
                                q, vx, vy, vz, px, py, pz = step_filter(
                                    q, vx, vy, vz, px, py, pz, bias,
                                    mean_ax, mean_ay, mean_az, mean_gx, mean_gy, mean_gz,
                                    dt_sub, kp, ki, kp_boost, gate, tau_v, is_boost,
                                    tau_p, p_mean
                                )

                            if dt > 2.0:
                                dt_rem = dt - 2.0
                                if not math.isinf(tau_v) and tau_v > 0.0:
                                    leak = math.exp(-dt_rem / tau_v)
                                    vx *= leak; vy *= leak; vz *= leak
                                px += vx * dt_rem; py += vy * dt_rem; pz += vz * dt_rem
                                if not math.isinf(tau_p) and tau_p > 0.0:
                                    alpha_ema = 1.0 - math.exp(-dt_rem / (3.0 * tau_p))
                                    p_mean[0] += alpha_ema * (px - p_mean[0])
                                    p_mean[1] += alpha_ema * (py - p_mean[1])
                                    p_mean[2] += alpha_ema * (pz - p_mean[2])
                                    leak_p = math.exp(-dt_rem / tau_p)
                                    px = p_mean[0] + (px - p_mean[0]) * leak_p
                                    py = p_mean[1] + (py - p_mean[1]) * leak_p
                                    pz = p_mean[2] + (pz - p_mean[2]) * leak_p
                        else:
                            # Normal single step
                            q, vx, vy, vz, px, py, pz = step_filter(
                                q, vx, vy, vz, px, py, pz, bias,
                                use_ax, use_ay, use_az, use_gx, use_gy, use_gz,
                                dt, kp, ki, kp_boost, gate, tau_v, is_boost,
                                tau_p, p_mean
                            )

            qx_c = clean_zero(q[0]); qy_c = clean_zero(q[1]); qz_c = clean_zero(q[2]); qw_c = clean_zero(q[3])
            px_c = clean_zero(px); py_c = clean_zero(py); pz_c = clean_zero(pz)
            prev_pose_str = f"{px_c:.9f} {py_c:.9f} {pz_c:.9f} {qx_c:.9f} {qy_c:.9f} {qz_c:.9f} {qw_c:.9f}"

            ts_s = format_timestamp(ts_raw, is_integral, ts_unit)
            out_buffer.append(f"{ts_s} {prev_pose_str}\n")
            total_poses_written += 1

            if len(out_buffer) >= OUT_CHUNK_SIZE:
                fout.writelines(out_buffer)
                out_buffer.clear()

        if out_buffer:
            fout.writelines(out_buffer)
            out_buffer.clear()

    if zf_obj:
        zf_obj.close()
    try:
        stream.close()
    except Exception:
        pass

    sys.stderr.write(f"Done: {total_poses_written} poses written to {output_path}\n")
    sys.stderr.write(
        f"[Stats] Blind rows: {count_blind}, Bad/NaN rows: {count_bad_rows}, Duplicates: {count_duplicates}, "
        f"Spikes rejected: {count_spikes}, Stuck coasted: {count_stuck}, Gaps bridged: {count_gap_steps}, "
        f"Accel gated: {count_accel_gated}, ZUPT triggers: {count_zupt_triggered}\n"
    )


if __name__ == "__main__":
    main()
