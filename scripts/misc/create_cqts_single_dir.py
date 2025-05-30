#!/usr/bin/env python3
"""Script for generating experiments.txt"""
import os
# import autorootcwd
USER = os.getenv("USER")
EDDIE = os.getenv("EDDIE")

REPO_HOME = f"/home/{USER}/LeadSheetTranscription"
DATA_HOME = f"{EDDIE}/data/processed"

input_dir = f"{DATA_HOME}/audio"
output_dir = f"{DATA_HOME}/cache/4096/cqts/"

os.makedirs(output_dir, exist_ok=True)
files = os.listdir(input_dir)
files = [f for f in files if f.endswith(".mp3")]
max_group_size = 1213

base_call = f"python {REPO_HOME}/src/data/create_cached_datasets.py --input_dir={input_dir} --output_dir={output_dir} --create_cqts"

output_file = open("./scripts/experiments.txt", "w")

for i in range(0, len(files), max_group_size):
    start_idx = i
    end_idx = min(i + max_group_size, len(files))

    expt_call = (
        f"{base_call} --start_idx={start_idx} --end_idx={end_idx}"
    )

    print(expt_call, file=output_file)

# Print number of experiments
print(
    f"Generated {len(files) // max_group_size} experiments with max group size of {max_group_size}."
)

output_file.close()
