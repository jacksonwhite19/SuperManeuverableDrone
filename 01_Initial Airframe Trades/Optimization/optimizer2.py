import subprocess
import time
import os
import sys
import numpy as np
import json
from scipy.optimize import differential_evolution

# ---------------------------------------------------------------------
# Logging setup - capture all output to file
# ---------------------------------------------------------------------
class TeeOutput:
    """Write to both stdout and log file."""
    def __init__(self, file_path):
        self.file = open(file_path, 'w', encoding='utf-8')
        self.stdout = sys.stdout
        
    def write(self, text):
        self.stdout.write(text)
        self.file.write(text)
        self.file.flush()
        
    def flush(self):
        self.stdout.flush()
        self.file.flush()
        
    def close(self):
        self.file.close()

# ---------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------
VSP_EXE = r"C:\Users\Jackson\Desktop\ZZ_Software Downloads\OpenVSP-3.46.0-win64\vsp.exe"
RESULTS_CSV = "Results.csv"
LOG_CSV = "opt_history.csv"
STATUS_FILE = "optimizer_status.json"
CONTROL_FILE = "optimizer_control.txt"
OUTPUT_LOG = "optimizer_output.log"

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

# Remote control flags
_should_stop = False
_should_pause = False

# CG caching - avoid recomputing MassProp for similar geometries
_cg_cache = {}
_CG_CACHE_MAX_SIZE = 200  # Limit cache size to prevent unbounded growth
# Parameter-specific tolerances for CG caching
# CG is sensitive to geometry changes, so we use conservative tolerances
# Format: (span_tol_mm, sweep_tol_deg, xloc_tol_mm, taper_tol, tip_tol_mm, ctrl_tol)
_cg_cache_tolerances = (
    1.0,   # span: 1mm tolerance (CG moves ~0.3mm per 1mm span change)
    0.2,   # sweep: 0.2 deg tolerance (CG moves ~0.5-1mm per 1 deg sweep on large wing)
    0.5,   # xloc: 0.5mm tolerance (CG moves ~0.5mm per 1mm xloc change)
    0.01,  # taper: 0.01 tolerance (minor CG impact)
    0.5,   # tip: 0.5mm tolerance (minor CG impact)
    0.01   # ctrl: 0.01 tolerance (very minor CG impact)
)

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
# Remote control functions
# ---------------------------------------------------------------------
def check_control_files():
    """Check for remote control commands via file system."""
    global _should_stop, _should_pause
    
    if os.path.exists(CONTROL_FILE):
        try:
            with open(CONTROL_FILE, "r") as f:
                command = f.read().strip().lower()
            
            if command == "stop":
                _should_stop = True
                print("\n[REMOTE CONTROL] STOP command received!", flush=True)
                # Clear the file after reading
                os.remove(CONTROL_FILE)
            elif command == "pause":
                _should_pause = True
                print("\n[REMOTE CONTROL] PAUSE command received!", flush=True)
            elif command == "resume":
                _should_pause = False
                print("\n[REMOTE CONTROL] RESUME command received!", flush=True)
                os.remove(CONTROL_FILE)
        except Exception as e:
            print(f"Warning: Error reading control file: {e}", flush=True)
    
    return _should_stop, _should_pause

def write_status_file():
    """Write current optimizer status to JSON file for remote monitoring."""
    global eval_counter, generation_counter, best_obj_so_far, best_x_so_far, t_start, vspaero_time
    # Note: generation_counter is calculated from eval_counter below, not from callback
    
    elapsed_s = time.time() - t_start
    elapsed_min = elapsed_s / 60.0
    
    status = {
        "status": "running" if not _should_stop else "stopping",
        "paused": _should_pause,
        "iteration": eval_counter,
        "generation": generation_counter,
        "elapsed_seconds": elapsed_s,
        "elapsed_minutes": elapsed_min,
        "best_objective": float(best_obj_so_far) if best_obj_so_far != -np.inf else None,
        "best_design": (best_x_so_far.tolist() if hasattr(best_x_so_far, 'tolist') else list(best_x_so_far)) if best_x_so_far is not None else None,
        "last_vspaero_time": float(vspaero_time),
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime()),
        "start_time": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t_start))
    }
    
    try:
        with open(STATUS_FILE, "w") as f:
            json.dump(status, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not write status file: {e}", flush=True)

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
    
    # Start progress indicator in a separate thread
    import threading
    progress_stop = threading.Event()
    
    def progress_indicator():
        """Print elapsed time every 30 seconds"""
        while not progress_stop.is_set():
            elapsed = time.time() - start
            if elapsed > 30:  # Only show after 30 seconds
                elapsed_min = elapsed / 60.0
                print(f"  ... still running ({elapsed_min:.1f} min elapsed) ...", flush=True)
                # Warn if taking unusually long
                if elapsed_min > 12:
                    print(f"  [WARNING] VSPAero run is taking longer than expected (>12 min)", flush=True)
                    print(f"  This may indicate a hung process or complex geometry. Consider checking system resources.", flush=True)
                if elapsed_min > 20:
                    print(f"  [CRITICAL] VSPAero run has exceeded 20 minutes - this is abnormally long!", flush=True)
                    print(f"  Consider interrupting (Ctrl+C) and checking VSPAero settings or geometry.", flush=True)
            progress_stop.wait(30)  # Check every 30 seconds
    
    progress_thread = threading.Thread(target=progress_indicator, daemon=True)
    progress_thread.start()
    
    try:
        result = subprocess.run(
            [VSP_EXE, "-script", "cruise.vspscript"],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else None
        )
    finally:
        progress_stop.set()  # Stop progress indicator
    
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
    
    # Expected time for 7 alpha points with 13 wake iterations should be 5-10 minutes
    elapsed_min = elapsed / 60.0
    if elapsed < 60:
        print(f"WARNING: VSPAero completed very quickly ({elapsed:.1f}s) - analysis may not have run fully", flush=True)
        print(f"Expected time: 5-10 minutes for full analysis", flush=True)
        # Print VSPAero output for debugging
        if result.stdout:
            print(f"\nVSPAero STDOUT (last 1000 chars):", flush=True)
            print(result.stdout[-1000:], flush=True)
        if result.stderr:
            print(f"\nVSPAero STDERR (last 1000 chars):", flush=True)
            print(result.stderr[-1000:], flush=True)
    elif elapsed_min > 15:
        print(f"WARNING: VSPAero took unusually long ({elapsed_min:.1f} min) - may indicate issues", flush=True)
        print(f"Expected time: 5-10 minutes. Check if geometry is valid and system resources are available.", flush=True)

# ---------------------------------------------------------------------
# Pitch stability run (Tier 2 - expensive, single alpha)
# ---------------------------------------------------------------------
def run_pitch_stability():
    """Run pitch stability analysis at single alpha (8 deg). Much faster than 7-alpha sweep."""
    global vspaero_time
    
    stab_file = "current.aerocenter.stab"
    if os.path.exists(stab_file):
        os.remove(stab_file)
    
    start = time.time()
    print(f"[TIER 2] Running pitch stability analysis (single alpha = 8 deg)...", flush=True)
    
    try:
        result = subprocess.run(
            [VSP_EXE, "-script", "pitch_stability.vspscript"],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else None
        )
    except Exception as e:
        print(f"ERROR: Pitch stability analysis failed: {e}", flush=True)
        raise RuntimeError(f"Pitch stability analysis failed: {e}")
    
    elapsed = time.time() - start
    print(f"Pitch stability completed in {elapsed:.1f}s ({elapsed/60:.1f} min)", flush=True)
    
    if result.returncode != 0:
        print(f"WARNING: Pitch stability returned non-zero exit code: {result.returncode}", flush=True)
        if result.stderr:
            print(f"STDERR: {result.stderr[-500:]}", flush=True)
    
    # Check if .stab file was created
    if not os.path.exists(stab_file):
        print(f"WARNING: {stab_file} not created - stability analysis may have failed", flush=True)
        return False
    
    return True

# ---------------------------------------------------------------------
# L/D extraction (α = 2–14°, step 2°)
# ---------------------------------------------------------------------
def extract_band_ld(results_path):
    alphas = np.arange(2, 15, 2)  # 2, 4, 6, 8, 10, 12, 14 (7 pts)

    with open(results_path, "r") as f:
        rows = [line.strip().split(",") for line in f if line.strip()]

    ld_row = next((r for r in rows if r[0].strip() == "L_D"), None)
    if ld_row is None:
        print(f"WARNING: L_D row not found in {results_path}. Available rows:", flush=True)
        # Print first 20 row headers for debugging
        for i, row in enumerate(rows[:20]):
            if row:
                print(f"  Row {i}: '{row[0].strip()}'", flush=True)
        return 0.001, None, None

    WINDOW = 3  # Reduced from 4 since we have fewer points now
    
    try:
        ld = np.array([float(v) for v in ld_row[1:1 + len(alphas)]])
        ld = -ld  # VSPAero outputs negative L/D
        # Removed hard ceiling - allow higher L/D but penalize sailplane-like designs (>20)
        ld = np.clip(ld, 0.0, 50.0)  # Upper bound to prevent numerical issues
        
        if len(ld) < WINDOW:
            print(f"WARNING: Only {len(ld)} L/D values found, need at least {WINDOW} for band calculation", flush=True)
            return 0.001, None, ld if len(ld) > 0 else None
    except (ValueError, IndexError) as e:
        print(f"WARNING: Error parsing L/D values from {results_path}: {e}", flush=True)
        print(f"  L_D row: {ld_row[:min(10, len(ld_row))]}", flush=True)
        return 0.001, None, None
    best_score = -np.inf
    best_idx = None

    for i in range(len(ld) - WINDOW + 1):
        band = ld[i:i + WINDOW]
        score = band.mean() - 0.2 * band.std()
        if score > best_score:
            best_score = score
            best_idx = i

    if best_idx is None or not np.isfinite(best_score) or best_score <= 0:
        print(f"WARNING: Invalid band L/D score: {best_score}, using fallback", flush=True)
        return 0.001, None, ld

    alpha_center = alphas[best_idx + WINDOW // 2] if best_idx is not None else None
    return best_score, alpha_center, ld

# ---------------------------------------------------------------------
# CG caching
# ---------------------------------------------------------------------
def get_cached_cg(x):
    """
    Get CG from cache if geometry is similar, otherwise return None to trigger recomputation.
    
    Uses parameter-specific tolerances:
    - Sweep: 0.2 deg (conservative - 1 deg sweep change can move CG by 0.5-1mm)
    - Span: 1.0 mm (moderate - affects CG position)
    - X Location: 0.5 mm (moderate - directly affects CG)
    - Others: Small tolerances (minor CG impact)
    """
    global _cg_cache, _cg_cache_tolerances
    
    # Create cache key by rounding each parameter to its specific tolerance
    key = tuple(
        round(v / tol) * tol 
        for v, tol in zip(x, _cg_cache_tolerances)
    )
    
    if key in _cg_cache:
        return _cg_cache[key]
    return None

def cache_cg(x, cg_x):
    """Cache CG for this geometry using parameter-specific tolerances."""
    global _cg_cache, _cg_cache_tolerances, _CG_CACHE_MAX_SIZE
    
    # Create cache key by rounding each parameter to its specific tolerance
    key = tuple(
        round(v / tol) * tol 
        for v, tol in zip(x, _cg_cache_tolerances)
    )
    
    # Limit cache size - if too large, clear oldest entries (simple FIFO)
    if len(_cg_cache) >= _CG_CACHE_MAX_SIZE:
        # Remove oldest 20% of entries (simple approach: clear all and let it rebuild)
        # In practice, cache should stay well below limit with conservative tolerances
        if len(_cg_cache) >= _CG_CACHE_MAX_SIZE * 1.5:
            print(f"[CACHE] Cache size ({len(_cg_cache)}) exceeded limit, clearing...", flush=True)
            _cg_cache.clear()
    
    _cg_cache[key] = cg_x

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
        # Fallback to Cm slope method if .stab file not found
        print(f"WARNING: {stab_file} not found, using Cm slope fallback method", flush=True)
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
        
        # Get X-coordinates (neutral point)
        # With single-alpha pitch stability, there should be only ONE AC location
        # If multiple found, use the first one (shouldn't happen with single alpha)
        xnp_values = [float(m[0]) for m in matches]
        if len(xnp_values) == 1:
            xnp = xnp_values[0]  # Single alpha = single AC location
        else:
            # Multiple ACs found (shouldn't happen with single alpha, but handle gracefully)
            print(f"WARNING: Found {len(xnp_values)} AC locations (expected 1 for single alpha), using first", flush=True)
            xnp = xnp_values[0]
        
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
        
        # Validate that neutral point is reasonable
        # VSPAero coordinates are relative to model origin (nose), same as wing X Location
        # If design_x is provided, check that Xnp is not ahead of wing leading edge
        invalid_geometry_penalty = 0.0
        if design_x is not None:
            span, sweep, xloc, taper, tip, ctrl = design_x
            wing_le_x = xloc  # Wing leading edge X position (from model origin/nose)
            # Aerodynamic center should be at or behind the wing leading edge
            # Allow small tolerance (20mm) for numerical precision, but flag if way ahead
            if xnp < wing_le_x - 20.0:  # More than 20mm ahead is suspicious
                print(f"\n[INVALID GEOMETRY DETECTED]", flush=True)
                print(f"  Neutral point ({xnp:.1f} mm) is {wing_le_x - xnp:.1f} mm ahead of wing LE ({wing_le_x:.1f} mm)", flush=True)
                print(f"  This is physically impossible. Applying penalty and using fallback method.", flush=True)
                # Penalize invalid geometry - this is a sign of a bad design
                invalid_geometry_penalty = 5.0  # Significant penalty for physically impossible results
                # Use fallback but add penalty
                result = extract_stability_fallback(results_path, cg_x)
                if len(result) == 5:
                    # Fallback returns 5 values, add penalty to crash_penalty and return 6 values
                    static_margin, crash_penalty, slug_penalty, xnp_fallback, mac_fallback = result
                    crash_penalty += invalid_geometry_penalty  # Add geometry penalty to crash penalty
                    return static_margin, crash_penalty, slug_penalty, xnp_fallback, mac_fallback, cg_x
                else:
                    # Fallback already returns 6 values
                    static_margin, crash_penalty, slug_penalty, xnp_fallback, mac_fallback, cg_x_fallback = result
                    crash_penalty += invalid_geometry_penalty
                    return static_margin, crash_penalty, slug_penalty, xnp_fallback, mac_fallback, cg_x_fallback
        
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
        # Don't silently fallback - penalize hard for extraction failures
        print(f"ERROR: Failed to extract stability from {stab_file}: {e}", flush=True)
        print(f"  Applying penalty - this indicates a problem with the analysis", flush=True)
        # Return large penalty instead of fallback
        return None, 5.0, 0.0, None, None, cg_x  # 5.0 penalty for extraction failure

def extract_stability_fallback(results_path, cg_x=310.0):
    """
    Fallback: Extract stability from Cm slope if stability file not available.
    Uses CMytot (total pitch moment) from Results.csv.
    Cm slope (dCm/dAlpha) is proportional to static margin.
    
    Returns: (static_margin_pct, crash_penalty, slug_penalty, xnp, mac, cg_x)
    All 6 values are always returned for consistency.
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
            return None, 0.0, 0.0, None, None, cg_x  # Returns 6 values
        
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
    global eval_counter, best_obj_so_far, best_x_so_far, prev_iter_obj, vspaero_time, _should_stop, _should_pause

    # Check for remote control commands
    check_control_files()
    
    # Handle pause
    if _should_pause:
        print("\n[PAUSED] Waiting for resume command...", flush=True)
        while _should_pause and not _should_stop:
            time.sleep(5)
            check_control_files()
            write_status_file()
        if _should_stop:
            raise KeyboardInterrupt("Stop requested via remote control")
    
    # Handle stop
    if _should_stop:
        raise KeyboardInterrupt("Stop requested via remote control")

    eval_counter += 1
    
    # Calculate generation from iteration count
    # Generation 0 = initial population (iterations 1-20, but iteration 1 is baseline)
    # So: iteration 1 = baseline, iterations 2-21 = generation 0, 22-41 = generation 1, etc.
    # After baseline: (eval_counter - 1) / popsize = generation number
    global generation_counter  # Need to declare as global to update it
    POPULATION_SIZE = 20  # Must match popsize in differential_evolution call
    if eval_counter > 1:  # After baseline
        generation_counter = (eval_counter - 2) // POPULATION_SIZE
    else:
        generation_counter = 0
    
    # Update status file (generation_counter is now calculated)
    write_status_file()
    span, sweep, xloc, taper, tip, ctrl = x

    elapsed_s = time.time() - t_start
    elapsed_min = elapsed_s / 60.0

    # Initialize vspaero_time in case run_vspaero() fails before setting it
    vspaero_time = 0.0

    # Trailing edge soft penalty
    sweep_rad = np.radians(sweep)
    te_x = xloc + np.sin(sweep_rad) * span + tip
    te_penalty = 0.0
    if te_x > 630.0:
        te_penalty = 0.002 * (te_x - 630.0) ** 2

    # =====================================================================
    # TIER 1: Cheap cruise analysis (L/D + geometry checks)
    # =====================================================================
    update_geometry_from_x(x)
    print(f"\n[TIER 1] Running cruise analysis (L/D sweep, no stability)...", flush=True)
    print(f"  Starting at {time.strftime('%H:%M:%S', time.localtime())}", flush=True)
    
    try:
        run_vspaero()  # Tier 1: Cruise only (no pitch stability)
    except RuntimeError as e:
        print(f"VSPAERO failed: {e}", flush=True)
        vspaero_time = 0.0
        # Penalize hard for failures - don't return clipped value
        return -100.0  # Strong negative penalty

    # Extract L/D data
    try:
        band_ld, alpha_center, ld_curve = extract_band_ld(RESULTS_CSV)
        if not np.isfinite(band_ld) or band_ld <= 0:
            print(f"[TIER 1] L/D extraction failed or invalid: {band_ld}", flush=True)
            band_ld = 0.0  # Don't use 0.001 - let penalties dominate
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
        print(f"[TIER 1] Error extracting L/D: {e}", flush=True)
        band_ld = 0.0
        alpha_center = None
        ld_curve = None
        ld_min = None
        ld_max = None
        ld_range = None

    # Get CG (use cache if available, otherwise extract from MassProp)
    cg_x_used = get_cached_cg(x)
    if cg_x_used is None:
        cg_x_used = extract_cg_from_results(RESULTS_CSV)
        if cg_x_used is None:
            # Fallback: estimate from geometry
            cg_x_used = xloc - 10.0
            print(f"[TIER 1] CG not found, using estimate: {cg_x_used:.1f} mm", flush=True)
        else:
            cache_cg(x, cg_x_used)  # Cache for future use
            print(f"[TIER 1] CG extracted: {cg_x_used:.1f} mm (cached)", flush=True)
    else:
        print(f"[TIER 1] CG from cache: {cg_x_used:.1f} mm", flush=True)

    # Calculate geometry penalties (before deciding on Tier 2)
    span_penalty = 0.0
    if span > 360.0:
        span_penalty = 0.001 * (span - 350.0) ** 2
    elif span < 320.0:
        span_penalty = 0.0005 * (330.0 - span) ** 2

    ld_penalty = 0.0
    if band_ld > 20.0:
        ld_penalty = 0.5 * (band_ld - 20.0) ** 2

    # =====================================================================
    # TIER 2 GATE: Only run expensive pitch stability for promising designs
    # =====================================================================
    # Gate criteria: L/D > 8.0 AND span penalty < 1.0
    # This filters out obviously bad designs before expensive stability analysis
    run_tier2 = (band_ld > 8.0) and (span_penalty < 1.0)
    
    static_margin = None
    crash_penalty = 0.0
    slug_penalty = 0.0
    gate_failure_penalty = 0.0  # Penalty for designs that don't pass Tier 2 gate
    xnp = None
    mac = None
    
    if run_tier2:
        print(f"\n[TIER 2] Design passed gate (L/D={band_ld:.2f} > 8.0, span_penalty={span_penalty:.3f} < 1.0)", flush=True)
        print(f"  Running pitch stability analysis (single alpha = 8 deg)...", flush=True)
        
        try:
            if run_pitch_stability():
                # Extract stability from single-alpha pitch analysis
                try:
                    static_margin, crash_penalty, slug_penalty, xnp, mac, cg_x_used = extract_stability_margin(
                        "Stability_Results.csv", RESULTS_CSV, cg_x=cg_x_used, design_x=x
                    )
                    print(f"[TIER 2] Stability extracted: SM={static_margin:.2f}%, Xnp={xnp:.1f} mm", flush=True)
                except Exception as e:
                    print(f"[TIER 2] Error extracting stability: {e}", flush=True)
                    # Penalize hard for stability extraction failure
                    crash_penalty = 5.0  # Significant penalty
                    static_margin = None
            else:
                print(f"[TIER 2] Pitch stability analysis failed - applying penalty", flush=True)
                crash_penalty = 5.0  # Penalize for failed analysis
        except Exception as e:
            print(f"[TIER 2] Pitch stability run failed: {e}", flush=True)
            crash_penalty = 5.0  # Penalize for failed run
    else:
        print(f"\n[TIER 2] Design failed gate (L/D={band_ld:.2f} <= 8.0 or span_penalty={span_penalty:.3f} >= 1.0)", flush=True)
        print(f"  Skipping expensive pitch stability analysis", flush=True)
        # Apply gate failure penalty to ensure these designs are clearly worse
        # This prevents optimizer from accidentally favoring designs that don't pass the gate
        gate_failure_penalty = 1.0  # Moderate penalty for not being promising enough
        print(f"[TIER 2] Applying gate failure penalty: {gate_failure_penalty:.2f}", flush=True)
        
        # Use Cm slope method from cruise results to estimate stability
        # This is cheaper than full pitch stability but still gives reasonable estimate
        try:
            static_margin, crash_penalty, slug_penalty, xnp, mac, cg_x_used = extract_stability_fallback(
                RESULTS_CSV, cg_x_used
            )
            print(f"[TIER 2] Stability estimated from Cm slope: SM={static_margin:.2f}% (if available)", flush=True)
            if static_margin is None:
                # If Cm slope extraction failed, apply moderate penalty
                static_margin = 10.0
                crash_penalty = 0.0
                slug_penalty = 0.0
                print(f"[TIER 2] Cm slope extraction failed, using neutral assumption", flush=True)
        except Exception as e:
            print(f"[TIER 2] Error estimating stability from Cm slope: {e}", flush=True)
            # Fallback to neutral assumption if extraction fails
            static_margin = 10.0
            crash_penalty = 0.0
            slug_penalty = 0.0
            xnp = None
            mac = None

    # Final objective with stability consideration
    # Weights: 60% efficiency, 20% agility, 20% stability
    # Crash penalty (100% weight) applied directly, slug penalty (35% weight) already scaled
    # REMOVED OBJECTIVE CLIPPING - let penalties dominate naturally to preserve gradient info
    obj = (
        0.6 * band_ld
        - 0.2 * span_penalty
        - crash_penalty  # Full weight (unstable = crash)
        - slug_penalty   # Already scaled to 35% weight
        - ld_penalty     # Penalize sailplane designs
        - te_penalty
        - gate_failure_penalty  # Penalty for designs that don't pass Tier 2 gate
    )
    # NO CLIPPING - if design is bad, let it go negative
    # This preserves gradient information for DE optimizer

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
    # Show raw L/D value and indicate if it's a fallback
    if band_ld == 0.001:
        print(f"  Band L/D:   {band_ld:6.4f}  |  Best at alpha: {alpha_str:>6} deg  [FALLBACK - L/D extraction may have failed]")
    else:
        print(f"  Band L/D:   {band_ld:6.4f}  |  Best at alpha: {alpha_str:>6} deg")
    
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
    total_penalty = span_penalty + te_penalty + ld_penalty + crash_penalty + slug_penalty + gate_failure_penalty
    if total_penalty > 0:
        print(f"\n[PENALTIES]")
        if span_penalty > 0:
            print(f"  Span:      {span_penalty:6.3f}")
        if te_penalty > 0:
            print(f"  Trailing Edge: {te_penalty:6.3f}")
        if ld_penalty > 0:
            print(f"  L/D (>20):  {ld_penalty:6.3f}")
        if gate_failure_penalty > 0:
            print(f"  Gate Failure: {gate_failure_penalty:6.3f} (didn't pass Tier 2 gate)")
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
    total_penalty = span_penalty + te_penalty + ld_penalty + crash_penalty + slug_penalty + gate_failure_penalty
    
    # Objective and convergence
    print(f"\n[OBJECTIVE]")
    print(f"  Raw Objective: {obj:7.4f} (no clipping - preserves gradient info)", flush=True)
    improvement = obj - prev_iter_obj if prev_iter_obj is not None else 0.0
    improvement_str = f"+{improvement:.4f}" if improvement > 0 else f"{improvement:.4f}"
    print(f"  Current:  {obj:7.4f}  ({improvement_str})", flush=True)
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
    global stagnation_counter, best_obj_so_far, eval_counter, generation_counter, _should_stop

    # Check for stop command
    check_control_files()
    if _should_stop:
        raise KeyboardInterrupt("Stop requested via remote control")
    
    generation_counter += 1  # Increment generation counter
    
    # Update status file
    write_status_file()
    
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
    # Set up output logging to file
    tee = TeeOutput(OUTPUT_LOG)
    sys.stdout = tee
    sys.stderr = tee  # Also capture errors
    
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
    
    # Write initial status to show optimizer is starting
    write_status_file()
    
    print("\n[STEP 1/2] Evaluating baseline design...")
    print("-"*80)
    evaluate_design(baseline)
    print("-"*80)

    print("\n[STEP 2/2] Starting differential evolution optimization...")
    print("="*80 + "\n")
    print(f"[REMOTE CONTROL] Status file: {STATUS_FILE}")
    print(f"[REMOTE CONTROL] Control file: {CONTROL_FILE}")
    print(f"[REMOTE CONTROL] Commands: 'stop', 'pause', 'resume'")
    print("="*80 + "\n")
    
    # Write initial status
    write_status_file()
    
    try:
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
    except KeyboardInterrupt as e:
        print("\n" + "="*80, flush=True)
        print("OPTIMIZATION INTERRUPTED", flush=True)
        print("="*80, flush=True)
        print(f"Reason: {e}", flush=True)
        write_status_file()
        # Update status to stopped
        status = {
            "status": "stopped",
            "paused": False,
            "iteration": eval_counter,
            "generation": generation_counter,
            "elapsed_seconds": time.time() - t_start,
            "elapsed_minutes": (time.time() - t_start) / 60.0,
            "best_objective": float(best_obj_so_far) if best_obj_so_far != -np.inf else None,
            "best_design": (best_x_so_far.tolist() if hasattr(best_x_so_far, 'tolist') else list(best_x_so_far)) if best_x_so_far is not None else None,
            "timestamp": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime()),
            "start_time": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t_start))
        }
        with open(STATUS_FILE, "w") as f:
            json.dump(status, f, indent=2)
        # Restore stdout before raising
        sys.stdout = tee.stdout
        sys.stderr = sys.__stderr__
        tee.close()
        raise
    except Exception as e:
        # Catch any other unexpected errors and write status before crashing
        print("\n" + "="*80, flush=True)
        print("OPTIMIZATION ERROR", flush=True)
        print("="*80, flush=True)
        print(f"Unexpected error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        try:
            status = {
                "status": "error",
                "paused": False,
                "iteration": eval_counter,
                "generation": generation_counter,
                "elapsed_seconds": time.time() - t_start,
                "elapsed_minutes": (time.time() - t_start) / 60.0,
                "best_objective": float(best_obj_so_far) if best_obj_so_far != -np.inf else None,
                "best_design": (best_x_so_far.tolist() if hasattr(best_x_so_far, 'tolist') else list(best_x_so_far)) if best_x_so_far is not None else None,
                "error": str(e),
                "timestamp": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime()),
                "start_time": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t_start))
            }
            with open(STATUS_FILE, "w") as f:
                json.dump(status, f, indent=2)
        except Exception as status_err:
            print(f"Warning: Could not write error status file: {status_err}", flush=True)
        # Restore stdout before raising
        sys.stdout = tee.stdout
        sys.stderr = sys.__stderr__
        tee.close()
        raise

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
    print(f"  Output Log:           {OUTPUT_LOG}")
    print(f"  Status File:          {STATUS_FILE}")
    print("="*80)
    
    # Write final status
    try:
        status = {
            "status": "completed",
            "paused": False,
            "iteration": eval_counter,
            "generation": generation_counter,
            "elapsed_seconds": total_s,
            "elapsed_minutes": total_min,
            "best_objective": float(best_obj_so_far) if best_obj_so_far != -np.inf else None,
            "best_design": (best_x_so_far.tolist() if hasattr(best_x_so_far, 'tolist') else list(best_x_so_far)) if best_x_so_far is not None else None,
            "timestamp": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime()),
            "start_time": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t_start))
        }
        with open(STATUS_FILE, "w") as f:
            json.dump(status, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not write final status file: {e}", flush=True)
    
    # Restore stdout and close log file
    sys.stdout = tee.stdout
    sys.stderr = sys.__stderr__
    tee.close()
