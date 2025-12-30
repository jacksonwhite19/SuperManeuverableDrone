"""
Standalone monitoring dashboard generator - Palantir Foundry Dark Mode Style
Comprehensive situational awareness dashboard
"""

import json
import csv
import os
from datetime import datetime
import math

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATUS_FILE = os.path.join(SCRIPT_DIR, "optimizer_status.json")
HISTORY_FILE = os.path.join(SCRIPT_DIR, "opt_history.csv")
DASHBOARD_FILE = os.path.join(SCRIPT_DIR, "dashboard.html")
OUTPUT_LOG = os.path.join(SCRIPT_DIR, "optimizer_output.log")

def calculate_de_phase(generation, total_generations, diversity_metric=None):
    """Determine which phase of Differential Evolution we're in."""
    progress = generation / total_generations if total_generations > 0 else 0
    
    if progress < 0.25:
        phase = "Exploration"
        phase_desc = "Wide search across design space. High diversity, exploring different regions."
        expected = "Large objective variance, many constraint violations, rapid parameter changes"
        color = "#FF9800"
    elif progress < 0.60:
        phase = "Transition"
        phase_desc = "Balancing exploration and exploitation. Starting to focus on promising regions."
        expected = "Reducing variance, fewer violations, gradual improvements"
        color = "#2196F3"
    elif progress < 0.85:
        phase = "Exploitation"
        phase_desc = "Refining good designs. Local search around promising solutions."
        expected = "Small improvements, stable parameters, convergence toward optimum"
        color = "#4CAF50"
    else:
        phase = "Convergence"
        phase_desc = "Final refinement. Small adjustments to find best solution."
        expected = "Minimal changes, fine-tuning, approaching final solution"
        color = "#9C27B0"
    
    return {
        'name': phase,
        'description': phase_desc,
        'expected': expected,
        'color': color,
        'progress': progress
    }

def calculate_diversity(history_data, window=20):
    """Calculate parameter diversity as a metric of exploration."""
    if len(history_data) < window:
        return None
    
    recent = history_data[-window:]
    params = ['span_mm', 'sweep_deg', 'xloc_mm', 'taper', 'tip_mm']
    
    diversities = []
    for param in params:
        try:
            values = [float(row.get(param, 0)) for row in recent if row.get(param, '').strip()]
            if values:
                std_dev = math.sqrt(sum((x - sum(values)/len(values))**2 for x in values) / len(values))
                mean_val = sum(values) / len(values)
                cv = (std_dev / mean_val) * 100 if mean_val != 0 else 0
                diversities.append(cv)
        except:
            pass
    
    return sum(diversities) / len(diversities) if diversities else None

def analyze_constraints(history_data, window=50):
    """Analyze constraint violations."""
    recent = history_data[-window:] if len(history_data) > window else history_data
    
    violations = {
        'span': 0,
        'trailing_edge': 0,
        'ld_penalty': 0,
        'crash': 0,
        'slug': 0,
        'gate_failure': 0,
        'total_feasible': 0
    }
    
    for row in recent:
        try:
            span_pen = float(row.get('span_penalty', 0) or 0)
            te_pen = float(row.get('te_penalty', 0) or 0)
            ld_pen = float(row.get('ld_penalty', 0) or 0)
            crash_pen = float(row.get('crash_penalty', 0) or 0)
            slug_pen = float(row.get('slug_penalty', 0) or 0)
            total_pen = float(row.get('total_penalty', 0) or 0)
            
            if span_pen > 0:
                violations['span'] += 1
            if te_pen > 0:
                violations['trailing_edge'] += 1
            if ld_pen > 0:
                violations['ld_penalty'] += 1
            if crash_pen > 0:
                violations['crash'] += 1
            if slug_pen > 0:
                violations['slug'] += 1
            if total_pen == 0:
                violations['total_feasible'] += 1
        except:
            pass
    
    total = len(recent)
    return {k: (v, (v/total*100) if total > 0 else 0) for k, v in violations.items()}

def analyze_stability_categories(history_data, window=50):
    """Analyze distribution of stability categories."""
    recent = history_data[-window:] if len(history_data) > window else history_data
    
    categories = {
        'sweet_spot': 0,  # 8-12%
        'acceptable': 0,   # 5-8% or 12-15%
        'unstable': 0,    # <5%
        'overly_stable': 0, # >15%
        'unknown': 0
    }
    
    for row in recent:
        cat = row.get('sm_category', 'unknown').strip().lower()
        if cat in categories:
            categories[cat] += 1
        else:
            categories['unknown'] += 1
    
    total = len(recent)
    return {k: (v, (v/total*100) if total > 0 else 0) for k, v in categories.items()}

def analyze_tier_performance(history_data):
    """Analyze Tier 1 vs Tier 2 gate performance."""
    tier1_passed = 0
    tier2_passed = 0
    tier2_failed = 0
    
    for row in history_data:
        try:
            gate_pen = float(row.get('gate_failure_penalty', 0) or 0)
            # Use band_LD instead of ld_at_8deg (band_LD is what's actually used for the gate)
            ld = float(row.get('band_LD', 0) or row.get('ld_at_8deg', 0) or 0)
            span_pen = float(row.get('span_penalty', 0) or 0)
            
            # Tier 1: L/D > 8 and span_penalty < 1 (gate criteria)
            if ld > 8.0 and span_pen < 1.0:
                tier1_passed += 1
                # Tier 2: passed gate (no gate failure penalty)
                if gate_pen == 0:
                    tier2_passed += 1
                else:
                    tier2_failed += 1
        except:
            pass
    
    total = len(history_data)
    return {
        'tier1_passed': (tier1_passed, (tier1_passed/total*100) if total > 0 else 0),
        'tier2_passed': (tier2_passed, (tier2_passed/total*100) if total > 0 else 0),
        'tier2_failed': (tier2_failed, (tier2_failed/total*100) if total > 0 else 0)
    }

def generate_alerts(status, history_data, de_phase):
    """Generate actionable alerts."""
    alerts = []
    
    # Check if optimizer is stuck (last 20 designs)
    if len(history_data) >= 20:
        recent_obj = [float(r.get('final_obj', 0)) for r in history_data[-20:] if r.get('final_obj', '').strip() and r.get('final_obj', '').strip() != 'N/A']
        if len(recent_obj) >= 10:
            recent_std = math.sqrt(sum((x - sum(recent_obj)/len(recent_obj))**2 for x in recent_obj) / len(recent_obj))
            if recent_std < 0.1:
                alerts.append({
                    'level': 'warning',
                    'title': 'Possible Stagnation',
                    'message': f'Objective variance is very low in last 20 designs. Optimizer may be stuck in local optimum.'
                })
    
    # Check for high penalty rate (last 50 designs)
    violations = analyze_constraints(history_data)
    if violations['total_feasible'][1] < 10:
        alerts.append({
            'level': 'warning',
            'title': 'Low Feasibility Rate',
            'message': f'Only {violations["total_feasible"][1]:.1f}% of last 50 designs are feasible. Consider adjusting constraints.'
        })
    
    # Check for stability issues (last 50 designs)
    stability = analyze_stability_categories(history_data)
    if stability['sweet_spot'][1] < 5:
        alerts.append({
            'level': 'warning',
            'title': 'Stability Sweet Spot Rare',
            'message': f'Only {stability["sweet_spot"][1]:.1f}% of last 50 designs in stability sweet spot (8-12%).'
        })
    
    # Check VSPAero time (last 10 designs)
    if len(history_data) > 0:
        recent_times = [float(r.get('vspaero_time_s', 0)) for r in history_data[-10:] if r.get('vspaero_time_s', '').strip()]
        if recent_times:
            avg_time = sum(recent_times) / len(recent_times)
            if avg_time > 250:
                alerts.append({
                    'level': 'info',
                    'title': 'Long VSPAero Runs',
                    'message': f'Average VSPAero time in last 10 designs: {avg_time:.1f}s. Consider reducing WakeNumIter if needed.'
                })
    
    # Check status file age
    timestamp_str = status.get('timestamp', '')
    if timestamp_str:
        try:
            timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
            age_min = (datetime.now() - timestamp).total_seconds() / 60.0
            if age_min > 15 and status.get('status') == 'running':
                alerts.append({
                    'level': 'error',
                    'title': 'Status File Stale',
                    'message': f'Status file hasn\'t updated in {age_min:.1f} minutes. Optimizer may be stuck or crashed.'
                })
        except:
            pass
    
    return alerts

def generate_ai_analysis(history_data, status, de_phase, violations, stability_cats, tier_perf, 
                        best_obj, baseline_obj, objectives, lds, static_margins, diversity,
                        convergence_rate, improvement_rate, param_ranges):
    """Generate comprehensive analysis insights of optimization results."""
    
    analysis = {
        'executive_summary': '',
        'key_findings': [],
        'performance_analysis': '',
        'design_trends': [],
        'constraint_analysis': '',
        'next_steps': '',
        'confidence_score': 0
    }
    
    # Executive Summary
    progress_pct = (status.get('iteration', 0) / (40 * 20)) * 100
    improvement = ((best_obj - baseline_obj) / abs(baseline_obj) * 100) if baseline_obj and best_obj and baseline_obj != 0 else 0
    
    analysis['executive_summary'] = f"""
    The optimization has completed {progress_pct:.1f}% of its planned evaluations, currently in the {de_phase['name']} phase.
    {'Significant improvement' if improvement > 10 else 'Moderate improvement' if improvement > 0 else 'No improvement yet'} 
    has been achieved over the baseline design ({improvement:+.1f}% objective change).
    The optimizer is {'actively exploring' if diversity and diversity > 15 else 'focusing on refinement' if diversity and diversity < 10 else 'balanced'} 
    the design space with {diversity:.1f}% parameter diversity.
    """
    
    # Key Findings
    if len(objectives) >= 20:
        recent_avg = sum(objectives[-10:]) / 10
        older_avg = sum(objectives[-20:-10]) / 10
        trend = "improving" if recent_avg > older_avg else "declining" if recent_avg < older_avg else "stable"
        analysis['key_findings'].append(f"Objective function is {trend} - recent average ({recent_avg:.4f}) vs previous ({older_avg:.4f})")
    
    if violations['total_feasible'][1] > 50:
        analysis['key_findings'].append(f"High feasibility rate: {violations['total_feasible'][1]:.1f}% of designs satisfy all constraints")
    elif violations['total_feasible'][1] < 20:
        analysis['key_findings'].append(f"Low feasibility rate: Only {violations['total_feasible'][1]:.1f}% of designs are feasible - constraint satisfaction is challenging")
    
    if stability_cats['sweet_spot'][1] > 30:
        analysis['key_findings'].append(f"Excellent stability performance: {stability_cats['sweet_spot'][1]:.1f}% of designs in the sweet spot (8-12% SM)")
    elif stability_cats['sweet_spot'][1] < 5:
        analysis['key_findings'].append(f"Stability challenge: Only {stability_cats['sweet_spot'][1]:.1f}% of designs achieve the stability sweet spot")
    
    if tier_perf['tier2_passed'][1] > 40:
        analysis['key_findings'].append(f"Strong Tier 2 performance: {tier_perf['tier2_passed'][1]:.1f}% of designs pass both analysis tiers")
    
    if lds:
        avg_ld = sum(lds[-20:]) / min(20, len(lds))
        if avg_ld > 15:
            analysis['key_findings'].append(f"High aerodynamic efficiency: Average L/D of {avg_ld:.2f} indicates excellent cruise performance")
        elif avg_ld < 10:
            analysis['key_findings'].append(f"Aerodynamic efficiency needs improvement: Average L/D of {avg_ld:.2f} is below target")
    
    # Performance Analysis
    if convergence_rate:
        if convergence_rate > 5:
            analysis['performance_analysis'] = f"Strong positive convergence ({convergence_rate:+.2f}%) - optimizer is making steady improvements. The algorithm is effectively refining designs."
        elif convergence_rate < -5:
            analysis['performance_analysis'] = f"Negative convergence ({convergence_rate:+.2f}%) - recent performance has declined. This may indicate exploration of new regions or a temporary setback."
        else:
            analysis['performance_analysis'] = f"Stable convergence ({convergence_rate:+.2f}%) - objective function is relatively stable, suggesting the optimizer is fine-tuning around a promising region."
    else:
        analysis['performance_analysis'] = "Insufficient data for convergence analysis. More evaluations needed to assess performance trends."
    
    # Design Trends
    if param_ranges:
        for param, (min_val, max_val, bound_min, bound_max) in param_ranges.items():
            coverage = ((max_val - min_val) / (bound_max - bound_min)) * 100 if bound_max != bound_min else 0
            if coverage > 70:
                analysis['design_trends'].append(f"{param.title()}: Wide exploration ({coverage:.1f}% of bounds) - good design space coverage")
            elif coverage < 30:
                analysis['design_trends'].append(f"{param.title()}: Narrow exploration ({coverage:.1f}% of bounds) - may be converging to a specific region")
            else:
                analysis['design_trends'].append(f"{param.title()}: Moderate exploration ({coverage:.1f}% of bounds) - balanced search")
    
    # Constraint Analysis
    constraint_issues = []
    if violations['crash'][1] > 30:
        constraint_issues.append(f"High instability rate ({violations['crash'][1]:.1f}%) - many designs are unstable (SM < 5%)")
    if violations['span'][1] > 40:
        constraint_issues.append(f"Frequent span violations ({violations['span'][1]:.1f}%) - designs often exceed span constraints")
    if violations['ld_penalty'][1] > 20:
        constraint_issues.append(f"L/D penalty common ({violations['ld_penalty'][1]:.1f}%) - many designs exceed L/D > 20 threshold")
    
    if constraint_issues:
        analysis['constraint_analysis'] = "Constraint satisfaction challenges: " + "; ".join(constraint_issues)
    else:
        analysis['constraint_analysis'] = "Constraint satisfaction is good - most designs respect the defined limits."
    
    # Next Steps
    if de_phase['name'] == 'Exploration':
        analysis['next_steps'] = "Continue exploration phase. Expect high variance in objectives and many constraint violations as the algorithm searches broadly. Best results typically emerge in later phases."
    elif de_phase['name'] == 'Transition':
        analysis['next_steps'] = "Transition phase - optimizer is beginning to focus on promising regions. Expect gradual improvements and fewer violations as it narrows the search."
    elif de_phase['name'] == 'Exploitation':
        analysis['next_steps'] = "Exploitation phase - optimizer is refining good designs. Expect steady, incremental improvements as it converges toward the optimum."
    else:
        analysis['next_steps'] = "Convergence phase - final refinement. Expect minimal changes as the optimizer fine-tunes the best solution found."
    
    # Confidence Score (0-100)
    confidence = 50  # Base score
    
    if progress_pct > 50:
        confidence += 10
    if improvement > 0:
        confidence += 15
    if violations['total_feasible'][1] > 40:
        confidence += 10
    if stability_cats['sweet_spot'][1] > 20:
        confidence += 10
    if convergence_rate and convergence_rate > 0:
        confidence += 5
    if diversity and 10 < diversity < 20:
        confidence += 5
    
    analysis['confidence_score'] = min(100, confidence)
    
    return analysis

def generate_dashboard():
    """Generate comprehensive Foundry-style dashboard."""
    
    # Read status
    status = {}
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, 'r', encoding='utf-8') as f:
                status = json.load(f)
        except:
            pass
    
    # Read history
    history_data = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                history_data = list(reader)
        except:
            pass
    
    # Extract baseline (iteration 1)
    baseline = None
    if history_data:
        baseline = history_data[0]
    
    # Extract all data
    objectives = []
    iterations = []
    static_margins = []
    lds = []
    penalties = []
    spans = []
    sweeps = []
    xlocs = []
    tapers = []
    tips = []
    generations_list = []
    vspaero_times = []
    crash_penalties = []
    ld_penalties = []
    span_penalties = []
    te_penalties = []
    sm_categories = []
    
    for row in history_data:
        try:
            obj_val = row.get('final_obj', '').strip()
            if obj_val and obj_val != 'N/A':
                objectives.append(float(obj_val))
                iterations.append(int(row.get('iter', 0)))
                
                sm = row.get('static_margin', '').strip()
                if sm and sm != 'N/A':
                    try:
                        static_margins.append(float(sm))
                    except:
                        pass
                
                ld = row.get('ld_at_8deg', '').strip()
                if ld and ld != 'N/A':
                    try:
                        lds.append(float(ld))
                    except:
                        pass
                
                penalty = row.get('total_penalty', '').strip()
                if penalty and penalty != 'N/A':
                    try:
                        penalties.append(float(penalty))
                    except:
                        pass
                
                for param, arr in [('span_mm', spans), ('sweep_deg', sweeps), ('xloc_mm', xlocs), 
                                   ('taper', tapers), ('tip_mm', tips)]:
                    val = row.get(param, '').strip()
                    if val and val != 'N/A':
                        try:
                            arr.append(float(val))
                        except:
                            pass
                
                gen = row.get('generation', '').strip()
                if gen and gen != 'N/A':
                    try:
                        generations_list.append(int(gen))
                    except:
                        pass
                
                vsp_time = row.get('vspaero_time_s', '').strip()
                if vsp_time and vsp_time != 'N/A':
                    try:
                        vspaero_times.append(float(vsp_time))
                    except:
                        pass
                
                for pen_type, arr in [('crash_penalty', crash_penalties), ('ld_penalty', ld_penalties),
                                      ('span_penalty', span_penalties), ('te_penalty', te_penalties)]:
                    val = row.get(pen_type, '').strip()
                    if val and val != 'N/A':
                        try:
                            arr.append(float(val))
                        except:
                            pass
                
                cat = row.get('sm_category', '').strip()
                if cat:
                    sm_categories.append(cat)
        except:
            pass
    
    # Calculate stats
    best_obj = status.get('best_objective', None)
    best_design = status.get('best_design', None)
    iteration = status.get('iteration', 0)
    generation = status.get('generation', 0)
    elapsed_min = status.get('elapsed_minutes', 0)
    elapsed_hr = elapsed_min / 60.0
    
    if generation == 0 and iteration > 1:
        generation = (iteration - 2) // 20
    
    if iteration > 0 and elapsed_min > 0:
        avg_time_per_iter = elapsed_min / iteration
        remaining_iters = (40 * 20) - iteration
        remaining_min = remaining_iters * avg_time_per_iter
        remaining_hr = remaining_min / 60.0
        progress_pct = (iteration / (40 * 20)) * 100
    else:
        remaining_hr = None
        progress_pct = 0
    
    # Calculate metrics
    de_phase = calculate_de_phase(generation, 40)
    diversity = calculate_diversity(history_data)
    violations = analyze_constraints(history_data)
    stability_cats = analyze_stability_categories(history_data)
    tier_perf = analyze_tier_performance(history_data)
    alerts = generate_alerts(status, history_data, de_phase)
    
    # Baseline comparison
    baseline_obj = float(baseline.get('final_obj', 0)) if baseline and baseline.get('final_obj', '').strip() else None
    baseline_ld = float(baseline.get('ld_at_8deg', 0)) if baseline and baseline.get('ld_at_8deg', '').strip() else None
    baseline_sm = float(baseline.get('static_margin', 0)) if baseline and baseline.get('static_margin', '').strip() else None
    improvement_pct = ((best_obj - baseline_obj) / abs(baseline_obj) * 100) if baseline_obj and best_obj and baseline_obj != 0 else None
    
    # Recent activity (last 10 iterations)
    recent_activity = history_data[-10:] if len(history_data) >= 10 else history_data
    recent_activity.reverse()  # Most recent first
    
    # Convergence metrics
    convergence_rate = None
    if len(objectives) >= 20:
        recent_avg = sum(objectives[-10:]) / 10
        older_avg = sum(objectives[-20:-10]) / 10
        convergence_rate = (recent_avg - older_avg) / abs(older_avg) * 100 if older_avg != 0 else 0
    
    improvements = sum(1 for row in history_data[-50:] if row.get('is_new_best', '').strip().lower() == 'true')
    improvement_rate = (improvements / min(50, len(history_data))) * 100 if history_data else 0
    
    # Recent window stats
    recent_window = min(20, len(objectives))
    recent_obj = objectives[-recent_window:] if recent_window > 0 else []
    recent_ld = lds[-recent_window:] if len(lds) >= recent_window else lds
    recent_sm = static_margins[-recent_window:] if len(static_margins) >= recent_window else static_margins
    recent_pen = penalties[-recent_window:] if len(penalties) >= recent_window else penalties
    
    avg_ld = sum(recent_ld) / len(recent_ld) if recent_ld else None
    avg_sm = sum(recent_sm) / len(recent_sm) if recent_sm else None
    avg_pen = sum(recent_pen) / len(recent_pen) if recent_pen else None
    obj_std = math.sqrt(sum((x - sum(recent_obj)/len(recent_obj))**2 for x in recent_obj) / len(recent_obj)) if len(recent_obj) > 1 else 0
    
    # Parameter ranges (design space coverage)
    param_ranges = {}
    if spans:
        param_ranges['span'] = (min(spans), max(spans), 275.0, 480.0)
    if sweeps:
        param_ranges['sweep'] = (min(sweeps), max(sweeps), 0.0, 40.0)
    if xlocs:
        param_ranges['xloc'] = (min(xlocs), max(xlocs), 220.0, 340.0)
    if tapers:
        param_ranges['taper'] = (min(tapers), max(tapers), 0.6, 0.9)
    if tips:
        param_ranges['tip'] = (min(tips), max(tips), 95.0, 125.0)
    
    # Generate Analysis Insights
    ai_analysis = generate_ai_analysis(
        history_data, status, de_phase, violations, stability_cats, tier_perf,
        best_obj, baseline_obj, objectives, lds, static_margins, diversity,
        convergence_rate, improvement_rate, param_ranges
    )
    
    # Format most recent run stats
    most_recent_html = ""
    if history_data:
        latest = history_data[-1]
        iter_num = latest.get('iter', 'N/A')
        obj = latest.get('final_obj', 'N/A')
        ld = latest.get('band_LD', 'N/A')
        sm = latest.get('static_margin', 'N/A')
        span = latest.get('span_mm', 'N/A')
        sweep = latest.get('sweep_deg', 'N/A')
        xloc = latest.get('xloc_mm', 'N/A')
        taper = latest.get('taper', 'N/A')
        tip = latest.get('tip_mm', 'N/A')
        ctrl = latest.get('ctrl_frac', 'N/A')
        vsp_time = latest.get('vspaero_time_s', 'N/A')
        span_pen = latest.get('span_penalty', 'N/A')
        ld_pen = latest.get('ld_penalty', 'N/A')
        crash_pen = latest.get('crash_penalty', 'N/A')
        slug_pen = latest.get('slug_penalty', 'N/A')
        te_pen = latest.get('te_penalty', 'N/A')
        gate_pen = latest.get('gate_failure_penalty', 'N/A')
        total_pen = latest.get('penalties', 'N/A')
        is_best = latest.get('is_new_best', '').strip().lower() == 'true'
        
        # Format values
        def fmt(val):
            if val == 'N/A' or val == '' or val is None:
                return 'N/A'
            try:
                fval = float(val)
                if abs(fval) < 0.01:
                    return f"{fval:.4f}"
                elif abs(fval) < 1:
                    return f"{fval:.3f}"
                elif abs(fval) < 100:
                    return f"{fval:.2f}"
                else:
                    return f"{fval:.1f}"
            except:
                return str(val)
        
        # Determine Tier 1 and Tier 2 gate status
        tier1_status = "PASSED"  # Tier 1 (cruise analysis) always runs
        tier2_status = "N/A"
        tier2_reason = ""
        try:
            gate_pen_val = float(gate_pen) if gate_pen != 'N/A' and gate_pen != '' and gate_pen is not None else 1.0
            ld_val = float(ld) if ld != 'N/A' and ld != '' and ld is not None else 0.0
            span_pen_val = float(span_pen) if span_pen != 'N/A' and span_pen != '' and span_pen is not None else 1.0
            
            # Check if design passed Tier 1 gate (L/D > 8.0 and span_penalty < 1.0)
            if ld_val > 8.0 and span_pen_val < 1.0:
                # Design passed Tier 1 gate, so Tier 2 (stability analysis) was attempted
                if gate_pen_val == 0.0:
                    tier2_status = "PASSED"
                    tier2_reason = f"L/D={fmt(ld_val)} > 8.0, span_penalty={fmt(span_pen_val)} < 1.0, stability analysis passed"
                else:
                    tier2_status = "FAILED"
                    tier2_reason = f"L/D={fmt(ld_val)} > 8.0, span_penalty={fmt(span_pen_val)} < 1.0, but stability analysis failed (gate_penalty={fmt(gate_pen_val)})"
            else:
                # Design did not pass Tier 1 gate, so Tier 2 was not attempted
                tier2_status = "N/A"
                fail_reasons = []
                if ld_val <= 8.0:
                    fail_reasons.append(f"L/D={fmt(ld_val)} <= 8.0")
                if span_pen_val >= 1.0:
                    fail_reasons.append(f"span_penalty={fmt(span_pen_val)} >= 1.0")
                tier2_reason = f"Tier 1 gate not passed: {', '.join(fail_reasons)}. Tier 2 (stability) not attempted."
        except Exception as e:
            tier2_status = "ERROR"
            tier2_reason = f"Unable to determine: {str(e)}"
        
        most_recent_html = f'''
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 16px;">
                <div style="background: #161b22; padding: 12px; border-radius: 6px; border: 1px solid #30363d;">
                    <div style="color: #8b949e; font-size: 12px; margin-bottom: 4px;">Iteration</div>
                    <div style="color: #c9d1d9; font-size: 18px; font-weight: 600;">{iter_num}</div>
                </div>
                <div style="background: #161b22; padding: 12px; border-radius: 6px; border: 1px solid #30363d;">
                    <div style="color: #8b949e; font-size: 12px; margin-bottom: 4px;">Objective</div>
                    <div style="color: #c9d1d9; font-size: 18px; font-weight: 600;">{fmt(obj)}</div>
                </div>
                <div style="background: #161b22; padding: 12px; border-radius: 6px; border: 1px solid #30363d;">
                    <div style="color: #8b949e; font-size: 12px; margin-bottom: 4px;">L/D Ratio</div>
                    <div style="color: #c9d1d9; font-size: 18px; font-weight: 600;">{fmt(ld)}</div>
                </div>
                <div style="background: #161b22; padding: 12px; border-radius: 6px; border: 1px solid #30363d;">
                    <div style="color: #8b949e; font-size: 12px; margin-bottom: 4px;">Static Margin</div>
                    <div style="color: #c9d1d9; font-size: 18px; font-weight: 600;">{fmt(sm)}%</div>
                </div>
                <div style="background: #161b22; padding: 12px; border-radius: 6px; border: 1px solid #30363d;">
                    <div style="color: #8b949e; font-size: 12px; margin-bottom: 4px;">VSPAero Time</div>
                    <div style="color: #c9d1d9; font-size: 18px; font-weight: 600;">{fmt(vsp_time)}s</div>
                </div>
                <div style="background: #161b22; padding: 12px; border-radius: 6px; border: 1px solid #30363d;">
                    <div style="color: #8b949e; font-size: 12px; margin-bottom: 4px;">Status</div>
                    <div style="color: {'#3fb950' if is_best else '#c9d1d9'}; font-size: 18px; font-weight: 600;">{'[BEST]' if is_best else 'Standard'}</div>
                </div>
            </div>
            
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px;">
                <div style="background: #161b22; padding: 16px; border-radius: 6px; border: 1px solid #30363d;">
                    <div style="color: #58a6ff; font-size: 14px; font-weight: 600; margin-bottom: 12px;">Tier Analysis</div>
                    <div style="font-size: 13px; line-height: 1.8;">
                        <div>
                            <span style="color: #8b949e;">Tier 1 (Cruise):</span>
                            <span style="color: #3fb950; font-weight: 600; margin-left: 8px;">{tier1_status}</span>
                        </div>
                        <div>
                            <span style="color: #8b949e;">Tier 2 (Stability):</span>
                            <span style="color: {'#3fb950' if tier2_status == 'PASSED' else '#f85149' if tier2_status == 'FAILED' else '#8b949e'}; font-weight: 600; margin-left: 8px;">{tier2_status}</span>
                        </div>
                        {f'<div style="color: #8b949e; font-size: 12px; margin-top: 8px; padding-top: 8px; border-top: 1px solid #30363d;">{tier2_reason}</div>' if tier2_reason else ''}
                    </div>
                </div>
            </div>
            
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
                <div style="background: #161b22; padding: 16px; border-radius: 6px; border: 1px solid #30363d;">
                    <div style="color: #58a6ff; font-size: 14px; font-weight: 600; margin-bottom: 12px;">Design Parameters</div>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 13px;">
                        <div><span style="color: #8b949e;">Span:</span> <span style="color: #c9d1d9;">{fmt(span)} mm</span></div>
                        <div><span style="color: #8b949e;">Sweep:</span> <span style="color: #c9d1d9;">{fmt(sweep)} deg</span></div>
                        <div><span style="color: #8b949e;">X Location:</span> <span style="color: #c9d1d9;">{fmt(xloc)} mm</span></div>
                        <div><span style="color: #8b949e;">Taper:</span> <span style="color: #c9d1d9;">{fmt(taper)}</span></div>
                        <div><span style="color: #8b949e;">Tip Chord:</span> <span style="color: #c9d1d9;">{fmt(tip)} mm</span></div>
                        <div><span style="color: #8b949e;">Control:</span> <span style="color: #c9d1d9;">{fmt(ctrl)}</span></div>
                    </div>
                </div>
                
                <div style="background: #161b22; padding: 16px; border-radius: 6px; border: 1px solid #30363d;">
                    <div style="color: #58a6ff; font-size: 14px; font-weight: 600; margin-bottom: 12px;">Penalties</div>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 13px;">
                        <div><span style="color: #8b949e;">Span:</span> <span style="color: #c9d1d9;">{fmt(span_pen)}</span></div>
                        <div><span style="color: #8b949e;">L/D:</span> <span style="color: #c9d1d9;">{fmt(ld_pen)}</span></div>
                        <div><span style="color: #8b949e;">Crash:</span> <span style="color: #c9d1d9;">{fmt(crash_pen)}</span></div>
                        <div><span style="color: #8b949e;">Slug:</span> <span style="color: #c9d1d9;">{fmt(slug_pen)}</span></div>
                        <div><span style="color: #8b949e;">Trailing Edge:</span> <span style="color: #c9d1d9;">{fmt(te_pen)}</span></div>
                        <div><span style="color: #8b949e;">Gate Failure:</span> <span style="color: #c9d1d9;">{fmt(gate_pen)}</span></div>
                        <div style="grid-column: 1 / -1; margin-top: 8px; padding-top: 8px; border-top: 1px solid #30363d;">
                            <span style="color: #8b949e;">Total Penalty:</span> <span style="color: #f85149; font-weight: 600;">{fmt(total_pen)}</span>
                        </div>
                    </div>
                </div>
            </div>
        '''
    else:
        most_recent_html = '<div style="color: #8b949e; padding: 20px; text-align: center;">No data available</div>'
    
    # Generate HTML (continuing in next part due to length)
    # This is a very long file, so I'll write it in parts...
    
    html_content = generate_html_content(
        status, history_data, objectives, iterations, static_margins, lds, penalties,
        spans, sweeps, xlocs, tapers, tips, generations_list, vspaero_times,
        crash_penalties, ld_penalties, span_penalties, te_penalties,
        best_obj, best_design, iteration, generation, elapsed_min, elapsed_hr,
        remaining_hr, progress_pct, de_phase, diversity, violations, stability_cats,
        tier_perf, alerts, baseline_obj, baseline_ld, baseline_sm, improvement_pct,
        recent_activity, convergence_rate, improvement_rate, avg_ld, avg_sm, avg_pen,
        obj_std, param_ranges, recent_window, ai_analysis, most_recent_html
    )
    
    try:
        with open(DASHBOARD_FILE, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"Dashboard generated: {DASHBOARD_FILE}")
        print(f"  - View locally: file://{DASHBOARD_FILE}")
        print(f"  - View remotely: http://[YOUR_IP]:8080")
        return True
    except Exception as e:
        print(f"Error generating dashboard: {e}")
        return False

def generate_html_content(*args):
    """Generate the full HTML content with comprehensive situational awareness."""
    # Unpack all arguments
    (status, history_data, objectives, iterations, static_margins, lds, penalties,
     spans, sweeps, xlocs, tapers, tips, generations_list, vspaero_times,
     crash_penalties, ld_penalties, span_penalties, te_penalties,
     best_obj, best_design, iteration, generation, elapsed_min, elapsed_hr,
     remaining_hr, progress_pct, de_phase, diversity, violations, stability_cats,
     tier_perf, alerts, baseline_obj, baseline_ld, baseline_sm, improvement_pct,
     recent_activity, convergence_rate, improvement_rate, avg_ld, avg_sm, avg_pen,
     obj_std, param_ranges, recent_window, ai_analysis, most_recent_html) = args
    
    # Format data for JavaScript
    recent_iterations = iterations[-100:] if len(iterations) > 100 else iterations
    recent_objectives = objectives[-100:] if len(objectives) > 100 else objectives
    recent_lds = lds[-50:] if len(lds) > 50 else lds
    recent_sms = static_margins[-50:] if len(static_margins) > 50 else static_margins
    recent_penalties_chart = penalties[-30:] if len(penalties) > 30 else penalties
    recent_times = vspaero_times[-50:] if len(vspaero_times) > 50 else vspaero_times
    
    # Format recent activity (most_recent_html is already generated and passed in, so we don't regenerate it here)
    activity_html = ""
    for i, row in enumerate(recent_activity[:10]):
        iter_num = row.get('iter', 'N/A')
        obj = row.get('final_obj', 'N/A')
        ld = row.get('ld_at_8deg', 'N/A')
        sm = row.get('static_margin', 'N/A')
        is_best = row.get('is_new_best', '').strip().lower() == 'true'
        activity_html += f'''
        <tr class="{'highlight' if is_best else ''}">
            <td>{iter_num}</td>
            <td>{obj}</td>
            <td>{ld}</td>
            <td>{sm}%</td>
            <td>{'[BEST]' if is_best else ''}</td>
        </tr>'''
    
    # Format alerts
    alerts_html = ""
    if alerts:
        for alert in alerts:
            level_class = alert['level']
            alerts_html += f'''
            <div class="alert alert-{level_class}">
                <div class="alert-title">{alert['title']}</div>
                <div class="alert-message">{alert['message']}</div>
            </div>'''
    else:
        alerts_html = '<div class="alert alert-success"><div class="alert-message">No critical issues detected</div></div>'
    
    # Format constraint violations
    violations_html = ""
    for key, (count, pct) in violations.items():
        if key != 'total_feasible':
            violations_html += f'''
            <div class="violation-item">
                <div class="violation-label">{key.replace('_', ' ').title()}</div>
                <div class="violation-bar">
                    <div class="violation-fill" style="width: {pct}%"></div>
                </div>
                <div class="violation-value">{count} ({pct:.1f}%)</div>
            </div>'''
    
    # Format stability categories
    stability_html = ""
    for key, (count, pct) in stability_cats.items():
        stability_html += f'''
        <div class="category-item">
            <div class="category-label">{key.replace('_', ' ').title()}</div>
            <div class="category-bar">
                <div class="category-fill" style="width: {pct}%"></div>
            </div>
            <div class="category-value">{count} ({pct:.1f}%)</div>
        </div>'''
    
    # Format parameter ranges
    param_ranges_html = ""
    for param, (min_val, max_val, bound_min, bound_max) in param_ranges.items():
        coverage = ((max_val - min_val) / (bound_max - bound_min)) * 100 if bound_max != bound_min else 0
        param_ranges_html += f'''
        <div class="range-item">
            <div class="range-label">{param.title()}</div>
            <div class="range-bar">
                <div class="range-fill" style="width: {coverage}%"></div>
            </div>
            <div class="range-value">{min_val:.1f} - {max_val:.1f} ({coverage:.1f}% of bounds)</div>
        </div>'''
    
    return f"""<!DOCTYPE html>
<html>
<head>
    <title>Optimizer Dashboard - Foundry</title>
    <meta http-equiv="refresh" content="60">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', sans-serif;
            background: #0d1117;
            color: #c9d1d9;
            line-height: 1.6;
            padding: 20px;
        }}
        .container {{ max-width: 1800px; margin: 0 auto; }}
        .header {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 20px;
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .header h1 {{ color: #58a6ff; font-size: 24px; font-weight: 600; }}
        .status-badge {{
            display: inline-flex;
            align-items: center;
            padding: 6px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .status-running {{ background: #1a472a; color: #3fb950; border: 1px solid #238636; }}
        .status-paused {{ background: #3d2817; color: #d29922; border: 1px solid #bb8009; }}
        .status-stopped {{ background: #3d1f1f; color: #f85149; border: 1px solid #da3633; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-bottom: 20px; }}
        .card {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 16px;
        }}
        .card-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; padding-bottom: 12px; border-bottom: 1px solid #21262d; }}
        .card-title {{ color: #f0f6fc; font-size: 14px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }}
        .card-value {{ color: #58a6ff; font-size: 28px; font-weight: 600; margin: 8px 0; }}
        .card-label {{ color: #8b949e; font-size: 12px; }}
        .progress-bar {{ width: 100%; height: 8px; background: #21262d; border-radius: 4px; overflow: hidden; margin-top: 8px; }}
        .progress-fill {{ height: 100%; background: linear-gradient(90deg, #1f6feb, #58a6ff); transition: width 0.3s; }}
        .phase-card {{
            background: {de_phase['color']}15;
            border: 1px solid {de_phase['color']}40;
            border-radius: 6px;
            padding: 16px;
            margin-bottom: 20px;
        }}
        .phase-title {{ color: {de_phase['color']}; font-size: 18px; font-weight: 600; margin-bottom: 8px; }}
        .phase-desc {{ color: #c9d1d9; font-size: 14px; margin-bottom: 8px; }}
        .phase-expected {{ color: #8b949e; font-size: 12px; font-style: italic; }}
        .chart-container {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 16px;
            margin-bottom: 20px;
        }}
        .chart-title {{ color: #f0f6fc; font-size: 14px; font-weight: 600; margin-bottom: 16px; text-transform: uppercase; letter-spacing: 0.5px; }}
        .alert {{
            background: #161b22;
            border: 1px solid #30363d;
            border-left: 3px solid #58a6ff;
            border-radius: 6px;
            padding: 12px;
            margin-bottom: 8px;
        }}
        .alert-error {{ border-left-color: #f85149; }}
        .alert-warning {{ border-left-color: #d29922; }}
        .alert-success {{ border-left-color: #3fb950; }}
        .alert-info {{ border-left-color: #58a6ff; }}
        .alert-title {{ color: #f0f6fc; font-size: 13px; font-weight: 600; margin-bottom: 4px; }}
        .alert-message {{ color: #8b949e; font-size: 12px; }}
        .section {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 16px;
            margin-bottom: 20px;
        }}
        .section-title {{ color: #58a6ff; font-size: 16px; font-weight: 600; margin-bottom: 12px; }}
        .comparison-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }}
        .comparison-item {{
            background: #0d1117;
            border: 1px solid #21262d;
            border-radius: 4px;
            padding: 12px;
        }}
        .comparison-label {{ color: #8b949e; font-size: 11px; text-transform: uppercase; margin-bottom: 4px; }}
        .comparison-value {{ color: #58a6ff; font-size: 18px; font-weight: 600; }}
        .comparison-diff {{ color: #3fb950; font-size: 12px; margin-top: 4px; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
        }}
        th {{
            background: #0d1117;
            color: #8b949e;
            text-align: left;
            padding: 8px;
            border-bottom: 1px solid #21262d;
            font-weight: 600;
            text-transform: uppercase;
            font-size: 11px;
        }}
        td {{
            padding: 8px;
            border-bottom: 1px solid #21262d;
            color: #c9d1d9;
        }}
        tr.highlight {{ background: #1a472a20; }}
        .violation-item, .category-item, .range-item {{
            margin-bottom: 8px;
        }}
        .violation-label, .category-label, .range-label {{
            color: #c9d1d9;
            font-size: 12px;
            margin-bottom: 4px;
        }}
        .violation-bar, .category-bar, .range-bar {{
            width: 100%;
            height: 6px;
            background: #21262d;
            border-radius: 3px;
            overflow: hidden;
            margin: 4px 0;
        }}
        .violation-fill, .category-fill, .range-fill {{
            height: 100%;
            background: #58a6ff;
            transition: width 0.3s;
        }}
        .violation-value, .category-value, .range-value {{
            color: #8b949e;
            font-size: 11px;
        }}
        .footer {{
            text-align: center;
            color: #8b949e;
            font-size: 11px;
            margin-top: 20px;
            padding-top: 16px;
            border-top: 1px solid #21262d;
        }}
        .footer a {{ color: #58a6ff; text-decoration: none; }}
        .footer a:hover {{ text-decoration: underline; }}
        canvas {{ max-height: 300px; }}
        .ai-analysis {{
            background: linear-gradient(135deg, #161b22 0%, #0d1117 100%);
            border: 1px solid #30363d;
            border-left: 4px solid #58a6ff;
            border-radius: 6px;
            padding: 20px;
            margin-bottom: 20px;
        }}
        .ai-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
            padding-bottom: 12px;
            border-bottom: 1px solid #21262d;
        }}
        .ai-title {{
            color: #58a6ff;
            font-size: 18px;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .confidence-badge {{
            background: #1a472a;
            color: #3fb950;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }}
        .ai-section {{
            margin-bottom: 16px;
        }}
        .ai-section-title {{
            color: #f0f6fc;
            font-size: 14px;
            font-weight: 600;
            margin-bottom: 8px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .ai-content {{
            color: #c9d1d9;
            font-size: 14px;
            line-height: 1.8;
        }}
        .ai-finding {{
            background: #0d1117;
            border-left: 3px solid #58a6ff;
            padding: 10px 12px;
            margin: 8px 0;
            border-radius: 4px;
        }}
        .ai-recommendation {{
            background: #0d1117;
            border-left: 3px solid #d29922;
            padding: 10px 12px;
            margin: 8px 0;
            border-radius: 4px;
        }}
    </style>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@3.9.1/dist/chart.min.js"></script>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Optimization Dashboard</h1>
            <span class="status-badge status-{status.get('status', 'unknown').lower()}">
                {status.get('status', 'unknown').upper()}
            </span>
        </div>
        
        <div class="phase-card">
            <div class="phase-title">DE Phase: {de_phase['name']}</div>
            <div class="phase-desc">{de_phase['description']}</div>
            <div class="phase-expected">Expected behavior: {de_phase['expected']}</div>
        </div>
        
        <div class="section">
            <div class="section-title">Alerts & Warnings <span style="color: #8b949e; font-size: 12px; font-weight: normal;">(Last 10-50 designs)</span></div>
            {alerts_html}
        </div>
        
        <div class="ai-analysis">
            <div class="ai-header">
                <div class="ai-title">Analysis Insights & Overview</div>
                <div class="confidence-badge">Confidence: {ai_analysis['confidence_score']}/100</div>
            </div>
            
            <div class="ai-section">
                <div class="ai-section-title">Executive Summary</div>
                <div class="ai-content">{ai_analysis['executive_summary'].strip()}</div>
            </div>
            
            <div class="ai-section">
                <div class="ai-section-title">Key Findings</div>
                <div class="ai-content">
                    {''.join([f'<div class="ai-finding">- {finding}</div>' for finding in ai_analysis['key_findings']]) if ai_analysis['key_findings'] else '<div class="ai-content">Insufficient data for key findings analysis.</div>'}
                </div>
            </div>
            
            <div class="ai-section">
                <div class="ai-section-title">Performance Analysis</div>
                <div class="ai-content">{ai_analysis['performance_analysis']}</div>
            </div>
            
            {f'''
            <div class="ai-section">
                <div class="ai-section-title">Design Space Trends</div>
                <div class="ai-content">
                    {''.join([f'<div class="ai-finding">- {trend}</div>' for trend in ai_analysis['design_trends']])}
                </div>
            </div>
            ''' if ai_analysis['design_trends'] else ''}
            
            <div class="ai-section">
                <div class="ai-section-title">Constraint Analysis</div>
                <div class="ai-content">{ai_analysis['constraint_analysis']}</div>
            </div>
            
            <div class="ai-section">
                <div class="ai-section-title">What to Expect Next</div>
                <div class="ai-content">{ai_analysis['next_steps']}</div>
            </div>
        </div>
        
        <div class="grid">
            <div class="card">
                <div class="card-header"><div class="card-title">Iterations</div></div>
                <div class="card-value">{iteration}</div>
                <div class="card-label">Total evaluations</div>
            </div>
            <div class="card">
                <div class="card-header"><div class="card-title">Generation</div></div>
                <div class="card-value">{generation} / 40</div>
                <div class="progress-bar"><div class="progress-fill" style="width: {progress_pct:.1f}%"></div></div>
                <div class="card-label">{progress_pct:.1f}% complete</div>
            </div>
            <div class="card">
                <div class="card-header"><div class="card-title">Elapsed Time</div></div>
                <div class="card-value">{elapsed_hr:.1f}h</div>
                <div class="card-label">{elapsed_min:.0f} minutes</div>
            </div>
            <div class="card">
                <div class="card-header"><div class="card-title">Best Objective</div></div>
                <div class="card-value">{f'{best_obj:.4f}' if best_obj else 'N/A'}</div>
                <div class="card-label">Current best</div>
            </div>
            <div class="card">
                <div class="card-header"><div class="card-title">Est. Remaining</div></div>
                <div class="card-value">{f'{remaining_hr:.1f}h' if remaining_hr else 'N/A'}</div>
                <div class="card-label">Time to completion</div>
            </div>
            <div class="card">
                <div class="card-header"><div class="card-title">Diversity</div></div>
                <div class="card-value">{f'{diversity:.1f}%' if diversity else 'N/A'}</div>
                <div class="card-label">Parameter variation</div>
            </div>
        </div>
        
        <div class="section">
            <div class="section-title">Baseline Comparison</div>
            <div class="comparison-grid">
                <div class="comparison-item">
                    <div class="comparison-label">Objective</div>
                    <div class="comparison-value">Baseline: {f'{baseline_obj:.4f}' if baseline_obj else 'N/A'}</div>
                    <div class="comparison-value">Best: {f'{best_obj:.4f}' if best_obj else 'N/A'}</div>
                    {f'<div class="comparison-diff">Improvement: {improvement_pct:+.1f}%</div>' if improvement_pct else ''}
                </div>
                <div class="comparison-item">
                    <div class="comparison-label">L/D Ratio</div>
                    <div class="comparison-value">Baseline: {f'{baseline_ld:.2f}' if baseline_ld else 'N/A'}</div>
                    <div class="comparison-value">Best: {f'{avg_ld:.2f}' if avg_ld else 'N/A'}</div>
                </div>
                <div class="comparison-item">
                    <div class="comparison-label">Static Margin</div>
                    <div class="comparison-value">Baseline: {f'{baseline_sm:.2f}%' if baseline_sm else 'N/A'}</div>
                    <div class="comparison-value">Best: {f'{avg_sm:.2f}%' if avg_sm else 'N/A'}</div>
                </div>
            </div>
        </div>
        
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px;">
            <div class="section">
                <div class="section-title">Constraint Violations (Last 50)</div>
                {violations_html}
                <div style="margin-top: 12px; padding-top: 12px; border-top: 1px solid #21262d;">
                    <div class="violation-label">Feasible Designs</div>
                    <div class="violation-bar">
                        <div class="violation-fill" style="width: {violations['total_feasible'][1]}%; background: #3fb950;"></div>
                    </div>
                    <div class="violation-value">{violations['total_feasible'][0]} ({violations['total_feasible'][1]:.1f}%)</div>
                </div>
            </div>
            <div class="section">
                <div class="section-title">Stability Categories (Last 50)</div>
                {stability_html}
            </div>
        </div>
        
        <div class="section">
            <div class="section-title">Tier Analysis</div>
            <div class="comparison-grid">
                <div class="comparison-item">
                    <div class="comparison-label">Tier 1 Passed</div>
                    <div class="comparison-value">{tier_perf['tier1_passed'][0]} ({tier_perf['tier1_passed'][1]:.1f}%)</div>
                </div>
                <div class="comparison-item">
                    <div class="comparison-label">Tier 2 Passed</div>
                    <div class="comparison-value">{tier_perf['tier2_passed'][0]} ({tier_perf['tier2_passed'][1]:.1f}%)</div>
                </div>
                <div class="comparison-item">
                    <div class="comparison-label">Tier 2 Failed</div>
                    <div class="comparison-value">{tier_perf['tier2_failed'][0]} ({tier_perf['tier2_failed'][1]:.1f}%)</div>
                </div>
            </div>
        </div>
        
        <div class="section">
            <div class="section-title">Design Space Coverage</div>
            {param_ranges_html}
        </div>
        
        {f'''
        <div class="section">
            <div class="section-title">Best Design Parameters</div>
            <div class="comparison-grid">
                <div class="comparison-item">
                    <div class="comparison-label">Span</div>
                    <div class="comparison-value">{best_design[0]:.1f} mm</div>
                </div>
                <div class="comparison-item">
                    <div class="comparison-label">Sweep</div>
                    <div class="comparison-value">{best_design[1]:.1f} deg</div>
                </div>
                <div class="comparison-item">
                    <div class="comparison-label">X Location</div>
                    <div class="comparison-value">{best_design[2]:.1f} mm</div>
                </div>
                <div class="comparison-item">
                    <div class="comparison-label">Taper</div>
                    <div class="comparison-value">{best_design[3]:.3f}</div>
                </div>
                <div class="comparison-item">
                    <div class="comparison-label">Tip Chord</div>
                    <div class="comparison-value">{best_design[4]:.1f} mm</div>
                </div>
            </div>
        </div>
        ''' if best_obj and best_design else ''}
        
        <div class="section">
            <div class="section-title">Most Recent Run</div>
            {most_recent_html}
        </div>
        
        <div class="section">
            <div class="section-title">Recent Activity (Last 10 Iterations)</div>
            <table>
                <thead>
                    <tr>
                        <th>Iter</th>
                        <th>Objective</th>
                        <th>L/D</th>
                        <th>SM %</th>
                        <th>New Best</th>
                    </tr>
                </thead>
                <tbody>
                    {activity_html}
                </tbody>
            </table>
        </div>
        
        <div class="chart-container">
            <div class="chart-title">Objective Function Trend</div>
            <canvas id="objectiveChart"></canvas>
        </div>
        
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px;">
            <div class="chart-container">
                <div class="chart-title">Lift-to-Drag Ratio</div>
                <canvas id="ldChart"></canvas>
            </div>
            <div class="chart-container">
                <div class="chart-title">Static Margin</div>
                <canvas id="smChart"></canvas>
            </div>
        </div>
        
        <div class="chart-container">
            <div class="chart-title">Design Parameters Evolution</div>
            <canvas id="paramsChart"></canvas>
        </div>
        
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px;">
            <div class="chart-container">
                <div class="chart-title">Penalty Breakdown</div>
                <canvas id="penaltyChart"></canvas>
            </div>
            <div class="chart-container">
                <div class="chart-title">VSPAero Runtime</div>
                <canvas id="timeChart"></canvas>
            </div>
        </div>
        
        <div class="footer">
            <p>Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p>Auto-refreshes every 60 seconds | <a href="/control">Control Interface</a> | <a href="/viewer" target="_blank">3D Viewer</a> | <a href="/status" download="status.json">Download Status JSON</a> | <a href="{HISTORY_FILE}" download="history.csv">Download History CSV</a></p>
        </div>
    </div>
    
    <script>
        const darkTheme = {{
            backgroundColor: '#161b22',
            borderColor: '#30363d',
            textColor: '#c9d1d9',
            gridColor: '#21262d',
            primaryColor: '#58a6ff',
            successColor: '#3fb950',
            warningColor: '#d29922',
            errorColor: '#f85149'
        }};
        
        Chart.defaults.color = darkTheme.textColor;
        Chart.defaults.borderColor = darkTheme.borderColor;
        Chart.defaults.backgroundColor = darkTheme.backgroundColor;
        
        const iterations_data = {recent_iterations};
        const objectives_data = {recent_objectives};
        const lds_data = {recent_lds};
        const sms_data = {recent_sms};
        const penalties_data = {recent_penalties_chart};
        const times_data = {recent_times};
        const spans_data = {spans[-50:] if len(spans) > 50 else spans};
        const sweeps_data = {sweeps[-50:] if len(sweeps) > 50 else sweeps};
        const xlocs_data = {xlocs[-50:] if len(xlocs) > 50 else xlocs};
        const tapers_data = {[t*100 for t in tapers[-50:]] if len(tapers) > 50 else [t*100 for t in tapers]};
        
        new Chart(document.getElementById('objectiveChart'), {{
            type: 'line',
            data: {{
                labels: iterations_data,
                datasets: [{{
                    label: 'Objective',
                    data: objectives_data,
                    borderColor: darkTheme.primaryColor,
                    backgroundColor: darkTheme.primaryColor + '20',
                    tension: 0.1,
                    fill: true
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: true,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{
                    x: {{ grid: {{ color: darkTheme.gridColor }}, ticks: {{ color: darkTheme.textColor }} }},
                    y: {{ grid: {{ color: darkTheme.gridColor }}, ticks: {{ color: darkTheme.textColor }} }}
                }}
            }}
        }});
        
        new Chart(document.getElementById('ldChart'), {{
            type: 'line',
            data: {{
                labels: iterations_data.slice(-lds_data.length),
                datasets: [{{
                    label: 'L/D at 8 deg',
                    data: lds_data,
                    borderColor: darkTheme.successColor,
                    backgroundColor: darkTheme.successColor + '20',
                    tension: 0.1,
                    fill: true
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: true,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{
                    x: {{ grid: {{ color: darkTheme.gridColor }}, ticks: {{ color: darkTheme.textColor }} }},
                    y: {{ grid: {{ color: darkTheme.gridColor }}, ticks: {{ color: darkTheme.textColor }} }}
                }}
            }}
        }});
        
        new Chart(document.getElementById('smChart'), {{
            type: 'line',
            data: {{
                labels: iterations_data.slice(-sms_data.length),
                datasets: [{{
                    label: 'Static Margin (%)',
                    data: sms_data,
                    borderColor: darkTheme.warningColor,
                    backgroundColor: darkTheme.warningColor + '20',
                    tension: 0.1,
                    fill: true
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: true,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{
                    x: {{ grid: {{ color: darkTheme.gridColor }}, ticks: {{ color: darkTheme.textColor }} }},
                    y: {{ grid: {{ color: darkTheme.gridColor }}, ticks: {{ color: darkTheme.textColor }} }}
                }}
            }}
        }});
        
        new Chart(document.getElementById('paramsChart'), {{
            type: 'line',
            data: {{
                labels: iterations_data.slice(-spans_data.length),
                datasets: [
                    {{ label: 'Span (mm)', data: spans_data, borderColor: '#58a6ff', tension: 0.1 }},
                    {{ label: 'Sweep (deg)', data: sweeps_data, borderColor: '#3fb950', tension: 0.1 }},
                    {{ label: 'X Loc (mm)', data: xlocs_data, borderColor: '#d29922', tension: 0.1 }},
                    {{ label: 'Taper (x100)', data: tapers_data, borderColor: '#f85149', tension: 0.1 }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: true,
                scales: {{
                    x: {{ grid: {{ color: darkTheme.gridColor }}, ticks: {{ color: darkTheme.textColor }} }},
                    y: {{ grid: {{ color: darkTheme.gridColor }}, ticks: {{ color: darkTheme.textColor }} }}
                }}
            }}
        }});
        
        new Chart(document.getElementById('penaltyChart'), {{
            type: 'bar',
            data: {{
                labels: iterations_data.slice(-penalties_data.length),
                datasets: [{{
                    label: 'Total Penalty',
                    data: penalties_data,
                    backgroundColor: darkTheme.errorColor + '80',
                    borderColor: darkTheme.errorColor
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: true,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{
                    x: {{ grid: {{ color: darkTheme.gridColor }}, ticks: {{ color: darkTheme.textColor }} }},
                    y: {{ grid: {{ color: darkTheme.gridColor }}, ticks: {{ color: darkTheme.textColor }} }}
                }}
            }}
        }});
        
        new Chart(document.getElementById('timeChart'), {{
            type: 'line',
            data: {{
                labels: iterations_data.slice(-times_data.length),
                datasets: [{{
                    label: 'VSPAero Time (s)',
                    data: times_data,
                    borderColor: darkTheme.primaryColor,
                    backgroundColor: darkTheme.primaryColor + '20',
                    tension: 0.1,
                    fill: true
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: true,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{
                    x: {{ grid: {{ color: darkTheme.gridColor }}, ticks: {{ color: darkTheme.textColor }} }},
                    y: {{ grid: {{ color: darkTheme.gridColor }}, ticks: {{ color: darkTheme.textColor }} }}
                }}
            }}
        }});
    </script>
</body>
</html>"""
