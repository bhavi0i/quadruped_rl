"""
HISTORY: replaces the original course train.py (commit 16dc2d4: custom robot, single stage,
curriculum from difficulty 0, no resume). See ../EXPERIMENT_LOG.md.

train.py - PPO training for the Go1 in two stages:

  1. ring:   learn to walk (natural trot, steering) by doing laps of the flat training ring
  2. course: continue from the ring policy on the obstacle course with a difficulty curriculum

    python train.py --arena ring --steps 30e6 --envs 32 --out runs/ring_seed0
    python train.py --arena course --init-from runs/ring_seed0/final.zip --out runs/course_seed0
    python train.py --arena course --injury random_leg ...   # train with a random weakened leg

The run resumes automatically from the newest checkpoint in --out (Amarel can preempt jobs).
Course curriculum: when the robot reliably makes progress, obstacles get bigger (difficulty += 0.1).
progress.json in the run folder logs distance, falls, speed and gait quality over training.
"""
import argparse
import glob
import json
import os
import re
import time

import numpy as np
import torch
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback, CheckpointCallback
from stable_baselines3.common.vec_env import SubprocVecEnv, DummyVecEnv, VecNormalize, VecMonitor

from quadruped_env import QuadrupedCourseEnv


def make_env(rank, args, difficulty):
    def _init():
        env = QuadrupedCourseEnv(difficulty=difficulty, random_start=True, injury=args.injury,
                                 course_seed=rank, robot=args.robot, arena=args.arena,
                                 target_speed=args.target_speed, reward_weights=args.reward_weights,
                                 turn_practice=args.turn_practice, ring_lookahead=args.ring_lookahead,
                                 wall_spawn=args.wall_spawn, max_steps=args.max_steps,
                                 spawn_offset=args.spawn_offset)
        env.reset(seed=args.seed * 1000 + rank)
        return env
    return _init


class ProgressCallback(BaseCallback):
    """Tracks walking quality, writes progress.json and (course only) raises difficulty."""

    def __init__(self, out, arena, start=0.0, step=0.1, threshold=3.0, window=200, verbose=1):  # window = episodes per progress row
        super().__init__(verbose)
        self.out, self.arena = out, arena
        self.difficulty, self.step_size, self.threshold, self.window = start, step, threshold, window
        self.reset_stats()
        self.history = []
        path = os.path.join(out, "progress.json")
        if os.path.exists(path):
            self.history = json.load(open(path)).get("history", [])

    def reset_stats(self):
        self.distances, self.goals, self.falls, self.sections, self.lengths = [], [], [], [], []
        self.trot, self.speed, self.body = [], [], []

    def _on_step(self):
        for done, info in zip(self.locals["dones"], self.locals["infos"]):
            self.trot.append(info["trot_match"])
            self.speed.append(info["v_fwd"])
            self.body.append(info["body_contacts"] > 0)
            if done:
                self.distances.append(info["max_x"] - info["start_x"])
                self.goals.append(info["reached_goal"])
                self.falls.append(info["fell"])
                self.sections.append(info["sections_cleared"])
                for k, v in info.get("episode_sums", {}).items():
                    self.logger.record_mean(f"reward_terms/{k}", float(v))

        if len(self.distances) >= self.window:
            row = dict(timesteps=int(self.num_timesteps), time=time.strftime("%Y-%m-%d %H:%M"),
                       difficulty=self.difficulty, distance=float(np.mean(self.distances)),
                       fall_rate=float(np.mean(self.falls)), goal_rate=float(np.mean(self.goals)),
                       sections_or_laps=float(np.mean(self.sections)),
                       speed=float(np.mean(self.speed)), trot_match=float(np.mean(self.trot)),
                       body_contact_rate=float(np.mean(self.body)))
            for k, v in row.items():
                if k not in ("timesteps", "time"):
                    self.logger.record(f"progress/{k}", v)
            if self.verbose:
                print(f"[{row['timesteps'] / 1e6:.1f}M] dist {row['distance']:.1f} m  falls {row['fall_rate']:.0%}  "
                      f"speed {row['speed']:.2f}  trot {row['trot_match']:.2f}  difficulty {self.difficulty:.1f}",
                      flush=True)
            self.history.append(row)
            if self.arena == "course" and row["distance"] > self.threshold and self.difficulty < 1.0:
                self.difficulty = round(min(1.0, self.difficulty + self.step_size), 2)
                self.training_env.env_method("set_difficulty", self.difficulty)
                print(f"[curriculum] -> difficulty {self.difficulty:.1f}", flush=True)
            with open(os.path.join(self.out, "progress.json"), "w") as f:
                json.dump({"arena": self.arena, "difficulty": self.difficulty, "history": self.history}, f, indent=1)
            self.reset_stats()
        return True


def latest_checkpoint(out):
    files = glob.glob(os.path.join(out, "ckpt_*_steps.zip"))
    return max(files, key=lambda f: int(re.search(r"ckpt_(\d+)_steps", f).group(1))) if files else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--arena", choices=["ring", "course"], default="ring")
    p.add_argument("--robot", choices=["go1", "custom"], default="go1")
    p.add_argument("--steps", type=float, default=30e6)
    p.add_argument("--envs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    p.add_argument("--difficulty", type=float, default=0.0)
    p.add_argument("--target-speed", type=float, default=0.6)
    p.add_argument("--injury", default=None, help='"random_leg", "random", or none')
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default="runs/ring_seed0")
    p.add_argument("--init-from", default=None, help="start from this model (e.g. the ring policy)")
    p.add_argument("--torch-threads", type=int, default=4)
    p.add_argument("--reward-weights", type=json.loads, default={},
                   help='override reward weights, e.g. \'{"turn_to_route": 1.0}\' (see EXPERIMENT_LOG)')
    p.add_argument("--turn-practice", type=float, default=0.25,
                   help="share of spawns facing a random direction (wall/turn practice)")
    p.add_argument("--ring-lookahead", type=float, default=0.6,
                   help="ring steering target, radians ahead on the track (E7/E8 0.6, E9 0.25)")
    p.add_argument("--wall-spawn", type=float, default=0.0,
                   help="extra share of ring spawns 1 m from the wall facing it (E10: 0.3)")
    p.add_argument("--max-steps", type=int, default=1500,
                   help="episode length in 50 Hz steps (ring 1500 = 30 s; course 3000 = 60 s)")
    p.add_argument("--curriculum-threshold", type=float, default=3.0,
                   help="course: raise difficulty when mean distance per episode exceeds this (m)")
    p.add_argument("--spawn-offset", type=float, default=0.8,
                   help="course: spawn at section start + this (C1 0.8 put ramp/stairs spawns ON them; C2 0.15)")
    p.add_argument("--device", default="auto", help="cpu / cuda / auto (see EXPERIMENT_LOG: hardware)")
    p.add_argument("--n-steps", type=int, default=1024, help="rollout length per env")
    p.add_argument("--ckpt-freq", type=float, default=1e6, help="env steps between checkpoints")
    args = p.parse_args()
    torch.set_num_threads(args.torch_threads)
    os.makedirs(args.out, exist_ok=True)

    # Resume after preemption: newest checkpoint + its normalisation stats + curriculum level.
    ckpt = latest_checkpoint(args.out)
    prog = os.path.join(args.out, "progress.json")
    difficulty = json.load(open(prog))["difficulty"] if ckpt and os.path.exists(prog) else args.difficulty
    with open(os.path.join(args.out, "config.json"), "w") as f:
        json.dump(vars(args), f, indent=2)

    fns = [make_env(i, args, difficulty) for i in range(args.envs)]
    venv = SubprocVecEnv(fns) if args.envs > 1 else DummyVecEnv(fns)
    venv = VecMonitor(venv)

    policy_kwargs = dict(net_arch=dict(pi=[256, 256, 128], vf=[256, 256, 128]), log_std_init=-0.5)
    src = ckpt or args.init_from
    if src:
        stats = (src.replace("ckpt_", "ckpt_vecnormalize_").replace(".zip", ".pkl") if ckpt
                 else src.replace(".zip", "_vecnormalize.pkl"))
        venv = VecNormalize.load(stats, venv) if os.path.exists(stats) else \
            VecNormalize(venv, norm_obs=True, norm_reward=True, clip_obs=10.0, gamma=0.99)
        venv.training = True
        model = PPO.load(src, env=venv, tensorboard_log=args.out, device=args.device)
        # [FAILED E8] PPO.load restores the *saved* seed and ignores --seed, so every continuation
        #   seed got identical randomness (E8 seeds 1 and 2 produced identical runs).
        # [NEW] re-seed continuations so each --seed explores differently (resumes keep the RNG
        #   behaviour of a fresh process anyway).
        if not ckpt:
            model.set_random_seed(args.seed)
        print(f"{'Resuming from' if ckpt else 'Initialised from'} {src} ({model.num_timesteps:,} steps, seed {args.seed})")
    else:
        venv = VecNormalize(venv, norm_obs=True, norm_reward=True, clip_obs=10.0, gamma=0.99)
        model = PPO("MlpPolicy", venv, n_steps=args.n_steps, batch_size=4096, n_epochs=5,
                    learning_rate=3e-4, gamma=0.99, gae_lambda=0.95, clip_range=0.2,
                    ent_coef=0.0, vf_coef=0.5, max_grad_norm=1.0, seed=args.seed,
                    policy_kwargs=policy_kwargs, tensorboard_log=args.out, verbose=1,
                    device=args.device)

    callbacks = [ProgressCallback(args.out, args.arena, start=difficulty,
                                  threshold=args.curriculum_threshold),
                 CheckpointCallback(save_freq=max(1, int(args.ckpt_freq) // args.envs), save_path=args.out,
                                    name_prefix="ckpt", save_vecnormalize=True)]
    # [FAILED, never run] done = model.num_timesteps if ckpt else 0  and  reset_num_timesteps=not ckpt
    #   -> with --init-from the counter restarted at 0 and trained the full --steps again.
    # [NEW] a continuation (--init-from) or resume keeps the step count; --steps is the total.
    done = model.num_timesteps if src else 0
    remaining = int(args.steps) - done
    if remaining > 0:
        model.learn(total_timesteps=remaining, callback=callbacks, reset_num_timesteps=not src,
                    tb_log_name=args.arena)
    model.save(f"{args.out}/final")
    venv.save(f"{args.out}/final_vecnormalize.pkl")
    print(f"saved to {args.out}/final.zip")


if __name__ == "__main__":
    main()
