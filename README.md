# Quadruped injury adaptation (MuJoCo, Unitree Go1)

Train a robot dog to walk with deep RL, then study how it copes, and adapts, when a leg is injured.

- Robot: Unitree Go1 from [MuJoCo Menagerie](https://github.com/google-deepmind/mujoco_menagerie)
  (`robots/unitree_go1`, Apache-2.0), run through Gymnasium's `Ant-v5` environment class.
  The classic MuJoCo Ant is still available with `--robot ant`.
- Algorithm: SAC (Stable-Baselines3). PPO is also supported.
- Gait: the reward asks for a natural dog trot (see `Go1Control` in `injury_wrapper.py`): a steady
  ~0.8 m/s, diagonal leg pairs stepping together on a 0.5 s stride clock, ~8 cm foot lift, level
  body, no knee or belly contact, and smooth low-torque motion.
- Injuries: `InjuryWrapper` weakens one leg's motors (gain, damping and force limit) to a strength in
  [0, 1]. 0 means the leg is paralysed and goes limp.

## Setup (local)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Phase 1: healthy baseline on Amarel

```bash
rsync -az --exclude .venv --exclude runs ./ <NetID>@amarel.rutgers.edu:~/rl_quadruped/   # from your laptop
ssh <NetID>@amarel.rutgers.edu
cd ~/rl_quadruped && bash amarel/setup_env.sh            # one time
mkdir -p logs && sbatch amarel/phase1.slurm              # Go1, 3 seeds x 3M steps; resumes if preempted
TAG=_trot2x GO1='{"w": {"gait": 1.2, "clearance": 0.8}}' sbatch --array=0-1 amarel/phase1.slurm   # reward variant
squeue -u $USER
```

Each run writes `runs/phase1_go1_seed<N>/healthy_policy.zip`. This is the starting point for Phase 2
(`train.py --init-from ...`) and the no-adaptation baseline. `results/*_damage_eval.json` holds its
performance and gait statistics with each leg paralysed (0.0) or weakened (0.3, 0.6).

`progress/` in this repo is updated automatically during training by `tools/push_progress.sh`. It holds
the best policy, learning curve and gait metrics for each run, at every 500k-step milestone.

## Local commands

```bash
python train.py --robot go1 --timesteps 3000000                     # train
python evaluate.py runs/<run>/healthy_policy.zip --strengths 0 0.3 0.6 --episodes 20 --out results/x.json
python evaluate.py runs/<run>/healthy_policy.zip --video videos/<run> --episodes 1
python watch.py runs/<run>/healthy_policy.zip                        # live MuJoCo viewer
python watch.py runs/<run>/healthy_policy.zip --injured-leg 0 --strength 0
python summarize_phase1.py results/phase1_go1_seed*_damage_eval.json
```

Legs: 0 front_right, 1 front_left, 2 rear_right, 3 rear_left.

Gait metrics reported by `evaluate.py`:
- trot match: share of foot contacts that follow the trot clock
- diagonal sync: diagonal leg pairs on the ground together
- duty factor: share of time each foot is on the ground (about 0.4 to 0.6 for a trot)
- steps per second and swing height
- body contact rate (knees or belly touching the ground)
- base height mean and standard deviation

## Research plan

1. Phase 1: healthy-trained policy, then test it injured. How much worse does it get?
2. Train with `--injury-prob 0.5`: one policy that is robust to injuries (dynamics randomization, paper 12).
3. Add `--expose-injury`: an injury-aware policy, like the RMA "teacher" (paper 9). A next step is training a
   module that estimates the injury from recent states and actions, so the robot doesn't need to be told.
