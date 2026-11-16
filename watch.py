"""Open the MuJoCo viewer and watch a policy walk, optionally pulling the newest
best_model.zip from Amarel between episodes so you can watch training progress.

python watch.py runs/live_seed0/best_model.zip
python watch.py runs/live_seed0/best_model.zip --sync bpa29@amarel.rutgers.edu:rl_quadruped/runs/phase1_go1_seed0
python watch.py runs/phase1_go1_seed0/healthy_policy.zip --injured-leg 2 --strength 0.0
"""

import argparse
import json
import os
import subprocess
import time

from stable_baselines3 import SAC

from injury_wrapper import LEG_NAMES, make_env


def main():
    p = argparse.ArgumentParser()
    p.add_argument("model_path")
    p.add_argument("--sync", default=None, help="remote run dir to pull best_model.zip from")
    p.add_argument("--injured-leg", type=int, default=None)
    p.add_argument("--strength", type=float, default=0.0)
    args = p.parse_args()

    cfg_path = os.path.join(os.path.dirname(args.model_path), "config.json")
    cfg = json.load(open(cfg_path)) if os.path.exists(cfg_path) else {"robot": "go1"}
    robot = cfg.get("robot", "ant")
    injury = {args.injured_leg: args.strength} if args.injured_leg is not None else None
    env = make_env(robot=robot, go1_kwargs=cfg.get("go1"), fixed_injury=injury, render_mode="human")
    label = "healthy" if injury is None else f"leg {args.injured_leg} ({LEG_NAMES[robot][args.injured_leg]}) @ {args.strength}"

    model, mtime, ep = None, None, 0
    while True:
        if args.sync:
            subprocess.run(["rsync", "-a", f"{args.sync}/best_model.zip", f"{args.sync}/evaluations.npz", f"{args.sync}/config.json",
                            os.path.dirname(args.model_path) + "/"], check=False, stderr=subprocess.DEVNULL)
        if not os.path.exists(args.model_path):
            print("Waiting for the first saved policy (after 25k training steps)...")
            time.sleep(60)
            continue
        if os.path.getmtime(args.model_path) != mtime:
            mtime = os.path.getmtime(args.model_path)
            model = SAC.load(args.model_path, device="cpu")
            print(f"Loaded policy trained for {model.num_timesteps:,} steps")
        obs, _ = env.reset()
        x0, done, steps = env.unwrapped.data.qpos[0], False, 0
        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, _, term, trunc, info = env.step(action)
            done, steps = term or trunc, steps + 1
        ep += 1
        print(f"episode {ep} [{label}]: walked {info['x_position'] - x0:.1f} m in {steps} steps"
              + (" (fell)" if term else ""))


if __name__ == "__main__":
    main()
