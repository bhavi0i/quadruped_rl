"""path_audit.py - [2026-11-17] how purposeful and agile the course walk looks, per section.
    cd obstacle_course && python ../tools/path_audit.py <milestone_dir> <difficulty> [layouts]
Per section: time, hesitation (forward speed < 0.1 m/s), backing up, path wander (path length / forward
distance), heading error, yaw wiggle, wall/barrier touches, closest wall distance, stride length and
its variation, and hind-knee bend (crouch) vs flat ground."""
import sys, os, json, collections, numpy as np
sys.path.insert(0, ".")
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize
from quadruped_env import QuadrupedCourseEnv
M, d = sys.argv[1], float(sys.argv[2]); L = int(sys.argv[3]) if len(sys.argv) > 3 else 6
cfg = json.load(open(M + "/config.json")) if os.path.exists(M + "/config.json") else {"friction_model": "elliptic"}
model = PPO.load(M + "/policy.zip", device="cpu")
SEC = (("slalom", 18.7), ("stairs", 14.2), ("ramp", 9.2), ("hurdles", 5.7), ("rubble", 2.2), ("start", -9))
sec = lambda x: next(n for n, a in SEC if x > a)
S = collections.defaultdict(lambda: collections.defaultdict(list))
goals = 0
for lay in range(L):
    env = QuadrupedCourseEnv(arena="course", difficulty=d, random_start=False, max_steps=3000,
                             friction_model=cfg["friction_model"], course_seed=lay,
                             gait_period=cfg.get("gait_period") or 0.5, target_speed=cfg.get("target_speed") or 0.6,
                             foot_scan=bool(cfg.get("foot_scan")))
    from quadruped_env import pd_for
    if pd_for(cfg, M + "/policy.zip"):                            # [C18]
        env.set_pd(*pd_for(cfg, M + "/policy.zip"))
    norm = VecNormalize.load(M + "/policy_vecnormalize.pkl", DummyVecEnv([lambda: env])); norm.training = False
    obs, _ = env.reset(seed=300 + lay)
    knee = [env.qadr[i] for i in range(12) if i % 3 == 2]          # calf joints FR FL RR RL
    last_td = {}; prev_xy = env.data.qpos[:2].copy(); prev_c = np.ones(4, bool)
    for t in range(3000):
        obs, _, term, trunc, info = env.step(model.predict(norm.normalize_obs(obs), deterministic=True)[0])
        q = env.data.qpos; s = sec(q[0]); R = S[s]
        R["n"].append(1)
        R["v"].append(info["v_fwd"])
        R["dx"].append(q[0] - prev_xy[0]); R["dl"].append(np.linalg.norm(q[:2] - prev_xy)); prev_xy = q[:2].copy()
        R["yawrate"].append(env.data.qvel[5])
        R["wall"].append(info["wall_hits"] > 0); R["minwall"].append(info["min_wall_dist"])
        R["hindknee"].append(np.degrees(np.mean([q[knee[2]], q[knee[3]]])))
        R["foreknee"].append(np.degrees(np.mean([q[knee[0]], q[knee[1]]])))
        c = info["foot_contact"]
        for i in range(4):
            if c[i] and not prev_c[i]:
                fp = env.data.geom_xpos[env.foot_geoms[i]][:2].copy()
                if i in last_td: R["stride"].append(np.linalg.norm(fp - last_td[i]))
                last_td[i] = fp
                R["touchdowns"].append(1)
        prev_c = c.copy()
        R["stumble"].append(env._feet_stumble())          # feet pushing into a vertical face (bar, riser)
        for i in range(4):                       # stance-foot sliding speed (slipperiness)
            if c[i]:
                import mujoco; vel = np.zeros(6)
                mujoco.mj_objectVelocity(env.model, env.data, mujoco.mjtObj.mjOBJ_GEOM, env.foot_geoms[i], vel, 0)
                R["slip"].append(np.linalg.norm(vel[3:5]))
        if term or trunc: break
    goals += int(info["reached_goal"])
print(f"{goals}/{L} goals at difficulty {d}")
hdr = f"{'section':8s} {'time s':>7s} {'hesit%':>7s} {'back%':>6s} {'wander':>7s} {'yawwig':>7s} {'wall%':>6s} {'minwall':>7s} {'stride cm':>9s} {'strideCV':>8s} {'hindknee':>8s} {'foreknee':>8s} {'slip cm/s':>9s} {'steps/s':>7s} {'stub/s':>6s}"
print(hdr)
for s in [n for n, _ in SEC][::-1]:
    R = S[s]
    if not R["n"]: continue
    v = np.array(R["v"]); st = np.array(R["stride"]) if R["stride"] else np.array([np.nan])
    print(f"{s:8s} {len(R['n'])*0.02/L:7.1f} {100*np.mean(v<0.1):7.0f} {100*np.mean(v<-0.05):6.0f} "
          f"{sum(R['dl'])/max(sum(R['dx']),1e-3):7.2f} {np.std(R['yawrate']):7.2f} {100*np.mean(R['wall']):6.1f} "
          f"{np.min(R['minwall']):7.2f} {100*np.nanmean(st):9.1f} {np.nanstd(st)/np.nanmean(st):8.2f} "
          f"{np.mean(R['hindknee']):8.1f} {np.mean(R['foreknee']):8.1f} {100*np.mean(R['slip']):9.1f} {len(R['touchdowns'])/(len(R['n'])*0.02):7.1f} {sum(R['stumble'])/(len(R['n'])*0.02):6.2f}")
