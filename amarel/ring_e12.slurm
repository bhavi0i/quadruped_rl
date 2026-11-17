#!/bin/bash
# E12: same as E11 but with ~3-4x stronger leg-posture terms, run in parallel with E11 from the
#   same start (milestone 3, 51M) - no restart. E11 at +4-6M barely moved the leg goals
#   (fore-aft 11.3 -> 8.2-10.2 cm, step-height spread 87 -> 66-78 %): a front leg lifting 15 cm
#   instead of 8 cost only ~0.5 of ~8 reward/s.
#   - foot_placement -10 -> -40, hip_abduction -2 -> -6, swing_shape 1.0 -> 3.0
#   INIT=runs/milestone_e10s1_51M.zip STEPS=66e6 sbatch amarel/ring_e12.slurm
#SBATCH -J ring_e12
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
$PY train.py --arena ring --steps $STEPS --envs $ENVS --seed $SEED --out runs/ring_e12_seed${SEED} \
    --init-from $INIT --torch-threads 2 \
    --reward-weights '{"heading_progress": 0.5, "track_following": 1.0, "body_alignment": 1.5, "lateral_velocity": -2.0, "orientation": -30.0, "foot_placement": -40.0, "hip_abduction": -6.0, "swing_shape": 3.0}' \
    --turn-practice 0.4 --ring-lookahead 0.25 --wall-spawn 0.5
