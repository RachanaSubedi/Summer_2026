import opendssdirect as dss
import numpy as np
import pandas as pd
import re, os
from collections import Counter

REPO = r"C:\Users\C838122727\Documents\CSU\research\Summer_2026\oedisi-ieee123"

master     = os.path.join(REPO, 'qsts/master.dss')
loads_path = os.path.join(REPO, 'qsts/IEEE123LoadsQsts.dss')
OUT_DIR    = os.path.dirname(os.path.abspath(__file__))

# Step 1: Compile and verify snapshot
dss.Command(f'Compile "{master}"')
dss.Command('Solve')

vmag_snap = [v for v in dss.Circuit.AllBusMagPu() if v > 0.01]
print(f"Snapshot solved.  Vmin={min(vmag_snap):.4f}  Vmax={max(vmag_snap):.4f}")


# Step 2: Parse ground-truth phase labels
node_to_phase = {1: 'A', 2: 'B', 3: 'C'}
load_labels   = {}   # load_name -> 'A' / 'B' / 'C'
load_node_map = {}   # load_name -> node string e.g. "1.1"

with open(loads_path) as f:
    for line in f:
        m = re.match(r'New Load\.(\S+)\s+Bus1=(\S+)', line, re.IGNORECASE)
        if m:
            name    = m.group(1)
            bus_raw = m.group(2).upper()
            parts   = bus_raw.split('.')
            bus     = parts[0]
            node_num = int(parts[1]) if len(parts) > 1 else 1
            load_labels[name]   = node_to_phase.get(node_num, 'Unknown')
            load_node_map[name] = f"{bus}.{node_num}"

print(f"\nLoads found: {len(load_labels)}")
print(f"Phase distribution: {Counter(load_labels.values())}")


# Step 3: Run QSTS and record measurements

N_STEPS = 35040 # yearly

dss.Command('Set Mode=Yearly')
dss.Command('Set StepSize=0.25h')   # 15-minute intervals
dss.Command('Set Number=1')         # solve one step at a time

load_names   = list(load_labels.keys())
volt_records = {n: [] for n in load_names}
p_records    = {n: [] for n in load_names}
q_records    = {n: [] for n in load_names}

print(f"\nRunning {N_STEPS} QSTS steps (~{N_STEPS//96} days at 15-min resolution)...")

for step in range(N_STEPS):
    dss.Command('Solve')

    node_names = [n.upper() for n in dss.Circuit.AllNodeNames()]
    vmag_pu    = dss.Circuit.AllBusMagPu()
    vmag_dict  = dict(zip(node_names, vmag_pu))

    for name in load_names:
        node_key = load_node_map[name].upper()
        volt_records[name].append(vmag_dict.get(node_key, np.nan))
        dss.Loads.Name(name)
        p_records[name].append(dss.Loads.kW())
        q_records[name].append(dss.Loads.kvar())

    if (step + 1) % 480 == 0:
        valid_v = [v for v in vmag_dict.values() if v > 0.01]
        print(f"  Step {step+1:4d}/{N_STEPS}  "
              f"Vmin={min(valid_v):.4f}  Vmax={max(valid_v):.4f}")

print("\nQSTS complete.")

# Step 4: Assemble and save
volt_df = pd.DataFrame(volt_records)
p_df    = pd.DataFrame(p_records)
q_df    = pd.DataFrame(q_records)

print(f"\nVoltage matrix shape: {volt_df.shape}   (timesteps × loads)")
print(f"Voltage range:        {volt_df.min().min():.4f} – {volt_df.max().max():.4f} pu")
print(f"NaN count:            {volt_df.isna().sum().sum()}")

labels_df  = pd.DataFrame.from_dict(load_labels,   orient='index', columns=['true_phase'])
nodemap_df = pd.DataFrame.from_dict(load_node_map, orient='index', columns=['node'])
labels_df.index.name  = 'load_name'
nodemap_df.index.name = 'load_name'

files = {
    'voltage_timeseries_30d.csv': volt_df,
    'active_power_30d.csv':       p_df,
    'reactive_power_30d.csv':     q_df,
    'ground_truth_phases.csv':    labels_df,
    'load_node_map.csv':          nodemap_df,
}

for fname, df in files.items():
    path = os.path.join(OUT_DIR, fname)
    df.to_csv(path, index=(df is labels_df or df is nodemap_df))
    print(f"  Saved: {fname}  ({os.path.getsize(path)/1024:.0f} KB)")
