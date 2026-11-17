#!/bin/bash
# Stage 1: Go1 learns to walk (natural trot, steering, wall avoidance) by doing laps of the
# flat training ring. PPO with one simulation per CPU core. Resumes from the newest checkpoint
# if Amarel preempts the job.
#   cd ~/rl_quadruped && sbatch amarel/ring_ppo.slurm
#   STEPS=50e6 sbatch --array=0-2 amarel/ring_ppo.slurm
#SBATCH -J ring_ppo
#SBATCH -p main
#SBATCH --requeue
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 32
#SBATCH --mem=48G
#SBATCH -t 24:00:00
#SBATCH --array=0-2
#SBATCH -o logs/%x_%A_%a.out
#SBATCH -e logs/%x_%A_%a.err

set -e
SEED=${SLURM_ARRAY_TASK_ID:-0}
STEPS=${STEPS:-40e6}
ENVS=$((SLURM_CPUS_PER_TASK - 2))
PY=~/.conda/envs/rlq/bin/python
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONUNBUFFERED=1

cd obstacle_course
echo "host=$(hostname) job=$SLURM_JOB_ID seed=$SEED envs=$ENVS restart=${SLURM_RESTART_COUNT:-0}"
$PY train.py --arena ring --steps $STEPS --envs $ENVS --seed $SEED --out runs/ring_seed${SEED} --torch-threads 2
