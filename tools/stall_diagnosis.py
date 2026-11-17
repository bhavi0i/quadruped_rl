"""stall_diagnosis.py - [C14, 2026-11-17] per-term reward while walking (start) vs stalled (after 25 s).
    cd obstacle_course && python ../tools/stall_diagnosis.py ../progress/milestones/<milestone> 1.0 [motion_gate]
Showed that trotting in place on the 15 deg ramp earned more reward than walking over rough ground."""
import sys, json, numpy as np, collections
sys.path.insert(0, '.')
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize
from quadruped_env import QuadrupedCourseEnv
M = sys.argv[1]; d = float(sys.argv[2])
cfg = json.load(open(M + '/config.json'))
model = PPO.load(M + '/policy.zip', device='cpu')
env = QuadrupedCourseEnv(arena='course', difficulty=d, random_start=False, max_steps=3000, friction_model='elliptic',
                         course_seed=0, reward_weights=cfg.get('reward_weights'), terrain_relative=cfg.get('terrain_relative_tilt', False),
                         swing_height=cfg.get('swing_height', 0.08), terrain_aware_swing=cfg.get('terrain_aware_swing', False), motion_gate=float(sys.argv[3]) if len(sys.argv)>3 else 0.0)
norm = VecNormalize.load(M + '/policy_vecnormalize.pkl', DummyVecEnv([lambda: env])); norm.training = False
obs, _ = env.reset(seed=300)
walk, stall = collections.defaultdict(list), collections.defaultdict(list)
tot_w, tot_s = [], []
for t in range(2000):
    obs, r, term, trunc, info = env.step(model.predict(norm.normalize_obs(obs), deterministic=True)[0])
    tgt = walk if 1 < t*0.02 < 2.2/0.6+1 else (stall if t*0.02 > 25 else None)
    if tgt is not None:
        for k, v in info['reward_terms'].items(): tgt[k].append(env.w.get(k, 0) * v)
        (tot_w if tgt is walk else tot_s).append(r)
    if term or trunc: break
print('reward/step  walking(flat start): %.3f   stalled(ramp): %.3f' % (np.mean(tot_w), np.mean(tot_s)))
rows = sorted(walk, key=lambda k: -abs(np.mean(walk[k]) - np.mean(stall[k])))
for k in rows[:18]: print(f"{k:20s} walk {np.mean(walk[k]): .3f}  stall {np.mean(stall[k]): .3f}  w={env.w.get(k,0)}")
