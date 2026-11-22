"""expand_obs.py - [C17, 2026-11-22] continue a trained policy with a larger observation (network surgery).

    cd obstacle_course && python ../tools/expand_obs.py <old.zip> <new.zip> [--foot-scan]

The old policy's weights are copied unchanged; the first layer of the actor and of the critic get
zero-weight columns for the new inputs, so the expanded policy acts exactly like the old one at the
start and training learns how to use the new inputs. VecNormalize statistics are extended with
mean 0 / variance 1 for the new inputs (they adapt during training). Writes <new.zip> and
<new>_vecnormalize.pkl for train.py --init-from. Rule: never restart from scratch (2026-11-16).
"""
import sys, pickle, copy
import numpy as np, torch
sys.path.insert(0, ".")
from gymnasium import spaces
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize
from quadruped_env import QuadrupedCourseEnv

old, new = sys.argv[1], sys.argv[2]
kw = dict(foot_scan="--foot-scan" in sys.argv)
env = QuadrupedCourseEnv(arena="course", friction_model="elliptic", **kw)
n_new = env.observation_space.shape[0]
venv = DummyVecEnv([lambda: env])

m_old = PPO.load(old, device="cpu")
n_old = m_old.observation_space.shape[0]
print(f"observation {n_old} -> {n_new}")
m_new = PPO("MlpPolicy", venv, policy_kwargs=m_old.policy_kwargs, device="cpu",
            n_steps=m_old.n_steps, batch_size=m_old.batch_size, n_epochs=m_old.n_epochs,
            learning_rate=m_old.learning_rate, gamma=m_old.gamma, gae_lambda=m_old.gae_lambda,
            clip_range=0.2, ent_coef=m_old.ent_coef, vf_coef=m_old.vf_coef, max_grad_norm=m_old.max_grad_norm)
sd_old, sd_new = m_old.policy.state_dict(), m_new.policy.state_dict()
for k, v in sd_old.items():
    if sd_new[k].shape == v.shape:
        sd_new[k] = v.clone()
    else:                                    # first layer: [out, n_old] -> [out, n_new], new columns = 0
        w = torch.zeros_like(sd_new[k]); w[:, :n_old] = v; sd_new[k] = w
        print("expanded", k, tuple(v.shape), "->", tuple(w.shape))
m_new.policy.load_state_dict(sd_new)
m_new.num_timesteps = m_old.num_timesteps
# check: identical actions on the old part of the observation
o = np.random.randn(5, n_new).astype(np.float32); o[:, n_old:] = 0
with torch.no_grad():
    a1 = m_old.policy.predict(o[:, :n_old], deterministic=True)[0]
    a2 = m_new.policy.predict(o, deterministic=True)[0]
print("max action difference old vs new:", float(np.abs(a1 - a2).max()))
m_new.save(new)

stats_old = old.replace(".zip", "_vecnormalize.pkl") if "ckpt_" not in old else \
    old.replace("ckpt_", "ckpt_vecnormalize_").replace(".zip", ".pkl")
old_env = QuadrupedCourseEnv(arena="course", friction_model="elliptic")
vo = VecNormalize.load(stats_old, DummyVecEnv([lambda: old_env]))
vn = VecNormalize(venv, norm_obs=vo.norm_obs, norm_reward=vo.norm_reward, clip_obs=vo.clip_obs,
                  clip_reward=vo.clip_reward, gamma=vo.gamma, epsilon=vo.epsilon)
vn.obs_rms.mean = np.concatenate([vo.obs_rms.mean, np.zeros(n_new - n_old)])
vn.obs_rms.var = np.concatenate([vo.obs_rms.var, np.ones(n_new - n_old)])
vn.obs_rms.count = vo.obs_rms.count
vn.ret_rms = copy.deepcopy(vo.ret_rms)
vn.save(new.replace(".zip", "_vecnormalize.pkl"))
print("saved", new)
