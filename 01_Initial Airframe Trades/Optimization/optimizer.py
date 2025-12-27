import subprocess
import time
from io import StringIO

import numpy as np
import pandas as pd
from scipy.optimize import differential_evolution

# --- Config -------------------------------------------------------------
VSP_EXE = r"C:\Users\Jackson\Desktop\ZZ_Software Downloads\OpenVSP-3.46.0-win64\vsp.exe"
RESULTS_CSV = "Results.csv"      # Output from cruise.vspscript
LOG_CSV = "opt_history.csv"      # Optimization history log

# Global counters for status
eval_counter = 0
best_ld_so_far = -np.inf
best_x_so_far = None
t_start = time.time()

# Initialize log file
with open(LOG_CSV, "w") as f:
    f.write(
        "iter,elapsed_s,elapsed_min,"
        "span_mm,sweep_deg,xloc_mm,taper,tip_mm,ctrl_frac,"
        "max_L_over_D,best_L_over_D,alpha_deg\n"
    )


# --- Post-processing: extract max L/D from Results.csv ------------------

def extract_max_ld(results_path: str) -> tuple[float, float]:
    """
    Returns (max_L_over_D, alpha_at_max) from VSPAERO polar summary
    using CLtot and CDtot, for a 2–10 deg alpha sweep.
    """
    with open(results_path, "r") as f:
        lines = f.readlines()

    block_start = None
    for i, line in enumerate(lines):
        parts = line.strip().split(",")
        if len(parts) >= 2 and parts[0] == "Alpha":
            try:
                float(parts[1])
                block_start = i
                break
            except ValueError:
                continue

    if block_start is None:
        raise RuntimeError("Could not find Alpha row for polar summary.")

    block = []
    for line in lines[block_start:]:
        if line.strip().startswith("Results_"):
            break
        if not line.strip():
            break
        block.append(line)

    block_csv = StringIO("".join(block))
    df = pd.read_csv(block_csv, header=None)

    def row_of(label: str) -> int:
        matches = df.index[df[0] == label]
        if len(matches) == 0:
            raise RuntimeError(f"Label '{label}' not found in polar block.")
        return matches[0]

    alpha_row = row_of("Alpha")
    cltot_row = row_of("CLtot")
    cdtot_row = row_of("CDtot")

    alphas = df.iloc[alpha_row, 1:].astype(float).values
    cltot  = df.iloc[cltot_row, 1:].astype(float).values
    cdtot  = df.iloc[cdtot_row, 1:].astype(float).values

    ld = cltot / (-cdtot)

    idx_max = ld.argmax()
    return float(ld[idx_max]), float(alphas[idx_max])


# --- DES writing: map x -> .des ----------------------------------------

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

def write_des_from_x(x, des_path="current.des"):
    # x = [span_mm, sweep_deg, xloc_mm, taper, tip_chord_mm, ctrl_chord_frac]
    span, sweep, xloc, taper, tip, ctrl = x
    with open(des_path, "w") as f:
        f.write(DES_TEMPLATE.format(
            span=span,
            sweep=sweep,
            xloc=xloc,
            taper=taper,
            tip=tip,
            ctrl=ctrl,
        ))


# --- Geometry update via update_geom.vspscript --------------------------

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
    result = subprocess.run(
        [VSP_EXE, "-script", "cruise.vspscript"],
        capture_output=True,
        text=True
    )
    print("VSPAERO: " + result.stdout.strip().split('\n')[-1])



# --- Objective function -------------------------------------------------

def evaluate_design(x):
    """
    x: [span, sweep, xloc, taper, tip, ctrl]
    Returns: −max L/D (for minimization).
    """
    global eval_counter, best_ld_so_far, best_x_so_far

    eval_counter += 1
    span, sweep, xloc, taper, tip, ctrl = x
    elapsed_s = time.time() - t_start
    elapsed_min = elapsed_s / 60.0

    # Status before run
    print(
        f"[{eval_counter:03d}] "
        f"t = {elapsed_s:6.1f} s ({elapsed_min:4.1f} min) | "
        f"span={span:7.1f} mm, sweep={sweep:5.1f} deg, "
        f"xloc={xloc:7.1f} mm, taper={taper:5.3f}, "
        f"tip={tip:6.1f} mm, ctrl={ctrl:5.3f}"
    )

    update_geometry_from_x(x)
    run_vspaero()
    max_ld, best_alpha = extract_max_ld(RESULTS_CSV)

    # Update running best
    if max_ld > best_ld_so_far:
        best_ld_so_far = max_ld
        best_x_so_far = x.copy()

    print(
        f"     -> max L/D = {max_ld:.3f} at alpha = {best_alpha:.2f} deg; "
        f"best so far = {best_ld_so_far:.3f}"
    )

    # Append to history log
    with open(LOG_CSV, "a") as f:
        f.write(
            f"{eval_counter},"
            f"{elapsed_s:.2f},{elapsed_min:.3f},"
            f"{span:.3f},{sweep:.3f},{xloc:.3f},{taper:.5f},"
            f"{tip:.3f},{ctrl:.5f},"
            f"{max_ld:.6f},{best_ld_so_far:.6f},{best_alpha:.3f}\n"
        )

    return -max_ld


# --- Driver -------------------------------------------------------------

if __name__ == "__main__":
    # Baseline (for reference)
    baseline = [500.0, 25.0, 320.0, 0.833333, 125.0, 0.28]

    # Bounds in mm / deg / nondim
    bounds = [
        (600.0, 1100.0),  # span [mm]
        (0.0,   50.0),    # sweep [deg]
        (230.0, 340.0),   # X location [mm]
        (0.5,    1.0),    # taper [-]
        (120.0, 130.0),   # tip chord [mm]
        (0.22,  0.38),    # control chord fraction [-]
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
    print(f"Total time: {total_s:.1f} s ({total_min:.2f} min)")
    print("Best design vector x* =", result.x)
    print("Best max L/D =", -result.fun)
    print("Best found during run =", best_ld_so_far, "at x =", best_x_so_far)
