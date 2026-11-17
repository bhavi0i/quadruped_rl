#!/bin/bash
# E9: continue from a finished E8 policy (no restart from scratch). Keeps E8's
#   turn_to_route 1.0, track_following 1.0, turn-practice 40 %, and adds natural posture:
#   - body_alignment reward 1.5   (body points where it moves; E7/E8 policies crab ~30 deg)
#   - lateral_velocity -2.0       (no diagonal / sideways walking)
#   - orientation -1 -> -30       (small leans and nose-down pitch now cost something)
#   - ring steering target 0.6 -> 0.25 rad ahead (old target sat ~17 deg inward of travel)
# See EXPERIMENT_LOG.md E9.
#   INIT=runs/ring_e8_seed0/final.zip STEPS=80e6 sbatch amarel/ring_e9.slurm
#SBATCH -J ring_e9
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
$PY train.py --arena ring --steps $STEPS --envs $ENVS --seed $SEED --out runs/ring_e9_seed${SEED} \
    --init-from $INIT --torch-threads 2 \
    --reward-weights '{"turn_to_route": 1.0, "track_following": 1.0, "body_alignment": 1.5, "lateral_velocity": -2.0, "orientation": -30.0}' \
    --turn-practice 0.4 --ring-lookahead 0.25
