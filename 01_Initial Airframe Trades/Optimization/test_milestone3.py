"""
Test script for Milestone 3: First Optimization Generation

This script runs a minimal optimization (1-2 generations, small population)
to verify the optimizer generates and evaluates multiple distinct designs.

SAFE TO RUN ALONGSIDE optimizer2.py - uses separate output files:
- test_current.des (instead of current.des)
- test_Results.csv (instead of Results.csv)
- test_opt_history.csv (instead of opt_history.csv)
"""

import subprocess
import time
import os
import numpy as np
from scipy.optimize import differential_evolution

# ---------------------------------------------------------------------
# Config - using test_ prefix to avoid conflicts with main optimizer
# ---------------------------------------------------------------------
VSP_EXE = r"C:\Users\Jackson\Desktop\ZZ_Software Downloads\OpenVSP-3.46.0-win64\vsp.exe"
RESULTS_CSV = "test_Results.csv"
LOG_CSV = "test_opt_history.csv"
DES_FILE = "test_current.des"

# ---------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------
eval_counter = 0
best_obj_so_far = -np.inf
best_x_so_far = None
prev_iter_obj = None
stagnation_counter = 0

STAGNATION_THRESHOLD = 5
STAGNATION_DELTA = 0.01

t_start = time.time()

# ---------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------
with open(LOG_CSV, "w") as f:
    f.write(
        "iter,elapsed_s,elapsed_min,"
        "span_mm,sweep_deg,xloc_mm,taper,tip_mm,ctrl_frac,"
        "band_LD,span_penalty,te_penalty,final_obj,alpha_center,LD_curve,iter_improvement\n"
    )

# ---------------------------------------------------------------------
# DES template
# ---------------------------------------------------------------------
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
ARLMRMBRQTY:TailGeom:XSec_1:Root_Chord: {fin_chord}
OJGNBNXLMTG:TailGeom:XSec_1:Sweep: {fin_sweep}
"""

# ---------------------------------------------------------------------
# Geometry update
# ---------------------------------------------------------------------
def write_des_from_x(x, path=DES_FILE):
    span, sweep, xloc, taper, tip, ctrl = x
    fin_chord = tip
    fin_sweep = 45.0

    with open(path, "w") as f:
        f.write("14\n")
        f.write(DES_TEMPLATE.format(
            span=span, sweep=sweep, xloc=xloc,
            taper=taper, tip=tip, ctrl=ctrl,
            fin_chord=fin_chord, fin_sweep=fin_sweep
        ))

def update_geometry_from_x(x):
    write_des_from_x(x)
    # Capture output to see what's wrong
    result = subprocess.run(
        [VSP_EXE, "-script", "update_geom.vspscript"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else None
    )
    if result.returncode != 0:
        print("OpenVSP script error:")
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
        raise subprocess.CalledProcessError(result.returncode, result.args, result.stdout, result.stderr)

# ---------------------------------------------------------------------
# VSPAERO run - modified to use test Results.csv
# ---------------------------------------------------------------------
def run_vspaero():
    if os.path.exists(RESULTS_CSV):
        os.remove(RESULTS_CSV)

    start = time.time()
    result = subprocess.run(
        [VSP_EXE, "-script", "cruise.vspscript"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else None
    )
    elapsed = time.time() - start
    
    # Check for errors in output
    if result.returncode != 0 or "ERROR" in result.stdout:
        print(f"VSPAero script may have errors:")
        print(result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)
    
    # cruise.vspscript now automatically writes to test_Results.csv when using test_current.vsp3
    # But check both locations just in case
    if not os.path.exists(RESULTS_CSV) and os.path.exists("Results.csv"):
        # Fallback: rename if cruise script wrote to Results.csv
        os.rename("Results.csv", RESULTS_CSV)
    
    print(f"VSPAERO run completed in {elapsed:.1f}s")
    
    # Check if test_current.vsp3 exists (should be created by update_geometry_from_x)
    if not os.path.exists("test_current.vsp3") and not os.path.exists("current.vsp3"):
        print("WARNING: No .vsp3 file found after geometry update!")

    if not os.path.exists(RESULTS_CSV):
        raise RuntimeError(f"No {RESULTS_CSV} produced")

# ---------------------------------------------------------------------
# L/D extraction
# ---------------------------------------------------------------------
def extract_band_ld(results_path):
    alphas = np.arange(2, 17, 1)

    with open(results_path, "r") as f:
        rows = [line.strip().split(",") for line in f if line.strip()]

    ld_row = next((r for r in rows if r[0].strip() == "L_D"), None)
    if ld_row is None:
        return 0.001, None, None

    ld = np.array([float(v) for v in ld_row[1:1 + len(alphas)]])
    ld = -ld
    ld = np.clip(ld, 0.0, 17.5)

    WINDOW = 4
    best_score = -np.inf
    best_idx = None

    for i in range(len(ld) - WINDOW + 1):
        band = ld[i:i + WINDOW]
        score = band.mean() - 0.2 * band.std()
        if score > best_score:
            best_score = score
            best_idx = i

    alpha_center = alphas[best_idx + WINDOW // 2] if best_idx is not None else None
    return best_score, alpha_center, ld

# ---------------------------------------------------------------------
# Objective function
# ---------------------------------------------------------------------
def evaluate_design(x):
    global eval_counter, best_obj_so_far, best_x_so_far, prev_iter_obj

    eval_counter += 1
    span, sweep, xloc, taper, tip, ctrl = x

    elapsed_s = time.time() - t_start
    elapsed_min = elapsed_s / 60.0

    # Trailing edge soft penalty
    sweep_rad = np.radians(sweep)
    te_x = xloc + np.sin(sweep_rad) * span + tip
    te_penalty = 0.0
    if te_x > 630.0:
        te_penalty = 0.002 * (te_x - 630.0) ** 2

    # Run solver
    update_geometry_from_x(x)
    try:
        run_vspaero()
    except RuntimeError as e:
        print(f"VSPAERO failed: {e}")
        return 0.001

    band_ld, alpha_center, ld_curve = extract_band_ld(RESULTS_CSV)
    if not np.isfinite(band_ld):
        band_ld = 0.001

    span_penalty = 0.0
    if span > 360.0:
        span_penalty = 0.001 * (span - 350.0) ** 2
    elif span < 320.0:
        span_penalty = 0.0005 * (330.0 - span) ** 2

    # Final objective
    obj = (
        0.7 * band_ld
        - 0.3 * span_penalty
        - te_penalty
    )
    obj = max(obj, 0.001)

    # Improvement tracking
    iter_improvement = 0.0 if prev_iter_obj is None else obj - prev_iter_obj
    prev_iter_obj = obj

    if obj > best_obj_so_far:
        best_obj_so_far = obj
        best_x_so_far = x.copy()

    print(f"\n--- Iteration {eval_counter} ---")
    print(f"t = {elapsed_min:.1f} min")
    print(f"span={span:.1f}, sweep={sweep:.1f}, xloc={xloc:.1f}, taper={taper:.3f}, tip={tip:.1f}, ctrl={ctrl:.3f}")
    print(f"Band L/D = {band_ld:.4f}, span_pen = {span_penalty:.3f}, te_pen = {te_penalty:.3f}")
    print(f"Objective = {obj:.4f}, best = {best_obj_so_far:.4f}, α_center = {alpha_center}")

    ld_str = ";".join(f"{v:.3f}" for v in ld_curve) if ld_curve is not None else ""
    with open(LOG_CSV, "a") as f:
        f.write(
            f"{eval_counter},{elapsed_s:.1f},{elapsed_min:.2f},"
            f"{span:.2f},{sweep:.2f},{xloc:.2f},{taper:.4f},{tip:.2f},{ctrl:.3f},"
            f"{band_ld:.5f},{span_penalty:.5f},{te_penalty:.5f},{obj:.5f},{alpha_center},"
            f"{ld_str},{iter_improvement:.5f}\n"
        )

    return -obj

# ---------------------------------------------------------------------
# Convergence callback
# ---------------------------------------------------------------------
def convergence_callback(xk, convergence):
    global stagnation_counter, best_obj_so_far

    if convergence < STAGNATION_DELTA:
        stagnation_counter += 1
        if stagnation_counter >= STAGNATION_THRESHOLD:
            print("Stagnation detected — perturbing population")
            xk += np.random.normal(scale=3.0, size=len(xk))
            stagnation_counter = 0
    else:
        stagnation_counter = 0

    print(f"Generation complete | Best obj = {best_obj_so_far:.4f} | Convergence = {convergence:.4f}")

# ---------------------------------------------------------------------
# Driver - MINIMAL TEST RUN
# ---------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("MILESTONE 3 TEST: First Optimization Generation")
    print("=" * 60)
    print("Running minimal optimization:")
    print("  - 1 generation (maxiter=1)")
    print("  - Population size: 6")
    print("  - Using test_* files to avoid conflicts")
    print("=" * 60)
    print()

    baseline = [330.0, 25.0, 320.0, 0.833333, 120.0, 0.22]

    bounds = [
        (275.0, 480.0),  # span
        (0.0, 40.0),     # sweep
        (220.0, 340.0),  # xloc
        (0.6, 0.9),      # taper
        (95.0, 125.0),   # tip
        (0.22, 0.22),    # control fraction
    ]

    print("Baseline evaluation:")
    evaluate_design(baseline)

    print("\nStarting minimal optimization test...\n")
    result = differential_evolution(
        evaluate_design,
        bounds,
        maxiter=1,        # Only 1 generation for quick test
        popsize=6,        # Small population for speed
        strategy='best1bin',
        tol=5e-3,
        polish=False,
        callback=convergence_callback
    )

    total_s = time.time() - t_start
    print("\n" + "=" * 60)
    print("MILESTONE 3 TEST COMPLETE")
    print("=" * 60)
    print(f"Total evals: {eval_counter}")
    print(f"Total time: {total_s/60:.1f} min")
    print(f"Best x: {best_x_so_far}")
    print(f"Best objective: {best_obj_so_far:.4f}")
    print()
    print("Check test_opt_history.csv for full iteration log")
    print("Run validate_milestone3.py to verify all criteria")
    print("=" * 60)

