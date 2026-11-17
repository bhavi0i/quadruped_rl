"""
play.py - watch or record a trained policy.

    (on macOS use `mjpython` instead of `python` for the interactive viewer)
    python play.py runs/ring_seed0/final.zip --arena ring             # watch laps in the ring
    python play.py runs/ppo_quadruped/final.zip                       # interactive viewer
    python play.py runs/ppo_quadruped/final.zip --video run.mp4       # save a video
    python play.py runs/ppo_quadruped/final.zip --injury FR=0.0       # front-right leg limp
    python play.py --random                                           # no model: random actions
"""
import argparse
import os
import time
import numpy as np
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

from quadruped_env import QuadrupedCourseEnv


def main():
    p = argparse.ArgumentParser()
    p.add_argument("model", nargs="?")
    p.add_argument("--difficulty", type=float, default=1.0)
    p.add_argument("--arena", choices=["ring", "course"], default="course")
    p.add_argument("--robot", choices=["go1", "custom"], default="go1")
    p.add_argument("--video", default=None)
    p.add_argument("--random", action="store_true")
    p.add_argument("--injury", default=None, help='e.g. "FR=0.0", "FL_calf=0.3" or "random_leg"')
    p.add_argument("--episodes", type=int, default=1, help="episodes to play (0 = keep going)")
    p.add_argument("--fast", action="store_true", help="don't slow the viewer down to real time")
    a = p.parse_args()

    injury = a.injury
    if injury and injury not in ("random", "random_leg"):
        injury = {k: float(v) for k, v in (s.split("=") for s in injury.split(","))}
    mode = "rgb_array" if a.video else "human"
    env = QuadrupedCourseEnv(difficulty=a.difficulty, random_start=False, injury=injury,
                             render_mode=mode, arena=a.arena, robot=a.robot)

    norm = None
    if a.model and not a.random:
        model = PPO.load(a.model)
        stats = a.model.replace(".zip", "_vecnormalize.pkl")
        if not os.path.exists(stats):                       # checkpoint naming from train.py
            stats = a.model.replace("ckpt_", "ckpt_vecnormalize_").replace(".zip", ".pkl")
        if os.path.exists(stats):
            norm = VecNormalize.load(stats, DummyVecEnv([lambda: env]))
            norm.training = False

    frames, ep = [], 0
    while a.episodes == 0 or ep < a.episodes:
        obs, _ = env.reset(seed=ep)
        done, total, speeds, trot = False, 0.0, [], []
        while not done:
            t0 = time.time()
            if a.random or not a.model:
                act = env.action_space.sample() * 0.3
            else:
                o = norm.normalize_obs(obs) if norm else obs
                act, _ = model.predict(o, deterministic=True)
            obs, r, term, trunc, info = env.step(act)
            total += r
            speeds.append(info["v_fwd"]); trot.append(info["trot_match"])
            done = term or trunc
            if a.video and env.steps % 2 == 0:
                frames.append(env.render())
            if mode == "human" and not a.fast:
                time.sleep(max(0.0, 0.02 - (time.time() - t0)))   # play at real time (50 Hz)
        ep += 1
        where = f"{info['x'] - info['start_x']:.1f} m around the ring" if a.arena == "ring" else \
            f"reached x = {info['x']:.2f} m | goal: {info['reached_goal']}"
        print(f"episode {ep}: return {total:.1f} | {where} | speed {np.mean(speeds):.2f} m/s | "
              f"trot match {np.mean(trot):.2f} | fell: {info['fell']}", flush=True)
    if a.video:
        import imageio
        imageio.mimsave(a.video, frames, fps=25)
        print("saved", a.video)
    env.close()


if __name__ == "__main__":
    main()
