"""contact_audit.py - [2026-11-17] which robot parts touch the terrain, in which course section.
    cd obstacle_course && python ../tools/contact_audit.py <milestone_dir> <difficulty> [layouts]"""
import sys, json, collections, numpy as np, mujoco
sys.path.insert(0, ".")
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize
from quadruped_env import QuadrupedCourseEnv
M, d = sys.argv[1], float(sys.argv[2]); L = int(sys.argv[3]) if len(sys.argv) > 3 else 3
import os; cfg = json.load(open(M + "/config.json")) if os.path.exists(M + "/config.json") else {"friction_model": "elliptic"}
model = PPO.load(M + "/policy.zip", device="cpu")
SEC = (("slalom", 18.7), ("stairs", 14.2), ("ramp", 9.2), ("hurdles", 5.7), ("rubble", 2.2), ("start", -9))
sec = lambda x: next(n for n, a in SEC if x > a)
hits, steps = collections.Counter(), collections.Counter()
for lay in range(L):
    env = QuadrupedCourseEnv(arena="course", difficulty=d, random_start=False, max_steps=3000,
                             friction_model=cfg["friction_model"], course_seed=lay)
    norm = VecNormalize.load(M + "/policy_vecnormalize.pkl", DummyVecEnv([lambda: env])); norm.training = False
    obs, _ = env.reset(seed=300 + lay)
    for t in range(3000):
        obs, _, term, trunc, info = env.step(model.predict(norm.normalize_obs(obs), deterministic=True)[0])
        s = sec(env.data.qpos[0]); steps[s] += 1
        seen = set()
        for k in range(env.data.ncon):
            c = env.data.contact[k]
            for g, o in ((c.geom1, c.geom2), (c.geom2, c.geom1)):
                if g in env.bad_contact_geoms and o not in env.robot_geoms and o not in env.wall_geoms:
                    b = mujoco.mj_id2name(env.model, mujoco.mjtObj.mjOBJ_BODY, env.model.geom_bodyid[g]) or "?"
                    part = b.replace("go1/", "").split("_")[-1]
                    # contacts within 4 cm of a foot centre: the calf capsule grazing next to a planted foot
                    near = min(np.linalg.norm(c.pos - env.data.geom_xpos[f]) for f in env.foot_geoms) < 0.04
                    seen.add(part + ("@foot" if near else ""))
        for b in seen: hits[(s, b)] += 1
        if term or trunc: break
print("fraction of control steps each part touches terrain, by section:")
for s in [n for n, _ in SEC][::-1]:
    if steps[s]:
        row = {b: round(hits[(s, b)] / steps[s], 2) for (ss, b) in hits if ss == s}
        print(f"  {s:8s} ({steps[s]:5d} steps) {row}")
