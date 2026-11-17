"""
quadruped_env.py - Gymnasium environment: a 12-DoF quadruped learning to cross the obstacle
course defined in course.py with a natural, dog-like trot.

    robot = "go1"    Unitree Go1 robot dog (MuJoCo Menagerie), default
    robot = "custom" the original hand-built quadruped from course.py

    obs  (116-dim):  body state (orientation, velocities, height), joint state, last action,
                     direction to the next waypoint, target speed, a trot gait clock,
                     9 horizontal wall-distance rays (-90..+90 deg), a "touching a wall" flag,
                     and an 11x5 height scan of the terrain ahead
    act  (12-dim):   target joint-angle offsets in [-1, 1] (scaled by the robot's action scale)
                     tracked by PD position servos at 200 Hz; the policy runs at 50 Hz

Injuries (for the damage-adaptation part of the project) weaken or disable motors:
    injury={"FR": 0.0}        whole front-right leg limp (leg names: FR, FL, RR, RL)
    injury={"FL_calf": 0.3}   one Go1 joint at 30 % strength (custom robot: "FL_knee" etc.)
    injury="random_leg"       a random leg at 0-50 % strength every episode
    injury="random"           a random single joint at 0-50 % strength every episode
"""
import numpy as np
import mujoco
import gymnasium as gym
from gymnasium import spaces

import course

FRAME_SKIP = 4              # 0.005 s * 4 = 20 ms control period (50 Hz)
MAX_STEPS = 1500            # 30 s episodes
SCAN_X = np.linspace(-0.2, 0.8, 11)   # height-scan grid in the robot's heading frame (m)
SCAN_Y = np.linspace(-0.3, 0.3, 5)
LIDAR_ANGLES = np.deg2rad([-90, -60, -40, -20, 0, 20, 40, 60, 90])   # horizontal range sensors
LIDAR_RANGE = 3.0           # m
WALL_PREFIXES = ("wall_", "ring_wall_", "slalom_")   # vertical barriers to steer around, not step over
LEG_NAMES = ("FR", "FL", "RR", "RL")
TROT_OFFSET = {"FR": 0.0, "RL": 0.0, "FL": 0.5, "RR": 0.5}   # diagonal pairs move together


# --------------------------------------------------------------------------------------
# Robot descriptions
# --------------------------------------------------------------------------------------
def _go1_cfg():
    parts = ("hip", "thigh", "calf")
    return dict(
        joints=[f"go1/{l}_{p}_joint" for l in LEG_NAMES for p in parts],
        actuators=[f"go1/{l}_{p}" for l in LEG_NAMES for p in parts],
        injury_names=[f"{l}_{p}" for l in LEG_NAMES for p in parts],
        feet=[f"go1/{l}" for l in LEG_NAMES],
        default_q=np.tile([0.0, 0.9, -1.8], 4),
        torso="go1/trunk",
        action_scale=np.tile([0.3, 0.6, 0.6], 4),
        base_height=0.27,       # standing trunk height above the ground (m)
        spawn_height=0.30,
        foot_radius=0.023,
    )


def _custom_cfg():
    legs = [l for l in LEG_NAMES]       # reorder the original robot's legs to FR, FL, RR, RL
    parts = ("abd", "hip", "knee")
    return dict(
        joints=[f"{l}_{p}" for l in legs for p in parts],
        actuators=[f"{l}_{p}_act" for l in legs for p in parts],
        injury_names=[f"{l}_{p}" for l in legs for p in parts],
        feet=[f"{l}_foot" for l in legs],
        default_q=np.array([course.DEFAULT_POSE[p] for _ in legs for p in parts]),
        torso="torso",
        action_scale=np.full(12, 0.5),
        base_height=0.31,
        spawn_height=0.34,
        foot_radius=0.025,
    )


ROBOTS = {"go1": _go1_cfg, "custom": _custom_cfg}


# --------------------------------------------------------------------------------------
# Reward weights.  Positive = reward, negative = punishment.  (dt = 0.02 s multiplies
# every term, so per-second magnitudes are what you see here.)
# --------------------------------------------------------------------------------------
DEFAULT_REWARD_WEIGHTS = dict(
    # ---- rewards (things we want) ----
    progress=2.0,          # metres of new ground per second, capped at the target speed (no sprinting)
    velocity_tracking=2.0, # exp(-(v_fwd - v_target)^2 / 0.1): moving at the commanded speed
    heading=0.5,           # facing the next waypoint
    feet_air_time=5.0,     # taking real steps instead of shuffling / vibrating
    alive=0.5,             # small per-step bonus for staying upright
    trot=2.0,              # feet follow the diagonal-trot clock (natural dog gait)
    foot_clearance=0.5,    # swing feet lifted to a real step height above the local terrain
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
    collision=-2.0,        # torso / thighs / calves (shins) hitting the terrain or obstacles
    wall_contact=-2.0,     # any part of the robot touching a wall or slalom barrier
    wall_proximity=-1.0,   # walking within ~0.4 m of a wall straight ahead / to the side
    # ---- one-off events ----
    checkpoint=10.0,       # bonus when the robot clears each course section (course only)
    goal=100.0,            # reaching the goal pad
    fall=-50.0,            # terminal penalty for falling over
)

# Waypoints the robot is steered toward (y offsets weave through the slalom gates)
WAYPOINTS = np.array([[5.8, 0.0], [9.3, 0.0], [14.2, 0.0], [18.7, 0.0],
                      [19.3, -0.75], [20.4, 0.75], [21.5, -0.75], [course.GOAL_X, 0.0]])
CHECKPOINT_X = [5.5, 9.0, 13.8, 17.6, 22.0]   # end of rubble, hurdles, ramp, stairs, slalom
SECTION_NAMES = ["rubble", "hurdles", "ramp", "stairs", "slalom"]


class QuadrupedCourseEnv(gym.Env):
    metadata = {"render_modes": ["human", "rgb_array"], "render_fps": 50}

    def __init__(self, difficulty=0.0, random_start=True, target_speed=0.6,
                 reward_weights=None, injury=None, render_mode=None, course_seed=0,
                 robot="go1", gait_period=0.5, swing_height=0.08, arena="course"):
        """
        difficulty   : 0..1, scales obstacle size (use for a curriculum)
        random_start : spawn at the start of a random course section (faster learning)
        target_speed : commanded forward speed in m/s
        injury       : see module docstring
        robot        : "go1" (default) or "custom"
        gait_period  : trot stride period in seconds (one full cycle of all four legs)
        swing_height : target foot lift above the local terrain during swing (m)
        arena        : "course" = obstacle lane; "ring" = flat walled training ring (walk laps)
        """
        assert arena in ("course", "ring")
        self.arena = arena
        self.difficulty = float(difficulty)
        self.random_start = random_start
        self.target_speed = target_speed
        self.w = dict(DEFAULT_REWARD_WEIGHTS, **(reward_weights or {}))
        self.injury = injury
        self.render_mode = render_mode
        self.course_seed = course_seed
        self.robot = robot
        self.cfg = ROBOTS[robot]()
        self.gait_period, self.swing_height = gait_period, swing_height
        self.trot_offset = np.array([TROT_OFFSET[l] for l in LEG_NAMES])
        self._build(self.difficulty)

        n_obs = 3 + 3 + 3 + 1 + 12 + 12 + 12 + 2 + 1 + 2 + len(LIDAR_ANGLES) + 1 + len(SCAN_X) * len(SCAN_Y)
        self.observation_space = spaces.Box(-np.inf, np.inf, shape=(n_obs,), dtype=np.float32)
        self.action_space = spaces.Box(-1.0, 1.0, shape=(12,), dtype=np.float32)
        self._renderer = None
        self._viewer = None

    # ---------------------------------------------------------------- model building
    def _build(self, difficulty):
        self.model = course.build_model(difficulty, seed=self.course_seed, robot=self.robot)
        self.data = mujoco.MjData(self.model)
        m, c = self.model, self.cfg
        self.default_q = c["default_q"].astype(float)
        self.action_scale = c["action_scale"]
        self.qadr = np.array([m.jnt_qposadr[m.joint(j).id] for j in c["joints"]])
        self.vadr = np.array([m.jnt_dofadr[m.joint(j).id] for j in c["joints"]])
        self.jnt_range = np.array([m.jnt_range[m.joint(j).id] for j in c["joints"]])
        self.act_ids = np.array([m.actuator(a).id for a in c["actuators"]])
        self.torso_id = m.body(c["torso"]).id
        self.foot_geoms = np.array([m.geom(g).id for g in c["feet"]])
        # every geom on the robot = geoms whose body is the torso or one of its descendants
        robot_bodies = {b for b in range(m.nbody) if self._is_robot_body(b)}
        self.robot_geoms = {g for g in range(m.ngeom) if m.geom_bodyid[g] in robot_bodies}
        self.bad_contact_geoms = self.robot_geoms - set(self.foot_geoms.tolist())
        self.torso_geoms = {g for g in range(m.ngeom) if m.geom_bodyid[g] == self.torso_id}
        self.wall_geoms = {g for g in range(m.ngeom)
                           if (mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, g) or "").startswith(WALL_PREFIXES)}
        self.wall_hits = 0
        self.base_kp = m.actuator_gainprm[:, 0].copy()
        self.base_bias = m.actuator_biasprm[:, :3].copy()
        self.base_force = m.actuator_forcerange.copy()
        self._ray_geomid = np.zeros(1, np.int32)
        self._scan_group = np.array([1, 0, 0, 0, 0, 0], np.uint8)   # terrain only (geom group 0)
        self._renderer = None

    def _is_robot_body(self, b):
        while b > 0:
            if b == self.torso_id:
                return True
            b = self.model.body_parentid[b]
        return False

    def set_difficulty(self, difficulty):
        """Called by the curriculum callback; rebuilds the course at the next reset."""
        self._pending_difficulty = float(np.clip(difficulty, 0, 1))

    # ---------------------------------------------------------------- injuries
    def _apply_injury(self):
        m = self.model
        m.actuator_gainprm[:, 0] = self.base_kp
        m.actuator_biasprm[:, :3] = self.base_bias
        m.actuator_forcerange[:] = self.base_force
        inj = self.injury
        if inj == "random":
            inj = {str(self.np_random.choice(self.cfg["injury_names"])): float(self.np_random.uniform(0, 0.5))}
        elif inj == "random_leg":
            inj = {str(self.np_random.choice(LEG_NAMES)): float(self.np_random.uniform(0, 0.5))}
        self.active_injury = inj or {}
        self.leg_strength = np.ones(4)
        for key, strength in self.active_injury.items():
            hit = [i for i, n in enumerate(self.cfg["injury_names"]) if n == key or n.startswith(key + "_")]
            if not hit:
                raise ValueError(f"unknown injury target {key!r}; use a leg {LEG_NAMES} or a joint "
                                 f"{self.cfg['injury_names']}")
            for i in hit:
                a = self.act_ids[i]
                m.actuator_gainprm[a, 0] = self.base_kp[a] * strength       # weaker P gain
                m.actuator_biasprm[a, 1] = self.base_bias[a, 1] * strength  # (bias = -kp*q - kv*qd)
                m.actuator_biasprm[a, 2] = self.base_bias[a, 2] * max(strength, 0.2)
                m.actuator_forcerange[a] = self.base_force[a] * max(strength, 1e-3)
                self.leg_strength[i // 3] = min(self.leg_strength[i // 3], strength)

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

    def _ring_angle(self, xy):
        return np.arctan2(xy[1] - course.RING_CENTER[1], xy[0] - course.RING_CENTER[0])

    def _update_progress_coord(self, xy):
        """Distance travelled along the route: x on the course, arc length on the ring track."""
        if self.arena == "course":
            return float(xy[0])
        a = self._ring_angle(xy)
        self.ring_theta += (a - self.ring_last_a + np.pi) % (2 * np.pi) - np.pi   # unwrap
        self.ring_last_a = a
        return float(self.ring_theta * course.RING_TRACK_RADIUS)

    def _lidar(self, pos, yaw):
        """Horizontal distances (m) from the torso to walls/obstacles, fanned left to right."""
        out = np.full(len(LIDAR_ANGLES), LIDAR_RANGE)
        pos = pos - np.array([0, 0, 0.1])     # cast below the 30 cm wall tops, above 11 cm hurdles
        for i, a in enumerate(LIDAR_ANGLES):
            v = np.array([np.cos(yaw + a), np.sin(yaw + a), 0.0])
            d = mujoco.mj_ray(self.model, self.data, pos, v, self._scan_group, 1, -1, self._ray_geomid)
            if 0 <= d < LIDAR_RANGE:
                out[i] = d
        return out

    def _next_waypoint(self, xy):
        if self.arena == "ring":            # carrot 0.6 rad ahead on the track circle (CCW)
            a = self._ring_angle(xy) + 0.6
            return np.array(course.RING_CENTER) + course.RING_TRACK_RADIUS * np.array([np.cos(a), np.sin(a)])
        while self.wp_idx < len(WAYPOINTS) - 1 and xy[0] > WAYPOINTS[self.wp_idx][0] - 0.1:
            self.wp_idx += 1
        return WAYPOINTS[self.wp_idx]

    def _phase(self):
        return (self.steps * FRAME_SKIP * self.model.opt.timestep / self.gait_period) % 1.0

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
        qpos[1] = self.np_random.uniform(-0.3, 0.3) if self.random_start else 0.0
        qpos[2] = self.cfg["spawn_height"]
        yaw = self.np_random.uniform(-0.3, 0.3) if self.random_start else 0.0
        turn_practice = self.random_start and self.np_random.random() < 0.25   # face a random way,
        if turn_practice and self.arena == "course":                          # often into a wall
            yaw = self.np_random.uniform(-1.6, 1.6)
        if self.arena == "ring":            # random spot on the track, facing along it (CCW)
            a = self.np_random.uniform(-np.pi, np.pi)
            r = course.RING_TRACK_RADIUS + self.np_random.uniform(-0.2, 0.2)
            qpos[0] = course.RING_CENTER[0] + r * np.cos(a)
            qpos[1] = course.RING_CENTER[1] + r * np.sin(a)
            yaw = a + np.pi / 2 + (self.np_random.uniform(-np.pi, np.pi) if turn_practice
                                   else self.np_random.uniform(-0.3, 0.3))
            if turn_practice:           # some spawns close to the outer wall, facing anywhere
                r = self.np_random.uniform(course.RING_TRACK_RADIUS, course.RING_RADIUS - 0.5)
                qpos[0] = course.RING_CENTER[0] + r * np.cos(a)
                qpos[1] = course.RING_CENTER[1] + r * np.sin(a)
            self.ring_theta, self.ring_last_a = 0.0, a
        qpos[3:7] = [np.cos(yaw / 2), 0, 0, np.sin(yaw / 2)]
        qpos[self.qadr] = self.default_q + self.np_random.uniform(-0.1, 0.1, 12)
        self.data.ctrl[self.act_ids] = self.default_q
        mujoco.mj_forward(self.model, self.data)

        self.steps = 0
        self.wp_idx = 0
        self.start_x = self._update_progress_coord(qpos[:2])
        self.last_action = np.zeros(12)
        self.wall_hits = 0
        self.last_qvel = np.zeros(12)
        self.feet_air_time = np.zeros(4)
        self.last_contacts = np.ones(4, bool)
        self.checkpoints_done = [cx < start_x for cx in CHECKPOINT_X]
        self.max_x = self.start_x
        self.laps = 0
        self.episode_sums = {k: 0.0 for k in self.w}
        return self._get_obs(), {}

    def step(self, action):
        action = np.clip(np.asarray(action, dtype=np.float64), -1, 1)
        self.data.ctrl[self.act_ids] = self.default_q + self.action_scale * action
        mujoco.mj_step(self.model, self.data, nstep=FRAME_SKIP)
        self.steps += 1

        reward, terms, fell, reached, gait = self._compute_reward(action)
        self.last_action = action
        self.last_qvel = self.data.qvel[self.vadr].copy()

        terminated = fell or reached
        truncated = self.steps >= MAX_STEPS
        sections = int(sum(self.max_x > cx for cx in CHECKPOINT_X)) if self.arena == "course" else self.laps
        info = {"x": self.progress_s, "arena": self.arena, "start_x": self.start_x, "max_x": self.max_x,
                "difficulty": self.difficulty, "reached_goal": reached, "fell": fell,
                "sections_cleared": sections, "reward_terms": terms, **gait}
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
        ph = 2 * np.pi * self._phase()
        obs = np.concatenate([
            lin_vel * 2.0, ang_vel * 0.25, grav, [ground_below],
            (d.qpos[self.qadr] - self.default_q), d.qvel[self.vadr] * 0.05, self.last_action,
            [np.sin(heading_err), np.cos(heading_err)], [self.target_speed],
            [np.sin(ph), np.cos(ph)],
            self._lidar(pos, yaw) / LIDAR_RANGE, [float(self.wall_hits > 0)],
            np.clip(scan.ravel() - self.cfg["base_height"], -1.0, 1.0),
        ])
        return obs.astype(np.float32)

    # ---------------------------------------------------------------- reward
    def _contacts(self):
        foot_contact = np.zeros(4, bool)
        collision = walls = 0
        torso_hit = False
        for k in range(self.data.ncon):
            c = self.data.contact[k]
            g1, g2 = c.geom1, c.geom2
            r1, r2 = g1 in self.robot_geoms, g2 in self.robot_geoms
            if r1 == r2:          # robot-robot or world-world
                continue
            g, other = (g1, g2) if r1 else (g2, g1)
            if other in self.wall_geoms:      # bumped into a wall / barrier
                walls += 1
                continue
            hit = np.where(self.foot_geoms == g)[0]
            if hit.size:
                foot_contact[hit[0]] = True
            elif g in self.bad_contact_geoms:
                collision += 1
                torso_hit |= g in self.torso_geoms
        self.wall_hits = walls
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

        # --- trot: first half of each foot's cycle on the ground, second half in the air
        foot_phase = (self._phase() + self.trot_offset) % 1.0
        want_down = foot_phase < 0.5
        trot_match = float(np.mean(foot_contact == want_down))
        feet_pos = d.geom_xpos[self.foot_geoms]
        lift = np.array([feet_pos[i, 2] - self.cfg["foot_radius"] - self._ground_height(*feet_pos[i, :2])
                         for i in range(4)])
        swing = ~want_down
        clearance = float(np.sum(np.clip(lift / self.swing_height, 0, 1) * swing) / max(swing.sum(), 1))

        # --- foot slip: horizontal foot speed while in contact
        slip = 0.0
        for i, gid in enumerate(self.foot_geoms):
            if foot_contact[i]:
                vel = np.zeros(6)
                mujoco.mj_objectVelocity(self.model, d, mujoco.mjtObj.mjOBJ_GEOM, gid, vel, 0)
                slip += float(np.sum(vel[3:5] ** 2))

        # --- distance to walls around the robot (front and sides)
        lidar = self._lidar(pos, yaw)

        # --- height above local terrain
        ground = self._ground_height(pos[0], pos[1])
        height = pos[2] - ground
        s = self.progress_s = self._update_progress_coord(pos[:2])

        # --- joint limits (soft margin of 0.1 rad)
        lo, hi = self.jnt_range[:, 0] + 0.1, self.jnt_range[:, 1] - 0.1
        limit_violation = float(np.sum(np.clip(lo - q, 0, None) + np.clip(q - hi, 0, None)))

        torque = d.actuator_force
        terms = {
            # only new ground counts, and never faster than the target speed (no reward for sprinting)
            "progress": min(max(0.0, s - self.max_x) / dt, self.target_speed),
            "velocity_tracking": np.exp(-((v_fwd - self.target_speed) ** 2) / 0.1),
            "heading": np.cos(heading_err),
            "feet_air_time": air_reward,             # per touchdown (not a rate)
            "alive": 1.0,
            "trot": trot_match,
            "foot_clearance": clearance,
            "lin_vel_z": lin_vel[2] ** 2,
            "ang_vel_xy": float(np.sum(ang_vel[:2] ** 2)),
            "orientation": float(np.sum(grav[:2] ** 2)),
            "base_height": (height - self.cfg["base_height"]) ** 2,
            "torque": float(np.sum(torque ** 2)),
            "joint_acc": float(np.sum(((qvel - self.last_qvel) / dt) ** 2)),
            "action_rate": float(np.sum((action - self.last_action) ** 2)),
            "joint_limit": limit_violation,
            "foot_slip": slip,
            "collision": float(n_collisions),
            "wall_contact": float(self.wall_hits),
            "wall_proximity": float(np.sum(np.clip(0.4 - lidar, 0, None) / 0.4)),
            "checkpoint": 0.0, "goal": 0.0, "fall": 0.0,
        }
        self.max_x = max(self.max_x, s)

        # --- one-off events (not scaled by dt)
        bonus = 0.0
        if self.arena == "course":
            for i, cx in enumerate(CHECKPOINT_X):
                if not self.checkpoints_done[i] and pos[0] > cx:
                    self.checkpoints_done[i] = True
                    bonus += w["checkpoint"]
                    self.episode_sums["checkpoint"] += w["checkpoint"]
            reached = bool(pos[0] > course.GOAL_X - 0.3 and abs(pos[1]) < 0.8)
        else:                               # ring: count laps for logging only (no bonus: it paid for sprinting)
            self.laps = (self.max_x - self.start_x) / (2 * np.pi * course.RING_TRACK_RADIUS)
            reached = False
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
        gait = {"foot_contact": foot_contact, "want_contact": want_down, "trot_match": trot_match,
                "foot_lift": lift, "base_height": height, "body_contacts": n_collisions,
                "v_fwd": v_fwd, "wall_hits": self.wall_hits, "min_wall_dist": float(lidar.min())}
        return reward, terms, fell, reached, gait

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
