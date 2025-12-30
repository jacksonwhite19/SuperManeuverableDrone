"""Quick script to check if optimizer is actually progressing"""
import csv
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(SCRIPT_DIR, "opt_history.csv")

if not os.path.exists(HISTORY_FILE):
    print("History file not found!")
    exit(1)

rows = list(csv.DictReader(open(HISTORY_FILE)))
best_objs = []
for r in rows:
    obj_val = r.get('final_obj', '').strip()
    if obj_val and obj_val != 'N/A':
        try:
            best_objs.append(float(obj_val))
        except:
            pass

if not best_objs:
    print("No valid objectives found!")
    exit(1)

print("="*80)
print("OPTIMIZER PROGRESS ANALYSIS")
print("="*80)
print(f"\nTotal Evaluations: {len(rows)}")
print(f"Valid Objectives: {len(best_objs)}")
print(f"\nFirst 5 objectives: {[f'{x:.2f}' for x in best_objs[:5]]}")
print(f"Last 5 objectives:  {[f'{x:.2f}' for x in best_objs[-5:]]}")
print(f"\nBest Overall: {max(best_objs):.4f}")
print(f"Worst Overall: {min(best_objs):.4f}")
print(f"Range: {max(best_objs) - min(best_objs):.4f}")

# Check if improving
if len(best_objs) >= 20:
    first_10_avg = sum(best_objs[:10]) / 10
    last_10_avg = sum(best_objs[-10:]) / 10
    improvement = last_10_avg - first_10_avg
    print(f"\nFirst 10 avg: {first_10_avg:.4f}")
    print(f"Last 10 avg:  {last_10_avg:.4f}")
    if improvement > 0.1:
        print(f"[IMPROVING] +{improvement:.4f}")
    elif improvement < -0.1:
        print(f"[DECLINING] {improvement:.4f}")
    else:
        print(f"[STABLE] {improvement:.4f}")

# Find best design
best_idx = best_objs.index(max(best_objs))
best_row = rows[best_idx]
print(f"\n[BEST DESIGN] (Iteration {best_row.get('iter', '?')})")
print(f"  Objective: {max(best_objs):.4f}")
print(f"  L/D: {best_row.get('band_LD', 'N/A')}")
print(f"  Static Margin: {best_row.get('static_margin', 'N/A')}%")
print("="*80)

