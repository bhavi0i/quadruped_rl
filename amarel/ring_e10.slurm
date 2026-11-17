#!/bin/bash
# E10: continue from milestone 2 (E9 seed 2 at 39M: all 9 goals, walls 100 %) - no restart.
#   Same rewards as E9, plus ONE change: --wall-spawn 0.5 -> about 30 % of all episodes start in
#   the exact wall-test situation (0.8-1.2 m from the ring wall, facing it within +-60 deg).
#   Why: E9's wall skill drifted between checkpoints (0-100 %); seeds that turned the "wrong" way
#   (right) ended up facing backwards along the route and stood still. More practice of the
#   left-turn decision at the wall should make it consistent. See EXPERIMENT_LOG.md E10.
#   INIT=runs/milestone_e9s2_39M.zip STEPS=59e6 sbatch amarel/ring_e10.slurm   (39M + 20M)
#SBATCH -J ring_e10
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
$PY train.py --arena ring --steps $STEPS --envs $ENVS --seed $SEED --out runs/ring_e10_seed${SEED} \
    --init-from $INIT --torch-threads 2 \
    --reward-weights '{"heading_progress": 0.5, "track_following": 1.0, "body_alignment": 1.5, "lateral_velocity": -2.0, "orientation": -30.0}' \
    --turn-practice 0.4 --ring-lookahead 0.25 --wall-spawn 0.5
