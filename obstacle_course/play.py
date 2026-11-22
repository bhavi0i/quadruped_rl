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

from quadruped_env import QuadrupedCourseEnv, MAX_STEPS


def place_facing_wall(env, ang, off_deg, dist=1.0):
    """Put the robot `dist` m from the ring wall at angle `ang`, facing the wall (+ offset)."""
    import mujoco
    import course
    r = course.RING_RADIUS - dist
    d = env.data
    d.qpos[0] = course.RING_CENTER[0] + r * np.cos(ang)
    d.qpos[1] = course.RING_CENTER[1] + r * np.sin(ang)
    yaw = ang + np.deg2rad(off_deg)
    d.qpos[3:7] = [np.cos(yaw / 2), 0, 0, np.sin(yaw / 2)]
    d.qvel[:] = 0
    mujoco.mj_forward(env.model, d)
    env.ring_last_a, env.ring_theta = ang, 0.0
    env.start_x = env.max_x = env.progress_s = 0.0
    return env._get_obs()


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
    p.add_argument("--layout", type=int, default=None,
                   help="replay benchmark layout L exactly (rubble seed L, start seed 300+L), as in evaluate_policy")
    p.add_argument("--fast", action="store_true", help="don't slow the viewer down to real time")
    p.add_argument("--wall-test", action="store_true",
                   help="ring only: start 1 m from the wall facing it (0, +-30, +-60 deg), 10 s each")
    a = p.parse_args()

    injury = a.injury
    if injury and injury not in ("random", "random_leg"):
        injury = {k: float(v) for k, v in (s.split("=") for s in injury.split(","))}
    mode = "rgb_array" if a.video else "human"
    # [REPLACED 2026-11-17] env built with the defaults (pyramidal friction, default episode
    #   length), not the settings the course policies (C5+) were trained with:
    # env = QuadrupedCourseEnv(difficulty=a.difficulty, random_start=False, injury=injury,
    #                          render_mode=mode, arena=a.arena, robot=a.robot)
    # [NEW] use the run's config.json (next to the model) for friction and episode length
    import json
    cfg_f = os.path.join(os.path.dirname(os.path.abspath(a.model)), "config.json") if a.model else ""
    cfg = json.load(open(cfg_f)) if cfg_f and os.path.exists(cfg_f) else {}
    env = QuadrupedCourseEnv(difficulty=a.difficulty, random_start=False, injury=injury,
                             render_mode=mode, arena=a.arena, robot=a.robot,
                             friction_model=cfg.get("friction_model", "pyramidal"),
                             max_steps=cfg.get("max_steps") or MAX_STEPS,
                             gait_period=cfg.get("gait_period") or 0.5,          # [C17]
                             target_speed=cfg.get("target_speed") or 0.6,
                             foot_scan=bool(cfg.get("foot_scan")))
    from quadruped_env import pd_for
    if a.model and pd_for(cfg, a.model):              # [C18]
        env.set_pd(*pd_for(cfg, a.model))

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
        # [NEW 2026-11-17] --layout: same rubble layout and start as the benchmark / validation runs
        if a.layout is not None and a.arena == "course":
            lay = a.layout
            if ep == 0:                                  # rebuild once (before the viewer opens);
                env.course_seed = lay                    # replays reuse the model and viewer
                env.set_difficulty(env.difficulty)
            obs, _ = env.reset(seed=300 + lay)
            print(f"layout {lay}, difficulty {env.difficulty}", flush=True)
        else:
            obs, _ = env.reset(seed=ep)
        if a.wall_test:
            off = [0, 30, -30, 60, -60][ep % 5]
            obs = place_facing_wall(env, ang=np.deg2rad(45 * ep), off_deg=off)
            print(f"wall trial {ep + 1}: facing the wall {'head-on' if off == 0 else f'{off:+d} deg off'}",
                  flush=True)
        done, total, speeds, trot = False, 0.0, [], []
        hits, touching = 0, False
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
            hits += int(info["wall_hits"] > 0 and not touching); touching = info["wall_hits"] > 0
            done = term or trunc or (a.wall_test and env.steps >= 500)
            if a.video and env.steps % 2 == 0:
                frames.append(env.render())
            if mode == "human" and not a.fast:
                time.sleep(max(0.0, 0.02 - (time.time() - t0)))   # play at real time (50 Hz)
        ep += 1
        if a.wall_test:
            print(f"   -> wall touches {hits}, got {abs(env.progress_s - env.start_x):.1f} m away along the ring, "
                  f"fell: {info['fell']}", flush=True)
            continue
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
