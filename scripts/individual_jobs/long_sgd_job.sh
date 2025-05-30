#!/bin/bash
# ====================
# Options for sbatch
# ====================

# Location for stdout log - see https://slurm.schedmd.com/sbatch.html#lbAH
#SBATCH --output=/home/%u/slurm_logs/slurm-%A_%a.out

# Location for stderr log - see https://slurm.schedmd.com/sbatch.html#lbAH
#SBATCH --error=/home/%u/slurm_logs/slurm-%A_%a.out

# Maximum number of nodes to use for the job
# #SBATCH --nodes=1

# Generic resources to use - typically you'll want gpu:n to get n gpus
#SBATCH --gres=gpu:1

# Megabytes of RAM required. Check `cluster-status` for node configurations
#SBATCH --mem=8000

# Number of CPUs to use. Check `cluster-status` for node configurations
#SBATCH --cpus-per-task=1

# Maximum time for the job to run, format: days-hours:minutes:seconds
#SBATCH --time=10:00:00

echo "Starting job $SLURM_JOB_ID"
echo "Running on $SLURM_JOB_NODELIST"
echo "Job submitted at `date`"
echo "-----------------------------------"

# ===================
# Environment setup
# ===================

echo "Setting up bash enviroment"

# Make available all commands on $PATH as on headnode
source ~/.bashrc

# Make script bail out after first error
set -e

# Make your own folder on the node's scratch disk
# N.B. disk could be at /disk/scratch_big, or /disk/scratch_fast. Check
# yourself using an interactive session, or check the docs:
#     http://computing.help.inf.ed.ac.uk/cluster-computing
SCRATCH_DISK=/disk/scratch
SCRATCH_HOME=${SCRATCH_DISK}/${USER}
mkdir -p ${SCRATCH_HOME}


# Set up the virtual environment
echo "Loading modules"

VENV_DIR=~/ug4_venv
python3 -m venv $VENV_DIR
source $VENV_DIR/bin/activate
pip install --upgrade pip
pip install -r ~/LeadSheetTranscription/requirements.txt


# Move data
echo "Moving input data to the compute node's scratch space: $SCRATCH_DISK"

repo_home=/home/${USER}/LeadSheetTranscription
src_path=${repo_home}/data/processed

# input data directory path on the scratch disk of the node
dest_path=${SCRATCH_HOME}/data/processed
mkdir -p ${dest_path}  # make it if required

rsync --archive --update --compress --progress ${src_path}/ ${dest_path}

# Empty the output directory
# rm -rf ${SCRATCH_HOME}/experiments
mkdir -p ${SCRATCH_HOME}/experiments

echo "Running script"
cd ${repo_home}

# Run script
python ${repo_home}/src/run.py --exp_name=long_sgd --input_dir=${dest_path} --output_dir=${repo_home}/experiments/long_sgd --epochs=2000 --optimiser=sgd

# ======================================
# Move output data from scratch to DFS
# ======================================
# This presumes your command wrote data to some known directory. In this
# example, send it back to the DFS with rsync

echo "Moving output data back to DFS"

src_path=${SCRATCH_HOME}/experiments
dest_path=${repo_home}/experiments/
rsync --archive --update --compress --progress ${src_path}/ ${dest_path}

# =========================
# Post experiment logging
# =========================
echo ""
echo "============"
echo "job finished successfully"
dt=$(date '+%d/%m/%Y %H:%M:%S')
echo "Job finished: $dt"

# Deactivate the virtual environment (optional but good practice)
deactivate