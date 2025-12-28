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
best_ld_so_far = -np.inf
best_x_so_far = None
prev_ld = None
t_start = time.time()

# --- Initialize log file ------------------------------------------------
with open(LOG_CSV, "w") as f:
    f.write(
        "iter,elapsed_s,elapsed_min,"
        "span_mm,sweep_deg,xloc_mm,taper,tip_mm,ctrl_frac,"
        "mean_L_over_D,best_mean_L_over_D,alpha_at_peak,L_over_D_all\n"
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
    result = subprocess.run(
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
    """
    Returns:
        obj_ld     : scalar objective (best contiguous-band mean L/D)
        best_alpha : center alpha of best band (for reporting)
        ld         : full L/D array
        alphas     : alpha array
    """

    # Fixed alpha sweep
    alphas = np.array([0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20])

    # --- Read CSV ---
    with open(results_path, "r") as f:
        rows = [line.strip().split(",") for line in f if line.strip()]

    # --- Locate L/D row ---
    ld_row = None
    for row in rows:
        if row[0].strip() == "L_D":
            ld_row = row
            break

    if ld_row is None:
        return -1e6, None, None, alphas

    # --- Parse & fix sign ---
    ld = np.array([float(x) for x in ld_row[1:1 + len(alphas)]])
    ld = -ld  # VSPAERO convention

    # --- Valid alpha range ---
    valid_mask = (alphas >= 4) & (alphas <= 14)
    alphas_v = alphas[valid_mask]
    ld_v = ld[valid_mask]

    # --- Hard sanity checks ---
    if (
        len(ld_v) < 5 or
        np.any(~np.isfinite(ld_v)) or
        np.any(ld_v < 0.0) or
        np.any(ld_v > 30.0)
    ):
        return -1e6, None, ld, alphas

    # --- Best contiguous band metric ---
    WINDOW = 6  # e.g. 3 points = 4° wide
    best_score = -np.inf
    best_idx = None

    for i in range(len(ld_v) - WINDOW + 1):
        band = ld_v[i:i + WINDOW]
        score = band.mean()

        if score > best_score:
            best_score = score
            best_idx = i

    # Representative alpha = center of band
    center_alpha = alphas_v[best_idx + WINDOW // 2]

    return best_score, center_alpha, ld, alphas


# --- Objective function ------------------------------------------------
def evaluate_design(x):
    global eval_counter, best_ld_so_far, best_x_so_far, prev_ld

    eval_counter += 1
    span, sweep, xloc, taper, tip, ctrl = x
    elapsed_s = time.time() - t_start
    elapsed_min = elapsed_s / 60.0
    prev_str = "N/A" if prev_ld is None else f"{prev_ld:.6f}"

    # --- Trailing edge constraint ---
    sweep_rad = np.radians(sweep)
    trailing_edge_x = xloc + np.sin(sweep_rad) * span + tip
    if trailing_edge_x > 630.0:
        print(f"Constraint violated: trailing_edge_x = {trailing_edge_x:.2f} > 630 mm")
        return 1e6

    print(f"\n--- Iteration {eval_counter} ---")
    print(
        f"t = {elapsed_s:6.1f}s ({elapsed_min:4.1f} min) | "
        f"prev mean L/D = {prev_str}, best = {best_ld_so_far:.6f}\n"
        f"Design: span={span:.1f} mm, sweep={sweep:.1f} deg, "
        f"xloc={xloc:.1f} mm, taper={taper:.3f}, "
        f"tip={tip:.1f} mm, ctrl={ctrl:.3f}"
    )

    update_geometry_from_x(x)
    run_vspaero()

    obj_ld, best_alpha, ld_arr, alphas = extract_ld_all(RESULTS_CSV)
    prev_ld = obj_ld

    if obj_ld > best_ld_so_far:
        best_ld_so_far = obj_ld
        best_x_so_far = x.copy()

    print(
        f"Result: mean L/D (4–14°) = {obj_ld:.6f}, "
        f"peak at alpha = {best_alpha:.2f} deg; "
        f"best so far = {best_ld_so_far:.6f}"
    )

    ld_str = ";".join(f"{v:.6f}" for v in ld_arr)

    with open(LOG_CSV, "a") as f:
        f.write(
            f"{eval_counter},{elapsed_s:.2f},{elapsed_min:.3f},"
            f"{span:.3f},{sweep:.3f},{xloc:.3f},{taper:.5f},"
            f"{tip:.3f},{ctrl:.5f},"
            f"{obj_ld:.6f},{best_ld_so_far:.6f},{best_alpha:.2f},{ld_str}\n"
        )

    return -obj_ld  # DE minimizes

# --- Driver ------------------------------------------------------------
if __name__ == "__main__":
    baseline = [400.0, 25.0, 320.0, 0.833333, 125.0, 0.22]

    bounds = [
        (275.0, 650.0),  # span
        (0.0, 45.0),     # sweep
        (220.0, 340.0),  # xloc
        (0.5, 1.0),      # taper
        (120.0, 125.0),  # tip chord
        (0.22, 0.22),    # control chord fraction
    ]

    print("Baseline evaluation:")
    _ = evaluate_design(baseline)

    print("\nStarting optimization...\n")
    result = differential_evolution(
        evaluate_design,
        bounds,
        maxiter=20,
        popsize=10,
        polish=False,
        tol=1e-2,
    )

    total_s = time.time() - t_start
    total_min = total_s / 60.0

    print("\nOptimization complete.")
    print(f"Total evaluations: {eval_counter}")
    print(f"Total time: {total_s:.1f}s ({total_min:.2f} min)")
    print("Best design vector x* =", result.x)
    print("Best mean L/D =", -result.fun)
    print("Best found during run =", best_ld_so_far, "at x =", best_x_so_far)
