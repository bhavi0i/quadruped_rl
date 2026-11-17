#!/bin/bash
# C13 validation (report 44): C13 seed 0 checkpoints 237-254M at 0.5 / 0.75 / 1.0 on 12 layouts,
# plus a 0.5 sweep of every C13 checkpoint (all seeds, >= 233M) on 6 layouts.
#SBATCH -J sweep_c13
#SBATCH -p main
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 32
#SBATCH --mem=64G
#SBATCH -t 06:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONUNBUFFERED=1 MUJOCO_GL=egl
W=$((SLURM_CPUS_PER_TASK - 1))
CK=$(ls obstacle_course/runs/course_c13_seed0/ckpt_2[345]*_steps.zip | grep -v vecnorm | awk -F_ '{s=$(NF-1); if (s>=237000000) print}')
~/.conda/envs/rlq/bin/python tools/checkpoint_sweep.py --checkpoints $CK --difficulties 0.5 0.75 1.0 \
    --layouts 12 --workers $W --out results/validate_c13s0.json
~/.conda/envs/rlq/bin/python tools/checkpoint_sweep.py --runs course_c13_seed0 course_c13_seed1 course_c13_seed2 \
    --every 1 --min-steps 233e6 --layouts 6 --workers $W --out results/sweep_c13.json
