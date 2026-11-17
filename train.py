# SUPERSEDED (2026-11-16): flat-ground SAC training of Phase 1. The project moved to
# obstacle_course/train.py (PPO, ~60x faster, training ring + obstacle course). Kept for the record;
# see EXPERIMENT_LOG.md (experiments E1-E3).
"""Train a 4-legged robot (MuJoCo Ant) to walk with deep RL.

Examples
--------
# Phase 1 baseline: healthy Go1 robot dog, SAC, 3M steps (resumable)
python train.py --robot go1 --timesteps 3000000 --run-name phase1_go1_seed0

# Same with the classic MuJoCo Ant
python train.py --robot ant --timesteps 3000000

# PPO with 8 parallel environments
python train.py --algo ppo --n-envs 8 --timesteps 3000000

# Injury-robust policy: 50% of episodes start with one weakened/paralysed leg
python train.py --algo sac --injury-prob 0.5 --run-name sac_injury_rand

# Fine-tune from an existing policy (Phase 2 starting point)
python train.py --robot go1 --init-from runs/phase1_go1_seed0/healthy_policy.zip --injury-prob 1.0

Watch progress with:  tensorboard --logdir runs
"""

import argparse
import glob
import json
import os
import re

import numpy as np
import torch
from stable_baselines3 import PPO, SAC
from stable_baselines3.common.callbacks import BaseCallback, CheckpointCallback, EvalCallback
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.vec_env import SubprocVecEnv, VecNormalize

from injury_wrapper import make_env


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--robot", choices=["go1", "ant"], default="go1")
    p.add_argument("--go1", type=json.loads, default={},
                   help='Go1 gait/reward settings as JSON, e.g. \'{"v_target": 1.0, "w": {"gait": 1.0}}\'')
    p.add_argument("--algo", choices=["sac", "ppo"], default="sac")
    p.add_argument("--timesteps", type=int, default=3_000_000)
    p.add_argument("--n-envs", type=int, default=None,
                   help="parallel envs (default: 1 for SAC, 8 for PPO)")
    p.add_argument("--injury-prob", type=float, default=0.0,
                   help="probability an episode starts with an injured leg (0 = plain walking)")
    p.add_argument("--expose-injury", action="store_true",
                   help="append per-leg strengths to the observation")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--run-name", type=str, default=None)
    p.add_argument("--runs-dir", type=str, default="runs")
    p.add_argument("--device", type=str, default="auto")
    p.add_argument("--checkpoint-freq", type=int, default=250_000,
                   help="env steps between checkpoints (model + replay buffer, used to resume)")
    p.add_argument("--eval-freq", type=int, default=25_000)
    p.add_argument("--no-resume", action="store_true",
                   help="start fresh even if checkpoints exist in the run dir")
    p.add_argument("--init-from", type=str, default=None,
                   help="initialise weights from this saved model (e.g. Phase 1 policy)")
    p.add_argument("--torch-threads", type=int, default=None,
                   help="limit torch CPU threads (defaults to SLURM_CPUS_PER_TASK if set)")
    return p.parse_args()


class WalkingStats(BaseCallback):
    """Log how far / fast the robot actually walks (return alone is misleading:
    standing still earns the healthy bonus)."""

    def __init__(self):
        super().__init__()
        self.x_vel = []

    def _on_step(self):
        for info, done in zip(self.locals["infos"], self.locals["dones"]):
            if "x_velocity" in info:
                self.x_vel.append(info["x_velocity"])
            if done and "episode" in info:
                self.logger.record_mean("walk/ep_x_position", info.get("x_position", 0.0))
        if self.num_timesteps % 1000 == 0 and self.x_vel:
            self.logger.record("walk/mean_x_velocity", float(np.mean(self.x_vel)))
            self.x_vel.clear()
        return True


class SaveReplayBuffer(BaseCallback):
    """Overwrite a single replay-buffer file periodically so a preempted job can resume."""

    def __init__(self, path, freq):
        super().__init__()
        self.path, self.freq = path, freq

    def _on_step(self):
        if self.n_calls % self.freq == 0 and hasattr(self.model, "save_replay_buffer"):
            tmp = self.path + "_tmp"  # SB3 appends .pkl
            self.model.save_replay_buffer(tmp)
            os.replace(tmp + ".pkl", self.path + ".pkl")
        return True


def latest_checkpoint(ckpt_dir):
    files = glob.glob(os.path.join(ckpt_dir, "model_*_steps.zip"))
    if not files:
        return None, 0
    steps = lambda f: int(re.search(r"model_(\d+)_steps", f).group(1))
    f = max(files, key=steps)
    return f, steps(f)


def main():
    args = parse_args()
    threads = args.torch_threads or int(os.environ.get("SLURM_CPUS_PER_TASK", 0)) or None
    if threads:
        torch.set_num_threads(threads)

    n_envs = args.n_envs or (1 if args.algo == "sac" else 8)
    run_name = args.run_name or f"{args.robot}_{args.algo}_inj{args.injury_prob}_seed{args.seed}"
    run_dir = os.path.join(args.runs_dir, run_name)
    ckpt_dir = os.path.join(run_dir, "checkpoints")
    old_cfg = os.path.join(run_dir, "config.json")
    if not args.no_resume and os.path.exists(old_cfg) and glob.glob(os.path.join(ckpt_dir, "*.zip")):
        # Resuming: keep the robot the run started with (runs from before --robot existed are Ant).
        args.robot = json.load(open(old_cfg)).get("robot", "ant")
    os.makedirs(ckpt_dir, exist_ok=True)
    with open(os.path.join(run_dir, "config.json"), "w") as f:
        json.dump(vars(args) | {"n_envs": n_envs}, f, indent=2)

    env_kwargs = dict(robot=args.robot, go1_kwargs=args.go1, injury_prob=args.injury_prob, expose_injury=args.expose_injury)
    vec_cls = SubprocVecEnv if n_envs > 1 else None
    env = make_vec_env(make_env, n_envs=n_envs, seed=args.seed,
                       env_kwargs=env_kwargs, vec_env_cls=vec_cls)
    # Evaluate on the same injury distribution we train on.
    eval_env = make_vec_env(make_env, n_envs=1, seed=args.seed + 1000, env_kwargs=env_kwargs)

    Algo = PPO if args.algo == "ppo" else SAC
    ckpt, done_steps = (None, 0) if args.no_resume else latest_checkpoint(ckpt_dir)
    rb_path = os.path.join(ckpt_dir, "replay_buffer")

    if args.algo == "ppo":
        # PPO is sensitive to observation/reward scale; normalise both.
        env = VecNormalize(env, norm_obs=True, norm_reward=True, clip_obs=10.0)
        eval_env = VecNormalize(eval_env, norm_obs=True, norm_reward=False, training=False)

    if ckpt:
        print(f"Resuming from {ckpt} ({done_steps} steps done)")
        if args.algo == "ppo":
            vn = ckpt.replace("model_", "model_vecnormalize_").replace(".zip", ".pkl")
            if os.path.exists(vn):
                env = VecNormalize.load(vn, env.venv)
        model = Algo.load(ckpt, env=env, device=args.device,
                          tensorboard_log=args.runs_dir)
        if args.algo == "sac" and os.path.exists(rb_path + ".pkl"):
            model.load_replay_buffer(rb_path + ".pkl")
            print(f"Loaded replay buffer ({model.replay_buffer.size()} transitions)")
    elif args.algo == "ppo":
        model = PPO(
            "MlpPolicy", env,
            n_steps=max(2048 // n_envs, 64),  # rollout length per env
            batch_size=256,
            n_epochs=10,
            learning_rate=3e-4,
            gamma=0.99,
            gae_lambda=0.95,
            clip_range=0.2,
            ent_coef=0.0,
            policy_kwargs=dict(net_arch=dict(pi=[256, 256], vf=[256, 256])),
            tensorboard_log=args.runs_dir, seed=args.seed, device=args.device, verbose=1,
        )
    else:
        # Standard SAC hyper-parameters for MuJoCo locomotion (Haarnoja et al. 2018 / rl-zoo).
        model = SAC(
            "MlpPolicy", env,
            learning_rate=3e-4,
            buffer_size=1_000_000,
            learning_starts=10_000,
            batch_size=256,
            tau=0.005,
            gamma=0.99,
            train_freq=1,
            gradient_steps=1,
            ent_coef="auto",
            policy_kwargs=dict(net_arch=[256, 256]),
            tensorboard_log=args.runs_dir, seed=args.seed, device=args.device, verbose=1,
        )

    if args.init_from and not ckpt:
        src = Algo.load(args.init_from, device=args.device)
        model.policy.load_state_dict(src.policy.state_dict())
        if args.algo == "sac":
            model.log_ent_coef = src.log_ent_coef.detach().clone().requires_grad_(True)
            model.ent_coef_optimizer = torch.optim.Adam([model.log_ent_coef], lr=model.lr_schedule(1))
        print(f"Initialised weights from {args.init_from}")

    ckpt_every = max(args.checkpoint_freq // n_envs, 1)
    callbacks = [
        WalkingStats(),
        CheckpointCallback(save_freq=ckpt_every, save_path=ckpt_dir,
                           name_prefix="model", save_vecnormalize=True),
        EvalCallback(eval_env, best_model_save_path=run_dir, log_path=run_dir,
                     eval_freq=max(args.eval_freq // n_envs, 1), n_eval_episodes=5,
                     deterministic=True),
    ]
    if args.algo == "sac":
        callbacks.append(SaveReplayBuffer(rb_path, ckpt_every))
    # Keep eval_env's normalisation stats in sync with training env (PPO only).
    if isinstance(env, VecNormalize):
        class SyncNorm(BaseCallback):
            def _on_step(self):
                eval_env.obs_rms = env.obs_rms
                return True
        callbacks.insert(0, SyncNorm())

    remaining = args.timesteps - done_steps
    if remaining > 0:
        model.learn(total_timesteps=remaining, callback=callbacks, tb_log_name=run_name,
                    reset_num_timesteps=not ckpt)

    model.save(os.path.join(run_dir, "final_model"))
    if isinstance(env, VecNormalize):
        env.save(os.path.join(run_dir, "vecnormalize.pkl"))
    print(f"Done. Saved to {run_dir}/")
    env.close()
    eval_env.close()


if __name__ == "__main__":
    main()
