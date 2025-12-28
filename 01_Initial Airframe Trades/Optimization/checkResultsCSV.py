import numpy as np

RESULTS_CSV = "Results1.csv"

def extract_ld_all(results_path):
    alpha_row = 774
    ld_row    = 811  # adjust to the 0-based row where L_D appears
    NUM_POINTS = 11

    with open(results_path, "r") as f:
        rows = [line.strip().split(",") for line in f if line.strip()]

    alphas = np.array([float(x) for x in rows[alpha_row][1:1 + NUM_POINTS]])
    ld     = np.array([float(x) for x in rows[ld_row][1:1 + NUM_POINTS]])
    ld = -ld
    if len(ld) == 0:
        raise RuntimeError(f"L/D row {ld_row} could not be read correctly")

    max_idx = ld.argmax()
    return ld[max_idx], alphas[max_idx], ld, alphas

max_ld, best_alpha, ld_arr, alphas_arr = extract_ld_all(RESULTS_CSV)
print("Alpha:", alphas_arr)
print("L/D:", ld_arr)
print(f"Max L/D = {max_ld:.4f} at alpha = {best_alpha:.2f} deg")
