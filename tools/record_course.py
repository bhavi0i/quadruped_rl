"""record_course.py - record one course run (layout L, difficulty D) as mp4 + gif, same setup as
evaluate_policy.course_test (course_seed=L, reset seed 300+L). Used for milestone videos when the
default video (layout 0) is not a crossing.
    cd obstacle_course && python ../tools/record_course.py <policy.zip> <difficulty> <layout> <out_prefix>
"""
import os, sys, json
import numpy as np, imageio.v3 as iio
sys.path.insert(0, ".")
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize
from quadruped_env import QuadrupedCourseEnv

pol, diff, lay, out = sys.argv[1], float(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
cfg = json.load(open(os.path.join(os.path.dirname(pol), "config.json")))
model = PPO.load(pol, device="cpu")
env = QuadrupedCourseEnv(arena="course", difficulty=diff, random_start=False, render_mode="rgb_array",
                         friction_model=cfg.get("friction_model", "elliptic"), max_steps=3000, course_seed=lay)
norm = VecNormalize.load(pol.replace(".zip", "_vecnormalize.pkl"), DummyVecEnv([lambda: env])); norm.training = False
obs, _ = env.reset(seed=300 + lay)
frames = []
for t in range(3000):
    obs, _, term, trunc, info = env.step(model.predict(norm.normalize_obs(obs), deterministic=True)[0])
    if t % 2 == 0:
        frames.append(env.render())
    if term or trunc:
        break
print(f"layout {lay} difficulty {diff}: goal={info['reached_goal']} fell={info['fell']} t={t*0.02:.1f}s x={env.max_x:.2f}")
iio.imwrite(out + ".mp4", np.stack(frames), fps=25)
small = [f[::2, ::2] for f in frames[::4]]
iio.imwrite(out + ".gif", np.stack(small), duration=80, loop=0)
