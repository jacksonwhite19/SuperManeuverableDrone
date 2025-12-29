"""
Export the best design from opt_history.csv to a .des file
Useful for running the best design again or sharing it
"""

import csv
import sys
import os

def export_best_design(history_file="opt_history.csv", output_file="best_design.des"):
    """
    Find the best design from history and export it to a .des file.
    """
    if not os.path.exists(history_file):
        print(f"ERROR: {history_file} not found!")
        return False
    
    # Read data
    iterations = []
    with open(history_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            iterations.append(row)
    
    if len(iterations) == 0:
        print("ERROR: No iterations found!")
        return False
    
    # Find best design (highest objective)
    best_iter = None
    best_obj = float('-inf')
    
    for it in iterations:
        try:
            obj = float(it.get('final_obj', '-inf'))
            if obj > best_obj:
                best_obj = obj
                best_iter = it
        except (ValueError, TypeError):
            continue
    
    if best_iter is None:
        print("ERROR: Could not find valid best design!")
        return False
    
    # Extract parameters
    try:
        span = float(best_iter['span_mm'])
        sweep = float(best_iter['sweep_deg'])
        xloc = float(best_iter['xloc_mm'])
        taper = float(best_iter['taper'])
        tip = float(best_iter['tip_mm'])
        ctrl = float(best_iter['ctrl_frac'])
    except (KeyError, ValueError) as e:
        print(f"ERROR: Could not extract design parameters: {e}")
        return False
    
    # DES file template (same format as optimizer2.py)
    # Uses OpenVSP parameter IDs
    fin_chord = tip  # fin chord equals tip chord
    fin_sweep = 45.0  # fixed
    
    # Write .des file (14 lines total)
    with open(output_file, 'w') as f:
        f.write("14\n")
        f.write(f"ZVZTXUKAZWE:Lwing:XSec_1:Span: {span:.6f}\n")
        f.write(f"QTIUMVPVMNM:Lwing:XSec_1:Sweep: {sweep:.6f}\n")
        f.write(f"QDYUWWIMJJA:Lwing:XSec_1:Taper: {taper:.6f}\n")
        f.write(f"IQQQXPRMWKO:Lwing:XSec_1:Tip_Chord: {tip:.6f}\n")
        f.write(f"VEBCTUVXEVB:Lwing:XForm:X_Rel_Location: {xloc:.6f}\n")
        f.write(f"EZZPYZAMUNE:Lwing:SS_Control_1:Length_C_Start: {ctrl:.6f}\n")
        f.write(f"JOOKRGHFGUK:Rwing:SS_Control_1:Length_C_Start: {ctrl:.6f}\n")
        f.write(f"QSAPUXPYQWU:Rwing:XForm:X_Rel_Location: {xloc:.6f}\n")
        f.write(f"FLPOVAIKYMN:Rwing:XSec_1:Span: {span:.6f}\n")
        f.write(f"OELVSBZPUKI:Rwing:XSec_1:Sweep: {sweep:.6f}\n")
        f.write(f"WETEDEKPMBU:Rwing:XSec_1:Taper: {taper:.6f}\n")
        f.write(f"UQYSYUAIZXN:Rwing:XSec_1:Tip_Chord: {tip:.6f}\n")
        f.write(f"ARLMRMBRQTY:TailGeom:XSec_1:Root_Chord: {fin_chord:.6f}\n")
        f.write(f"OJGNBNXLMTG:TailGeom:XSec_1:Sweep: {fin_sweep:.6f}\n")
    
    print(f"Best design exported to: {output_file}")
    print(f"  Objective: {best_obj:.4f}")
    print(f"  Parameters: span={span:.1f}, sweep={sweep:.1f}, xloc={xloc:.1f}, taper={taper:.3f}, tip={tip:.1f}, ctrl={ctrl:.3f}")
    print(f"  Static Margin: {best_iter.get('static_margin', 'N/A')}")
    print(f"  Band L/D: {best_iter.get('band_LD', 'N/A')}")
    
    return True

if __name__ == "__main__":
    output_file = sys.argv[1] if len(sys.argv) > 1 else "best_design.des"
    export_best_design(output_file=output_file)

