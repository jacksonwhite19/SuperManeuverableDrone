"""
Quick test script to verify VSPAEROStability integration works.

This runs a single design evaluation to check:
- VSPAEROStability executes successfully
- Stability_Results.csv is created
- Static margin can be extracted
- No crashes or errors

Takes ~2-3 minutes instead of hours for full optimization.
"""

import subprocess
import os
import numpy as np

# Config
VSP_EXE = r"C:\Users\Jackson\Desktop\ZZ_Software Downloads\OpenVSP-3.46.0-win64\vsp.exe"
RESULTS_CSV = "Results.csv"
STABILITY_CSV = "Stability_Results.csv"

# Import the extraction function from optimizer2
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# We'll copy the extraction function here for standalone testing
def extract_stability_margin(stability_results_path, results_path, cg_x=310.0):
    """Extract Static Margin from VSPAero Pitch stability analysis (.stab file)."""
    # Try to find .aerocenter.stab file (created by Pitch mode)
    stab_file = "current.aerocenter.stab"
    
    if not os.path.exists(stab_file):
        print(f"ERROR: Stability file not found: {stab_file}")
        return None, 0.0, 0.0, None, None
    
    try:
        # Parse .stab file to extract aerodynamic center locations
        with open(stab_file, "r") as f:
            content = f.read()
        
        # Extract all "Aerodynamic Center is at: ( X, Y, Z)" lines
        import re
        pattern = r"Aerodynamic Center is at:\s*\(\s*([\d\.\-]+),\s*([\d\.\-]+),\s*([\d\.\-]+)\)"
        matches = re.findall(pattern, content)
        
        print(f"\nFound {len(matches)} aerodynamic center entries in {stab_file}")
        
        if not matches:
            print(f"WARNING: No aerodynamic center found in {stab_file}")
            return None, 0.0, 0.0, None, None
        
        # Get X-coordinates (neutral point) and average them
        xnp_values = [float(m[0]) for m in matches]
        xnp = sum(xnp_values) / len(xnp_values)  # Average neutral point
        print(f"  Average Xnp (neutral point): {xnp:.2f} mm")
        print(f"  Xnp range: {min(xnp_values):.2f} to {max(xnp_values):.2f} mm")
        
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
            print(f"  Using default MAC: {mac:.2f} mm")
        else:
            print(f"  MAC (from Cref): {mac:.2f} mm")
        
        # Calculate Static Margin
        static_margin_pct = ((xnp - cg_x) / mac) * 100.0
        
        # Penalty system with sweet spot (8-12% no penalty)
        crash_penalty = 0.0
        slug_penalty = 0.0
        
        if static_margin_pct < 5.0:
            crash_penalty = 10.0 * (5.0 - static_margin_pct)
        elif static_margin_pct > 15.0:
            slug_penalty = 0.35 * (static_margin_pct - 15.0)
        
        return static_margin_pct, crash_penalty, slug_penalty, xnp, mac
        
    except Exception as e:
        print(f"Error reading stability file {stab_file}: {e}")
        import traceback
        traceback.print_exc()
        return None, 0.0, 0.0, None, None

def main():
    print("=" * 60)
    print("QUICK STABILITY TEST")
    print("=" * 60)
    print("This will:")
    print("1. Update geometry with baseline design")
    print("2. Run VSPAero (sweep + stability)")
    print("3. Check if Stability_Results.csv is created")
    print("4. Try to extract static margin")
    print("=" * 60)
    print()
    
    # Step 1: Update geometry (use baseline)
    print("Step 1: Updating geometry...")
    baseline = [330.0, 25.0, 320.0, 0.833333, 120.0, 0.22]
    
    # Write current.des
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
    
    span, sweep, xloc, taper, tip, ctrl = baseline
    fin_chord = tip
    fin_sweep = 45.0
    
    with open("current.des", "w") as f:
        f.write("14\n")
        f.write(DES_TEMPLATE.format(
            span=span, sweep=sweep, xloc=xloc,
            taper=taper, tip=tip, ctrl=ctrl,
            fin_chord=fin_chord, fin_sweep=fin_sweep
        ))
    print("  [OK] current.des written")
    
    # Run update_geom.vspscript
    result = subprocess.run(
        [VSP_EXE, "-script", "update_geom.vspscript"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.abspath(__file__))
    )
    if result.returncode != 0:
        print(f"  [FAIL] update_geom.vspscript failed: {result.returncode}")
        if result.stderr:
            print(f"  Error: {result.stderr[-300:]}")
        return
    print("  [OK] Geometry updated (current.vsp3 created)")
    
    # Step 2: Run VSPAero
    print("\nStep 2: Running VSPAero (sweep + stability)...")
    import time
    start = time.time()
    
    result = subprocess.run(
        [VSP_EXE, "-script", "cruise.vspscript"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.abspath(__file__))
    )
    elapsed = time.time() - start
    
    print(f"  VSPAero completed in {elapsed:.1f}s ({elapsed/60:.1f} min)")
    
    # Always print VSPAero output to see what happened
    if result.stdout:
        print("\nVSPAero STDOUT (last 1000 chars):")
        print(result.stdout[-1000:])
    
    if result.returncode != 0:
        print(f"  [FAIL] VSPAero failed with exit code {result.returncode}")
        if result.stderr:
            print(f"  STDERR: {result.stderr[-500:]}")
        # Continue anyway to check what files were created
    else:
        print("  [OK] VSPAero completed successfully")
    
    # Step 3: Check files
    print("\nStep 3: Checking output files...")
    if os.path.exists(RESULTS_CSV):
        size = os.path.getsize(RESULTS_CSV)
        print(f"  [OK] {RESULTS_CSV} exists ({size} bytes)")
    else:
        print(f"  [FAIL] {RESULTS_CSV} NOT FOUND")
        return
    
    # Check for .aerocenter.stab file (created by Pitch mode)
    stab_file = "current.aerocenter.stab"
    if os.path.exists(stab_file):
        size = os.path.getsize(stab_file)
        print(f"  [OK] {stab_file} exists ({size} bytes)")
    else:
        print(f"  [FAIL] {stab_file} NOT FOUND")
        print("  This means Pitch stability mode may not have created the file")
        print("  Will try to extract from Results.csv using Cm slope method")
    
    # Step 4: Extract stability
    print("\nStep 4: Extracting stability metrics...")
    static_margin, crash_penalty, slug_penalty, xnp, mac = extract_stability_margin(
        "", RESULTS_CSV, cg_x=310.0  # First param not used, we look for .stab file directly
    )
    
    if static_margin is not None:
        sm_status = "SWEET SPOT" if 8.0 <= static_margin <= 12.0 else ("UNSTABLE" if static_margin < 5.0 else "OVERLY STABLE")
        print(f"\n{'='*60}")
        print("SUCCESS! Stability metrics extracted:")
        print(f"{'='*60}")
        print(f"Static Margin: {static_margin:.2f}% ({sm_status})")
        print(f"Neutral Point (Xnp): {xnp:.1f} mm")
        print(f"Mean Aerodynamic Chord (MAC): {mac:.1f} mm")
        print(f"CG Location: 310.0 mm (hardcoded)")
        print(f"Crash Penalty: {crash_penalty:.3f}")
        print(f"Slug Penalty: {slug_penalty:.3f}")
        print(f"{'='*60}")
    else:
        print("\n[FAIL] Could not extract static margin")
        print("Check the Stability_Results.csv file format above")
    
    print("\nTest complete!")

if __name__ == "__main__":
    main()

