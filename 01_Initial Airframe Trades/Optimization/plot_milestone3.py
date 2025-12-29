"""
Visualization script for Milestone 3: First Optimization Generation

Creates plots showing:
- Design parameter variation across iterations
- Objective function progression
- Parameter distributions

Optional - requires matplotlib. If not available, validation can be done
manually by inspecting test_opt_history.csv
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
    print("WARNING: matplotlib not available. Skipping plots.")
    print("Install with: pip install matplotlib")

def plot_milestone3(history_file="test_opt_history.csv"):
    """
    Create visualization plots for Milestone 3 validation.
    """
    if not HAS_MATPLOTLIB:
        print("Cannot create plots without matplotlib.")
        return
    
    if not os.path.exists(history_file):
        print(f"ERROR: {history_file} not found!")
        return
    
    # Read history file
    iterations = []
    with open(history_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            iterations.append(row)
    
    if len(iterations) == 0:
        print("ERROR: No iterations found!")
        return
    
    # Extract data
    iter_nums = []
    span = []
    sweep = []
    xloc = []
    taper = []
    tip = []
    objectives = []
    
    for it in iterations:
        try:
            iter_nums.append(int(it['iter']))
            span.append(float(it['span_mm']))
            sweep.append(float(it['sweep_deg']))
            xloc.append(float(it['xloc_mm']))
            taper.append(float(it['taper']))
            tip.append(float(it['tip_mm']))
            objectives.append(float(it['final_obj']))
        except (KeyError, ValueError):
            continue
    
    if len(iter_nums) == 0:
        print("ERROR: Could not extract data!")
        return
    
    iter_nums = np.array(iter_nums)
    span = np.array(span)
    sweep = np.array(sweep)
    xloc = np.array(xloc)
    taper = np.array(taper)
    tip = np.array(tip)
    objectives = np.array(objectives)
    
    # Create figure with subplots
    fig = plt.figure(figsize=(14, 10))
    
    # Plot 1: Objective function progression
    ax1 = plt.subplot(3, 2, 1)
    ax1.plot(iter_nums, objectives, 'b-', marker='o', markersize=4, linewidth=1.5)
    ax1.axhline(y=objectives[0], color='r', linestyle='--', label='Baseline', alpha=0.7)
    ax1.set_xlabel('Iteration')
    ax1.set_ylabel('Objective Function')
    ax1.set_title('Objective Function Progression')
    ax1.grid(True, alpha=0.3)
    ax1.legend()
    
    # Plot 2: Best objective so far
    ax2 = plt.subplot(3, 2, 2)
    best_obj = np.maximum.accumulate(objectives)
    ax2.plot(iter_nums, best_obj, 'g-', marker='s', markersize=4, linewidth=2)
    ax2.set_xlabel('Iteration')
    ax2.set_ylabel('Best Objective So Far')
    ax2.set_title('Best Objective History')
    ax2.grid(True, alpha=0.3)
    
    # Plot 3: Design parameter variation - Span
    ax3 = plt.subplot(3, 2, 3)
    ax3.scatter(iter_nums, span, alpha=0.6, s=30)
    ax3.axhline(y=span[0], color='r', linestyle='--', label='Baseline', alpha=0.7)
    ax3.set_xlabel('Iteration')
    ax3.set_ylabel('Span (mm)')
    ax3.set_title('Span Variation')
    ax3.grid(True, alpha=0.3)
    ax3.legend()
    
    # Plot 4: Design parameter variation - Sweep
    ax4 = plt.subplot(3, 2, 4)
    ax4.scatter(iter_nums, sweep, alpha=0.6, s=30, color='orange')
    ax4.axhline(y=sweep[0], color='r', linestyle='--', label='Baseline', alpha=0.7)
    ax4.set_xlabel('Iteration')
    ax4.set_ylabel('Sweep (deg)')
    ax4.set_title('Sweep Variation')
    ax4.grid(True, alpha=0.3)
    ax4.legend()
    
    # Plot 5: Design parameter variation - Taper
    ax5 = plt.subplot(3, 2, 5)
    ax5.scatter(iter_nums, taper, alpha=0.6, s=30, color='purple')
    ax5.axhline(y=taper[0], color='r', linestyle='--', label='Baseline', alpha=0.7)
    ax5.set_xlabel('Iteration')
    ax5.set_ylabel('Taper Ratio')
    ax5.set_title('Taper Variation')
    ax5.grid(True, alpha=0.3)
    ax5.legend()
    
    # Plot 6: Parameter distributions (histogram)
    ax6 = plt.subplot(3, 2, 6)
    ax6.hist(span, bins=min(10, len(span)//2), alpha=0.5, label='Span', color='blue')
    ax6.hist(sweep, bins=min(10, len(sweep)//2), alpha=0.5, label='Sweep', color='orange')
    ax6.set_xlabel('Parameter Value (normalized)')
    ax6.set_ylabel('Frequency')
    ax6.set_title('Parameter Distributions')
    ax6.legend()
    ax6.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    # Save figure
    output_file = history_file.replace('.csv', '_plots.png')
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"\nPlots saved to: {output_file}")
    
    # Show if in interactive environment
    try:
        plt.show()
    except:
        pass
    
    return fig


if __name__ == "__main__":
    # Try test file first, then main file
    if len(sys.argv) > 1:
        history_file = sys.argv[1]
    else:
        if os.path.exists("test_opt_history.csv"):
            history_file = "test_opt_history.csv"
        elif os.path.exists("opt_history.csv"):
            history_file = "opt_history.csv"
        else:
            print("ERROR: No history file found!")
            sys.exit(1)
    
    print(f"Creating plots from: {history_file}")
    plot_milestone3(history_file)

