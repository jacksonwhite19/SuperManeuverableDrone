import numpy as np

# Path to your CSV file
RESULTS_CSV = r"C:\Users\Jackson\Desktop\02_Projects\07_Supermaneueverable Drone\01_Initial Airframe Trades\Optimization\Results1.csv"

# Known alpha values
alphas = np.array([0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20])

# Read CSV manually
with open(RESULTS_CSV, "r") as f:
    rows = [line.strip().split(",") for line in f if line.strip()]

# Find the row that starts with 'L_D'
ld_row = None
for row in rows:
    if row[0].strip() == "L_D":
        ld_row = row
        break

if ld_row is None:
    raise RuntimeError("Could not find L_D row in CSV")

# Convert L/D values to float (skip first column)
ld = np.array([float(x) for x in ld_row[1:1 + len(alphas)]])
ld = -ld  # Note: VSPAERO outputs L/D negative

# Find max L/D
max_idx = ld.argmax()
max_ld = ld[max_idx]
best_alpha = alphas[max_idx]

# Print results
print("Alpha array:", alphas)
print("L/D array:", ld)
print(f"Max L/D = {max_ld:.4f} at alpha = {best_alpha:.2f} deg")
