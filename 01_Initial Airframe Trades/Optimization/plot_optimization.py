"""
Enhanced plotting script for optimization results
Plots convergence, design space exploration, and stability metrics
"""

import csv
import numpy as np
import sys
import os

try:
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    print("WARNING: matplotlib not available. Install with: pip install matplotlib")

def plot_optimization(history_file="opt_history.csv"):
    """
    Create comprehensive plots of optimization results.
    """
    if not HAS_MATPLOTLIB:
        print("Cannot create plots without matplotlib.")
        return None
    
    if not os.path.exists(history_file):
        print(f"ERROR: {history_file} not found!")
        return None
    
    # Read data
    iterations = []
    with open(history_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            iterations.append(row)
    
    if len(iterations) == 0:
        print("ERROR: No iterations found!")
        return None
    
    # Extract data
    data = {}
    keys = ['iter', 'generation', 'final_obj', 'band_LD', 'static_margin', 
            'span_mm', 'sweep_deg', 'xloc_mm', 'taper', 'tip_mm', 'cg_x',
            'total_penalty', 'sm_category']
    
    for key in keys:
        data[key] = []
        for it in iterations:
            val = it.get(key, 'N/A')
            if val != 'N/A' and val != '':
                try:
                    data[key].append(float(val))
                except (ValueError, TypeError):
                    data[key].append(None)
            else:
                data[key].append(None)
    
    # Convert to arrays (filtering None)
    def to_array(lst):
        return np.array([x for x in lst if x is not None])
    
    iter_nums = np.array([int(x) for x in data['iter'] if x is not None])
    objs = to_array(data['final_obj'])
    band_ld = to_array(data['band_LD'])
    sm = to_array(data['static_margin'])
    
    if len(objs) == 0:
        print("ERROR: No valid data found!")
        return None
    
    # Create figure
    fig = plt.figure(figsize=(16, 12))
    
    # Plot 1: Objective progression
    ax1 = plt.subplot(3, 3, 1)
    ax1.plot(iter_nums, objs, 'b-', alpha=0.6, linewidth=1, label='All')
    best_obj = np.maximum.accumulate(objs)
    ax1.plot(iter_nums[:len(best_obj)], best_obj, 'g-', linewidth=2, label='Best So Far')
    ax1.axhline(y=objs[0], color='r', linestyle='--', alpha=0.7, label='Baseline')
    ax1.set_xlabel('Iteration')
    ax1.set_ylabel('Objective')
    ax1.set_title('Objective Function Progression')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Plot 2: L/D vs Static Margin trade-off
    ax2 = plt.subplot(3, 3, 2)
    if len(band_ld) > 0 and len(sm) > 0:
        # Color by category if available
        categories = data.get('sm_category', [])
        colors = {'sweet_spot': 'green', 'acceptable': 'blue', 
                 'unstable': 'red', 'overly_stable': 'orange', 'unknown': 'gray'}
        for i, cat in enumerate(categories):
            if i < len(band_ld) and i < len(sm):
                color = colors.get(cat, 'gray')
                ax2.scatter(sm[i], band_ld[i], c=color, alpha=0.6, s=30)
        
        # Highlight sweet spot region
        ax2.axvspan(8, 12, alpha=0.2, color='green', label='Sweet Spot')
        ax2.set_xlabel('Static Margin (%)')
        ax2.set_ylabel('Band L/D')
        ax2.set_title('L/D vs Static Margin Trade-off')
        ax2.legend()
        ax2.grid(True, alpha=0.3)
    
    # Plot 3: Static Margin progression
    ax3 = plt.subplot(3, 3, 3)
    if len(sm) > 0:
        ax3.plot(iter_nums[:len(sm)], sm, 'b-', alpha=0.6, linewidth=1)
        ax3.axhspan(8, 12, alpha=0.2, color='green', label='Sweet Spot')
        ax3.axhline(y=5, color='r', linestyle='--', alpha=0.5, label='Unstable Threshold')
        ax3.axhline(y=15, color='orange', linestyle='--', alpha=0.5, label='Over-stable Threshold')
        ax3.set_xlabel('Iteration')
        ax3.set_ylabel('Static Margin (%)')
        ax3.set_title('Static Margin Progression')
        ax3.legend()
        ax3.grid(True, alpha=0.3)
    
    # Plot 4-6: Design parameters
    params = [
        ('span_mm', 'Span (mm)', 4),
        ('sweep_deg', 'Sweep (deg)', 5),
        ('xloc_mm', 'X Location (mm)', 6)
    ]
    
    for param_key, param_label, subplot_idx in params:
        ax = plt.subplot(3, 3, subplot_idx)
        param_vals = to_array(data[param_key])
        if len(param_vals) > 0:
            ax.scatter(iter_nums[:len(param_vals)], param_vals, alpha=0.6, s=20)
            if len(param_vals) > 0:
                ax.axhline(y=param_vals[0], color='r', linestyle='--', alpha=0.7, label='Baseline')
            ax.set_xlabel('Iteration')
            ax.set_ylabel(param_label)
            ax.set_title(f'{param_label} Variation')
            ax.legend()
            ax.grid(True, alpha=0.3)
    
    # Plot 7: CG progression (should change with geometry)
    ax7 = plt.subplot(3, 3, 7)
    cg_vals = to_array(data['cg_x'])
    if len(cg_vals) > 0:
        ax7.plot(iter_nums[:len(cg_vals)], cg_vals, 'purple', alpha=0.6, linewidth=1)
        ax7.set_xlabel('Iteration')
        ax7.set_ylabel('CG X (mm)')
        ax7.set_title('CG Location (Dynamic)')
        ax7.grid(True, alpha=0.3)
    
    # Plot 8: Penalties
    ax8 = plt.subplot(3, 3, 8)
    penalty_vals = to_array(data['total_penalty'])
    if len(penalty_vals) > 0:
        ax8.plot(iter_nums[:len(penalty_vals)], penalty_vals, 'r-', alpha=0.6, linewidth=1)
        ax8.set_xlabel('Iteration')
        ax8.set_ylabel('Total Penalty')
        ax8.set_title('Penalty Progression')
        ax8.grid(True, alpha=0.3)
    
    # Plot 9: Generation summary
    ax9 = plt.subplot(3, 3, 9)
    gen_vals = to_array(data['generation'])
    if len(gen_vals) > 0:
        # Average objective per generation
        unique_gens = np.unique(gen_vals)
        gen_avg_obj = []
        for gen in unique_gens:
            mask = gen_vals == gen
            gen_avg_obj.append(np.mean(objs[:len(gen_vals)][mask]))
        
        ax9.plot(unique_gens, gen_avg_obj, 'b-o', linewidth=2, markersize=6)
        ax9.set_xlabel('Generation')
        ax9.set_ylabel('Avg Objective')
        ax9.set_title('Average Objective per Generation')
        ax9.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    # Save figure
    output_file = history_file.replace('.csv', '_plots.png')
    try:
        plt.savefig(output_file, dpi=150, bbox_inches='tight')
        print(f"Plots saved to: {output_file}")
    except Exception as e:
        print(f"Warning: Could not save plots: {e}")
    
    try:
        plt.show()
    except:
        pass
    
    return fig

if __name__ == "__main__":
    history_file = sys.argv[1] if len(sys.argv) > 1 else "opt_history.csv"
    plot_optimization(history_file)

