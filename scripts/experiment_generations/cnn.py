#!/usr/bin/env python3
"""Script for generating experiments.txt"""
import os

USER = os.getenv("USER")
EDDIE = os.getenv("EDDIE")
REPO_HOME = f"/home/{USER}/LeadSheetTranscription"

if EDDIE is None:
    EDDIE = REPO_HOME  # Compatibility with eddie and mlt clusters

DATA_HOME = f"{EDDIE}/data/processed"

output_file = open("./scripts/experiments.txt", "w")

base_call = f"python {REPO_HOME}/src/run.py --input_dir={DATA_HOME} --output_dir={EDDIE}/experiments/cnn --model=cnn"

kernel_sizes = [5, 5, 9]

layers = [1, 3, 5]

channels = [1, 5, 10]

params = [(k, l, c) for k, l, c in zip(kernel_sizes, layers, channels)]
nr_expts = len(params)


output_file = open("./scripts/experiments.txt", "w")

for kernel_size, layer, channel in params:
    # Note that we don't set a seed for rep - a seed is selected at random
    # and recorded in the output data by the python script
    expt_call = (
        f"{base_call} "
        f"--exp_name=cnn_k{kernel_size}_l{layer}_c{channel} "
        f"--cnn_kernel_size={kernel_size} "
        f"--num_layers={layer} "
        f"--cnn_channels={channel} "
    )
    print(expt_call, file=output_file)

output_file.close()
