"""
Test script to run baseline configuration and extract all stability metrics.
Outputs: Neutral Point, Static Margin, CG Location, MAC, and penalties.
"""

import os
import sys
import subprocess
import time
import re

# Add current directory to path to import optimizer functions
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import from optimizer2
from optimizer2 import (
    VSP_EXE, RESULTS_CSV, extract_cg_from_results, 
    extract_stability_margin, extract_band_ld
)

# Baseline design parameters
BASELINE_X = [330.0, 25.0, 320.0, 0.833333, 120.0, 0.22]  # span, sweep, xloc, taper, tip, ctrl

def update_geometry_from_x(x):
    """Update geometry from design vector."""
    from optimizer2 import write_des_from_x
    
    write_des_from_x(x, "current.des")
    
    result = subprocess.run(
        [VSP_EXE, "-script", "update_geom.vspscript"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.abspath(__file__))
    )
    if result.returncode != 0:
        print(f"ERROR: update_geom.vspscript failed: {result.returncode}", flush=True)
        if result.stderr:
            print(f"STDERR: {result.stderr[-500:]}", flush=True)
        raise RuntimeError("Failed to update geometry")
    
    if not os.path.exists("current.vsp3"):
        raise RuntimeError("current.vsp3 not created")

def run_vspaero():
    """Run VSPAero analysis (includes MassProp)."""
    if os.path.exists(RESULTS_CSV):
        os.remove(RESULTS_CSV)
    
    start = time.time()
    result = subprocess.run(
        [VSP_EXE, "-script", "cruise.vspscript"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.abspath(__file__))
    )
    elapsed = time.time() - start
    
    if result.returncode != 0:
        print(f"ERROR: cruise.vspscript failed: {result.returncode}", flush=True)
        if result.stdout:
            print(f"STDOUT (last 1000 chars): {result.stdout[-1000:]}", flush=True)
        raise RuntimeError("VSPAero failed")
    
    if not os.path.exists(RESULTS_CSV):
        raise RuntimeError("No Results.csv produced")
    
    return elapsed

def main():
    print("=" * 80)
    print("BASELINE CONFIGURATION STABILITY ANALYSIS")
    print("=" * 80)
    print(f"\nBaseline Design:")
    print(f"  Span: {BASELINE_X[0]:.1f} mm")
    print(f"  Sweep: {BASELINE_X[1]:.1f} deg")
    print(f"  X Location: {BASELINE_X[2]:.1f} mm")
    print(f"  Taper: {BASELINE_X[3]:.4f}")
    print(f"  Tip: {BASELINE_X[4]:.1f} mm")
    print(f"  Control Fraction: {BASELINE_X[5]:.3f}")
    
    # Step 1: Update geometry
    print("\n" + "-" * 80)
    print("Step 1: Updating geometry from baseline design...")
    try:
        update_geometry_from_x(BASELINE_X)
        print("  [OK] Geometry updated (current.vsp3 created)")
    except Exception as e:
        print(f"  [FAIL] Geometry update failed: {e}")
        return
    
    # Step 2: Run VSPAero (includes MassProp)
    print("\n" + "-" * 80)
    print("Step 2: Running VSPAero analysis (MassProp + Sweep + Stability)...")
    try:
        elapsed = run_vspaero()
        print(f"  [OK] VSPAero completed in {elapsed:.1f}s ({elapsed/60:.1f} min)")
    except Exception as e:
        print(f"  [FAIL] VSPAero failed: {e}")
        return
    
    # Step 3: Extract CG from MassProp
    print("\n" + "-" * 80)
    print("Step 3: Extracting CG from MassProp results...")
    cg_x = extract_cg_from_results(RESULTS_CSV)
    if cg_x is not None:
        print(f"  [OK] CG X-location: {cg_x:.2f} mm")
    else:
        print(f"  [WARNING] Could not extract CG, using fallback (310.0 mm)")
        cg_x = 310.0
    
    # Step 4: Extract stability metrics
    print("\n" + "-" * 80)
    print("Step 4: Extracting stability metrics...")
    try:
        static_margin, crash_penalty, slug_penalty, xnp, mac, cg_x_used = extract_stability_margin(
            "Stability_Results.csv", RESULTS_CSV, cg_x=cg_x, design_x=None
        )
        
        if static_margin is not None:
            print("  [OK] Stability metrics extracted successfully")
        else:
            print("  [WARNING] Could not extract static margin (using fallback)")
    except Exception as e:
        print(f"  [FAIL] Error extracting stability: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Step 5: Extract L/D metrics
    print("\n" + "-" * 80)
    print("Step 5: Extracting L/D metrics...")
    try:
        band_ld, alpha_center, ld_curve = extract_band_ld(RESULTS_CSV)
        if band_ld is not None:
            alpha_str = f"{alpha_center:.1f}" if alpha_center is not None else "N/A"
            print(f"  [OK] Band L/D: {band_ld:.4f} at alpha = {alpha_str} deg")
        else:
            print(f"  [WARNING] Band L/D extraction returned None")
            band_ld = None
            alpha_center = None
            ld_curve = None
    except Exception as e:
        print(f"  [WARNING] Could not extract L/D: {e}")
        import traceback
        traceback.print_exc()
        band_ld = None
        alpha_center = None
        ld_curve = None
    
    # Step 6: Display results
    print("\n" + "=" * 80)
    print("RESULTS SUMMARY")
    print("=" * 80)
    
    print(f"\n[MASS PROPERTIES]")
    print(f"  CG Location (X): {cg_x_used:.2f} mm")
    print(f"  CG Source: MassProp analysis (dynamic)")
    
    print(f"\n[AERODYNAMICS]")
    if xnp is not None:
        print(f"  Neutral Point (Xnp): {xnp:.2f} mm")
    else:
        print(f"  Neutral Point (Xnp): N/A (not extracted)")
    
    if mac is not None:
        print(f"  Mean Aerodynamic Chord (MAC): {mac:.2f} mm")
    else:
        print(f"  Mean Aerodynamic Chord (MAC): N/A")
    
    if static_margin is not None:
        # Determine stability status
        if static_margin < 5.0:
            status = "UNSTABLE [WARNING]"
        elif static_margin > 15.0:
            status = "OVERLY STABLE (Sluggish)"
        elif 8.0 <= static_margin <= 12.0:
            status = "SWEET SPOT [OK]"
        else:
            status = "ACCEPTABLE"
        
        print(f"\n[STATIC MARGIN]")
        print(f"  Static Margin: {static_margin:.2f}% ({status})")
        print(f"  Calculation: SM = (Xnp - Xcg) / MAC * 100")
        if xnp is not None and mac is not None:
            print(f"  Formula: ({xnp:.2f} - {cg_x_used:.2f}) / {mac:.2f} * 100 = {static_margin:.2f}%")
        
        print(f"\n[PENALTIES]")
        print(f"  Crash Penalty (SM < 5%): {crash_penalty:.4f}")
        print(f"  Slug Penalty (SM > 15%): {slug_penalty:.4f}")
    else:
        print(f"\n[STATIC MARGIN]: N/A (could not be calculated)")
    
    if band_ld is not None:
        print(f"\n[PERFORMANCE]")
        print(f"  Band Mean L/D: {band_ld:.4f}")
        if alpha_center is not None:
            print(f"  Best L/D at alpha: {alpha_center:.1f} deg")
        if ld_curve is not None:
            alphas = [2, 4, 6, 8, 10, 12, 14]
            print(f"  L/D at each alpha:")
            for i, alpha in enumerate(alphas):
                if i < len(ld_curve):
                    print(f"    alpha = {alpha:2d} deg: L/D = {ld_curve[i]:.3f}")
    
    print(f"\n" + "=" * 80)
    print("Analysis complete!")
    print("=" * 80)

if __name__ == "__main__":
    main()

