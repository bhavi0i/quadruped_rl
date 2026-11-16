#!/bin/bash
# One-time setup on an Amarel LOGIN node (only installs packages, runs nothing heavy).
#   bash amarel/setup_env.sh
set -e
CONDA=/projects/community/anaconda/2025.06/ts840/bin/conda
mkdir -p ~/.conda/pkgs/cache ~/.conda/envs
$CONDA create -y -n rlq --override-channels -c conda-forge python=3.11
~/.conda/envs/rlq/bin/pip install --upgrade pip
# CPU-only torch keeps the env small; SAC with 256x256 nets is CPU-bound anyway.
~/.conda/envs/rlq/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
~/.conda/envs/rlq/bin/pip install -r "$(dirname "$0")/../requirements.txt"
~/.conda/envs/rlq/bin/python -c "import gymnasium as g; e=g.make('Ant-v5'); print('Ant-v5 OK', e.observation_space.shape)"
