import pandas as pd
import numpy as np

RESULTS_CSV = "Results.csv"

df = pd.read_csv(RESULTS_CSV, header=None)

alpha_row = 361 - 1
cd_row    = 366 - 1
cl_row    = 380 - 1

alphas = df.iloc[alpha_row, 1:6].astype(float).values
cd     = df.iloc[cd_row,    1:6].astype(float).values
cl     = df.iloc[cl_row,    1:6].astype(float).values

ld = cl / cd
idx = np.argmax(ld)

print("Alphas:", alphas)
print("CL    :", cl)
print("CD    :", cd)
print("L/D   :", ld)
print()
print(f"Max L/D = {ld[idx]:.4f} at alpha = {alphas[idx]:.2f} deg")
