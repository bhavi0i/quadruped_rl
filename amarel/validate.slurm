#!/bin/bash
# Generic validation (C14+): every EVERY-th checkpoint of RUNS (>= MIN_STEPS) at DIFFS on LAYOUTS layouts.
#   RUNS="course_c14_seed0 course_c14_seed1 course_c14_seed2" MIN_STEPS=216e6 EVERY=2 OUT=results/validate_c14.json sbatch amarel/validate.slurm
#SBATCH -J validate
#SBATCH -p main
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 32
#SBATCH --mem=64G
#SBATCH -t 08:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONUNBUFFERED=1 MUJOCO_GL=egl
~/.conda/envs/rlq/bin/python tools/checkpoint_sweep.py --runs $RUNS --every ${EVERY:-2} --min-steps ${MIN_STEPS:-0} \
    --difficulties ${DIFFS:-0.5 0.75 1.0} --layouts ${LAYOUTS:-12} --workers $((SLURM_CPUS_PER_TASK - 1)) \
    --out ${OUT:-results/validate.json}
