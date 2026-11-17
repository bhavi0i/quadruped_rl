#!/bin/bash
# E11: continue from milestone 3 (E10 seed 1 at 51M, stage-1 final) - no restart.
#   Same as E10 plus leg posture / step uniformity (the group saw slanted legs, uneven steps):
#   - foot_placement -10  (stance feet back under the hips as in the standing pose)
#   - hip_abduction  -2   (no hip splay)
#   - swing_shape     1.0 (every swinging foot follows the same 8 cm lift curve)
#   Milestone 3 measured: rear feet 13-18 cm behind the hips, step heights 15.5/10/9.3/6.5 cm.
#   INIT=runs/milestone_e10s1_51M.zip STEPS=66e6 sbatch amarel/ring_e11.slurm   (51M + 15M)
#SBATCH -J ring_e11
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
$PY train.py --arena ring --steps $STEPS --envs $ENVS --seed $SEED --out runs/ring_e11_seed${SEED} \
    --init-from $INIT --torch-threads 2 \
    --reward-weights '{"heading_progress": 0.5, "track_following": 1.0, "body_alignment": 1.5, "lateral_velocity": -2.0, "orientation": -30.0, "foot_placement": -10.0, "hip_abduction": -2.0, "swing_shape": 1.0}' \
    --turn-practice 0.4 --ring-lookahead 0.25 --wall-spawn 0.5
