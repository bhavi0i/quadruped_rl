"""Evaluate a trained walker: healthy body vs. each leg injured.

Examples
--------
python evaluate.py runs/phase1_go1_seed0/healthy_policy.zip
python evaluate.py runs/phase1_go1_seed0/healthy_policy.zip --strengths 0.0 0.3 0.6 --episodes 20
python evaluate.py runs/phase1_go1_seed0/healthy_policy.zip --out results/phase1.json
python evaluate.py runs/phase1_go1_seed0/healthy_policy.zip --video videos/ --episodes 1
python evaluate.py runs/phase1_go1_seed0/healthy_policy.zip --render --injured-leg 2
"""

import argparse
import json
import os

import numpy as np
from stable_baselines3 import PPO, SAC
from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

from injury_wrapper import LEG_NAMES, N_LEGS, make_env


def load(model_path):
    run_dir = os.path.dirname(model_path)
    cfg_path = os.path.join(run_dir, "config.json")
    cfg = json.load(open(cfg_path)) if os.path.exists(cfg_path) else {}
    algo = cfg.get("algo") or ("ppo" if "ppo" in model_path.lower() else "sac")
    model = (PPO if algo == "ppo" else SAC).load(model_path, device="cpu")
    vecnorm = os.path.join(run_dir, "vecnormalize.pkl")
    return model, cfg, (vecnorm if os.path.exists(vecnorm) else None)


def run(model, cfg, vecnorm_path, fixed_injury, episodes, seed, render=False, video_path=None):
    render_mode = "human" if render else ("rgb_array" if video_path else None)

    def make():
        return make_env(robot=cfg.get("robot", "ant"), go1_kwargs=cfg.get("go1"), fixed_injury=fixed_injury,
                            expose_injury=cfg.get("expose_injury", False),
                            render_mode=render_mode)

    env = DummyVecEnv([make])
    if vecnorm_path:
        env = VecNormalize.load(vecnorm_path, env)
        env.training, env.norm_reward = False, False
    env.seed(seed)

    frames = []
    returns, distances, speeds, lengths, falls = [], [], [], [], []
    contacts, wanted, heights, bodyhits, base_z = [], [], [], [], []
    for ep in range(episodes):
        obs = env.reset()
        done, ep_ret, ep_len = False, 0.0, 0
        x0 = x = float(env.envs[0].unwrapped.data.qpos[0])
        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, dones, infos = env.step(action)
            done = dones[0]
            ep_ret += float(reward[0])
            ep_len += 1
            info = infos[0]
            x = info.get("x_position", x)
            if "foot_contact" in info:
                contacts.append(info["foot_contact"]); wanted.append(info["want_contact"])
                heights.append(info["foot_height"]); bodyhits.append(info["body_contacts"])
                base_z.append(info["base_height"])
            if video_path and ep == 0:
                frames.append(env.envs[0].render())
        returns.append(ep_ret)
        distances.append(x - x0)
        speeds.append((x - x0) / (ep_len * env.envs[0].unwrapped.dt))
        lengths.append(ep_len)
        falls.append(ep_len < 1000)  # terminated early = fell over
    env.close()

    if video_path and frames:
        import imageio
        os.makedirs(os.path.dirname(video_path) or ".", exist_ok=True)
        imageio.mimsave(video_path, frames, fps=round(1 / env.envs[0].unwrapped.dt))

    out = gait_stats(np.array(contacts), np.array(wanted), np.array(heights), np.array(bodyhits),
                     np.array(base_z), env.envs[0].unwrapped.dt) if contacts else {}
    return out | dict(return_mean=float(np.mean(returns)), return_std=float(np.std(returns)),
                distance_mean=float(np.mean(distances)), distance_std=float(np.std(distances)),
                speed_mean=float(np.mean(speeds)), length_mean=float(np.mean(lengths)),
                fall_rate=float(np.mean(falls)), episodes=episodes)


def gait_stats(c, want, h, body, z, dt):
    """How dog-like the gait is (Go1 only). c: (T, 4) foot contacts in order FR, FL, RR, RL."""
    touchdowns = np.sum(c[1:] & ~c[:-1], axis=0)
    swing_peaks = []
    for f in range(4):  # highest point of each swing
        air = ~c[:, f]
        edges = np.flatnonzero(np.diff(np.r_[0, air.astype(int), 0]))
        for s0, s1 in zip(edges[::2], edges[1::2]):
            swing_peaks.append(h[s0:s1, f].max() - 0.01)
    return dict(
        trot_match=float(np.mean(c == want)),                  # 1.0 = perfect clocked trot
        diagonal_sync=float(np.mean((c[:, 0] == c[:, 3]) & (c[:, 1] == c[:, 2]))),
        duty_factor=float(np.mean(c)),                          # dogs trotting: ~0.4-0.6
        step_freq_hz=float(np.mean(touchdowns) / (len(c) * dt)),
        swing_height_cm=float(100 * np.mean(swing_peaks)) if swing_peaks else 0.0,
        feet_down_mean=float(np.mean(c.sum(1))),
        body_contact_rate=float(np.mean(body > 0)),             # knees/belly touching ground
        base_height_mean=float(np.mean(z)), base_height_std=float(np.std(z)),
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("model_path")
    p.add_argument("--episodes", type=int, default=10)
    p.add_argument("--strengths", type=float, nargs="+", default=[0.0],
                   help="strength(s) of the injured leg to test (0 = paralysed)")
    p.add_argument("--injured-leg", type=int, default=None,
                   help="only test this leg (default: healthy + every leg)")
    p.add_argument("--render", action="store_true", help="live viewer (needs a display)")
    p.add_argument("--video", type=str, default=None,
                   help="directory to save one mp4 per scenario (set MUJOCO_GL=egl on headless nodes)")
    p.add_argument("--out", type=str, default=None, help="write results JSON here")
    p.add_argument("--seed", type=int, default=123)
    p.add_argument("--healthy-only", action="store_true", help="skip the injury scenarios")
    args = p.parse_args()

    model, cfg, vecnorm = load(args.model_path)
    names = LEG_NAMES[cfg.get("robot", "ant")]
    legs = [args.injured_leg] if args.injured_leg is not None else range(N_LEGS)
    scenarios = {"healthy": None}
    for s in ([] if args.healthy_only else args.strengths):
        scenarios.update({f"leg{l}_{names[l]}_str{s:g}": {l: s} for l in legs})

    results = {}
    print(f"{'scenario':<26}{'return':>16}{'x distance':>16}{'speed m/s':>11}{'steps':>7}{'drop%':>7}")
    for name, injury in scenarios.items():
        vid = os.path.join(args.video, f"{name}.mp4") if args.video else None
        r = run(model, cfg, vecnorm, injury, args.episodes, args.seed, args.render, vid)
        healthy = results.get("healthy", r)
        r["return_drop_pct"] = 100 * (1 - r["return_mean"] / healthy["return_mean"])
        r["distance_drop_pct"] = 100 * (1 - r["distance_mean"] / healthy["distance_mean"]) \
            if healthy["distance_mean"] else float("nan")
        results[name] = r
        print(f"{name:<26}{r['return_mean']:>9.1f}±{r['return_std']:<6.0f}"
              f"{r['distance_mean']:>9.2f}±{r['distance_std']:<6.2f}{r['speed_mean']:>11.2f}"
              f"{r['length_mean']:>7.0f}{r['distance_drop_pct']:>7.1f}")
        if "trot_match" in r:
            print(f"{'':<26}gait: trot match {r['trot_match']:.2f}, diagonal sync {r['diagonal_sync']:.2f}, "
                  f"duty {r['duty_factor']:.2f}, {r['step_freq_hz']:.1f} steps/s, "
                  f"swing {r['swing_height_cm']:.1f} cm, body contact {r['body_contact_rate']:.2f}, "
                  f"height {r['base_height_mean']:.3f}±{r['base_height_std']:.3f}")

    injured = [v for k, v in results.items() if k != "healthy"]
    if injured:
        avg = np.mean([v["distance_drop_pct"] for v in injured])
        print(f"\nAverage distance drop across injury scenarios: {avg:.1f}%")
        results["summary"] = {"avg_distance_drop_pct": float(avg),
                              "avg_return_drop_pct": float(np.mean([v["return_drop_pct"] for v in injured]))}

    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w") as f:
            json.dump({"model": args.model_path, "results": results}, f, indent=2)
        print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
