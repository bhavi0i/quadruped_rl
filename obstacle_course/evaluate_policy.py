"""
evaluate_policy.py - check a trained policy against the Phase 1 goals and save evidence.

    python evaluate_policy.py runs/ring_seed0/ckpt_10000000_steps.zip --out eval/ring_seed0
    python evaluate_policy.py runs/ring_seed0/final.zip --arena course --difficulty 0.3

Two tests (deterministic policy):

1. Natural walking (ring): 5 episodes of 20 s from normal track spawns. Measures speed vs the
   0.6 m/s target, trot match (feet follow the diagonal-trot clock), mean feet on the ground,
   posture (crab angle = body heading vs direction of travel, roll, pitch),
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
    # "body_contact_rate": ("<=", 0.05),   [REPLACED 2026-11-17] counted the calf capsule grazing the
    #   ground next to a planted foot (a Go1 model artifact, see quadruped_env foot_graze_radius):
    #   ~0.1 on flat ground even for the stage-1 policy, 0.4-0.6 on the course. Still reported.
    "shin_contact_rate": ("<=", 0.05),  # [NEW] shin/thigh/torso contacts > 4 cm from any foot
    "fall_rate": ("<=", 0.05),
    "wall_pass_rate": (">=", 0.8),
    # posture / natural look (added 2026-11-16 after the group saw a slanted, crabbing walk)
    "crab_angle_deg": ("<=", 10.0),     # |angle between body heading and direction of travel|
    "roll_deg": ("<=", 3.0),            # |mean sideways lean|
    "pitch_deg": ("<=", 4.0),           # |mean nose-up/down tilt|
    # leg posture / step uniformity (added 2026-11-16: legs looked slanted, steps uneven)
    "foot_splay_cm": ("<=", 5.0),       # mean |sideways| stance-foot offset from standing pose
    "foot_fore_aft_cm": ("<=", 8.0),    # mean |fore-aft| stance-foot offset from standing pose
    "step_height_spread": ("<=", 0.2),  # (max - min) / mean of the four legs' swing heights
    # stage 2: obstacle course from the start
    "goal_rate": (">=", 0.67),          # reached the goal pad in >= 4 of 6 runs (6 rubble layouts)
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
    crabs, rolls, pitches, vlat = [], [], [], []
    rel_off, contacts_l, lifts_l = [], [], []
    shin = []
    frames = []
    for ep in range(episodes):
        env.random_start = True
        obs, _ = env.reset(seed=100 + ep)
        for t in range(steps):
            obs, _, term, trunc, info = env.step(act(model, norm, obs))
            speeds.append(info["v_fwd"]); trots.append(info["trot_match"])
            feet.append(info["foot_contact"].sum()); body.append(info["body_contacts"] > 0)
            shin.append(info["shin_contacts"] > 0)
            swing = ~info["foot_contact"]
            if swing.any():
                lifts.append(float(info["foot_lift"][swing].max()))
            if t >= 100:
                rel_off.append(info["foot_rel_hip"] - info["nominal_foot_rel"])
                contacts_l.append(info["foot_contact"]); lifts_l.append(info["foot_lift"])
            if t >= 100:                                   # posture once walking has settled
                _, lv, _, g, yaw = env._body_frame()
                rolls.append(np.degrees(np.arctan2(g[1], -g[2])))
                pitches.append(np.degrees(np.arctan2(-g[0], -g[2])))
                vlat.append(lv[1])
                v = env.data.qvel[:2]
                if np.linalg.norm(v) > 0.2:
                    crabs.append(np.degrees((np.arctan2(v[1], v[0]) - yaw + np.pi) % (2 * np.pi) - np.pi))
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
             shin_contact_rate=float(np.mean(shin)),
             swing_lift_cm=float(100 * np.mean(lifts)) if lifts else 0.0,
             fall_rate=float(np.mean(falls)),
             track_error_m=float(np.mean(track_err)) if track_err else None)
    m["speed_err"] = abs(m["speed"] - env.target_speed)
    if rel_off:
        ro, cc, ll = np.array(rel_off), np.array(contacts_l), np.array(lifts_l)
        per_leg = []
        for k in range(4):                                # mean peak lift per leg
            air = ~cc[:, k]
            e = np.flatnonzero(np.diff(np.r_[0, air.astype(int), 0]))
            pk = [ll[a:b, k].max() for a, b in zip(e[::2], e[1::2])]
            per_leg.append(float(np.mean(pk)) if pk else 0.0)
        per_leg = np.array(per_leg)
        m.update(foot_splay_cm=float(100 * np.mean([np.abs(ro[cc[:, k], k, 1]).mean() for k in range(4) if cc[:, k].any()])),
                 foot_fore_aft_cm=float(100 * np.mean([np.abs(ro[cc[:, k], k, 0]).mean() for k in range(4) if cc[:, k].any()])),
                 step_height_spread=float((per_leg.max() - per_leg.min()) / max(per_leg.mean(), 1e-6)),
                 step_height_per_leg_cm=[round(float(100 * x), 1) for x in per_leg])
    m.update(crab_angle_signed_deg=float(np.mean(crabs)) if crabs else 0.0,
             crab_angle_deg=abs(float(np.mean(crabs))) if crabs else 0.0,
             roll_deg=abs(float(np.mean(rolls))), pitch_deg=abs(float(np.mean(pitches))),
             sideways_speed=float(np.mean(vlat)))
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


def course_test(model, norm, env, episodes=6, seconds=60):
    """Stage 2: start at the beginning of the course and try to reach the goal pad.
    [C8 review] each run uses a different rubble layout (course_seed 0..episodes-1). With one fixed
    layout (seed 0) results were unrepresentative: the same policy reached the goal on layout 3
    and fell early on layouts 0 and 2."""
    import course as C
    from quadruped_env import CHECKPOINT_X, SECTION_NAMES
    runs, video = [], []
    for ep in range(episodes):
        env.random_start = False
        env.course_seed = ep
        env.set_difficulty(env.difficulty)          # rebuild with this rubble layout
        obs, _ = env.reset(seed=300 + ep)
        t, fell, reached = 0, False, False
        while t < int(seconds / 0.02):
            obs, _, term, trunc, info = env.step(act(model, norm, obs))
            if ep == 0 and t % 4 == 0:
                video.append(env.render())
            t += 1
            if term or trunc:
                fell, reached = bool(info["fell"]), bool(info["reached_goal"])
                break
        x = float(env.max_x)
        cleared = [n for n, cx in zip(SECTION_NAMES, CHECKPOINT_X) if x > cx]
        runs.append(dict(layout=ep, max_x=round(x, 2), sections_cleared=cleared, reached_goal=reached, fell=fell,
                         time_s=round(t * 0.02, 1), stopped_in=next((n for n, cx in zip(SECTION_NAMES, CHECKPOINT_X)
                                                                     if x <= cx), "goal")))
    return dict(goal_rate=float(np.mean([r["reached_goal"] for r in runs])),
                mean_progress_m=float(np.mean([r["max_x"] for r in runs])),
                course_progress=float(np.mean([r["max_x"] for r in runs]) / C.GOAL_X),
                course_runs=runs), video


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
    p.add_argument("--difficulty", type=lambda v: json.loads(v) if v.strip().startswith("{") else float(v),
                   default=0.0, help='course obstacle size 0..1, or per section as JSON {"ramp": 0.3, ...}')
    p.add_argument("--friction-model", choices=["pyramidal", "elliptic"], default=None,
                   help="default: the model's training config (pyramidal if unknown)")
    a = p.parse_args()
    os.makedirs(a.out, exist_ok=True)

    model, stats = load(a.model)
    fm = a.friction_model
    if fm is None:
        cfg_f = os.path.join(os.path.dirname(a.model), "config.json")
        fm = json.load(open(cfg_f)).get("friction_model", "pyramidal") if os.path.exists(cfg_f) else "pyramidal"
    # [NEW 2026-11-22] also take the run's gait rhythm and target speed (C17 changes both; before C17
    #   every run used the defaults 0.5 s / 0.6 m/s, so earlier evaluations are unaffected)
    cfg_f = os.path.join(os.path.dirname(a.model), "config.json")
    cfg = json.load(open(cfg_f)) if os.path.exists(cfg_f) else {}
    gait = dict(gait_period=cfg.get("gait_period") or 0.5, target_speed=cfg.get("target_speed") or 0.6,
                foot_scan=bool(cfg.get("foot_scan")))
    env, norm = make(dict(arena=a.arena, difficulty=a.difficulty, friction_model=fm, **gait), stats)
    walk, f_walk, v_walk = walk_test(model, norm, env)
    metrics = dict(walk)
    f_wall, v_wall = [], []
    if a.arena == "ring":
        wall, f_wall, v_wall = wall_test(model, norm, env)
        metrics.update(wall_pass_rate=wall["wall_pass_rate"], wall_trials=wall["trials"])
    else:
        env.max_steps = 3000
        crs, v_course = course_test(model, norm, env)
        metrics.update(crs)
        if v_course:                                      # frames every 4 steps = 12.5 fps real time
            imageio.mimsave(os.path.join(a.out, "course.mp4"), v_course, fps=12.5, quality=7,
                            macro_block_size=8)
            small = [f[::2, ::2] for f in v_course[::2]][:190]   # GIF: 6.25 fps, up to ~30 s
            imageio.v3.imwrite(os.path.join(a.out, "course.gif"), np.stack(small), duration=160, loop=0)
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
    print(f"  crab {metrics['crab_angle_signed_deg']:+.1f} deg, sideways speed {metrics['sideways_speed']:+.2f} m/s")
    if "step_height_per_leg_cm" in metrics:
        print(f"  step height per leg (FR, FL, RR, RL) cm: {metrics['step_height_per_leg_cm']}")
    print(f"  swing lift {metrics['swing_lift_cm']:.1f} cm, speed {metrics['speed']:.2f} m/s, "
          f"track error {metrics['track_error_m']}")
    if "course_runs" in metrics:
        for r in metrics["course_runs"]:
            print("   course", r)
    if "wall_trials" in metrics:
        for t in metrics["wall_trials"]:
            print("   wall", t)


if __name__ == "__main__":
    main()
