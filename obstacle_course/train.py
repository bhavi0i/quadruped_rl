"""
train.py - PPO training with an automatic difficulty curriculum.

    python train.py                          # train from scratch (default 30M steps)
    python train.py --steps 2e6 --envs 8     # shorter run
    python train.py --injury random          # train with a random weakened joint each episode

Curriculum: every evaluation the mean distance travelled is checked; when the robot
covers most of the sections it is spawned on, the obstacles get bigger (difficulty += 0.1).
"""
import argparse
import os
import numpy as np
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback, CheckpointCallback
from stable_baselines3.common.vec_env import SubprocVecEnv, DummyVecEnv, VecNormalize, VecMonitor

from quadruped_env import QuadrupedCourseEnv


def make_env(rank, difficulty, injury):
    def _init():
        env = QuadrupedCourseEnv(difficulty=difficulty, random_start=True, injury=injury,
                                 course_seed=rank)          # different rubble per worker
        env.reset(seed=rank)
        return env
    return _init


class CurriculumCallback(BaseCallback):
    """Raises obstacle difficulty when the robot reliably makes progress."""

    def __init__(self, start=0.0, step=0.1, threshold=3.0, window=200, verbose=1):
        super().__init__(verbose)
        self.difficulty, self.step_size, self.threshold, self.window = start, step, threshold, window
        self.distances, self.goals, self.falls = [], [], []
        self.start_x = None

    def _on_training_start(self):
        self.start_x = np.array(self.training_env.get_attr("max_x"), dtype=float)

    def _on_step(self):
        for i, (done, info) in enumerate(zip(self.locals["dones"], self.locals["infos"])):
            if done:
                self.distances.append(info["x"] - self.start_x[i])
                self.goals.append(info["reached_goal"])
                self.falls.append(info["fell"])
                for k, v in info.get("episode_sums", {}).items():
                    self.logger.record_mean(f"reward_terms/{k}", float(v))
        # start position of the episode that just began in each env
        dones = self.locals["dones"]
        if np.any(dones):
            xs = np.array(self.training_env.get_attr("max_x"), dtype=float)
            self.start_x[dones] = xs[dones]

        if len(self.distances) >= self.window:
            mean_d = float(np.mean(self.distances))
            self.logger.record("curriculum/mean_distance", mean_d)
            self.logger.record("curriculum/fall_rate", float(np.mean(self.falls)))
            self.logger.record("curriculum/goal_rate", float(np.mean(self.goals)))
            if mean_d > self.threshold and self.difficulty < 1.0:
                self.difficulty = min(1.0, self.difficulty + self.step_size)
                self.training_env.env_method("set_difficulty", self.difficulty)
                if self.verbose:
                    print(f"[curriculum] mean distance {mean_d:.2f} m -> difficulty {self.difficulty:.1f}")
            self.logger.record("curriculum/difficulty", self.difficulty)
            self.distances, self.goals, self.falls = [], [], []
        return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--steps", type=float, default=30e6)
    p.add_argument("--envs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    p.add_argument("--difficulty", type=float, default=0.0)
    p.add_argument("--injury", default=None, help='"random" for random joint injuries')
    p.add_argument("--out", default="runs/ppo_quadruped")
    p.add_argument("--resume", default=None, help="path to a saved model .zip")
    args = p.parse_args()

    fns = [make_env(i, args.difficulty, args.injury) for i in range(args.envs)]
    venv = SubprocVecEnv(fns) if args.envs > 1 else DummyVecEnv(fns)
    venv = VecMonitor(venv)
    venv = VecNormalize(venv, norm_obs=True, norm_reward=True, clip_obs=10.0, gamma=0.99)

    policy_kwargs = dict(net_arch=dict(pi=[256, 256, 128], vf=[256, 256, 128]),
                         log_std_init=-0.5)
    if args.resume:
        model = PPO.load(args.resume, env=venv)
        venv_stats = args.resume.replace(".zip", "_vecnormalize.pkl")
        if os.path.exists(venv_stats):
            venv = VecNormalize.load(venv_stats, venv.venv)
            model.set_env(venv)
    else:
        model = PPO("MlpPolicy", venv, n_steps=1024, batch_size=4096, n_epochs=5,
                    learning_rate=3e-4, gamma=0.99, gae_lambda=0.95, clip_range=0.2,
                    ent_coef=0.0, vf_coef=0.5, max_grad_norm=1.0,
                    policy_kwargs=policy_kwargs, tensorboard_log=args.out, verbose=1)

    os.makedirs(args.out, exist_ok=True)
    callbacks = [CurriculumCallback(start=args.difficulty),
                 CheckpointCallback(save_freq=max(1, 500_000 // args.envs), save_path=args.out,
                                    name_prefix="ckpt", save_vecnormalize=True)]
    model.learn(total_timesteps=int(args.steps), callback=callbacks, reset_num_timesteps=not args.resume)
    model.save(f"{args.out}/final")
    venv.save(f"{args.out}/final_vecnormalize.pkl")
    print(f"saved to {args.out}/final.zip")


if __name__ == "__main__":
    main()
