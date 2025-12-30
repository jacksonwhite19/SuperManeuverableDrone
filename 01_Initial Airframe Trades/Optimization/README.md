# Fixed-Wing Tailsitter Drone Planform Optimizer

An automated optimization system that uses OpenVSP and VSPAero to find optimal fixed-wing drone planform configurations. The optimizer balances **high cruise efficiency (L/D)** with **flyable longitudinal stability (Static Margin)** while respecting geometric constraints for a "supermaneuverable" platform.

## Project Overview

This optimizer solves a multi-objective design problem for a fixed-wing tailsitter drone by:

1. **Exploring the design space** - Systematically varies wing geometry parameters (span, sweep, taper, position, etc.)
2. **Running aerodynamic simulations** - Executes VSPAero panel method analyses at multiple angles of attack (2-14°)
3. **Evaluating stability** - Calculates static margin using VSPAero Pitch stability analysis and dynamic CG from MassProp
4. **Applying constraints** - Enforces geometric limits and stability requirements through penalty functions
5. **Converging to optimal designs** - Uses differential evolution to find configurations that maximize efficiency while maintaining stability

## Objective

**Find the optimal airframe configuration that:**
- Maximizes lift-to-drag ratio (L/D) for efficient cruise performance
- Maintains flyable longitudinal stability (Static Margin between 8-12% is ideal)
- Respects geometric constraints (span limits, trailing edge position)
- Avoids "sailplane" designs (excessive L/D > 20) and unstable configurations

## How It Works

### Design Variables

The optimizer adjusts six wing planform parameters within specified bounds:

| Parameter | Range | Description |
|-----------|-------|-------------|
| **Span** | 275-480 mm | Wing half-span |
| **Sweep** | 0-40° | Wing sweep angle |
| **X Location** | 220-340 mm | Wing root position along fuselage |
| **Taper Ratio** | 0.6-0.9 | Ratio of tip chord to root chord |
| **Tip Chord** | 95-125 mm | Wing tip chord length |
| **Control Fraction** | 0.22 (fixed) | Control surface length as fraction of chord |

### Optimization Workflow

```
┌─────────────────┐
│  Start: Baseline│
│  Design         │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Generate Design │
│ Parameters (x)  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐      ┌──────────────┐
│ Update Geometry │─────▶│ Write .des   │
│ from .des file  │      │ file         │
└────────┬────────┘      └──────────────┘
         │
         ▼
┌─────────────────┐      ┌──────────────┐
│ Run MassProp    │─────▶│ Extract CG   │
│ Analysis        │      │ (Dynamic)    │
└────────┬────────┘      └──────────────┘
         │
         ▼
┌─────────────────┐      ┌──────────────┐
│ Run VSPAero     │─────▶│ Extract L/D  │
│ (Pitch Mode)    │      │ & Neutral Pt │
└────────┬────────┘      └──────────────┘
         │
         ▼
┌─────────────────┐
│ Calculate       │
│ Static Margin   │
│ = (Xnp-Xcg)/MAC │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Evaluate        │
│ Objective +     │
│ Penalties       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Differential    │
│ Evolution       │
│ (Next Design)   │
└─────────────────┘
```

### Detailed Process

1. **Geometry Update**
   - Python writes design parameters to `current.des` file
   - OpenVSP script (`update_geom.vspscript`) reads `.des` and updates geometry
   - Updated geometry saved to `current.vsp3`

2. **Mass Properties Analysis**
   - MassProp analysis calculates center of gravity (CG)
   - CG location varies with geometry (dynamic CG)
   - Results written to `MassProp_Results.csv`

3. **Aerodynamic Analysis**
   - VSPAero runs with **Pitch stability mode** enabled (`UnsteadyType=5`)
   - Alpha sweep: 2° to 14° in 2° increments (7 points total)
   - Wake iterations: 13 (optimized for speed)
   - Uses 16 CPU cores for parallel computation
   - Extracts L/D ratios at each angle of attack
   - Calculates neutral point (Xnp) from stability derivatives

4. **Stability Calculation**
   - Static Margin = `(Xnp - Xcg) / MAC × 100%`
   - Xnp: Neutral point from VSPAero Pitch analysis (`.aerocenter.stab` file)
   - Xcg: Dynamic CG from MassProp analysis
   - MAC: Mean Aerodynamic Chord from VSPAero results

5. **Objective Evaluation**
   - **Performance Metric**: Band Mean L/D (4° window, penalized by std dev)
   - **Penalties Applied**:
     - **Crash Penalty** (100% weight): Static Margin < 5% (unstable)
     - **Slug Penalty** (35% weight): Static Margin > 15% (overly stable)
     - **Sweet Spot**: 8-12% Static Margin (no penalty)
     - **L/D Penalty**: Quadratic penalty for L/D > 20 (avoid sailplanes)
     - **Span Penalty**: Soft constraint for span outside 320-360 mm range
     - **Trailing Edge Penalty**: Soft constraint for TE X > 630 mm

6. **Evolutionary Search**
   - Differential Evolution algorithm (best1bin strategy)
   - Population size: 20
   - Max generations: 40
   - Convergence tolerance: 5e-3
   - Stagnation detection with population perturbation

### Objective Function

```
Objective = 0.6 × (Band L/D)
          - 0.2 × (Span Penalty)
          - (Crash Penalty)      [100% weight if SM < 5%]
          - (Slug Penalty)       [35% weight if SM > 15%]
          - (L/D Penalty)        [if L/D > 20]
          - (Trailing Edge Penalty)
```

**Band L/D**: Mean L/D over a 4° angle-of-attack window, with penalty for high standard deviation (ensures robust performance across the range).

## Tech Stack

- **Python 3.x** - Core optimization logic, data processing, and automation
- **OpenVSP 3.46.0** - Geometry modeling and modification
- **VSPAero** - Aerodynamic analysis solver (panel method) with stability derivatives
- **SciPy** - Differential evolution optimization algorithm
- **NumPy** - Numerical computations and array operations
- **VSP-Script** - OpenVSP scripting language for headless automation

## Key Features

### Stability Integration
- **VSPAero Pitch Mode**: Uses `UnsteadyType=5` to compute stability derivatives
- **Neutral Point Extraction**: Parses `.aerocenter.stab` file for aerodynamic center
- **Dynamic CG**: MassProp analysis provides geometry-dependent center of gravity
- **Static Margin Calculation**: Accurate longitudinal stability metric

### Penalty System
- **Crash Penalty**: Heavy penalty for unstable designs (SM < 5%)
- **Slug Penalty**: Moderate penalty for overly stable designs (SM > 15%)
- **Sweet Spot**: No penalty for 8-12% Static Margin (optimal range)
- **L/D Clipping**: Prevents optimization toward unrealistic sailplane designs
- **Geometric Constraints**: Soft penalties for span and trailing edge limits

### Computational Efficiency
- **Reduced Alpha Sweep**: 7 points (2-14°) instead of 15
- **Optimized Wake Iterations**: 13 iterations (balanced speed/accuracy)
- **Multi-core Processing**: Utilizes 16 CPU cores for VSPAero

### Enhanced Logging
- **Comprehensive CSV**: All metrics logged to `opt_history.csv`
  - Design parameters, L/D values, stability metrics, penalties, timing
  - Individual L/D at each alpha, L/D statistics (min/max/range)
  - Static margin category, generation tracking, new best flags
- **Real-time Output**: Detailed terminal logging with formatted sections
- **Performance Tracking**: VSPAero run time, convergence trends, improvement indicators

## Setup

### Prerequisites

1. **OpenVSP 3.46.0**
   - Download from [OpenVSP website](https://openvsp.org/)
   - Install and note the path to `vsp.exe`

2. **Python 3.x** with required packages:
   ```bash
   pip install numpy scipy matplotlib
   ```

### Configuration

Edit `optimizer2.py` to set your OpenVSP executable path:

```python
VSP_EXE = r"C:\path\to\OpenVSP-3.46.0-win64\vsp.exe"
```

### Required Files

- `baseline.vsp3` - Starting geometry file (must exist)
- `cruise.vspscript` - VSPAero analysis script (includes MassProp + Pitch stability)
- `update_geom.vspscript` - Geometry update script

## Usage

### Running the Optimizer

```bash
# Navigate to Optimization directory
cd "01_Initial Airframe Trades/Optimization"

# Run the optimizer
python optimizer2.py
```

**Recommended**: Run in a separate PowerShell/CMD window (not in Cursor) for long-running optimizations. This allows you to:
- Close the IDE without stopping the optimizer
- Monitor system resources independently
- Capture output to log files

### Output Files

#### Generated During Optimization

- **`opt_history.csv`** - Complete optimization history
  - All design parameters, performance metrics, stability data
  - Individual L/D values, penalties, timing information
  - Generation tracking, convergence indicators

- **`Results.csv`** - Latest VSPAero analysis results (overwritten each iteration)
- **`MassProp_Results.csv`** - Mass properties including dynamic CG
- **`current.aerocenter.stab`** - Neutral point data from Pitch stability analysis
- **`current.des`** - Current design parameters
- **`current.vsp3`** - Current geometry file

#### Analysis Tools

- **`analyze_results.py`** - Generate summary statistics and identify best designs
  ```bash
  python analyze_results.py [opt_history.csv]
  ```

- **`export_best_design.py`** - Export best design to `.des` file
  ```bash
  python export_best_design.py [output_file.des]
  ```

- **`plot_optimization.py`** - Create comprehensive visualization dashboard
  ```bash
  python plot_optimization.py [opt_history.csv]
  ```

### Monitoring Progress

The optimizer provides real-time terminal output with:
- **Design Parameters**: Current geometry configuration
- **Performance Metrics**: Band L/D, L/D range, best angle of attack
- **Stability Metrics**: Static margin, neutral point, CG location, category
- **Penalties**: Breakdown of all penalty terms
- **Objective**: Current and best objective values, improvement trends
- **Timing**: Elapsed time, VSPAero run time per iteration

Watch `opt_history.csv` for complete data logging (can be analyzed even if console output is missed).

## File Structure

```
Optimization/
├── README.md                    # This file
├── optimizer2.py                # Main optimizer script
├── cruise.vspscript             # VSPAero analysis script (MassProp + Pitch mode)
├── update_geom.vspscript        # Geometry update script
│
├── Analysis Tools/
│   ├── analyze_results.py       # Results summary and statistics
│   ├── export_best_design.py    # Export best design to .des file
│   └── plot_optimization.py    # Visualization dashboard
│
├── Testing/
│   ├── test_baseline_stability.py  # Baseline stability validation
│   ├── test_stability.py           # Quick stability test
│   ├── test_milestone3.py         # Milestone 3 validation
│   └── validate_milestone3.py      # Automated milestone checking
│
├── Input Files/
│   ├── baseline.vsp3          # Starting geometry
│   └── baseline.des            # Baseline design parameters
│
└── Generated Files/ (created during optimization)
    ├── opt_history.csv         # Complete optimization log
    ├── Results.csv             # Latest VSPAero results
    ├── MassProp_Results.csv    # Mass properties
    ├── current.aerocenter.stab # Neutral point data
    ├── current.des             # Current design
    └── current.vsp3             # Current geometry
```

## Understanding the Results

### Static Margin Categories

- **`sweet_spot`**: 8-12% Static Margin (optimal, no penalty)
- **`acceptable`**: 5-8% or 12-15% (slight penalty)
- **`unstable`**: < 5% (heavy crash penalty)
- **`overly_stable`**: > 15% (moderate slug penalty)

### Performance Metrics

- **Band L/D**: Mean L/D over optimal 4° window (robust performance metric)
- **L/D Range**: Spread of L/D values (lower = more consistent)
- **Best at α**: Angle of attack where best L/D occurs

### Convergence Indicators

- **New Best**: Flag indicating if this iteration found a new best design
- **Iteration Improvement**: Change in objective from previous iteration
- **Generation Summary**: Average performance per generation

## Troubleshooting

### VSPAero Fails to Run
- Verify OpenVSP executable path is correct in `optimizer2.py`
- Check that `baseline.vsp3` exists and is valid
- Ensure `cruise.vspscript` and `update_geom.vspscript` are in the same directory
- Check VSPAero console output for error messages

### No Stability Data
- Verify `UnsteadyType=5` is set in `cruise.vspscript`
- Check that `current.aerocenter.stab` file is generated
- Ensure MassProp analysis runs before VSPAero (in `cruise.vspscript`)

### Optimization Stagnates
- Adjust `STAGNATION_THRESHOLD` and `STAGNATION_DELTA` in `optimizer2.py`
- Increase population size (`popsize=20`) for better exploration
- Increase maximum generations (`maxiter=40`)
- Review penalty weights if optimizer is too conservative

### Unreasonable Results
- Verify VSPAero analysis settings (Reynolds number, Mach number in `cruise.vspscript`)
- Check that geometry is valid (no self-intersections, reasonable dimensions)
- Review alpha sweep range matches expected flight conditions
- Validate static margin calculations using `test_baseline_stability.py`

## Next Steps / Future Enhancements

- **Multi-Objective Optimization**: Pareto front for L/D vs. stability trade-offs
- **Parallel Evaluation**: Run multiple VSPAero analyses simultaneously
- **Resume/Checkpoint**: Save optimization state to resume interrupted runs
- **Adaptive Convergence**: Auto-adjust parameters based on improvement rate
- **Sensitivity Analysis**: Parameter sensitivity around best design
- **Design Comparison**: Side-by-side comparison of multiple designs

## License

[Add your license information here]

## Contact

[Add contact information if desired]
