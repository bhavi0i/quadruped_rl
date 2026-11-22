"""
checkpoint_sweep.py - evaluate many saved checkpoints on the fixed course benchmark, in parallel,
and rank them. Runs on an Amarel compute node (see amarel/sweep.slurm).

    python tools/checkpoint_sweep.py --runs course_c10_seed0 course_c10_seed1 course_c10_seed2 \
        --every 2 --difficulty 0.5 --layouts 6 --workers 30 --out results/sweep_c10.json

Why: policies drift between checkpoints (e.g. C10 seed 1: 2/6 goals at 200M, 0/6 at 205M; C8 seed 1:
2/6 at 193M, 0/6 at its final). Picking the final policy from the last checkpoint, or from one
review, is unreliable. This scores every k-th checkpoint on the same benchmark (6 rubble layouts,
deterministic) and ranks by goals, then mean distance.
"""
import argparse
import glob
import json
import os
import re
import sys
from multiprocessing import Pool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "obstacle_course"))


def evaluate(job):
    ckpt, difficulty, layouts, friction = job
    import numpy as np
    import torch
    torch.set_num_threads(1)
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize
    from quadruped_env import QuadrupedCourseEnv

    stats = ckpt.replace("ckpt_", "ckpt_vecnormalize_").replace(".zip", ".pkl")
    model = PPO.load(ckpt, device="cpu")
    cfg_f = os.path.join(os.path.dirname(ckpt), "config.json")        # [C17] run's gait rhythm / speed
    cfg = json.load(open(cfg_f)) if os.path.exists(cfg_f) else {}
    gait = dict(gait_period=cfg.get("gait_period") or 0.5, target_speed=cfg.get("target_speed") or 0.6,
                foot_scan=bool(cfg.get("foot_scan")))
    goals, dists, times = 0, [], []
    for lay in range(layouts):
        env = QuadrupedCourseEnv(arena="course", difficulty=difficulty, random_start=False, max_steps=3000,
                                 friction_model=friction, course_seed=lay, **gait)
        from quadruped_env import pd_for
        if pd_for(cfg, ckpt):                         # [C18]
            env.set_pd(*pd_for(cfg, ckpt))
        norm = VecNormalize.load(stats, DummyVecEnv([lambda: env]))
        norm.training = False
        obs, _ = env.reset(seed=300 + lay)
        for t in range(3000):
            obs, _, term, trunc, info = env.step(model.predict(norm.normalize_obs(obs), deterministic=True)[0])
            if term or trunc:
                break
        goals += int(info["reached_goal"])
        dists.append(float(env.max_x))
        if info["reached_goal"]:
            times.append(round(t * 0.02, 1))
    steps = int(re.search(r"ckpt_(\d+)_steps", ckpt).group(1))
    return dict(checkpoint=ckpt, steps=steps, difficulty=difficulty, goals=goals, layouts=layouts,
                mean_distance=round(float(np.mean(dists)), 2), distances=[round(d, 1) for d in dists],
                goal_times=times)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--runs", nargs="*", default=[], help="run folders under obstacle_course/runs")
    p.add_argument("--checkpoints", nargs="*", default=[], help="explicit checkpoint paths (relative to repo)")
    p.add_argument("--difficulties", type=float, nargs="*", default=None,
                   help="evaluate each checkpoint at several benchmark difficulties")
    p.add_argument("--every", type=int, default=2, help="evaluate every k-th checkpoint")
    p.add_argument("--min-steps", type=float, default=0)
    p.add_argument("--difficulty", type=float, default=0.5)
    p.add_argument("--layouts", type=int, default=6)
    p.add_argument("--friction", default="elliptic")
    p.add_argument("--workers", type=int, default=os.cpu_count())
    p.add_argument("--out", default="results/sweep.json")
    a = p.parse_args()

    jobs = []
    for run in a.runs:
        ck = sorted(glob.glob(os.path.join(ROOT, "obstacle_course", "runs", run, "ckpt_[0-9]*_steps.zip")),
                    key=lambda f: int(re.search(r"ckpt_(\d+)_steps", f).group(1)))
        ck = [c for c in ck if int(re.search(r"ckpt_(\d+)_steps", c).group(1)) >= a.min_steps][::a.every]
        # [C14] --difficulties also applies to --runs (was: --checkpoints only)
        jobs += [(c, dfc, a.layouts, a.friction) for c in ck for dfc in (a.difficulties or [a.difficulty])]
    for c in a.checkpoints:
        for dfc in (a.difficulties or [a.difficulty]):
            jobs.append((os.path.join(ROOT, c), dfc, a.layouts, a.friction))
    print(f"evaluating {len(jobs)} checkpoints x {a.layouts} layouts on {a.workers} workers", flush=True)
    with Pool(a.workers) as pool:
        results = pool.map(evaluate, jobs, chunksize=1)
    results.sort(key=lambda r: (-r["goals"], -r["mean_distance"]))
    os.makedirs(os.path.dirname(os.path.join(ROOT, a.out)), exist_ok=True)
    json.dump({"difficulty": a.difficulty, "layouts": a.layouts, "results": results},
              open(os.path.join(ROOT, a.out), "w"), indent=1)
    print("top 10:")
    for r in results[:10]:
        print(f"  d={r['difficulty']}  {r['goals']}/{r['layouts']} goals  mean {r['mean_distance']:5.1f} m  {os.path.relpath(r['checkpoint'], ROOT)}"
              f"  times {r['goal_times']}", flush=True)


if __name__ == "__main__":
    main()
