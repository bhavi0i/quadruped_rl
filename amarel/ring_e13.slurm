#!/bin/bash
# E13: continue from the best E12 checkpoint (seed 2 at 55M: feet under hips 6.9/3.5 cm, walls
#   100 %) - no restart. Same as E12 plus swing_overshoot -1000: a quadratic penalty on any foot
#   lifting more than 10 cm. In E11/E12 the front-right leg kept lifting 13-15 cm (others ~8 cm)
#   because the swing_shape bell curve gives no gradient that far from target.
#   INIT=runs/e12s2_55M.zip STEPS=70e6 sbatch amarel/ring_e13.slurm
#SBATCH -J ring_e13
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
$PY train.py --arena ring --steps $STEPS --envs $ENVS --seed $SEED --out runs/ring_e13_seed${SEED} \
    --init-from $INIT --torch-threads 2 \
    --reward-weights '{"heading_progress": 0.5, "track_following": 1.0, "body_alignment": 1.5, "lateral_velocity": -2.0, "orientation": -30.0, "foot_placement": -40.0, "hip_abduction": -6.0, "swing_shape": 3.0, "swing_overshoot": -1000.0}' \
    --turn-practice 0.4 --ring-lookahead 0.25 --wall-spawn 0.5
