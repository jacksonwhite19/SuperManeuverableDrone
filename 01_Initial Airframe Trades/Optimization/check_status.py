"""
Quick status checker for running optimizer
Shows current progress, best design, and recent evaluations

SAFETY: This script is completely read-only and non-intrusive.
It only reads files and never writes, locks, or modifies anything.
Safe to run while optimizer is running.
"""

import json
import csv
import os
import sys
from datetime import datetime, timedelta

# Get the directory where this script is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Status files are in the same directory as this script
STATUS_FILE = os.path.join(SCRIPT_DIR, "optimizer_status.json")
HISTORY_FILE = os.path.join(SCRIPT_DIR, "opt_history.csv")

def format_time(seconds):
    """Format seconds into readable time string."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"

def check_status():
    """Read and display optimizer status. Completely read-only and non-intrusive."""
    
    print("="*80)
    print("OPTIMIZER STATUS CHECK")
    print("="*80)
    print()
    
    # Read status file - read-only, with timeout and error handling
    if not os.path.exists(STATUS_FILE):
        print(f"⚠️  Status file not found: {STATUS_FILE}")
        print("   Optimizer may not be running or hasn't started yet.")
        return
    
    status = None
    try:
        # Read-only mode, non-blocking
        with open(STATUS_FILE, 'r', encoding='utf-8') as f:
            status = json.load(f)
    except (json.JSONDecodeError, IOError, OSError) as e:
        print(f"⚠️  Could not read status file (may be locked by optimizer): {e}")
        print("   This is normal - optimizer is likely writing to it. Try again in a moment.")
        return
    except Exception as e:
        print(f"⚠️  Unexpected error reading status file: {e}")
        return
    
    if status is None:
        return
    
    # Display status
    print(f"[STATUS] {status.get('status', 'unknown').upper()}")
    if status.get('paused', False):
        print("         ⚠️  PAUSED")
    print()
    
    # Progress
    iteration = status.get('iteration', 0)
    generation = status.get('generation', 0)
    elapsed_min = status.get('elapsed_minutes', 0)
    elapsed_hr = elapsed_min / 60.0
    
    print(f"[PROGRESS]")
    print(f"  Iterations:  {iteration}")
    print(f"  Generations: {generation}")
    print(f"  Elapsed:     {format_time(status.get('elapsed_seconds', 0))} ({elapsed_hr:.1f} hours)")
    
    if iteration > 0:
        avg_time = status.get('elapsed_seconds', 0) / iteration
        print(f"  Avg/Iter:    {avg_time:.1f}s ({avg_time/60:.1f} min)")
    
    last_vsp_time = status.get('last_vspaero_time', 0)
    if last_vsp_time > 0:
        print(f"  Last VSP:    {last_vsp_time:.1f}s ({last_vsp_time/60:.1f} min)")
    print()
    
    # Best design
    best_obj = status.get('best_objective')
    best_design = status.get('best_design')
    
    if best_obj is not None:
        print(f"[BEST DESIGN]")
        print(f"  Objective: {best_obj:.4f}")
        if best_design:
            span, sweep, xloc, taper, tip, ctrl = best_design
            print(f"  Span:      {span:.1f} mm")
            print(f"  Sweep:     {sweep:.1f} deg")
            print(f"  X Location: {xloc:.1f} mm")
            print(f"  Taper:     {taper:.3f}")
            print(f"  Tip Chord: {tip:.1f} mm")
            print(f"  Control:   {ctrl:.3f}")
        print()
    else:
        print(f"[BEST DESIGN] None yet")
        print()
    
    # Timestamps
    start_time = status.get('start_time')
    timestamp = status.get('timestamp')
    if start_time:
        print(f"[TIMING]")
        print(f"  Started:    {start_time}")
        if timestamp:
            print(f"  Last Update: {timestamp}")
        print()
    
    # Recent history from CSV - read-only, safe to read while optimizer writes
    if os.path.exists(HISTORY_FILE):
        try:
            # Read-only, non-blocking - safe even if optimizer is writing
            with open(HISTORY_FILE, 'r', encoding='utf-8', errors='ignore') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                
            if rows:
                print(f"[RECENT EVALUATIONS] (last 5)")
                print("-"*80)
                # Show last 5 rows
                for row in rows[-5:]:
                    eval_num = row.get('iter', row.get('eval', '?'))
                    try:
                        obj = float(row.get('final_obj', row.get('objective', 0)))
                        ld = float(row.get('band_LD', row.get('band_ld', 0)))
                        sm = float(row.get('static_margin', row.get('static_margin_pct', 0)))
                        span = float(row.get('span_mm', row.get('span', 0)))
                        sweep = float(row.get('sweep_deg', row.get('sweep', 0)))
                        print(f"  Eval {eval_num:>4}: Obj={obj:>8.4f} | L/D={ld:>6.2f} | SM={sm:>5.1f}% | "
                              f"Span={span:>5.1f}mm | Sweep={sweep:>4.1f}deg")
                    except (ValueError, TypeError) as e:
                        print(f"  Eval {eval_num}: Error parsing row - {e}")
                print()
                
                # Show trend
                if len(rows) >= 2:
                    recent_objs = []
                    for r in rows[-10:]:
                        obj_val = r.get('final_obj', r.get('objective', ''))
                        if obj_val and obj_val != '':
                            try:
                                recent_objs.append(float(obj_val))
                            except (ValueError, TypeError):
                                pass
                    if len(recent_objs) >= 2:
                        trend = recent_objs[-1] - recent_objs[0]
                        if trend > 0:
                            print(f"[TREND] Improving: +{trend:.4f} over last {len(recent_objs)} evals")
                        elif trend < 0:
                            print(f"[TREND] Declining: {trend:.4f} over last {len(recent_objs)} evals")
                        else:
                            print(f"[TREND] Stable over last {len(recent_objs)} evals")
                        print()
        except (IOError, OSError) as e:
            # File may be locked by optimizer - this is fine, just skip history
            print(f"[HISTORY] File locked by optimizer (normal) - skipping recent evaluations")
            print()
        except Exception as e:
            # Any other error - don't crash, just skip
            print(f"[HISTORY] Could not read history file: {e}")
            print()
    
    print("="*80)
    print(f"Run this script anytime to check status: python check_status.py")
    print("="*80)

if __name__ == "__main__":
    try:
        check_status()
    except KeyboardInterrupt:
        # User interrupted - exit cleanly
        print("\n\nStatus check interrupted by user.")
        sys.exit(0)
    except Exception as e:
        # Any unexpected error - don't crash, just report and exit
        print(f"\n\n⚠️  Unexpected error in status checker: {e}")
        print("   This does NOT affect the optimizer - it continues running safely.")
        sys.exit(1)

