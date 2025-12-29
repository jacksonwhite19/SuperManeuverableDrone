"""
Analyze optimization results from opt_history.csv
Generates summary statistics and identifies best designs
"""

import csv
import os
import sys
import numpy as np

def analyze_results(history_file="opt_history.csv"):
    """
    Analyze optimization history and generate summary report.
    """
    if not os.path.exists(history_file):
        print(f"ERROR: {history_file} not found!")
        return
    
    print("="*80)
    print("OPTIMIZATION RESULTS ANALYSIS")
    print("="*80)
    
    # Read data
    iterations = []
    with open(history_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            iterations.append(row)
    
    if len(iterations) == 0:
        print("ERROR: No iterations found!")
        return
    
    # Extract numeric data
    data = {
        'iter': [], 'generation': [], 'final_obj': [], 'band_LD': [],
        'static_margin': [], 'span_mm': [], 'sweep_deg': [], 'xloc_mm': [],
        'taper': [], 'tip_mm': [], 'cg_x': [], 'xnp': [], 'mac': [],
        'total_penalty': [], 'vspaero_time_s': [], 'is_new_best': []
    }
    
    for it in iterations:
        try:
            for key in data.keys():
                val = it.get(key, 'N/A')
                if val != 'N/A' and val != '':
                    try:
                        data[key].append(float(val))
                    except (ValueError, TypeError):
                        data[key].append(None)
                else:
                    data[key].append(None)
        except Exception as e:
            continue
    
    # Convert to numpy arrays (filtering None values)
    def to_array(lst):
        return np.array([x for x in lst if x is not None])
    
    objs = to_array(data['final_obj'])
    if len(objs) == 0:
        print("ERROR: No valid objective values found!")
        return
    
    # Find best design
    best_idx = np.argmax(objs)
    best_iter = int(data['iter'][best_idx]) if best_idx < len(data['iter']) else None
    
    print(f"\n[OVERVIEW]")
    print(f"  Total Iterations: {len(iterations)}")
    if data['generation']:
        gens = [g for g in data['generation'] if g is not None]
        if gens:
            print(f"  Total Generations: {int(max(gens))}")
    print(f"  Best Iteration: {best_iter}")
    print(f"  Best Objective: {objs[best_idx]:.4f}")
    
    # Best design parameters
    if best_idx < len(iterations):
        best = iterations[best_idx]
        print(f"\n[BEST DESIGN]")
        print(f"  Span:      {best.get('span_mm', 'N/A')} mm")
        print(f"  Sweep:     {best.get('sweep_deg', 'N/A')} deg")
        print(f"  X Location: {best.get('xloc_mm', 'N/A')} mm")
        print(f"  Taper:     {best.get('taper', 'N/A')}")
        print(f"  Tip Chord:  {best.get('tip_mm', 'N/A')} mm")
        print(f"  Control:   {best.get('ctrl_frac', 'N/A')}")
        
        sm = best.get('static_margin', 'N/A')
        if sm != 'N/A' and sm != '':
            print(f"  Static Margin: {float(sm):.2f}% ({best.get('sm_category', 'N/A')})")
        print(f"  Band L/D:   {best.get('band_LD', 'N/A')}")
        print(f"  CG:         {best.get('cg_x', 'N/A')} mm")
        print(f"  Neutral Pt: {best.get('xnp', 'N/A')} mm")
    
    # Statistics
    print(f"\n[STATISTICS]")
    print(f"  Objective Range: {np.min(objs):.4f} - {np.max(objs):.4f}")
    print(f"  Objective Mean:  {np.mean(objs):.4f} ± {np.std(objs):.4f}")
    print(f"  Improvement from Baseline: {objs[best_idx] - objs[0]:.4f} ({((objs[best_idx]/objs[0] - 1)*100):.1f}%)")
    
    # Stability statistics
    sm_vals = to_array(data['static_margin'])
    if len(sm_vals) > 0:
        print(f"\n[STABILITY]")
        print(f"  Static Margin Range: {np.min(sm_vals):.2f}% - {np.max(sm_vals):.2f}%")
        print(f"  Static Margin Mean:  {np.mean(sm_vals):.2f}% ± {np.std(sm_vals):.2f}%")
        
        # Count by category
        categories = {}
        for it in iterations:
            cat = it.get('sm_category', 'unknown')
            categories[cat] = categories.get(cat, 0) + 1
        print(f"  Distribution:")
        for cat, count in sorted(categories.items()):
            pct = (count / len(iterations)) * 100
            print(f"    {cat:15s}: {count:3d} ({pct:5.1f}%)")
    
    # Performance statistics
    ld_vals = to_array(data['band_LD'])
    if len(ld_vals) > 0:
        print(f"\n[PERFORMANCE]")
        print(f"  Band L/D Range: {np.min(ld_vals):.4f} - {np.max(ld_vals):.4f}")
        print(f"  Band L/D Mean:  {np.mean(ld_vals):.4f} ± {np.std(ld_vals):.4f}")
    
    # Timing statistics
    time_vals = to_array(data['vspaero_time_s'])
    if len(time_vals) > 0:
        print(f"\n[TIMING]")
        print(f"  Avg VSPAero Time: {np.mean(time_vals)/60:.1f} min ({np.mean(time_vals):.1f} s)")
        print(f"  Min: {np.min(time_vals)/60:.1f} min  |  Max: {np.max(time_vals)/60:.1f} min")
        total_time = np.sum(time_vals)
        print(f"  Total Analysis Time: {total_time/3600:.2f} hours ({total_time/60:.1f} min)")
    
    # Convergence analysis
    if len(objs) > 1:
        print(f"\n[CONVERGENCE]")
        # Find when best was found
        best_so_far = np.maximum.accumulate(objs)
        last_improvement = np.where(best_so_far == objs[best_idx])[0][0]
        print(f"  Best found at iteration: {last_improvement + 1}")
        print(f"  Iterations since improvement: {len(objs) - last_improvement - 1}")
        
        # Recent trend (last 10%)
        recent_size = max(1, len(objs) // 10)
        recent_objs = objs[-recent_size:]
        if len(recent_objs) > 1:
            recent_trend = (recent_objs[-1] - recent_objs[0]) / recent_objs[0] * 100
            print(f"  Recent trend (last {recent_size} iters): {recent_trend:+.2f}%")
    
    # Top 5 designs
    top_indices = np.argsort(objs)[-5:][::-1]
    print(f"\n[TOP 5 DESIGNS]")
    for i, idx in enumerate(top_indices, 1):
        it = iterations[idx]
        print(f"  {i}. Iter {int(data['iter'][idx])}: Obj={objs[idx]:.4f}, "
              f"SM={it.get('static_margin', 'N/A')}, L/D={it.get('band_LD', 'N/A')}")
    
    print("="*80)

if __name__ == "__main__":
    history_file = sys.argv[1] if len(sys.argv) > 1 else "opt_history.csv"
    analyze_results(history_file)

