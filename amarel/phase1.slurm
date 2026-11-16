#!/bin/bash
# Phase 1: train a healthy Go1 (or Ant, with ROBOT=ant) SAC walker (3 seeds as a job array), then
# measure how each healthy policy does on the damaged robot.
#   cd ~/rl_quadruped && sbatch amarel/phase1.slurm
# The main partition is preemptible: --requeue + checkpoints make the job resume where it stopped.
#SBATCH -J phase1_go1
#SBATCH -p main
#SBATCH --requeue
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 4
#SBATCH --mem=24G
#SBATCH -t 72:00:00
#SBATCH --array=0-2
#SBATCH -o logs/%x_%A_%a.out
#SBATCH -e logs/%x_%A_%a.err

set -e
SEED=${SLURM_ARRAY_TASK_ID:-0}
STEPS=${STEPS:-3000000}
ROBOT=${ROBOT:-go1}
TAG=${TAG:-}
GO1=${GO1:-'{}'}
RUN=phase1_${ROBOT}${TAG}_seed${SEED}
RUNS_DIR=${RUNS_DIR:-runs}
PY=~/.conda/envs/rlq/bin/python
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK MKL_NUM_THREADS=$SLURM_CPUS_PER_TASK

echo "host=$(hostname) job=$SLURM_JOB_ID seed=$SEED restart=${SLURM_RESTART_COUNT:-0}"
$PY train.py --robot $ROBOT --go1 "$GO1" --algo sac --timesteps $STEPS --seed $SEED --run-name $RUN \
    --runs-dir $RUNS_DIR --device cpu

# The saved healthy policy: starting point for Phase 2 and the no-adaptation baseline.
cp $RUNS_DIR/$RUN/best_model.zip $RUNS_DIR/$RUN/healthy_policy.zip

mkdir -p results
$PY evaluate.py $RUNS_DIR/$RUN/healthy_policy.zip --episodes 20 \
    --strengths 0.0 0.3 0.6 --out results/${RUN}_damage_eval.json
MUJOCO_GL=egl $PY evaluate.py $RUNS_DIR/$RUN/healthy_policy.zip --episodes 1 \
    --video videos/$RUN || echo "video rendering unavailable on this node (non-fatal)"
