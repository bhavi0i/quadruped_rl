"""
quadruped_env.py - Gymnasium environment: a 12-DoF quadruped learning to walk through
the obstacle course defined in course.py.

    obs  (104-dim):  body state (orientation, velocities, height), joint state, last action,
                     direction to the goal, and a 11x5 height-scan of the terrain ahead
    act  (12-dim):   target joint-angle offsets in [-1, 1] (scaled by ACTION_SCALE) that
                     are tracked by PD position servos at 200 Hz; policy runs at 50 Hz

Also includes an `injury` option (weaken or disable joint motors) so the same
environment can be reused for the damage-adaptation part of the project.
"""
import numpy as np
import mujoco
import gymnasium as gym
from gymnasium import spaces

import course

ACTION_SCALE = 0.5          # rad of joint offset per unit action
FRAME_SKIP = 4              # 0.005 s * 4 = 20 ms control period (50 Hz)
MAX_STEPS = 1500            # 30 s episodes
SCAN_X = np.linspace(-0.2, 0.8, 11)   # height-scan grid in the robot's heading frame (m)
SCAN_Y = np.linspace(-0.3, 0.3, 5)


# --------------------------------------------------------------------------------------
# Reward weights.  Positive = reward, negative = punishment.  (dt = 0.02 s multiplies
# every term, so per-second magnitudes are what you see here.)
# --------------------------------------------------------------------------------------
DEFAULT_REWARD_WEIGHTS = dict(
    # ---- rewards (things we want) ----
    progress=2.0,          # metres gained toward the goal (along course centre line / waypoint)
    velocity_tracking=1.0, # exp(-(v_fwd - v_target)^2 / 0.25): moving at the commanded speed
    heading=0.5,           # facing the next waypoint
    feet_air_time=5.0,     # taking real steps instead of shuffling / vibrating
    alive=0.5,             # small per-step bonus for staying upright
    # ---- punishments (things we don't want) ----
    lin_vel_z=-2.0,        # bouncing up and down
    ang_vel_xy=-0.05,      # rolling / pitching rates
    orientation=-1.0,      # body tilt (projected gravity off vertical)
    base_height=-10.0,     # crouching or rearing far from nominal height above local terrain
    torque=-2e-4,          # energy use
    joint_acc=-2.5e-7,     # jerky motion
    action_rate=-0.01,     # large changes in action between steps
    joint_limit=-5.0,      # pushing joints into their limits
    foot_slip=-0.1,        # feet sliding while in contact
    collision=-1.0,        # torso / thighs / calves hitting the terrain or obstacles
    # ---- one-off events ----
    checkpoint=10.0,       # bonus when the robot clears each course section
    goal=100.0,            # reaching the goal pad
    fall=-50.0,            # terminal penalty for falling over
)

# Waypoints the robot is steered toward (y offsets weave through the slalom gates)
WAYPOINTS = np.array([[5.8, 0.0], [9.3, 0.0], [14.2, 0.0], [18.7, 0.0],
                      [19.3, -0.75], [20.4, 0.75], [21.5, -0.75], [course.GOAL_X, 0.0]])
CHECKPOINT_X = [5.5, 9.0, 13.8, 17.6, 22.0]   # end of rubble, hurdles, ramp, stairs, slalom


class QuadrupedCourseEnv(gym.Env):
    metadata = {"render_modes": ["human", "rgb_array"], "render_fps": 50}

    def __init__(self, difficulty=0.0, random_start=True, target_speed=0.6,
                 reward_weights=None, injury=None, render_mode=None, course_seed=0):
        """
        difficulty   : 0..1, scales obstacle size (use for a curriculum)
        random_start : spawn at the start of a random course section (faster learning)
        target_speed : commanded forward speed in m/s
        injury       : dict {joint_name: strength}, e.g. {"FL_knee": 0.0} = limp knee,
                       {"RR_hip": 0.3} = 30 % motor strength.  Use "random" for a random
                       single-leg injury every episode (for adaptation experiments).
        """
        self.difficulty = float(difficulty)
        self.random_start = random_start
        self.target_speed = target_speed
        self.w = dict(DEFAULT_REWARD_WEIGHTS, **(reward_weights or {}))
        self.injury = injury
        self.render_mode = render_mode
        self.course_seed = course_seed
        self._build(self.difficulty)

        n_obs = 3 + 3 + 3 + 1 + 12 + 12 + 12 + 2 + 1 + len(SCAN_X) * len(SCAN_Y)
        self.observation_space = spaces.Box(-np.inf, np.inf, shape=(n_obs,), dtype=np.float32)
        self.action_space = spaces.Box(-1.0, 1.0, shape=(12,), dtype=np.float32)
        self._renderer = None
        self._viewer = None

    # ---------------------------------------------------------------- model building
    def _build(self, difficulty):
        self.model = mujoco.MjModel.from_xml_string(
            course.build_mjcf(difficulty, seed=self.course_seed))
        self.data = mujoco.MjData(self.model)
        m = self.model
        self.default_q = np.array([course.DEFAULT_POSE[j.split("_")[1]] for j in course.JOINT_NAMES])
        self.qadr = np.array([m.jnt_qposadr[m.joint(j).id] for j in course.JOINT_NAMES])
        self.vadr = np.array([m.jnt_dofadr[m.joint(j).id] for j in course.JOINT_NAMES])
        self.jnt_range = np.array([m.jnt_range[m.joint(j).id] for j in course.JOINT_NAMES])
        self.torso_id = m.body("torso").id
        self.foot_geoms = np.array([m.geom(g).id for g in course.FOOT_GEOMS])
        robot_geoms = {i for i in range(m.ngeom) if m.geom_group[i] == 1}
        self.robot_geoms = robot_geoms
        self.bad_contact_geoms = robot_geoms - set(self.foot_geoms.tolist())
        self.torso_geom = m.geom("torso_geom").id
        self.base_kp = m.actuator_gainprm[:, 0].copy()
        self.base_bias = m.actuator_biasprm[:, :3].copy()
        self._ray_geomid = np.zeros(1, np.int32)
        self._scan_group = np.array([1, 0, 0, 0, 0, 0], np.uint8)   # terrain only
        self._renderer = None

    def set_difficulty(self, difficulty):
        """Called by the curriculum callback; rebuilds the course at the next reset."""
        self._pending_difficulty = float(np.clip(difficulty, 0, 1))

    # ---------------------------------------------------------------- injuries
    def _apply_injury(self):
        m = self.model
        m.actuator_gainprm[:, 0] = self.base_kp
        m.actuator_biasprm[:, :3] = self.base_bias
        inj = self.injury
        if inj == "random":
            leg = self.np_random.choice(list(course.LEGS))
            joint = f"{leg}_{self.np_random.choice(['abd', 'hip', 'knee'])}"
            inj = {joint: float(self.np_random.uniform(0.0, 0.5))}
        self.active_injury = inj or {}
        for joint, strength in self.active_injury.items():
            a = m.actuator(f"{joint}_act").id
            m.actuator_gainprm[a, 0] = self.base_kp[a] * strength      # weaker P gain
            m.actuator_biasprm[a, 1] = self.base_bias[a, 1] * strength  # (bias = -kp*q - kv*qd)
            m.actuator_biasprm[a, 2] = self.base_bias[a, 2] * max(strength, 0.2)

    # ---------------------------------------------------------------- terrain helpers
    def _ground_height(self, x, y):
        dist = mujoco.mj_ray(self.model, self.data, np.array([x, y, 3.0]), np.array([0, 0, -1.0]),
                             self._scan_group, 1, -1, self._ray_geomid)
        return 3.0 - dist if dist >= 0 else 0.0

    def _height_scan(self, pos, yaw):
        c, s = np.cos(yaw), np.sin(yaw)
        out = np.empty((len(SCAN_X), len(SCAN_Y)))
        for i, dx in enumerate(SCAN_X):
            for j, dy in enumerate(SCAN_Y):
                out[i, j] = self._ground_height(pos[0] + c * dx - s * dy, pos[1] + s * dx + c * dy)
        return pos[2] - out            # height of torso above each terrain point

    def _next_waypoint(self, xy):
        while self.wp_idx < len(WAYPOINTS) - 1 and xy[0] > WAYPOINTS[self.wp_idx][0] - 0.1:
            self.wp_idx += 1
        return WAYPOINTS[self.wp_idx]

    # ---------------------------------------------------------------- gym API
    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        if getattr(self, "_pending_difficulty", None) is not None:
            self.difficulty, self._pending_difficulty = self._pending_difficulty, None
            self._build(self.difficulty)
        mujoco.mj_resetData(self.model, self.data)
        self._apply_injury()

        start_x = 0.8
        if self.random_start:
            start_x = self.np_random.choice(list(course.SECTION_STARTS.values())) + 0.8
            start_x = min(start_x, 18.7 + 0.2)
        qpos = self.data.qpos
        qpos[0] = start_x
        qpos[1] = self.np_random.uniform(-0.3, 0.3)
        qpos[2] = 0.34
        yaw = self.np_random.uniform(-0.3, 0.3)
        qpos[3:7] = [np.cos(yaw / 2), 0, 0, np.sin(yaw / 2)]
        qpos[self.qadr] = self.default_q + self.np_random.uniform(-0.1, 0.1, 12)
        self.data.ctrl[:] = self.default_q
        mujoco.mj_forward(self.model, self.data)

        self.steps = 0
        self.wp_idx = 0
        self.last_action = np.zeros(12)
        self.last_qvel = np.zeros(12)
        self.feet_air_time = np.zeros(4)
        self.last_contacts = np.ones(4, bool)
        self.checkpoints_done = [cx < start_x for cx in CHECKPOINT_X]
        self.max_x = start_x
        self.episode_sums = {k: 0.0 for k in self.w}
        return self._get_obs(), {}

    def step(self, action):
        action = np.clip(np.asarray(action, dtype=np.float64), -1, 1)
        self.data.ctrl[:] = self.default_q + ACTION_SCALE * action
        mujoco.mj_step(self.model, self.data, nstep=FRAME_SKIP)
        self.steps += 1

        reward, terms, fell, reached = self._compute_reward(action)
        self.last_action = action
        self.last_qvel = self.data.qvel[self.vadr].copy()

        terminated = fell or reached
        truncated = self.steps >= MAX_STEPS
        info = {"x": float(self.data.qpos[0]), "difficulty": self.difficulty,
                "reached_goal": reached, "fell": fell, "reward_terms": terms}
        if terminated or truncated:
            info["episode_sums"] = self.episode_sums
        if self.render_mode == "human":
            self.render()
        return self._get_obs(), float(reward), terminated, truncated, info

    # ---------------------------------------------------------------- observation
    def _body_frame(self):
        d = self.data
        quat = d.qpos[3:7]
        R = np.zeros(9)
        mujoco.mju_quat2Mat(R, quat)
        R = R.reshape(3, 3)                          # body -> world
        lin_vel = R.T @ d.qvel[0:3]                  # body-frame linear velocity
        ang_vel = d.qvel[3:6].copy()                 # freejoint angular vel is already in body frame
        gravity = R.T @ np.array([0, 0, -1.0])       # projected gravity (tilt)
        yaw = np.arctan2(R[1, 0], R[0, 0])
        return R, lin_vel, ang_vel, gravity, yaw

    def _get_obs(self):
        d = self.data
        R, lin_vel, ang_vel, grav, yaw = self._body_frame()
        pos = d.qpos[0:3]
        wp = self._next_waypoint(pos[:2])
        to_wp = wp - pos[:2]
        heading_err = np.arctan2(to_wp[1], to_wp[0]) - yaw
        heading_err = (heading_err + np.pi) % (2 * np.pi) - np.pi
        scan = self._height_scan(pos, yaw)
        ground_below = scan[2, 2]                    # scan point roughly under the torso
        obs = np.concatenate([
            lin_vel * 2.0, ang_vel * 0.25, grav, [ground_below],
            (d.qpos[self.qadr] - self.default_q), d.qvel[self.vadr] * 0.05, self.last_action,
            [np.sin(heading_err), np.cos(heading_err)], [self.target_speed],
            np.clip(scan.ravel() - 0.32, -1.0, 1.0),
        ])
        return obs.astype(np.float32)

    # ---------------------------------------------------------------- reward
    def _contacts(self):
        foot_contact = np.zeros(4, bool)
        collision = 0
        torso_hit = False
        for k in range(self.data.ncon):
            c = self.data.contact[k]
            g1, g2 = c.geom1, c.geom2
            r1, r2 = g1 in self.robot_geoms, g2 in self.robot_geoms
            if r1 == r2:          # robot-robot or world-world
                continue
            g = g1 if r1 else g2
            hit = np.where(self.foot_geoms == g)[0]
            if hit.size:
                foot_contact[hit[0]] = True
            elif g in self.bad_contact_geoms:
                collision += 1
                torso_hit |= g == self.torso_geom
        return foot_contact, collision, torso_hit

    def _compute_reward(self, action):
        d, w, dt = self.data, self.w, FRAME_SKIP * self.model.opt.timestep
        R, lin_vel, ang_vel, grav, yaw = self._body_frame()
        pos = d.qpos[0:3]
        qvel = d.qvel[self.vadr]
        q = d.qpos[self.qadr]
        foot_contact, n_collisions, torso_hit = self._contacts()

        # --- direction of travel toward the current waypoint
        wp = self._next_waypoint(pos[:2])
        to_wp = wp - pos[:2]
        dir_wp = to_wp / (np.linalg.norm(to_wp) + 1e-6)
        v_world = d.qvel[0:2]
        v_fwd = float(v_world @ dir_wp)
        heading_err = np.arctan2(dir_wp[1], dir_wp[0]) - yaw
        heading_err = (heading_err + np.pi) % (2 * np.pi) - np.pi

        # --- feet air time (reward steps of >= 0.25 s, only when touching down)
        first_contact = foot_contact & ~self.last_contacts
        self.feet_air_time += dt
        air_reward = float(np.sum((self.feet_air_time - 0.25) * first_contact))
        self.feet_air_time[foot_contact] = 0.0
        self.last_contacts = foot_contact

        # --- foot slip: horizontal foot speed while in contact
        slip = 0.0
        for i, gid in enumerate(self.foot_geoms):
            if foot_contact[i]:
                vel = np.zeros(6)
                mujoco.mj_objectVelocity(self.model, d, mujoco.mjtObj.mjOBJ_GEOM, gid, vel, 0)
                slip += float(np.sum(vel[3:5] ** 2))

        # --- height above local terrain
        ground = self._ground_height(pos[0], pos[1])
        height = pos[2] - ground

        # --- joint limits (soft margin of 0.1 rad)
        lo, hi = self.jnt_range[:, 0] + 0.1, self.jnt_range[:, 1] - 0.1
        limit_violation = float(np.sum(np.clip(lo - q, 0, None) + np.clip(q - hi, 0, None)))

        torque = d.actuator_force
        terms = {
            "progress": max(0.0, pos[0] - self.max_x) / dt,        # only new ground counts
            "velocity_tracking": np.exp(-((v_fwd - self.target_speed) ** 2) / 0.25),
            "heading": np.cos(heading_err),
            "feet_air_time": air_reward,             # per touchdown (not a rate)
            "alive": 1.0,
            "lin_vel_z": lin_vel[2] ** 2,
            "ang_vel_xy": float(np.sum(ang_vel[:2] ** 2)),
            "orientation": float(np.sum(grav[:2] ** 2)),
            "base_height": (height - 0.31) ** 2,
            "torque": float(np.sum(torque ** 2)),
            "joint_acc": float(np.sum(((qvel - self.last_qvel) / dt) ** 2)),
            "action_rate": float(np.sum((action - self.last_action) ** 2)),
            "joint_limit": limit_violation,
            "foot_slip": slip,
            "collision": float(n_collisions),
            "checkpoint": 0.0, "goal": 0.0, "fall": 0.0,
        }
        self.max_x = max(self.max_x, pos[0])

        # --- one-off events (not scaled by dt)
        bonus = 0.0
        for i, cx in enumerate(CHECKPOINT_X):
            if not self.checkpoints_done[i] and pos[0] > cx:
                self.checkpoints_done[i] = True
                bonus += w["checkpoint"]
                self.episode_sums["checkpoint"] += w["checkpoint"]
        reached = bool(pos[0] > course.GOAL_X - 0.3 and abs(pos[1]) < 0.8)
        fell = bool(torso_hit or grav[2] > -0.5 or height < 0.12)   # >60 deg tilt or collapsed
        if reached:
            bonus += w["goal"]
            self.episode_sums["goal"] += w["goal"]
        if fell:
            bonus += w["fall"]
            self.episode_sums["fall"] += w["fall"]

        reward = bonus
        for k, v in terms.items():
            if k in ("checkpoint", "goal", "fall"):
                continue
            r = w[k] * v * dt
            reward += r
            self.episode_sums[k] += r
        return reward, terms, fell, reached

    # ---------------------------------------------------------------- rendering
    def render(self):
        if self.render_mode == "rgb_array":
            if self._renderer is None:
                self._renderer = mujoco.Renderer(self.model, 480, 640)
                self._cam = mujoco.MjvCamera()
                self._cam.distance, self._cam.azimuth, self._cam.elevation = 2.2, -130, -20
            self._cam.lookat[:] = self.data.qpos[:3]
            self._renderer.update_scene(self.data, self._cam)
            return self._renderer.render()
        if self.render_mode == "human":
            if self._viewer is None:
                from mujoco import viewer as mj_viewer
                self._viewer = mj_viewer.launch_passive(self.model, self.data)
                self._viewer.cam.type = mujoco.mjtCamera.mjCAMERA_TRACKING
                self._viewer.cam.trackbodyid = self.torso_id
                self._viewer.cam.distance = 2.5
            self._viewer.sync()

    def close(self):
        if self._viewer is not None:
            self._viewer.close()
            self._viewer = None
