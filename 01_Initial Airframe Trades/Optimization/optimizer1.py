import subprocess
import time
import os
import numpy as np
from scipy.optimize import differential_evolution

# --- Config -------------------------------------------------------------
VSP_EXE = r"C:\Users\Jackson\Desktop\ZZ_Software Downloads\OpenVSP-3.46.0-win64\vsp.exe"
RESULTS_CSV = "Results.csv"
LOG_CSV = "opt_history.csv"

# --- Global counters ----------------------------------------------------
eval_counter = 0
best_obj_so_far = -np.inf
best_x_so_far = None
prev_obj = None
prev_best_obj = -np.inf
prev_iter_obj = None
stagnation_counter = 0
STAGNATION_THRESHOLD = 5
STAGNATION_DELTA = 0.01
t_start = time.time()

# --- Initialize log file ------------------------------------------------
with open(LOG_CSV, "w") as f:
    f.write(
        "iter,elapsed_s,elapsed_min,"
        "span_mm,sweep_deg,xloc_mm,taper,tip_mm,ctrl_frac,"
        "raw_LD,penalties,final_obj,alpha_at_peak,L_over_D_all,iter_improvement\n"
    )

# --- DES template -------------------------------------------------------
DES_TEMPLATE = """\
ZVZTXUKAZWE:Lwing:XSec_1:Span: {span}
QTIUMVPVMNM:Lwing:XSec_1:Sweep: {sweep}
QDYUWWIMJJA:Lwing:XSec_1:Taper: {taper}
IQQQXPRMWKO:Lwing:XSec_1:Tip_Chord: {tip}
VEBCTUVXEVB:Lwing:XForm:X_Rel_Location: {xloc}
EZZPYZAMUNE:Lwing:SS_Control_1:Length_C_Start: {ctrl}
JOOKRGHFGUK:Rwing:SS_Control_1:Length_C_Start: {ctrl}
QSAPUXPYQWU:Rwing:XForm:X_Rel_Location: {xloc}
FLPOVAIKYMN:Rwing:XSec_1:Span: {span}
OELVSBZPUKI:Rwing:XSec_1:Sweep: {sweep}
WETEDEKPMBU:Rwing:XSec_1:Taper: {taper}
UQYSYUAIZXN:Rwing:XSec_1:Tip_Chord: {tip}
"""

# --- Write DES from design vector --------------------------------------
def write_des_from_x(x, des_path="current.des"):
    span, sweep, xloc, taper, tip, ctrl = x
    NUM_DES_VARS = 12
    with open(des_path, "w") as f:
        f.write(f"{NUM_DES_VARS}\n")
        f.write(DES_TEMPLATE.format(
            span=span, sweep=sweep, xloc=xloc,
            taper=taper, tip=tip, ctrl=ctrl
        ))

# --- Update geometry ----------------------------------------------------
def update_geometry_from_x(x):
    write_des_from_x(x, "current.des")
    subprocess.run(
        [VSP_EXE, "-script", "update_geom.vspscript"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

# --- Run VSPAERO --------------------------------------------------------
def run_vspaero():
    if os.path.exists(RESULTS_CSV):
        os.remove(RESULTS_CSV)

    start = time.time()
    subprocess.run(
        [VSP_EXE, "-script", "cruise.vspscript"],
        capture_output=True,
        text=True
    )
    elapsed = time.time() - start
    print(f"VSPAERO run completed in {elapsed:.2f}s")

    if not os.path.exists(RESULTS_CSV) or os.path.getsize(RESULTS_CSV) == 0:
        raise RuntimeError("VSPAERO did not produce a valid Results.csv")

# --- Extract L/D --------------------------------------------------------
def extract_ld_all(results_path: str):
    # Hard-coded alpha band
    alphas = np.array([2, 4, 6, 8, 10, 12, 14, 16])

    with open(results_path, "r") as f:
        rows = [line.strip().split(",") for line in f if line.strip()]

    ld_row = next((row for row in rows if row[0].strip() == "L_D"), None)
    if ld_row is None:
        return 0.001, None, None, alphas

    ld = np.array([float(x) for x in ld_row[1:1 + len(alphas)]])
    ld = -ld  # VSPAERO convention
    ld = np.clip(ld, 0.0, 17.5)  # cap at 17.5

    # Best contiguous band of length 4
    WINDOW = 4
    best_score = -np.inf
    best_idx = None
    for i in range(len(ld) - WINDOW + 1):
        band = ld[i:i + WINDOW]
        score = band.mean() - 0.2 * band.std()
        if score > best_score:
            best_score = score
            best_idx = i

    center_alpha = alphas[best_idx + WINDOW // 2] if best_idx is not None else None
    return best_score, center_alpha, ld, alphas

# --- Evaluate design ---------------------------------------------------
def evaluate_design(x):
    global eval_counter, best_obj_so_far, best_x_so_far, prev_obj, prev_best_obj, prev_iter_obj

    eval_counter += 1
    span, sweep, xloc, taper, tip, ctrl = x
    elapsed_s = time.time() - t_start
    elapsed_min = elapsed_s / 60.0
    prev_str = "N/A" if prev_obj is None else f"{prev_obj:.6f}"

    sweep_rad = np.radians(sweep)
    trailing_edge_x = xloc + np.sin(sweep_rad) * span + tip

    # Soft trailing-edge penalty
    soft_penalty = 0.0
    if trailing_edge_x > 630.0:
        excess = trailing_edge_x - 630.0
        soft_penalty = 0.002 * excess ** 2

    # Update geometry & run VSPAERO
    update_geometry_from_x(x)
    try:
        run_vspaero()
    except RuntimeError:
        print("VSPAERO failed; returning minimal objective")
        return 0.001

    raw_ld, best_alpha, ld_arr, alphas = extract_ld_all(RESULTS_CSV)
    if raw_ld is None or not np.isfinite(raw_ld):
        raw_ld = 0.001
    prev_obj = raw_ld

    # Span penalty for balanced optimization (shorter = more agile)
    span_penalty = (span - 400.0) * 0.3
    span_penalty = np.clip(span_penalty, -10.0, 10.0)

    # Weighted objective: efficiency vs agility
    efficiency_factor = 0.7
    agility_factor = 0.3
    obj = efficiency_factor * raw_ld - agility_factor * span_penalty - soft_penalty
    obj = max(obj, 0.001)

    # Iteration improvement tracking
    iter_improvement = 0.0 if prev_iter_obj is None else obj - prev_iter_obj
    prev_iter_obj = obj

    # Track best overall
    if obj > best_obj_so_far:
        best_obj_so_far = obj
        best_x_so_far = x.copy()

    ld_min = np.min(ld_arr) if ld_arr is not None else np.nan
    ld_max = np.max(ld_arr) if ld_arr is not None else np.nan
    alpha_str = "N/A" if best_alpha is None else f"{best_alpha:.2f}"

    print(f"\n--- Iteration {eval_counter} ---")
    print(f"t = {elapsed_s:.1f}s ({elapsed_min:.1f} min)")
    print(
        f"Design: span={span:.1f} mm, sweep={sweep:.1f} deg, xloc={xloc:.1f} mm, taper={taper:.3f}, tip={tip:.1f} mm, ctrl={ctrl:.3f}")
    print(f"Raw L/D = {raw_ld:.6f}, Soft penalty = {soft_penalty:.6f}, Span penalty = {span_penalty:.6f}")
    print(f"Final objective = {obj:.6f}, Best so far = {best_obj_so_far:.6f}, Peak α = {alpha_str} deg")
    print(f"L/D range = {ld_min:.2f}–{ld_max:.2f}, Improvement vs last = {iter_improvement:.6f}")

    ld_str = ";".join(f"{v:.6f}" for v in ld_arr) if ld_arr is not None else ""
    with open(LOG_CSV, "a") as f:
        f.write(f"{eval_counter},{elapsed_s:.2f},{elapsed_min:.3f},"
                f"{span:.3f},{sweep:.3f},{xloc:.3f},{taper:.5f},{tip:.5f},{ctrl:.5f},"
                f"{raw_ld:.6f},{soft_penalty+span_penalty:.6f},{obj:.6f},{alpha_str},{ld_str},{iter_improvement:.6f}\n")

    return -obj

# --- Convergence callback ------------------------------------------------
def convergence_callback(xk, convergence):
    global stagnation_counter, prev_best_obj

    improvement = best_obj_so_far - prev_best_obj
    if improvement < STAGNATION_DELTA:
        stagnation_counter += 1
        if stagnation_counter >= STAGNATION_THRESHOLD:
            print("Optimizer stagnating — perturbing best design slightly")
            perturb = np.random.normal(scale=5.0, size=len(xk))
            xk += perturb
            stagnation_counter = 0
    else:
        stagnation_counter = 0

    prev_best_obj = best_obj_so_far
    print(f"Generation complete. Best objective so far: {best_obj_so_far:.6f}, Convergence metric: {convergence:.4f}")

# --- Driver ------------------------------------------------------------
if __name__ == "__main__":
    baseline = [400.0, 25.0, 320.0, 0.833333, 125.0, 0.22]
    bounds = [
        (275.0, 650.0),  # span
        (0.0, 45.0),     # sweep
        (220.0, 340.0),  # xloc
        (0.5, 1.0),      # taper
        (120.0, 125.0),  # tip chord
        (0.22, 0.22),    # control fraction
    ]

    print("Baseline evaluation:")
    _ = evaluate_design(baseline)

    print("\nStarting optimization...\n")
    result = differential_evolution(
        evaluate_design,
        bounds,
        maxiter=20,
        popsize=15,
        polish=False,
        tol=1e-2,
        callback=convergence_callback
    )

    total_s = time.time() - t_start
    total_min = total_s / 60.0

    print("\nOptimization complete.")
    print(f"Total evaluations: {eval_counter}")
    print(f"Total time: {total_s:.1f}s ({total_min:.2f} min)")
    print("Best design vector x* =", result.x)
    print("Best objective =", -result.fun)
    print("Best found during run =", best_obj_so_far, "at x =", best_x_so_far)
