import subprocess
import time
import os
import numpy as np
from scipy.optimize import differential_evolution

# ---------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------
VSP_EXE = r"C:\Users\Jackson\Desktop\ZZ_Software Downloads\OpenVSP-3.46.0-win64\vsp.exe"
RESULTS_CSV = "Results.csv"
LOG_CSV = "opt_history.csv"

# ---------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------
eval_counter = 0
generation_counter = 0  # Track which generation we're in
best_obj_so_far = -np.inf
best_x_so_far = None
prev_iter_obj = None
stagnation_counter = 0
vspaero_time = 0.0  # Track VSPAero run time

STAGNATION_THRESHOLD = 5
STAGNATION_DELTA = 0.01

t_start = time.time()

# ---------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------
with open(LOG_CSV, "w") as f:
    f.write(
        "iter,generation,elapsed_s,elapsed_min,vspaero_time_s,"
        "span_mm,sweep_deg,xloc_mm,taper,tip_mm,ctrl_frac,te_x_mm,"
        "band_LD,ld_min,ld_max,ld_range,ld_at_2deg,ld_at_4deg,ld_at_6deg,ld_at_8deg,ld_at_10deg,ld_at_12deg,ld_at_14deg,"
        "span_penalty,te_penalty,ld_penalty,crash_penalty,slug_penalty,total_penalty,"
        "static_margin,sm_category,xnp,mac,cg_x,"
        "final_obj,alpha_center,is_new_best,iter_improvement\n"
    )

# ---------------------------------------------------------------------
# DES template
# ---------------------------------------------------------------------
# ---------------------------------------------------------------------
# DES template - now including fin chord/sweep
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
def write_des_from_x(x, path="current.des"):
    span, sweep, xloc, taper, tip, ctrl = x
    fin_chord = tip        # fin chord always equals tip chord
    fin_sweep = 45.0       # fixed

    with open(path, "w") as f:
        f.write("14\n")  # updated from 12 to 14 to account for tail lines
        f.write(DES_TEMPLATE.format(
            span=span, sweep=sweep, xloc=xloc,
            taper=taper, tip=tip, ctrl=ctrl,
            fin_chord=fin_chord, fin_sweep=fin_sweep
        ))

def update_geometry_from_x(x):
    write_des_from_x(x)
    result = subprocess.run(
        [VSP_EXE, "-script", "update_geom.vspscript"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else None
    )
    if result.returncode != 0:
        print(f"ERROR: update_geom.vspscript failed with exit code {result.returncode}", flush=True)
        if result.stderr:
            print(f"STDERR: {result.stderr[-500:]}", flush=True)
        raise RuntimeError("Failed to update geometry")
    
    # Verify current.vsp3 was created
    if not os.path.exists("current.vsp3"):
        print("ERROR: current.vsp3 was not created by update_geom.vspscript", flush=True)
        if result.stdout:
            print(f"STDOUT: {result.stdout[-500:]}", flush=True)
        raise RuntimeError("current.vsp3 not created")

# ---------------------------------------------------------------------
# VSPAERO run (includes MassProp for CG calculation)
# ---------------------------------------------------------------------
def run_vspaero():
    global vspaero_time
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
    vspaero_time = elapsed
    print(f"VSPAERO run completed in {elapsed:.1f}s ({elapsed/60:.1f} min)", flush=True)
    
    # Check for errors in VSPAero output
    if result.returncode != 0:
        print(f"WARNING: VSPAero returned non-zero exit code: {result.returncode}", flush=True)
        if result.stderr:
            print(f"STDERR: {result.stderr[-500:]}", flush=True)
    
    # Check if Results.csv was created and has content
    if not os.path.exists(RESULTS_CSV):
        raise RuntimeError("No Results.csv produced")
    
    # Check file size - if it's too small, the analysis probably didn't complete
    file_size = os.path.getsize(RESULTS_CSV)
    if file_size < 1000:  # Less than 1KB is suspicious
        print(f"WARNING: Results.csv is very small ({file_size} bytes) - analysis may have failed", flush=True)
    
    # Expected time for 7 alpha points with 13 wake iterations should be 2-5 minutes minimum
    if elapsed < 60:
        print(f"WARNING: VSPAero completed very quickly ({elapsed:.1f}s) - analysis may not have run fully", flush=True)
        print(f"Expected time: 2-5 minutes for full analysis", flush=True)
        # Print VSPAero output for debugging
        if result.stdout:
            print(f"\nVSPAero STDOUT (last 1000 chars):", flush=True)
            print(result.stdout[-1000:], flush=True)
        if result.stderr:
            print(f"\nVSPAero STDERR (last 1000 chars):", flush=True)
            print(result.stderr[-1000:], flush=True)

# ---------------------------------------------------------------------
# L/D extraction (α = 2–14°, step 2°)
# ---------------------------------------------------------------------
def extract_band_ld(results_path):
    alphas = np.arange(2, 15, 2)  # 2, 4, 6, 8, 10, 12, 14 (7 pts)

    with open(results_path, "r") as f:
        rows = [line.strip().split(",") for line in f if line.strip()]

    ld_row = next((r for r in rows if r[0].strip() == "L_D"), None)
    if ld_row is None:
        return 0.001, None, None

    ld = np.array([float(v) for v in ld_row[1:1 + len(alphas)]])
    ld = -ld
    # Removed hard ceiling - allow higher L/D but penalize sailplane-like designs (>20)
    ld = np.clip(ld, 0.0, 50.0)  # Upper bound to prevent numerical issues

    WINDOW = 3  # Reduced from 4 since we have fewer points now
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
# Dynamic CG calculation
# ---------------------------------------------------------------------
def extract_cg_from_results(results_path, stab_file=None):
    """
    Extract Center of Gravity from MassProp_Results.csv file (written by massprop.vspscript).
    
    Parameters:
    - results_path: Path to Results.csv (used to determine test vs main run)
    - stab_file: Path to .aerocenter.stab file (optional, not used for CG)
    
    Returns:
    - cg_x: X-location of CG in mm, or None if not found
    """
    # Determine which MassProp CSV file to use
    if "test_" in results_path:
        massprop_file = "test_MassProp_Results.csv"
    else:
        massprop_file = "MassProp_Results.csv"
    
    if os.path.exists(massprop_file):
        try:
            with open(massprop_file, "r") as f:
                for line in f:
                    line = line.strip()
                    # Total_CG is stored as: Total_CG,X,Y,Z
                    if line.startswith("Total_CG,"):
                        # Split by comma: first is label, rest are X,Y,Z
                        parts = line.split(",")
                        if len(parts) >= 2:  # At least "Total_CG" and X value
                            try:
                                cg_x = float(parts[1].strip())
                                if cg_x != 0.0:
                                    return cg_x
                            except (ValueError, IndexError):
                                pass
        except Exception as e:
            print(f"Warning: Could not extract CG from {massprop_file}: {e}", flush=True)
    
    # Final fallback: Try Results.csv
    try:
        with open(results_path, "r") as f:
            for line in f:
                if line.startswith("FC_Xcg_,"):
                    cg_x = float(line.split(",")[1])
                    if cg_x != 0.0:
                        return cg_x
    except Exception as e:
        print(f"Warning: Could not extract CG from {results_path}: {e}", flush=True)
    
    return None

# ---------------------------------------------------------------------
# Stability extraction (Static Margin from VSPAEROStability)
# ---------------------------------------------------------------------
def extract_stability_margin(stability_results_path, results_path, cg_x=None, design_x=None):
    """
    Extract Static Margin from VSPAero Pitch stability analysis.
    With UnsteadyType=5 (Pitch mode), VSPAero outputs aerodynamic center in .stab file.
    Static Margin = (Xnp - Xcg) / MAC * 100
    
    Parameters:
    - stability_results_path: Path to stability results (not used, we use .stab file)
    - results_path: Path to Results.csv
    - cg_x: CG X-location (mm). If None, calculates dynamically from design_x
    - design_x: Design vector [span, sweep, xloc, taper, tip, ctrl] for dynamic CG calculation
    
    Returns: (static_margin_pct, crash_penalty, slug_penalty, xnp, mac, cg_x_used)
    - static_margin_pct: Static margin as percentage of MAC
    - crash_penalty: Heavy penalty if SM < 5% (unstable)
    - slug_penalty: Moderate penalty if SM > 15% (overly stable)
    - xnp: Neutral point location (mm) - average aerodynamic center X
    - mac: Mean aerodynamic chord (mm) - from Cref in results
    - cg_x_used: CG X-location actually used (mm)
    """
    # Extract CG from VSPAero results (set by MassProp analysis)
    # Try to find .aerocenter.stab file for CG extraction
    stab_file = None
    if "test_" in results_path:
        stab_file = "test_current.aerocenter.stab"
    else:
        stab_file = "current.aerocenter.stab"
    
    # If cg_x not provided, extract from results
    if cg_x is None:
        extracted_cg = extract_cg_from_results(results_path, stab_file)
        if extracted_cg is not None:
            cg_x = extracted_cg
        else:
            # Fallback: use design_x to estimate if available
            if design_x is not None:
                # Rough estimate based on wing position (will be overridden by MassProp)
                span, sweep, xloc, taper, tip, ctrl = design_x
                cg_x = xloc - 10.0  # Temporary estimate
            else:
                cg_x = 310.0  # Final fallback to default
    # Try to find .aerocenter.stab file (created by Pitch mode)
    stab_file = None
    if "test_" in results_path:
        stab_file = "test_current.aerocenter.stab"
    else:
        stab_file = "current.aerocenter.stab"
    
    if not os.path.exists(stab_file):
        # Fallback to Cm slope method
        return extract_stability_fallback(results_path, cg_x)
    
    try:
        # Parse .stab file to extract aerodynamic center locations
        with open(stab_file, "r") as f:
            content = f.read()
        
        # Extract all "Aerodynamic Center is at: ( X, Y, Z)" lines
        import re
        pattern = r"Aerodynamic Center is at:\s*\(\s*([\d\.\-]+),\s*([\d\.\-]+),\s*([\d\.\-]+)\)"
        matches = re.findall(pattern, content)
        
        if not matches:
            print(f"WARNING: No aerodynamic center found in {stab_file}, using fallback", flush=True)
            return extract_stability_fallback(results_path, cg_x)
        
        # Get X-coordinates (neutral point) and average them
        xnp_values = [float(m[0]) for m in matches]
        xnp = sum(xnp_values) / len(xnp_values)  # Average neutral point
        
        # Get MAC from Results.csv (Cref is approximately MAC)
        mac = None
        with open(results_path, "r") as f:
            for line in f:
                if line.startswith("FC_Cref_,"):
                    mac = float(line.split(",")[1])
                    break
        
        if mac is None or mac <= 0:
            # Fallback: estimate MAC from Cref if not found
            mac = 137.88  # Approximate MAC from baseline
        
        # Calculate Static Margin
        static_margin_pct = ((xnp - cg_x) / mac) * 100.0
        
        # Penalty system with sweet spot (8-12% no penalty)
        crash_penalty = 0.0
        slug_penalty = 0.0
        
        if static_margin_pct < 5.0:
            # Crash Penalty (100% weight) - unstable aircraft
            crash_penalty = 10.0 * (5.0 - static_margin_pct)
        elif static_margin_pct > 15.0:
            # Slug Penalty (35% weight) - overly stable
            slug_penalty = 0.35 * (static_margin_pct - 15.0)
        # Sweet spot 8-12%: no penalty
        
        return static_margin_pct, crash_penalty, slug_penalty, xnp, mac, cg_x
        
    except Exception as e:
        print(f"Error reading stability file {stab_file}: {e}, using fallback", flush=True)
        result = extract_stability_fallback(results_path, cg_x)
        # Fallback returns 5 values, we need to add cg_x to make it 6
        if len(result) == 5:
            return result[0], result[1], result[2], result[3], result[4], cg_x
        return result

def extract_stability_fallback(results_path, cg_x=310.0):
    """
    Fallback: Extract stability from Cm slope if stability file not available.
    Uses CMytot (total pitch moment) from Results.csv.
    Cm slope (dCm/dAlpha) is proportional to static margin.
    
    Returns: (static_margin_pct, crash_penalty, slug_penalty, xnp, mac, cg_x)
    """
    alphas = np.arange(2, 15, 2)  # 2, 4, 6, 8, 10, 12, 14 (7 pts)

    with open(results_path, "r") as f:
        rows = [line.strip().split(",") for line in f if line.strip()]

    # Find CMytot (total pitch moment coefficient about Y-axis)
    cm_row = None
    for row in rows:
        row_header = row[0].strip()
        if row_header == "CMytot":
            cm_row = row
            break
    
    if cm_row is None:
        print(f"WARNING: CMytot not found in {results_path}, using default stability", flush=True)
        return None, 0.0, 0.0, None, None, cg_x

    try:
        cm_values = np.array([float(v) for v in cm_row[1:1 + len(alphas)]])
        
        if len(cm_values) < 3:
            return None, 0.0, 0.0, None, None, cg_x
        
        # Calculate Cm slope (dCm/dAlpha)
        # Negative slope = stable (Cm becomes more negative as alpha increases)
        cm_slope = np.polyfit(alphas, cm_values, 1)[0]
        
        # Convert Cm slope to approximate static margin
        # For a typical aircraft: SM ≈ -dCm/dCL ≈ -dCm/dAlpha * (dAlpha/dCL)
        # Rough approximation: assume dCL/dAlpha ≈ 0.1 per degree
        # So SM ≈ -dCm/dAlpha / 0.1 * 100 (as percentage)
        # This is approximate but gives reasonable values
        if cm_slope >= 0:
            # Unstable (positive slope)
            static_margin_pct = -10.0  # Very unstable
            crash_penalty = 10.0 * 15.0  # Large penalty
            slug_penalty = 0.0
        else:
            # Stable (negative slope)
            # Rough conversion: SM ≈ -dCm/dAlpha * 10 (as percentage)
            static_margin_pct = abs(cm_slope) * 10.0
            
            crash_penalty = 0.0
            slug_penalty = 0.0
            
            if static_margin_pct < 5.0:
                crash_penalty = 10.0 * (5.0 - static_margin_pct)
            elif static_margin_pct > 15.0:
                slug_penalty = 0.35 * (static_margin_pct - 15.0)
        
        return static_margin_pct, crash_penalty, slug_penalty, None, None, cg_x
        
    except (ValueError, IndexError):
        return None, 0.0, 0.0, None, None, cg_x

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
        run_vspaero()  # MassProp now runs inside cruise.vspscript
    except RuntimeError as e:
        print(f"VSPAERO failed: {e}")
        vspaero_time = 0.0  # Reset on failure
        return 0.001

    # Extract L/D data
    try:
        band_ld, alpha_center, ld_curve = extract_band_ld(RESULTS_CSV)
        if not np.isfinite(band_ld):
            band_ld = 0.001
        # Calculate L/D statistics
        if ld_curve is not None and len(ld_curve) > 0:
            ld_min = float(np.min(ld_curve))
            ld_max = float(np.max(ld_curve))
            ld_range = ld_max - ld_min
        else:
            ld_min = None
            ld_max = None
            ld_range = None
    except Exception as e:
        print(f"Error extracting L/D: {e}")
        band_ld = 0.001
        alpha_center = None
        ld_curve = None
        ld_min = None
        ld_max = None
        ld_range = None

    # Extract stability metrics (Static Margin from VSPAEROStability)
    # CG is now extracted from MassProp results (set in VSP script)
    try:
        static_margin, crash_penalty, slug_penalty, xnp, mac, cg_x_used = extract_stability_margin(
            "Stability_Results.csv", RESULTS_CSV, cg_x=None, design_x=None
        )
    except Exception as e:
        print(f"Error extracting stability: {e}", flush=True)
        static_margin = None
        crash_penalty = 0.0
        slug_penalty = 0.0
        xnp = None
        mac = None
        # Try to extract CG as fallback
        cg_x_used = extract_cg_from_results(RESULTS_CSV) or 310.0

    # L/D penalty for sailplane-like designs (>20)
    ld_penalty = 0.0
    if band_ld > 20.0:
        ld_penalty = 0.5 * (band_ld - 20.0) ** 2  # Quadratic penalty above 20

    span_penalty = 0.0
    if span > 360.0:
        span_penalty = 0.001 * (span - 350.0) ** 2
    elif span < 320.0:
        span_penalty = 0.0005 * (330.0 - span) ** 2  # small penalty for short span

    # Final objective with stability consideration
    # Weights: 60% efficiency, 20% agility, 20% stability
    # Crash penalty (100% weight) applied directly, slug penalty (35% weight) already scaled
    obj = (
        0.6 * band_ld
        - 0.2 * span_penalty
        - crash_penalty  # Full weight (unstable = crash)
        - slug_penalty   # Already scaled to 35% weight
        - ld_penalty     # Penalize sailplane designs
        - te_penalty
    )
    obj = max(obj, 0.001)

    # Improvement tracking
    iter_improvement = 0.0 if prev_iter_obj is None else obj - prev_iter_obj
    prev_iter_obj = obj

    if obj > best_obj_so_far:
        best_obj_so_far = obj
        best_x_so_far = x.copy()

    # Enhanced logging with better formatting
    print("\n" + "="*80, flush=True)
    current_time = time.strftime('%H:%M:%S', time.localtime())
    print(f"ITERATION {eval_counter} | Elapsed: {elapsed_min:.1f} min | Time: {current_time}", flush=True)
    print("="*80, flush=True)
    
    # Design parameters
    print(f"\n[DESIGN PARAMETERS]")
    print(f"  Span:      {span:6.1f} mm  |  Sweep:    {sweep:5.1f} deg")
    print(f"  X Location: {xloc:6.1f} mm  |  Taper:    {taper:5.3f}")
    print(f"  Tip Chord:  {tip:6.1f} mm  |  Control:   {ctrl:5.3f}")
    print(f"  Trailing Edge X: {te_x:6.1f} mm", flush=True)
    
    # Performance metrics
    print(f"\n[PERFORMANCE]")
    alpha_str = f"{alpha_center:.1f}" if alpha_center is not None else "N/A"
    print(f"  Band L/D:   {band_ld:6.4f}  |  Best at α: {alpha_str:>6} deg")
    
    # Stability metrics
    print(f"\n[STABILITY]")
    if static_margin is not None:
        # Determine status with visual indicators
        if static_margin < 5.0:
            sm_status = "UNSTABLE [WARNING]"
            sm_indicator = "!!!"
        elif static_margin > 15.0:
            sm_status = "OVERLY STABLE (Sluggish)"
            sm_indicator = "+++"
        elif 8.0 <= static_margin <= 12.0:
            sm_status = "SWEET SPOT [OK]"
            sm_indicator = "***"
        else:
            sm_status = "ACCEPTABLE"
            sm_indicator = "---"
        
        xnp_str = f"{xnp:.1f}" if xnp is not None else "N/A"
        mac_str = f"{mac:.1f}" if mac is not None else "N/A"
        cg_str = f"{cg_x_used:.1f}" if cg_x_used is not None else "N/A"
        
        print(f"  Static Margin: {static_margin:5.2f}% {sm_indicator} ({sm_status})")
        print(f"  Neutral Point:  {xnp_str:>6} mm  |  MAC: {mac_str:>6} mm  |  CG: {cg_str:>6} mm")
        
        if crash_penalty > 0 or slug_penalty > 0:
            print(f"  Penalties:     Crash={crash_penalty:.3f}, Slug={slug_penalty:.3f}")
        else:
            print(f"  Penalties:     None (within acceptable range)")
    else:
        print(f"  Status: Could not extract static margin (using fallback)")
    
    # Penalties summary
    total_penalty = span_penalty + te_penalty + ld_penalty + crash_penalty + slug_penalty
    if total_penalty > 0:
        print(f"\n[PENALTIES]")
        if span_penalty > 0:
            print(f"  Span:      {span_penalty:6.3f}")
        if te_penalty > 0:
            print(f"  Trailing Edge: {te_penalty:6.3f}")
        if ld_penalty > 0:
            print(f"  L/D (>20):  {ld_penalty:6.3f}")
        if crash_penalty > 0:
            print(f"  Crash (SM<5%): {crash_penalty:6.3f}")
        if slug_penalty > 0:
            print(f"  Slug (SM>15%): {slug_penalty:6.3f}")
        print(f"  Total Penalty: {total_penalty:6.3f}")
    else:
        print(f"\n[PENALTIES] None")
    
    # Determine if this is a new best
    is_new_best = (obj > best_obj_so_far)
    
    # Determine static margin category
    if static_margin is not None:
        if static_margin < 5.0:
            sm_category = "unstable"
        elif static_margin > 15.0:
            sm_category = "overly_stable"
        elif 8.0 <= static_margin <= 12.0:
            sm_category = "sweet_spot"
        else:
            sm_category = "acceptable"
    else:
        sm_category = "unknown"
    
    # Calculate total penalty
    total_penalty = span_penalty + te_penalty + ld_penalty + crash_penalty + slug_penalty
    
    # Objective and convergence
    print(f"\n[OBJECTIVE]")
    improvement = obj - prev_iter_obj if prev_iter_obj is not None else 0.0
    improvement_str = f"+{improvement:.4f}" if improvement > 0 else f"{improvement:.4f}"
    print(f"  Current:  {obj:7.4f}  ({improvement_str})")
    print(f"  Best:     {best_obj_so_far:7.4f}", end="")
    if is_new_best:
        print("  [NEW BEST!]", flush=True)
    else:
        print(f"  (gap: {best_obj_so_far - obj:.4f})", flush=True)
    
    # Convergence indicator
    if eval_counter > 1:
        improvement_pct = ((obj - prev_iter_obj) / abs(prev_iter_obj) * 100) if prev_iter_obj != 0 else 0
        if improvement_pct > 1.0:
            print(f"  Trend: Improving (+{improvement_pct:.1f}%)", flush=True)
        elif improvement_pct < -1.0:
            print(f"  Trend: Declining ({improvement_pct:.1f}%)", flush=True)
        else:
            print(f"  Trend: Stable ({improvement_pct:+.1f}%)", flush=True)
    
    # Add L/D range info to performance section
    if ld_range is not None and ld_min is not None and ld_max is not None:
        print(f"  L/D Range: {ld_min:.3f} - {ld_max:.3f} (span: {ld_range:.3f})", flush=True)

    # Prepare values for CSV logging
    static_margin_str = f"{static_margin:.3f}" if static_margin is not None else "N/A"
    xnp_str = f"{xnp:.2f}" if xnp is not None else "N/A"
    mac_str = f"{mac:.2f}" if mac is not None else "N/A"
    cg_x_str = f"{cg_x_used:.2f}" if cg_x_used is not None else "N/A"
    ld_min_str = f"{ld_min:.5f}" if ld_min is not None else "N/A"
    ld_max_str = f"{ld_max:.5f}" if ld_max is not None else "N/A"
    ld_range_str = f"{ld_range:.5f}" if ld_range is not None else "N/A"
    alpha_center_str = f"{alpha_center}" if alpha_center is not None else "N/A"
    
    # Extract individual L/D values at each alpha
    alphas = [2, 4, 6, 8, 10, 12, 14]
    ld_values = {}
    if ld_curve is not None and len(ld_curve) >= len(alphas):
        for i, alpha in enumerate(alphas):
            ld_values[alpha] = f"{ld_curve[i]:.5f}"
    else:
        for alpha in alphas:
            ld_values[alpha] = "N/A"
    
    with open(LOG_CSV, "a") as f:
        f.write(
            f"{eval_counter},{generation_counter},{elapsed_s:.1f},{elapsed_min:.2f},{vspaero_time:.1f},"
            f"{span:.2f},{sweep:.2f},{xloc:.2f},{taper:.4f},{tip:.2f},{ctrl:.3f},{te_x:.2f},"
            f"{band_ld:.5f},{ld_min_str},{ld_max_str},{ld_range_str},"
            f"{ld_values[2]},{ld_values[4]},{ld_values[6]},{ld_values[8]},{ld_values[10]},{ld_values[12]},{ld_values[14]},"
            f"{span_penalty:.5f},{te_penalty:.5f},{ld_penalty:.5f},{crash_penalty:.5f},{slug_penalty:.5f},{total_penalty:.5f},"
            f"{static_margin_str},{sm_category},{xnp_str},{mac_str},{cg_x_str},"
            f"{obj:.5f},{alpha_center_str},{is_new_best},{iter_improvement:.5f}\n"
        )

    return -obj

# ---------------------------------------------------------------------
# Convergence callback
# ---------------------------------------------------------------------
def convergence_callback(xk, convergence):
    global stagnation_counter, best_obj_so_far, eval_counter, generation_counter

    generation_counter += 1  # Increment generation counter
    
    if convergence < STAGNATION_DELTA:
        stagnation_counter += 1
        if stagnation_counter >= STAGNATION_THRESHOLD:
            print("\n" + "!"*80, flush=True)
            print("STAGNATION DETECTED - Perturbing population to escape local optimum", flush=True)
            print("!"*80 + "\n", flush=True)
            xk += np.random.normal(scale=3.0, size=len(xk))
            stagnation_counter = 0
    else:
        stagnation_counter = 0

    elapsed_min = (time.time() - t_start) / 60.0
    print("\n" + "-"*80, flush=True)
    print(f"GENERATION {generation_counter} SUMMARY | Evaluations: {eval_counter} | Time: {elapsed_min:.1f} min", flush=True)
    print(f"Best Objective: {best_obj_so_far:.4f} | Convergence: {convergence:.6f}", flush=True)
    if best_x_so_far is not None:
        span, sweep, xloc, taper, tip, ctrl = best_x_so_far
        print(f"Best Design: span={span:.1f}, sweep={sweep:.1f}, xloc={xloc:.1f}, taper={taper:.3f}", flush=True)
    print("-"*80 + "\n", flush=True)

# ---------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------
if __name__ == "__main__":

    baseline = [330.0, 25.0, 320.0, 0.833333, 120.0, 0.22]

    bounds = [
        (275.0, 480.0),  # span
        (0.0, 40.0),     # sweep
        (220.0, 340.0),  # xloc
        (0.6, 0.9),      # taper
        (95.0, 125.0),  # tip
        (0.22, 0.22),    # control fraction
    ]

    print("="*80)
    print("FIXED-WING DRONE PLANFORM OPTIMIZER")
    print("="*80)
    print(f"\nConfiguration:")
    print(f"  Population Size: 20")
    print(f"  Max Generations: 40")
    print(f"  Strategy: best1bin")
    print(f"  Convergence Tolerance: 5e-3")
    print(f"\nDesign Bounds:")
    print(f"  Span:      {bounds[0][0]:.1f} - {bounds[0][1]:.1f} mm")
    print(f"  Sweep:     {bounds[1][0]:.1f} - {bounds[1][1]:.1f} deg")
    print(f"  X Location: {bounds[2][0]:.1f} - {bounds[2][1]:.1f} mm")
    print(f"  Taper:     {bounds[3][0]:.2f} - {bounds[3][1]:.2f}")
    print(f"  Tip Chord: {bounds[4][0]:.1f} - {bounds[4][1]:.1f} mm")
    print(f"  Control:   {bounds[5][0]:.2f} (fixed)")
    print(f"\nObjective Weights:")
    print(f"  L/D Efficiency:  60%")
    print(f"  Span Penalty:    20%")
    print(f"  Stability:       20% (crash penalty 100%, slug penalty 35%)")
    print(f"  L/D Penalty:     Applied for L/D > 20")
    print(f"\nStability Targets:")
    print(f"  Sweet Spot: 8-12% Static Margin (no penalty)")
    print(f"  Unstable:   <5% (heavy penalty)")
    print(f"  Over-stable: >15% (moderate penalty)")
    print("="*80)
    
    print("\n[STEP 1/2] Evaluating baseline design...")
    print("-"*80)
    evaluate_design(baseline)
    print("-"*80)

    print("\n[STEP 2/2] Starting differential evolution optimization...")
    print("="*80 + "\n")
    result = differential_evolution(
        evaluate_design,
        bounds,
        maxiter=40,
        popsize=20,
        strategy='best1bin',
        tol=5e-3,
        polish=False,
        callback=convergence_callback
    )

    total_s = time.time() - t_start
    total_min = total_s / 60.0
    
    print("\n" + "="*80)
    print("OPTIMIZATION COMPLETE")
    print("="*80)
    print(f"\n[SUMMARY]")
    print(f"  Total Evaluations: {eval_counter}")
    print(f"  Total Time:        {total_min:.1f} min ({total_s/3600:.2f} hours)")
    print(f"  Avg Time/Eval:     {total_s/eval_counter:.1f} s")
    
    if best_x_so_far is not None:
        span, sweep, xloc, taper, tip, ctrl = best_x_so_far
        print(f"\n[BEST DESIGN FOUND]")
        print(f"  Objective Value:  {best_obj_so_far:.4f}")
        print(f"  Design Parameters:")
        print(f"    Span:      {span:6.1f} mm")
        print(f"    Sweep:     {sweep:5.1f} deg")
        print(f"    X Location: {xloc:6.1f} mm")
        print(f"    Taper:     {taper:5.3f}")
        print(f"    Tip Chord:  {tip:6.1f} mm")
        print(f"    Control:   {ctrl:5.3f}")
        print(f"\n  Full Vector: {best_x_so_far}")
    else:
        print(f"\n[BEST DESIGN] None found")
    
    print(f"\n[OUTPUT FILES]")
    print(f"  Optimization History: {LOG_CSV}")
    print(f"  Latest Results:       {RESULTS_CSV}")
    print(f"  MassProp Results:     MassProp_Results.csv")
    print("="*80)
