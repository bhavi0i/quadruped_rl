#!/bin/bash
# Hardware benchmark: same 2M-step ring PPO run on different node types; compare fps in the log.
#   sbatch -p main -c 32 amarel/bench.slurm cpu      sbatch -p main -c 64 amarel/bench.slurm cpu
#   sbatch -p gpu -c 32 --gres=gpu:1 amarel/bench.slurm cuda
#SBATCH -J bench
#SBATCH -N 1
#SBATCH -n 1
#SBATCH --mem=48G
#SBATCH -t 01:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err
DEV=${1:-cpu}
THREADS=${THREADS:-2}
PY=~/.conda/envs/rlq/bin/python
[ "$DEV" = cuda ] && PY=~/.conda/envs/rlq-gpu/bin/python
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONUNBUFFERED=1
cd obstacle_course
echo "host=$(hostname) cpus=$SLURM_CPUS_PER_TASK device=$DEV torch_threads=$THREADS"; nvidia-smi -L 2>/dev/null
$PY train.py --arena ring --steps 2e6 --envs $((SLURM_CPUS_PER_TASK - 2)) --device $DEV \
    --out /tmp/bench_$SLURM_JOB_ID --torch-threads $THREADS --ckpt-freq 1e9
