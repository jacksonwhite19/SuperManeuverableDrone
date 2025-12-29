# Fixed Wing Drone Planform Optimizer

An automated optimization system that uses OpenVSP and VSPAero to iteratively improve fixed-wing drone planform configurations. The optimizer evaluates aerodynamic performance across multiple angles of attack and uses evolutionary algorithms to find efficient vehicle designs.

## Overview

This optimizer automates the design exploration process by:
1. **Generating design variations** - Modifies wing geometry parameters (span, sweep, taper, etc.)
2. **Running aerodynamic simulations** - Executes VSPAero analyses at multiple angles of attack (2-16°)
3. **Evaluating performance** - Extracts lift-to-drag (L/D) ratios and applies design constraints
4. **Iterating toward optimal designs** - Uses differential evolution to converge on high-performing configurations

## Tech Stack

- **Python 3.x** - Core optimization logic and automation
- **OpenVSP** - Geometry generation and modification
- **VSPAero** - Aerodynamic analysis solver (integrated with OpenVSP)
- **SciPy** - Differential evolution optimization algorithm
- **NumPy** - Numerical computations and data processing

## How It Works

### Design Variables
The optimizer adjusts the following wing planform parameters:
- **Span** (mm) - Wing half-span
- **Sweep** (degrees) - Wing sweep angle
- **X Location** (mm) - Wing root position along fuselage
- **Taper Ratio** - Ratio of tip chord to root chord
- **Tip Chord** (mm) - Wing tip chord length
- **Control Fraction** - Control surface length as fraction of chord

### Optimization Process

1. **Geometry Update**: Python writes a `.des` file with design parameters, then calls OpenVSP script to update the geometry
2. **Aerodynamic Analysis**: VSPAero sweeps through angles of attack (2-16°) and computes L/D ratios
3. **Performance Extraction**: Python parses `Results.csv` to extract L/D values across the alpha range
4. **Objective Evaluation**: Combines L/D performance with penalties for:
   - Span constraints (balance between efficiency and agility)
   - Trailing edge position (geometric constraints)
5. **Evolutionary Search**: Differential evolution algorithm generates new candidate designs based on performance feedback

### Objective Function
The optimizer maximizes a weighted objective:
```
Objective = 0.7 × (Band L/D) - 0.3 × (Span Penalty) - (Trailing Edge Penalty)
```

Where "Band L/D" is the mean L/D over a 4-point window, penalized by standard deviation to favor consistent performance.

## Setup

### Prerequisites
1. **OpenVSP** - Download and install from [OpenVSP website](https://openvsp.org/)
2. **Python 3.x** with packages:
   ```bash
   pip install numpy scipy
   ```

### Configuration
Edit the optimizer script to set your OpenVSP executable path:
```python
VSP_EXE = r"C:\path\to\vsp.exe"
```

### Required Files
- `baseline.vsp3` - Starting geometry file
- `cruise.vspscript` - OpenVSP script for running VSPAero analysis
- `update_geom.vspscript` - OpenVSP script for updating geometry from `.des` file (if separate)

## Usage

### Running the Optimizer

```bash
python optimizer2.py
```

The optimizer will:
1. Evaluate the baseline design first
2. Run differential evolution optimization
3. Log all iterations to `opt_history.csv`
4. Print progress to console

### Output Files

- **`opt_history.csv`** - Complete optimization history with:
  - Design parameters for each iteration
  - L/D values and penalties
  - Objective function values
  - Timing information
  
- **`Results.csv`** - Latest VSPAero analysis results (overwritten each iteration)
- **`current.des`** - Current design parameter file

### Monitoring Progress

Watch the console output for:
- Iteration number and elapsed time
- Current design parameters
- L/D performance metrics
- Objective function values
- Best design found so far

## Testing Milestones

Use these milestones to verify the optimizer is working correctly:

### Milestone 1: Baseline Evaluation ✓
**Goal**: Verify the system can run a single VSPAero analysis

**Check**:
- [ ] Baseline design is evaluated successfully
- [ ] `Results.csv` is generated after baseline run
- [ ] Console shows L/D values and objective function
- [ ] No errors in OpenVSP/VSPAero execution

**Expected Output**:
```
Baseline evaluation:
--- Iteration 1 ---
t = 0.0 min
Design: span=330.0 mm, sweep=25.0 deg, ...
Band L/D = X.XXXX, ...
```

### Milestone 2: Geometry Updates ✓
**Goal**: Verify design parameters can be modified

**Check**:
- [ ] `current.des` file is created with correct format
- [ ] OpenVSP successfully updates geometry from `.des` file
- [ ] Modified geometry produces different L/D results
- [ ] Design parameters in log file match input values

**Test**: Manually modify `current.des` and verify geometry changes in OpenVSP GUI

### Milestone 3: First Optimization Generation ✓
**Goal**: Verify the optimizer generates and evaluates multiple designs

**Check**:
- [ ] Multiple iterations appear in console (population size = 20)
- [ ] Each iteration shows different design parameters
- [ ] `opt_history.csv` contains entries for all evaluations
- [ ] Best objective value updates as better designs are found

**Expected**: After first generation, you should see ~20 iterations logged

### Milestone 4: Convergence Behavior ✓
**Goal**: Verify the optimizer improves designs over time

**Check**:
- [ ] Best objective value increases over multiple generations
- [ ] Design parameters show reasonable variation within bounds
- [ ] Convergence callback triggers when stagnation is detected
- [ ] Total optimization time is reasonable (minutes to hours depending on problem)

**Expected**: Best objective should improve from baseline, then plateau or converge

### Milestone 5: Results Validation ✓
**Goal**: Verify extracted L/D values are reasonable

**Check**:
- [ ] L/D values in `opt_history.csv` are positive and reasonable (typically 5-20 for fixed wing)
- [ ] Alpha center values are within the sweep range (2-16°)
- [ ] L/D curve shows expected behavior (peak at moderate alpha)
- [ ] Penalties are applied correctly (check span_penalty and te_penalty columns)

**Test**: Use `checkResultsCSV.py` to manually verify `Results.csv` parsing

### Milestone 6: Complete Optimization Run ✓
**Goal**: Verify full optimization completes successfully

**Check**:
- [ ] Optimization completes without errors
- [ ] Final best design is printed to console
- [ ] `opt_history.csv` contains complete optimization history
- [ ] Best design parameters are within specified bounds
- [ ] Final objective is better than baseline

**Expected Output**:
```
Optimization complete
Total evals: XXX
Total time: XX.X min
Best x: [span, sweep, xloc, taper, tip, ctrl]
Best objective: X.XXXX
```

## Troubleshooting

### VSPAero Fails to Run
- Verify OpenVSP executable path is correct
- Check that `baseline.vsp3` exists and is valid
- Ensure `cruise.vspscript` is in the same directory
- Check OpenVSP console for error messages

### No Results.csv Generated
- Verify VSPAero analysis completes successfully
- Check that the script has write permissions
- Ensure `cruise.vspscript` includes `WriteResultsCSVFile()` call

### Optimization Stagnates
- Adjust `STAGNATION_THRESHOLD` and `STAGNATION_DELTA` parameters
- Increase population size (`popsize`) for better exploration
- Increase maximum iterations (`maxiter`)
- Review bounds to ensure they're not too restrictive

### Unreasonable L/D Values
- Verify VSPAero analysis settings (Reynolds number, Mach number)
- Check that geometry is valid (no self-intersections, reasonable dimensions)
- Review alpha sweep range matches expected flight conditions

## File Structure

```
Optimization/
├── README.md              # This file
├── optimizer1.py          # Original optimizer version
├── optimizer2.py          # Current optimizer version
├── cruise.vspscript       # VSPAero analysis script
├── baseline.vsp3          # Starting geometry
├── baseline.des           # Baseline design parameters
├── current.des            # Current design (generated)
├── Results.csv            # VSPAero results (generated)
├── opt_history.csv        # Optimization log (generated)
├── checkResultsCSV.py     # Utility to verify results parsing
└── find LD by name.py     # Utility to find L/D in results
```

## Next Steps

- **Parameter Tuning**: Adjust objective function weights and penalty terms
- **Constraint Refinement**: Add more geometric or performance constraints
- **Multi-Objective**: Extend to Pareto optimization (e.g., L/D vs. agility)
- **Parallelization**: Run multiple VSPAero analyses in parallel
- **Visualization**: Add plotting scripts to visualize optimization history

