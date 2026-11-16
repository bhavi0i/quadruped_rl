"""Quadruped environments and injury simulation.

Two robots, both run through Gymnasium's Ant-v5 environment class:
  * "go1": Unitree Go1 robot dog (MuJoCo Menagerie model, 12 position-controlled motors,
           3 per leg: hip abduction, thigh, calf). This is the main robot for the project.
  * "ant": the classic MuJoCo Ant (8 torque motors, 2 per leg).

An "injury" weakens every motor of one leg by a strength in [0, 1]:
    1.0 = healthy, 0.0 = leg fully paralysed (limp), 0.3 = badly weakened.
It is applied to the simulated motor itself (gain, damping and force limit), not to the
policy's command. That way a paralysed Go1 leg goes limp instead of being held stiff at a
fixed angle (a position motor with a zero command still holds the joint).

With injury_prob=0 nothing is changed, so the same code trains plain walking. Raising
injury_prob gives a domain-randomised policy (dynamics randomisation, RMA). With
expose_injury=True the per-leg strengths are appended to the observation, which is the
"privileged information" the RMA teacher policy gets.
"""

import os
from typing import Optional, Sequence

import gymnasium as gym
import mujoco
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
GO1_XML = os.path.join(HERE, "robots", "unitree_go1", "scene.xml")

N_LEGS = 4
# Leg index -> (name, actuator indices)
ROBOT_LEGS = {
    # Gymnasium ant.xml actuator order: hip_4, ankle_4, hip_1, ankle_1, hip_2, ankle_2, hip_3, ankle_3
    "ant": {0: ("back_right", (0, 1)), 1: ("front_left", (2, 3)),
            2: ("front_right", (4, 5)), 3: ("back_left", (6, 7))},
    # Menagerie go1.xml actuator order: FR(hip,thigh,calf), FL, RR, RL
    "go1": {0: ("front_right", (0, 1, 2)), 1: ("front_left", (3, 4, 5)),
            2: ("rear_right", (6, 7, 8)), 3: ("rear_left", (9, 10, 11))},
}
LEG_NAMES = {r: {i: v[0] for i, v in legs.items()} for r, legs in ROBOT_LEGS.items()}


class InjuryWrapper(gym.Wrapper):
    def __init__(
        self,
        env: gym.Env,
        robot: str = "go1",
        injury_prob: float = 0.0,
        strength_range: Sequence[float] = (0.0, 0.5),
        fixed_injury: Optional[dict] = None,
        expose_injury: bool = False,
    ):
        """
        injury_prob:    chance that an episode starts with one injured leg.
        strength_range: (low, high) for the random injured leg's strength.
        fixed_injury:   e.g. {2: 0.0} always disables leg 2 (used for evaluation).
                        Overrides the random sampling.
        expose_injury:  append the 4 leg strengths to the observation.
        """
        super().__init__(env)
        self.legs = ROBOT_LEGS[robot]
        self.injury_prob = injury_prob
        self.strength_range = strength_range
        self.fixed_injury = fixed_injury
        self.expose_injury = expose_injury
        self.leg_strength = np.ones(N_LEGS, dtype=np.float32)

        m = env.unwrapped.model
        assert m.nu == sum(len(a) for _, a in self.legs.values()), "actuator count mismatch"
        self._gain0 = m.actuator_gainprm.copy()
        self._bias0 = m.actuator_biasprm.copy()
        self._force0 = m.actuator_forcerange.copy()

        if expose_injury:
            low = np.concatenate([env.observation_space.low, np.zeros(N_LEGS)])
            high = np.concatenate([env.observation_space.high, np.ones(N_LEGS)])
            self.observation_space = gym.spaces.Box(low=low, high=high, dtype=np.float64)

    def _sample_injury(self):
        self.leg_strength[:] = 1.0
        if self.fixed_injury is not None:
            for leg, strength in self.fixed_injury.items():
                self.leg_strength[leg] = strength
        elif self.np_random.random() < self.injury_prob:
            leg = self.np_random.integers(N_LEGS)
            self.leg_strength[leg] = self.np_random.uniform(*self.strength_range)

    def _apply_injury(self):
        m = self.env.unwrapped.model
        m.actuator_gainprm[:] = self._gain0
        m.actuator_biasprm[:] = self._bias0
        m.actuator_forcerange[:] = self._force0
        for leg, (_, acts) in self.legs.items():
            s = float(self.leg_strength[leg])
            for a in acts:
                m.actuator_gainprm[a, 0] *= s          # kp (position) / gain (motor)
                m.actuator_biasprm[a, 1:3] *= s        # -kp, -kv (position); zeros for motor
                m.actuator_forcerange[a] *= s          # weaker motor saturates sooner

    def _obs(self, obs):
        if self.expose_injury:
            return np.concatenate([obs, self.leg_strength]).astype(np.float64)
        return obs

    def reset(self, **kwargs):
        self._sample_injury()
        self._apply_injury()
        obs, info = self.env.reset(**kwargs)
        info["leg_strength"] = self.leg_strength.copy()
        return self._obs(obs), info

    def step(self, action):
        obs, reward, terminated, truncated, info = self.env.step(action)
        info["leg_strength"] = self.leg_strength.copy()
        return self._obs(obs), reward, terminated, truncated, info


FOOT_GEOMS = ("FR", "FL", "RR", "RL")
TROT_OFFSET = np.array([0.0, 0.5, 0.5, 0.0])   # FR+RL move together, FL+RR half a cycle later


class Go1Control(gym.Wrapper):
    """Teach the Go1 to walk like a dog: a steady diagonal trot, not just "move forward somehow".

    Control
      * Episodes start from the standing "home" pose.
      * Actions are joint offsets around that pose (target = home + scale * a, a in [-1, 1]),
        the usual set-up for legged robots.
      * The observation gets a gait clock (sin/cos of the trot phase) and the previous action,
        so the policy knows where it is in the stride.

    Reward (per 0.02 s step), modelled on legged_gym / "Walk These Ways" quadruped rewards
      + track a natural forward speed (v_target m/s) rather than "as fast as possible",
        which otherwise gives frantic bounding or lunging
      + walk straight (no sideways drift or spinning)
      + trot: each foot on the ground / in the air when the trot pattern says so
      + lift swing feet to a real step height (no shuffling or foot dragging)
      - feet slipping while on the ground
      - body too low/high, tilted, bouncing or rocking
      - knees, thighs or belly touching the ground (no crawling)
      - large torques and jerky actions (smooth, efficient motion)
    The episode ends if the body tips over (> max_tilt_deg) or the trunk hits the ground.
    """

    def __init__(self, env, action_scale=(0.3, 0.6, 0.6), v_target=0.8, gait_period=0.5,
                 base_height=0.28, swing_height=0.08, max_tilt_deg=50.0, gait_weight=0.6,
                 w=None):
        super().__init__(env)
        u = env.unwrapped
        m = u.model
        self.home = m.key_qpos[0].copy()
        u.init_qpos[:] = self.home
        self.default_ctrl = self.home[7:].copy()
        self.scale = np.tile(np.asarray(action_scale), 4)
        self.lo, self.hi = m.actuator_ctrlrange[:, 0], m.actuator_ctrlrange[:, 1]
        self.action_space = gym.spaces.Box(-1.0, 1.0, (m.nu,), np.float32)
        n_obs = env.observation_space.shape[0] + 2 + m.nu
        self.observation_space = gym.spaces.Box(-np.inf, np.inf, (n_obs,), np.float64)

        self.v_target, self.period, self.base_height = v_target, gait_period, base_height
        self.swing_height = swing_height
        self.min_upright = np.cos(np.deg2rad(max_tilt_deg))
        self.w = dict(track=2.0, straight=0.5, gait=gait_weight, clearance=0.4, slip=0.1,
                      height=20.0, tilt=1.0, bounce=0.5, rock=0.02, body_contact=1.0,
                      torque=2e-4, action_rate=0.05, action=0.01)
        self.w.update(w or {})

        self.floor = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "floor")
        self.feet = np.array([mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, f) for f in FOOT_GEOMS])
        trunk = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "trunk")
        self.trunk_geoms = set(np.where(m.geom_bodyid == trunk)[0])
        self.dt = u.dt
        self.prev_a = np.zeros(m.nu)
        self.t = 0

    # ---- helpers -------------------------------------------------------------------------
    def _phase(self):
        return (self.t * self.dt / self.period) % 1.0

    def _obs(self, obs):
        ph = 2 * np.pi * self._phase()
        return np.concatenate([obs, [np.sin(ph), np.cos(ph)], self.prev_a])

    def _contacts(self):
        d = self.env.unwrapped.data
        feet_down = np.zeros(4, bool)
        body_hits, trunk_hit = 0, False
        for c in d.contact[: d.ncon] if d.ncon else []:
            g1, g2 = c.geom1, c.geom2
            if self.floor not in (g1, g2):
                continue
            g = g2 if g1 == self.floor else g1
            idx = np.where(self.feet == g)[0]
            if len(idx):
                feet_down[idx[0]] = True
            else:
                body_hits += 1
                trunk_hit |= g in self.trunk_geoms
        return feet_down, body_hits, trunk_hit

    # ---- gym API -------------------------------------------------------------------------
    def reset(self, **kwargs):
        self.prev_a[:] = 0
        self.t = 0
        obs, info = self.env.reset(**kwargs)
        self.prev_feet = self.env.unwrapped.data.geom_xpos[self.feet].copy()
        return self._obs(obs), info

    def step(self, action):
        a = np.clip(np.asarray(action, dtype=np.float64), -1, 1)
        target = np.clip(self.default_ctrl + self.scale * a, self.lo, self.hi)
        obs, _, terminated, truncated, info = self.env.step(target)
        self.t += 1
        d = self.env.unwrapped.data
        w = self.w

        qw, qx, qy, qz = d.qpos[3:7]
        upright = 1 - 2 * (qx * qx + qy * qy)            # cos of body tilt from vertical
        vx, vy, vz = info["x_velocity"], info["y_velocity"], d.qvel[2]
        wx, wy, wz = d.qvel[3:6]
        feet_pos = d.geom_xpos[self.feet].copy()
        feet_vel = (feet_pos - self.prev_feet) / self.dt
        self.prev_feet = feet_pos
        feet_down, body_hits, trunk_hit = self._contacts()

        # desired trot pattern: first half of each foot's cycle on the ground, second half in the air
        foot_phase = (self._phase() + TROT_OFFSET) % 1.0
        want_down = foot_phase < 0.5
        gait_match = float(np.mean(feet_down == want_down))
        swing = ~want_down
        lift = np.clip((feet_pos[:, 2] - 0.01) / self.swing_height, 0, 1)
        clearance = float(np.sum(lift * swing) / max(swing.sum(), 1))
        slip = float(np.sum(np.sum(feet_vel[:, :2] ** 2, axis=1) * feet_down))

        terms = {
            "track": w["track"] * np.exp(-((vx - self.v_target) ** 2) / 0.15),
            "straight": w["straight"] * np.exp(-(vy ** 2 + wz ** 2) / 0.1),
            "alive": info["reward_survive"],
            "gait": w["gait"] * gait_match,
            "clearance": w["clearance"] * clearance,
            "slip": -w["slip"] * slip,
            "height": -w["height"] * (d.qpos[2] - self.base_height) ** 2,
            "tilt": -w["tilt"] * (1 - upright),
            "bounce": -w["bounce"] * vz ** 2,
            "rock": -w["rock"] * (wx ** 2 + wy ** 2),
            "body_contact": -w["body_contact"] * body_hits,
            "torque": -w["torque"] * float(np.sum(d.actuator_force ** 2)),
            "action_rate": -w["action_rate"] * float(np.sum((a - self.prev_a) ** 2)),
            "action": -w["action"] * float(np.sum(a ** 2)),
        }
        reward = float(sum(terms.values()))
        self.prev_a = a

        fell = upright < self.min_upright or trunk_hit
        info.update(upright=upright, foot_contact=feet_down, want_contact=want_down,
                    gait_match=gait_match, foot_height=feet_pos[:, 2], body_contacts=body_hits,
                    base_height=d.qpos[2], reward_terms=terms)
        return self._obs(obs), reward, terminated or fell, truncated, info


def make_env(
    robot: str = "go1",
    injury_prob: float = 0.0,
    fixed_injury: Optional[dict] = None,
    expose_injury: bool = False,
    render_mode: Optional[str] = None,
    go1_kwargs: Optional[dict] = None,
    **env_kwargs,
) -> gym.Env:
    if robot == "go1":
        env = gym.make(
            "Ant-v5",
            xml_file=GO1_XML,
            frame_skip=10,                       # 0.002 s x 10 = 50 Hz control
            max_episode_steps=1000,              # 20 s episodes
            forward_reward_weight=0.0,           # reward is computed in Go1Control
            ctrl_cost_weight=0.0,
            contact_cost_weight=0.0,
            healthy_reward=0.5,
            main_body=1,
            healthy_z_range=(0.18, 0.75),
            include_cfrc_ext_in_observation=False,
            reset_noise_scale=0.05,
            render_mode=render_mode,
            **env_kwargs,
        )
        env = Go1Control(env, **(go1_kwargs or {}))
    else:
        env = gym.make("Ant-v5", render_mode=render_mode, **env_kwargs)
    return InjuryWrapper(env, robot=robot, injury_prob=injury_prob,
                         fixed_injury=fixed_injury, expose_injury=expose_injury)


def make_ant_env(**kwargs) -> gym.Env:
    """Backwards-compatible alias."""
    return make_env(robot="ant", **kwargs)
