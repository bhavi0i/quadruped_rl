#!/bin/bash
# Checkpoint sweep: evaluate saved course checkpoints in parallel on the fixed benchmark and rank them.
#   RUNS="course_c10_seed0 course_c10_seed1 course_c10_seed2" EVERY=2 OUT=results/sweep_c10.json sbatch amarel/sweep.slurm
#SBATCH -J sweep
#SBATCH -p main
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 32
#SBATCH --mem=64G
#SBATCH -t 06:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONUNBUFFERED=1 MUJOCO_GL=egl
~/.conda/envs/rlq/bin/python tools/checkpoint_sweep.py --runs $RUNS --every ${EVERY:-2} \
    --min-steps ${MIN_STEPS:-0} --difficulty ${BENCH:-0.5} --layouts ${LAYOUTS:-6} \
    --workers $((SLURM_CPUS_PER_TASK - 1)) --out ${OUT:-results/sweep.json}
