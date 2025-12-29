"""
Validation script for Milestone 3: First Optimization Generation

Automatically checks if the optimizer meets Milestone 3 criteria:
- Multiple iterations appear (population size expected)
- Each iteration shows different design parameters
- opt_history.csv contains entries for all evaluations
- Best objective value updates as better designs are found

Can validate either:
- test_opt_history.csv (from test_milestone3.py)
- opt_history.csv (from main optimizer2.py)
"""

import csv
import numpy as np
import sys
import os

def validate_milestone3(history_file="test_opt_history.csv"):
    """
    Validate Milestone 3 criteria from optimization history file.
    
    Returns: (all_passed, results_dict)
    """
    print("=" * 60)
    print(f"MILESTONE 3 VALIDATION: {history_file}")
    print("=" * 60)
    
    if not os.path.exists(history_file):
        print(f"ERROR: {history_file} not found!")
        print("Run test_milestone3.py or optimizer2.py first.")
        return False, {}
    
    # Read history file
    iterations = []
    with open(history_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            iterations.append(row)
    
    if len(iterations) == 0:
        print("ERROR: No iterations found in history file!")
        return False, {}
    
    print(f"\nFound {len(iterations)} iterations in history file")
    
    # Extract data
    design_params = []
    objectives = []
    iterations_nums = []
    
    for it in iterations:
        try:
            iterations_nums.append(int(it['iter']))
            design_params.append([
                float(it['span_mm']),
                float(it['sweep_deg']),
                float(it['xloc_mm']),
                float(it['taper']),
                float(it['tip_mm']),
                float(it['ctrl_frac'])
            ])
            objectives.append(float(it['final_obj']))
        except (KeyError, ValueError) as e:
            print(f"WARNING: Error parsing row {it.get('iter', 'unknown')}: {e}")
            continue
    
    if len(design_params) == 0:
        print("ERROR: Could not extract any valid data!")
        return False, {}
    
    design_params = np.array(design_params)
    objectives = np.array(objectives)
    
    # Validation checks
    results = {
        'total_iterations': len(iterations),
        'checks': {}
    }
    
    print("\n" + "-" * 60)
    print("VALIDATION CHECKS")
    print("-" * 60)
    
    # Check 1: Multiple iterations
    min_expected = 2  # At least baseline + 1 generation
    check1 = len(iterations) >= min_expected
    results['checks']['multiple_iterations'] = check1
    status1 = "[PASS]" if check1 else "[FAIL]"
    print(f"\n1. Multiple iterations: {status1}")
    print(f"   Found: {len(iterations)} iterations")
    print(f"   Expected: >= {min_expected}")
    
    # Check 2: Design parameters vary
    param_variations = []
    param_names = ['span_mm', 'sweep_deg', 'xloc_mm', 'taper', 'tip_mm', 'ctrl_frac']
    
    for i, name in enumerate(param_names):
        values = design_params[:, i]
        std_dev = np.std(values)
        range_val = np.max(values) - np.min(values)
        param_variations.append({
            'name': name,
            'std': std_dev,
            'range': range_val,
            'varies': std_dev > 1e-6  # Non-zero variation threshold
        })
    
    all_vary = all(p['varies'] for p in param_variations if p['name'] != 'ctrl_frac')  # ctrl_frac might be fixed
    results['checks']['design_parameters_vary'] = all_vary
    status2 = "[PASS]" if all_vary else "[FAIL]"
    print(f"\n2. Design parameters vary: {status2}")
    for p in param_variations:
        if p['name'] != 'ctrl_frac' or p['varies']:  # Show all, or ctrl_frac if it varies
            print(f"   {p['name']:12s}: std={p['std']:8.3f}, range={p['range']:8.3f}")
    
    # Check 3: All iterations logged
    expected_iters = set(range(1, len(iterations) + 1))
    actual_iters = set(iterations_nums)
    missing = expected_iters - actual_iters
    check3 = len(missing) == 0
    results['checks']['all_iterations_logged'] = check3
    status3 = "[PASS]" if check3 else "[FAIL]"
    print(f"\n3. All iterations logged: {status3}")
    print(f"   Expected iterations: 1 to {len(iterations)}")
    if missing:
        print(f"   Missing: {sorted(missing)}")
    else:
        print(f"   All iterations present")
    
    # Check 4: Best objective updates
    best_obj_history = []
    current_best = -np.inf
    improvements = 0
    
    for i, obj in enumerate(objectives):
        if obj > current_best:
            current_best = obj
            improvements += 1
            best_obj_history.append((i + 1, obj))
    
    check4 = improvements > 1  # At least one improvement beyond baseline
    results['checks']['objective_updates'] = check4
    status4 = "[PASS]" if check4 else "[FAIL]"
    print(f"\n4. Best objective updates: {status4}")
    print(f"   Number of improvements: {improvements}")
    print(f"   Best objective: {np.max(objectives):.6f}")
    print(f"   Baseline objective: {objectives[0]:.6f}")
    if len(best_obj_history) > 0:
        print(f"   Improvement events at iterations: {[x[0] for x in best_obj_history[:5]]}")
    
    # Check 5: Parameter bounds respected
    bounds = [
        (275.0, 480.0),  # span
        (0.0, 40.0),     # sweep
        (220.0, 340.0),  # xloc
        (0.6, 0.9),      # taper
        (95.0, 125.0),   # tip
        (0.22, 0.22),    # control fraction
    ]
    
    all_in_bounds = True
    violations = []
    for i, (name, (low, high)) in enumerate(zip(param_names, bounds)):
        values = design_params[:, i]
        if np.any(values < low - 1e-6) or np.any(values > high + 1e-6):
            all_in_bounds = False
            violations.append({
                'param': name,
                'min': np.min(values),
                'max': np.max(values),
                'bounds': (low, high)
            })
    
    results['checks']['parameters_in_bounds'] = all_in_bounds
    status5 = "[PASS]" if all_in_bounds else "[FAIL]"
    print(f"\n5. Parameters within bounds: {status5}")
    if violations:
        for v in violations:
            print(f"   {v['param']}: min={v['min']:.3f}, max={v['max']:.3f}, bounds={v['bounds']}")
    else:
        print(f"   All parameters within specified bounds")
    
    # Summary
    all_passed = all([
        check1, all_vary, check3, check4, all_in_bounds
    ])
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    passed_count = sum([
        check1, all_vary, check3, check4, all_in_bounds
    ])
    
    print(f"Passed: {passed_count}/5 checks")
    
    if all_passed:
        print("\n[MILESTONE 3: PASSED]")
        print("The optimizer successfully generates and evaluates multiple designs!")
    else:
        print("\n[MILESTONE 3: FAILED]")
        print("Some criteria were not met. Review the checks above.")
    
    print("=" * 60)
    
    results['all_passed'] = all_passed
    return all_passed, results


if __name__ == "__main__":
    # Try test file first, then main file
    if len(sys.argv) > 1:
        history_file = sys.argv[1]
    else:
        # Default: try test file, fall back to main file
        if os.path.exists("test_opt_history.csv"):
            history_file = "test_opt_history.csv"
            print("Using test_opt_history.csv (from test_milestone3.py)")
        elif os.path.exists("opt_history.csv"):
            history_file = "opt_history.csv"
            print("Using opt_history.csv (from optimizer2.py)")
        else:
            print("ERROR: No history file found!")
            print("Run test_milestone3.py or optimizer2.py first.")
            sys.exit(1)
    
    validate_milestone3(history_file)

