"""
evaluate_policy.py - check a trained policy against the Phase 1 goals and save evidence.

    python evaluate_policy.py runs/ring_seed0/ckpt_10000000_steps.zip --out eval/ring_seed0
    python evaluate_policy.py runs/ring_seed0/final.zip --arena course --difficulty 0.3

Two tests (deterministic policy):

1. Natural walking (ring): 5 episodes of 20 s from normal track spawns. Measures speed vs the
   0.6 m/s target, trot match (feet follow the diagonal-trot clock), mean feet on the ground,
   share of steps with shins/knees/belly touching the ground, swing foot lift, falls and how
   far it stays from the track line.

2. Wall handling: the robot starts 1.0 m from the ring wall, facing it head-on or at 30/60 deg
   (6 trials, 10 s each). A pass means it never touched the wall, or touched it once and got
   away, and turned to walk at least 1.5 m around the ring (either direction).

Writes metrics.json, contact sheets of frames (frames_walk.png, frames_wall.png), videos of the
first walking episode and the head-on wall trial (walk.mp4 / wall.mp4 at 25 fps, plus small
looping walk.gif / wall.gif that play inline on GitHub), and prints a summary with PASS/FAIL
against the goal thresholds.
"""
import argparse
import glob
import json
import os

import imageio
import mujoco
import numpy as np
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

import course
from quadruped_env import QuadrupedCourseEnv

GOALS = {  # what "walking naturally and handling walls" means, numerically
    "speed_err": ("<=", 0.15),          # |speed - 0.6| m/s
    "trot_match": (">=", 0.75),
    "feet_down": ("between", (1.6, 2.6)),
    "body_contact_rate": ("<=", 0.05),
    "fall_rate": ("<=", 0.05),
    "wall_pass_rate": (">=", 0.8),
}


def load(model_path):
    d = os.path.dirname(model_path)
    stats = model_path.replace("ckpt_", "ckpt_vecnormalize_").replace(".zip", ".pkl")
    if not os.path.exists(stats):
        stats = model_path.replace(".zip", "_vecnormalize.pkl")
    if not os.path.exists(stats):
        cands = glob.glob(os.path.join(d, "*vecnormalize*.pkl"))
        stats = max(cands, key=os.path.getmtime) if cands else None
    return PPO.load(model_path, device="cpu"), stats


def make(env_kwargs, stats):
    env = QuadrupedCourseEnv(render_mode="rgb_array", **env_kwargs)
    norm = None
    if stats:
        norm = VecNormalize.load(stats, DummyVecEnv([lambda: env]))
        norm.training = False
    return env, norm


def act(model, norm, obs):
    o = norm.normalize_obs(obs) if norm else obs
    return model.predict(o, deterministic=True)[0]


def contact_sheet(frames, path, cols=4):
    if not frames:
        return
    h, w, _ = frames[0].shape
    rows = (len(frames) + cols - 1) // cols
    sheet = np.full((rows * h, cols * w, 3), 255, np.uint8)
    for k, f in enumerate(frames):
        r, c = divmod(k, cols)
        sheet[r * h:(r + 1) * h, c * w:(c + 1) * w] = f
    imageio.imwrite(path, sheet[::2, ::2])


def walk_test(model, norm, env, episodes=5, steps=1000):
    video = []
    speeds, trots, feet, body, lifts, falls, track_err = [], [], [], [], [], [], []
    frames = []
    for ep in range(episodes):
        env.random_start = True
        obs, _ = env.reset(seed=100 + ep)
        for t in range(steps):
            obs, _, term, trunc, info = env.step(act(model, norm, obs))
            speeds.append(info["v_fwd"]); trots.append(info["trot_match"])
            feet.append(info["foot_contact"].sum()); body.append(info["body_contacts"] > 0)
            swing = ~info["foot_contact"]
            if swing.any():
                lifts.append(float(info["foot_lift"][swing].max()))
            if env.arena == "ring":
                xy = env.data.qpos[:2] - np.array(course.RING_CENTER)
                track_err.append(abs(np.linalg.norm(xy) - course.RING_TRACK_RADIUS))
            if ep == 0 and t < 500 and t % 2 == 0:          # 10 s video at 25 fps
                video.append(env.render())
                if 100 <= t < 196 and t % 12 == 0:
                    frames.append(video[-1])
            if term or trunc:
                break
        falls.append(bool(info["fell"]))
    m = dict(speed=float(np.mean(speeds)), trot_match=float(np.mean(trots)),
             feet_down=float(np.mean(feet)), body_contact_rate=float(np.mean(body)),
             swing_lift_cm=float(100 * np.mean(lifts)) if lifts else 0.0,
             fall_rate=float(np.mean(falls)),
             track_error_m=float(np.mean(track_err)) if track_err else None)
    m["speed_err"] = abs(m["speed"] - env.target_speed)
    return m, frames, video


def wall_test(model, norm, env, seconds=10):
    """Spawn 1 m from the ring wall facing it (0, +-30, +-60 deg off head-on) and watch."""
    results, frames, video = [], [], []
    angles = [0, 30, -30, 60, -60, 0]
    for k, off in enumerate(angles):
        env.random_start = False
        obs, _ = env.reset(seed=200 + k)
        a = np.deg2rad(45 * k)                       # different spots around the ring
        r = course.RING_RADIUS - 1.0
        d = env.data
        d.qpos[0] = course.RING_CENTER[0] + r * np.cos(a)
        d.qpos[1] = course.RING_CENTER[1] + r * np.sin(a)
        yaw = a + np.deg2rad(off)                   # a = pointing radially outward, at the wall
        d.qpos[3:7] = [np.cos(yaw / 2), 0, 0, np.sin(yaw / 2)]
        d.qvel[:] = 0
        mujoco.mj_forward(env.model, d)
        env.ring_last_a, env.ring_theta = a, 0.0
        env.start_x = env.max_x = 0.0
        obs = env._get_obs()
        hits, steps_touching, min_d = 0, 0, 9.0
        touching = False
        for t in range(int(seconds / 0.02)):
            obs, _, term, trunc, info = env.step(act(model, norm, obs))
            min_d = min(min_d, info["min_wall_dist"])
            now = info["wall_hits"] > 0
            hits += int(now and not touching)
            steps_touching += int(now)
            touching = now
            if k == 0 and t % 2 == 0:                       # head-on trial: 10 s video
                video.append(env.render())
                if t % 25 == 0 and len(frames) < 12:
                    frames.append(video[-1])
            if term:
                break
        along = abs(env.progress_s - env.start_x)   # either direction counts as getting away
        passed = (hits <= 1 and steps_touching < 50 and along >= 1.5 and not info["fell"])
        results.append(dict(offset_deg=off, wall_touches=hits, steps_touching=steps_touching,
                            min_wall_dist=round(min_d, 3), metres_along_track=round(along, 2),
                            fell=bool(info["fell"]), passed=bool(passed)))
    return dict(wall_pass_rate=float(np.mean([r["passed"] for r in results])), trials=results), frames, video


def save_video(frames, out, name):
    """Full-quality mp4 (25 fps) for presentations + small looping GIF that plays on GitHub."""
    if not frames:
        return
    imageio.mimsave(os.path.join(out, f"{name}.mp4"), frames, fps=25, quality=7, macro_block_size=8)
    small = [f[::2, ::2] for f in frames[::2]][:75]          # 320x240, 12.5 fps, 6 s
    imageio.v3.imwrite(os.path.join(out, f"{name}.gif"), np.stack(small), duration=80, loop=0)


def check(metrics):
    out = {}
    for k, (op, thr) in GOALS.items():
        v = metrics.get(k)
        if v is None:
            continue
        ok = (v <= thr if op == "<=" else v >= thr if op == ">=" else thr[0] <= v <= thr[1])
        out[k] = dict(value=round(v, 3), goal=f"{op} {thr}", passed=bool(ok))
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("model")
    p.add_argument("--out", default="eval/latest")
    p.add_argument("--arena", choices=["ring", "course"], default="ring")
    p.add_argument("--difficulty", type=float, default=0.0)
    a = p.parse_args()
    os.makedirs(a.out, exist_ok=True)

    model, stats = load(a.model)
    env, norm = make(dict(arena=a.arena, difficulty=a.difficulty), stats)
    walk, f_walk, v_walk = walk_test(model, norm, env)
    metrics = dict(walk)
    f_wall, v_wall = [], []
    if a.arena == "ring":
        wall, f_wall, v_wall = wall_test(model, norm, env)
        metrics.update(wall_pass_rate=wall["wall_pass_rate"], wall_trials=wall["trials"])
    metrics["goals"] = check(metrics)
    metrics["model"] = a.model
    contact_sheet(f_walk, os.path.join(a.out, "frames_walk.png"))
    contact_sheet(f_wall, os.path.join(a.out, "frames_wall.png"))
    save_video(v_walk, a.out, "walk")
    save_video(v_wall, a.out, "wall")
    with open(os.path.join(a.out, "metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2)

    print(f"model: {a.model}")
    for k, g in metrics["goals"].items():
        print(f"  {'PASS' if g['passed'] else 'FAIL'}  {k:<18} {g['value']:>8}   goal {g['goal']}")
    print(f"  swing lift {metrics['swing_lift_cm']:.1f} cm, speed {metrics['speed']:.2f} m/s, "
          f"track error {metrics['track_error_m']}")
    if "wall_trials" in metrics:
        for t in metrics["wall_trials"]:
            print("   wall", t)


if __name__ == "__main__":
    main()
