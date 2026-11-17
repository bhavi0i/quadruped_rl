#!/bin/bash
# E8: continue training from a finished E7 ring policy (no restart from scratch) with
#   - turn_to_route reward 1.0   (turn toward the route when facing > 45 deg away, e.g. at a wall)
#   - track_following reward 1.0 (stay on the yellow line)
#   - turn-practice spawns 40 % (up from 25 %)
# Walking rewards are unchanged. See EXPERIMENT_LOG.md E8.
#   INIT=runs/ring_seed1/final.zip STEPS=60e6 sbatch amarel/ring_e8.slurm
# STEPS is the total step count (the E7 policy already has 40M), so 60e6 = 20M more steps.
#SBATCH -J ring_e8
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
STEPS=${STEPS:-60e6}
INIT=${INIT:?set INIT to the E7 final policy, e.g. runs/ring_seed1/final.zip}
ENVS=$((SLURM_CPUS_PER_TASK - 2))
PY=~/.conda/envs/rlq/bin/python
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONUNBUFFERED=1

cd obstacle_course
echo "host=$(hostname) job=$SLURM_JOB_ID seed=$SEED init=$INIT restart=${SLURM_RESTART_COUNT:-0}"
$PY train.py --arena ring --steps $STEPS --envs $ENVS --seed $SEED --out runs/ring_e8_seed${SEED} \
    --init-from $INIT --torch-threads 2 \
    --reward-weights '{"turn_to_route": 1.0, "track_following": 1.0}' --turn-practice 0.4
