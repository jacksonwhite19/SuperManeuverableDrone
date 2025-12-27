import subprocess
import time
import os
import csv
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
        "max_L_over_D,best_L_over_D,L_over_D_all\n"
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
            span=span, sweep=sweep, xloc=xloc, taper=taper, tip=tip, ctrl=ctrl
        ))

# --- Update geometry ----------------------------------------------------
def update_geometry_from_x(x):
    start = time.time()
    write_des_from_x(x, "current.des")
    elapsed = time.time() - start
    # print(f"Geometry written in {elapsed:.2f}s")
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

    if result.stdout:
        last_lines = "\n".join(result.stdout.strip().splitlines()[-3:])
        print("VSPAERO stdout (last 3 lines):")
        print(last_lines)
    if result.stderr:
        print("VSPAERO stderr:")
        print(result.stderr)

    if not os.path.exists(RESULTS_CSV) or os.path.getsize(RESULTS_CSV) == 0:
        raise RuntimeError("VSPAERO did not produce a valid Results.csv")

# --- Extract L/D --------------------------------------------------------
def extract_ld_all(results_path: str):
    """Returns max L/D, index of max, L/D array, alpha array."""
    rows = []
    with open(results_path, newline="") as f:
        reader = csv.reader(f)
        for r in reader:
            rows.append(r)

    # Find row indices by header names
    def find_row(label):
        for i, r in enumerate(rows):
            if len(r) > 0 and r[0].strip() == label:
                return i
        raise RuntimeError(f"Row with label '{label}' not found in CSV")

    alpha_row = find_row("Alpha")
    cl_row = find_row("CLtot")
    cd_row = find_row("CDtot")

    # Convert strings to floats, skip first column
    alphas = np.array([float(a) for a in rows[alpha_row][1:] if a.strip() != ''])
    cl = np.array([float(a) for a in rows[cl_row][1:] if a.strip() != ''])
    cd = np.array([float(a) for a in rows[cd_row][1:] if a.strip() != ''])
    ld = cl / cd

    max_ld_idx = ld.argmax()
    max_ld = ld[max_ld_idx]
    best_alpha = alphas[max_ld_idx]

    return max_ld, best_alpha, ld, alphas

# --- Objective function -----------------------------------------------
def evaluate_design(x):
    global eval_counter, best_ld_so_far, best_x_so_far, prev_ld

    eval_counter += 1
    span, sweep, xloc, taper, tip, ctrl = x
    elapsed_s = time.time() - t_start
    elapsed_min = elapsed_s / 60.0
    prev_str = "N/A" if prev_ld is None else f"{prev_ld:.6f}"

    print(f"\n--- Iteration {eval_counter} ---")
    print(
        f"t = {elapsed_s:6.1f}s ({elapsed_min:4.1f} min) | "
        f"prev L/D = {prev_str}, best = {best_ld_so_far:.6f}\n"
        f"Design: span={span:.1f} mm, sweep={sweep:.1f} deg, xloc={xloc:.1f} mm, "
        f"taper={taper:.3f}, tip={tip:.1f} mm, ctrl={ctrl:.3f}"
    )

    update_geometry_from_x(x)
    run_vspaero()

    max_ld, best_alpha, ld_arr, alphas = extract_ld_all(RESULTS_CSV)
    prev_ld = max_ld

    if max_ld > best_ld_so_far:
        best_ld_so_far = max_ld
        best_x_so_far = x.copy()

    print(f"Result: max L/D = {max_ld:.6f} at alpha = {best_alpha:.2f} deg; best so far = {best_ld_so_far:.6f}")

    # --- Log L/D at all alphas as semicolon-separated string
    ld_str = ";".join(f"{v:.6f}" for v in ld_arr)

    # --- Write to CSV ---
    with open(LOG_CSV, "a") as f:
        f.write(
            f"{eval_counter},{elapsed_s:.2f},{elapsed_min:.3f},"
            f"{span:.3f},{sweep:.3f},{xloc:.3f},{taper:.5f},"
            f"{tip:.3f},{ctrl:.5f},"
            f"{max_ld:.6f},{best_ld_so_far:.6f},{ld_str}\n"
        )

    return -max_ld  # minimize negative L/D

# --- Driver ------------------------------------------------------------
if __name__ == "__main__":
    baseline = [400.0, 25.0, 320.0, 0.833333, 125.0, 0.28]
    bounds = [
        (275.0, 650.0),  # span
        (0.0, 45.0),     # sweep
        (230.0, 340.0),  # xloc
        (0.5, 1.0),      # taper
        (120.0, 130.0),  # tip chord
        (0.22, 0.38),    # control chord fraction
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
    print("Best max L/D =", -result.fun)
    print("Best found during run =", best_ld_so_far, "at x =", best_x_so_far)
