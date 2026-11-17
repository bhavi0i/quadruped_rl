#!/bin/bash
# STAGE 2 (C1): the healthy Go1 learns the obstacle course, continuing from the best stage-1 ring
# policy (no restart from scratch). Obstacles start tiny (difficulty 0) and grow by 0.1 each time
# the robot reliably makes progress (mean distance per episode > CURRIC m). Episodes are 60 s
# (the 23.5 m course takes ~40 s at the natural 0.6 m/s). Spawns: start of a random course section
# (the start line included), so every obstacle type gets practice; evaluation always runs the
# whole course from the start. Natural-gait rewards from stage 1 are kept; swing_shape is halved
# (0.5) so the dog can lift its feet higher than 8 cm for hurdles and steps.
#   INIT=runs/<best_ring_policy>.zip STEPS=<init + 60e6> sbatch amarel/course_ppo.slurm
#   C2: INIT=runs/c1s1_70M.zip STEPS=130e6 TAG=c2 OFFSET=0.15 sbatch amarel/course_ppo.slurm
#   C3: INIT=runs/c2s1_78M.zip STEPS=140e6 TAG=c3 OFFSET=0.15 EXPLORE="--reset-log-std -1.2 --ent-coef 0.002" sbatch amarel/course_ppo.slurm
#SBATCH -J course_ppo
#SBATCH -p main
#SBATCH --requeue
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 32
#SBATCH --mem=48G
#SBATCH -t 48:00:00
#SBATCH --array=0-2
#SBATCH -o logs/%x_%A_%a.out
#SBATCH -e logs/%x_%A_%a.err

set -e
SEED=${SLURM_ARRAY_TASK_ID:-0}
INIT=${INIT:?set INIT to the stage-1 ring policy}
STEPS=${STEPS:?set STEPS (total, e.g. init steps + 60e6)}
CURRIC=${CURRIC:-5.0}
TAG=${TAG:-c1}
OFFSET=${OFFSET:-0.8}
EXPLORE=${EXPLORE:-}    # [C3] e.g. "--reset-log-std -1.2 --ent-coef 0.002" (exploration had collapsed)   # [C1] 0.8 spawned ON the ramp/stairs; [C2] 0.15 = flat run-up before each obstacle
ENVS=$((SLURM_CPUS_PER_TASK - 2))
PY=~/.conda/envs/rlq/bin/python
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONUNBUFFERED=1

cd obstacle_course
echo "host=$(hostname) job=$SLURM_JOB_ID seed=$SEED init=$INIT restart=${SLURM_RESTART_COUNT:-0}"
$PY train.py --arena course --steps $STEPS --envs $ENVS --seed $SEED --out runs/course_${TAG}_seed${SEED} \
    --init-from $INIT --torch-threads 2 --difficulty 0.0 --max-steps 3000 --curriculum-threshold $CURRIC \
    --reward-weights '{"heading_progress": 0.5, "body_alignment": 1.5, "lateral_velocity": -2.0, "orientation": -30.0, "foot_placement": -10.0, "hip_abduction": -2.0, "swing_shape": 0.5}' \
    --turn-practice 0.25 --spawn-offset $OFFSET $EXPLORE
