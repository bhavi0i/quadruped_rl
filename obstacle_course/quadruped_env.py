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
        hips=[f"go1/{l}_hip" for l in LEG_NAMES],
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
        hips=[f"{l}_hip" for l in legs],
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
#
# HISTORY - see ../EXPERIMENT_LOG.md for the full record. Earlier settings stay commented out
# next to the current ones with a note on what happened.  Status tags:
#   [WORKS]  verified good in training       [FAILED]  tried, caused a problem (kept for the record)
#   [NEW]    added, not yet verified          [ORIGINAL] from the first version of this course env
#
DEFAULT_REWARD_WEIGHTS = dict(
    # ---- rewards (things we want) ----
    # progress=2.0 uncapped                     [FAILED v1 ring, 2026-11-16] paid for every extra metre,
    #                                            so the Go1 learned to bound at ~3 m/s (target 0.6) with
    #                                            ~1 foot down. Now capped at target_speed (see _compute_reward).
    # velocity_tracking=1.0, sigma^2 = 0.25     [ORIGINAL; FAILED v1 ring] too weak/wide to stop sprinting
    # trot=1.0                                  [FAILED v1 ring] trot match stayed at chance (~0.52)
    # collision=-1.0                            [ORIGINAL; FAILED v1 ring] shins still scraped the ground
    progress=2.0,          # [NEW v2] metres of new ground per second, capped at the target speed
    velocity_tracking=2.0, # [NEW v2] exp(-(v_fwd - v_target)^2 / 0.1): moving at the commanded speed
    heading=0.5,           # [ORIGINAL] facing the next waypoint
    feet_air_time=5.0,     # [ORIGINAL] taking real steps instead of shuffling / vibrating
    alive=0.5,             # [ORIGINAL] small per-step bonus for staying upright
    trot=2.0,              # [NEW v2] feet follow the diagonal-trot clock (natural dog gait)
    foot_clearance=0.5,    # [NEW v1] swing feet lifted to a real step height above the local terrain
    # ---- punishments (things we don't want) ----
    lin_vel_z=-2.0,        # bouncing up and down
    ang_vel_xy=-0.05,      # rolling / pitching rates
    orientation=-1.0,      # [ORIGINAL] body tilt (projected gravity off vertical). Too weak to fix small
                           #   leans: 5 deg costs ~0.008/s. E9 continuation raises it to -30 via
                           #   --reward-weights (5 deg -> ~0.23/s).
    base_height=-10.0,     # crouching or rearing far from nominal height above local terrain
    torque=-2e-4,          # energy use
    joint_acc=-2.5e-7,     # jerky motion
    action_rate=-0.01,     # large changes in action between steps
    joint_limit=-5.0,      # pushing joints into their limits
    foot_slip=-0.1,        # feet sliding while in contact
    collision=-2.0,        # [NEW v2] torso / thighs / calves (shins) hitting the terrain or obstacles
    wall_contact=-2.0,     # [NEW v1] any part of the robot touching a wall or slalom barrier
    wall_proximity=-1.0,   # [NEW v1] walking within ~0.4 m of a wall straight ahead / to the side
    turn_to_route=0.0,     # [FAILED E8] when facing > 45 deg off the route (e.g. at a wall):
                           #   clip(yaw_rate * sign(heading error), -1, 1). The -1 side punished the
                           #   small yaw wobble of trotting in place, so policies learned to FREEZE
                           #   at walls (wall pass 0 % at 50M, from 17-83 %). Kept off (0).
    heading_progress=0.0,  # [E9, opt-in] potential-based: (|heading err| before - after) / dt,
                           #   only while > 30 deg off the route. Turning toward the route pays,
                           #   wobbling nets zero, so freezing gains nothing. E9 sets 0.5.
    track_following=0.0,   # [E8, opt-in] ring only: exp(-(distance from the yellow line)^2 / 0.25).
                           #   E7 seeds 0/1 drifted to walk ~1.1-1.4 m outside the line because
                           #   nothing rewarded staying on it. 0 = off (E7); E8 sets 1.0.
    body_alignment=0.0,    # [E9, opt-in] exp(-crab^2 / (2 * 10deg^2)): body points where it moves.
                           #   E7 policies all crabbed ~30 deg (body turned away from the direction of
                           #   travel, 0.4 m/s sideways) -> looked slanted/unnatural. 0 = off; E9 sets 1.5.
    lateral_velocity=0.0,  # [E9, opt-in] body-frame sideways speed^2 (walking diagonally). E9 sets -2.0.
    foot_placement=0.0,    # [E11, opt-in] stance feet away from where they sit under the hip in the
                           #   standing pose: sum over stance feet of (sideways^2 + fore-aft^2) in m^2.
                           #   Milestone 3 planted rear feet 12-17 cm out and 13-18 cm behind the hips
                           #   (legs visibly slanted). E11 sets -10.
    hip_abduction=0.0,     # [E11, opt-in] sum of hip-abduction (splay) angle^2 vs the standing pose.
                           #   Milestone 3 rear-left hip splayed +18 deg. E11 sets -2.
    swing_shape=0.0,       # [E11, opt-in] every swinging foot follows the same lift curve
                           #   swing_height * sin(pi * swing progress): exp(-err^2 / 3cm^2), averaged.
                           #   Milestone 3 lifted 15.5 / 9.8 / 9.1 / 6.6 cm per leg (uneven, limp-like;
                           #   the old foot_clearance only asks for >= 8 cm). E11 sets 1.0.
                           #   [LIMIT found in E12] the bell curve is ~0 once a foot is > 6 cm off, so
                           #   it gives no pull on a leg lifting 14-15 cm (FR) -> see swing_overshoot.
    feet_stumble=0.0,      # [C11, opt-in] feet hitting vertical faces (stair risers, hurdle sides):
                           #   count of feet whose contact force is mostly horizontal (|F_xy| > 2 |F_z|).
                           #   Stairs trace (C10, 0.5): rear feet stubbed into the riser at 14.9 m
                           #   instead of lifting over it. Standard legged_gym term. C11 sets -1.0.
    swing_overshoot=0.0,   # [E13, opt-in] quadratic penalty that keeps growing: sum over feet of
                           #   max(0, lift - (swing_height + 2 cm))^2. FR lifted 13-15 cm in E11/E12
                           #   while the others lifted ~8 cm. E13 sets -1000 (~1.25/s at 15 cm).
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
                 robot="go1", gait_period=0.5, swing_height=0.08, arena="course",
                 turn_practice=0.25, ring_lookahead=0.6, wall_spawn=0.0, max_steps=MAX_STEPS,
                 spawn_offset=0.8, friction_model="pyramidal", terrain_relative=False,
                 ramp_spawn=0.0, section_weights=None, terrain_aware_swing=False,
                 motion_gate=0.0):
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
        self.turn_practice = turn_practice   # share of spawns facing a random way (E7: 0.25, E8: 0.4)
        # Ring steering target: a point this many radians ahead on the yellow circle.
        # [E7/E8] 0.6 rad -> the target sits ~17 deg inward of the travel direction, so "face the
        #   target" (heading reward) pulled the body to angle inward (part of the crab).
        # [E9] 0.25 rad -> ~7 deg.
        self.ring_lookahead = ring_lookahead
        self.wall_spawn = wall_spawn         # [E10] extra share of ring spawns facing the wall (0 = off)
        # [stage 2] episode length in steps (50 Hz). Ring: 1500 (30 s). Course: 3000 (60 s), because
        #   23.5 m at the natural 0.6 m/s takes ~40 s - a 30 s episode could never reach the goal.
        self.max_steps = max_steps
        self.spawn_offset = spawn_offset     # course section spawns: section start + this (m)
        self.friction_model = friction_model # "pyramidal" (E1-E13, C1-C4: slippery) or "elliptic" (C5+)
        self.terrain_relative = terrain_relative  # [C6] orientation penalty relative to ground slope
        self.ramp_spawn = ramp_spawn         # [C9] share of course spawns placed partway up the ramp
        self.section_weights = dict(section_weights or {})  # [C10] relative spawn weight per section
        self.terrain_aware_swing = terrain_aware_swing      # [C13] swing lift measured vs the step ahead
        # [C14] gait rewards paid in proportion to forward speed. 0 = off (E1-C13). With x > 0 the
        #   trot / foot-lift / step-shape / air-time / heading rewards are scaled by
        #   clip(v_fwd / (x * target_speed), 0, 1). Found 2026-11-17: the stage-2 policy stalls
        #   on the 15 deg ramp trotting in place, and that stall earns MORE per step (+0.053)
        #   than walking over rough ground (+0.013), because these rewards were paid even at
        #   zero speed. Stopping in front of any hard obstacle was a stable local optimum.
        self.motion_gate = motion_gate
        # a number (all sections alike) or a dict per course section (C7 section curriculum)
        self.difficulty = dict(difficulty) if isinstance(difficulty, dict) else float(difficulty)
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
        self.model = course.build_model(difficulty, seed=self.course_seed, robot=self.robot,
                                        friction_model=getattr(self, "friction_model", "pyramidal"))
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
        self.hip_bodies = np.array([m.body(h).id for h in c["hips"]])
        self.abd_idx = np.array([0, 3, 6, 9])                  # first joint of each leg = hip splay
        # nominal foot position relative to its hip (body frame) in the standing pose
        tmp = mujoco.MjData(m)
        tmp.qpos[self.qadr] = self.default_q
        tmp.qpos[3:7] = [1, 0, 0, 0]
        mujoco.mj_forward(m, tmp)
        self.nominal_foot_rel = self._feet_rel_hips(tmp)
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

    def _feet_rel_hips(self, d):
        """(4, 2) foot minus hip position in the torso frame: [fore-aft, sideways]."""
        R = d.xmat[self.torso_id].reshape(3, 3)
        p0 = d.xpos[self.torso_id]
        fb = (d.geom_xpos[self.foot_geoms] - p0) @ R
        hb = (d.xpos[self.hip_bodies] - p0) @ R
        return (fb - hb)[:, :2]

    def _is_robot_body(self, b):
        while b > 0:
            if b == self.torso_id:
                return True
            b = self.model.body_parentid[b]
        return False

    def set_difficulty(self, difficulty):
        """Called by the curriculum callback; rebuilds the course at the next reset."""
        self._pending_difficulty = (dict(difficulty) if isinstance(difficulty, dict)
                                    else float(np.clip(difficulty, 0, 1)))

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

    def _feet_stumble(self):
        """[C11] number of feet pushing mostly sideways/forward into an obstacle face."""
        d, m = self.data, self.model
        f_world = np.zeros((4, 3))
        frc = np.zeros(6)
        for k in range(d.ncon):
            c = d.contact[k]
            for sign, g in ((1.0, c.geom1), (-1.0, c.geom2)):
                hit = np.where(self.foot_geoms == g)[0]
                if hit.size:
                    mujoco.mj_contactForce(m, d, k, frc)
                    f_world[hit[0]] += sign * (c.frame.reshape(3, 3).T @ frc[:3])
        horiz = np.linalg.norm(f_world[:, :2], axis=1)
        self._last_foot_forces = f_world
        return float(np.sum((horiz > 2.0 * np.abs(f_world[:, 2])) & (horiz > 1.0)))

    def _section_results(self):
        """[C7] per course section: True = cleared, False = reached but not cleared this episode.
        Sections behind the spawn point or never reached are left out."""
        out = {}
        for name, cx in zip(SECTION_NAMES, CHECKPOINT_X):
            start = course.SECTION_STARTS[name]
            if self.start_x <= start + 0.9 and self.max_x >= start:     # spawned on its run-up or reached it
                out[name] = bool(self.max_x > cx)
        return out

    def _terrain_relative_tilt(self, pos, yaw, grav):
        """Roll^2 + (pitch - ground pitch)^2, ground pitch from heights 0.3 m ahead / behind."""
        c, s = np.cos(yaw), np.sin(yaw)
        h_f = self._ground_height(pos[0] + 0.3 * c, pos[1] + 0.3 * s)
        h_b = self._ground_height(pos[0] - 0.3 * c, pos[1] - 0.3 * s)
        ground_pitch = np.arctan2(h_f - h_b, 0.6)              # + = uphill ahead
        body_pitch = np.arctan2(-grav[0], -grav[2])            # + = nose up (checked on the 9 deg ramp)
        roll = np.arctan2(grav[1], -grav[2])
        return float(roll ** 2 + (body_pitch - ground_pitch) ** 2)

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
            a = self._ring_angle(xy) + self.ring_lookahead
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
            # [ORIGINAL] section start + 0.8 m. For the ramp (9.2 + 0.8 = 10.0 > ramp foot 9.6) and the
            #   stairs (15.0 > first step 14.6) this spawns the dog ON the obstacle, so walking onto it
            #   from flat ground was never practised - C1 stopped at the ramp foot in every run.
            # [C2, opt-in] spawn_offset 0.15 m: torso just past the section start, all four feet on
            #   the flat run-up before each obstacle.
            # [C10, opt-in] weighted choice of section (e.g. more stairs/rubble practice)
            names = list(course.SECTION_STARTS)
            w = np.array([self.section_weights.get(n, 1.0) for n in names], float)
            start_x = course.SECTION_STARTS[names[self.np_random.choice(len(names), p=w / w.sum())]] + self.spawn_offset
            start_x = min(start_x, 18.7 + 0.2)
        qpos = self.data.qpos
        qpos[0] = start_x
        qpos[1] = self.np_random.uniform(-0.3, 0.3) if self.random_start else 0.0
        qpos[2] = self.cfg["spawn_height"]
        yaw = self.np_random.uniform(-0.3, 0.3) if self.random_start else 0.0
        turn_practice = self.random_start and self.np_random.random() < self.turn_practice  # random heading,
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
            # [E10, opt-in] exact wall-test situation: 0.8-1.2 m from the wall, facing it +-60 deg.
            #   E7/E9 wall skill drifted between checkpoints; most turn-practice spawns above are not
            #   actually facing the wall, so the "turn left toward the route" decision was rare.
            if self.random_start and not turn_practice and self.np_random.random() < self.wall_spawn:
                r = course.RING_RADIUS - self.np_random.uniform(0.8, 1.2)
                qpos[0] = course.RING_CENTER[0] + r * np.cos(a)
                qpos[1] = course.RING_CENTER[1] + r * np.sin(a)
                yaw = a + self.np_random.uniform(-np.pi / 3, np.pi / 3)   # a = facing the wall
            self.ring_theta, self.ring_last_a = 0.0, a
        qpos[3:7] = [np.cos(yaw / 2), 0, 0, np.sin(yaw / 2)]
        # [C9, opt-in] start some course episodes partway up the ramp, up to and over the crest, so
        #   cresting gets direct practice (C8: rubble ~7 s, hurdles ~15 s, then 40-100 s or stuck at
        #   the 11 deg ramp crest). Body pitched to the slope, height set from the local ground.
        if (self.arena == "course" and self.random_start and self.ramp_spawn > 0
                and self.np_random.random() < self.ramp_spawn):
            x = self.np_random.uniform(10.0, 11.4)
            mujoco.mj_forward(self.model, self.data)
            g = self._ground_height(x, 0.0)
            pitch = np.arctan2(self._ground_height(x + 0.2, 0.0) - self._ground_height(x - 0.2, 0.0), 0.4)
            qpos[0], qpos[1] = x, self.np_random.uniform(-0.3, 0.3)
            qpos[2] = g + self.cfg["spawn_height"]
            yaw = self.np_random.uniform(-0.3, 0.3)
            q_yaw = np.array([np.cos(yaw / 2), 0, 0, np.sin(yaw / 2)])
            q_pitch = np.array([np.cos(-pitch / 2), 0, np.sin(-pitch / 2), 0])   # nose up on an uphill
            qpos[3:7] = np.array([q_yaw[0] * q_pitch[0], -q_yaw[3] * q_pitch[2], q_yaw[0] * q_pitch[2],
                                  q_yaw[3] * q_pitch[0]])
            start_x = x
        qpos[self.qadr] = self.default_q + self.np_random.uniform(-0.1, 0.1, 12)
        self.data.ctrl[self.act_ids] = self.default_q
        mujoco.mj_forward(self.model, self.data)

        self.steps = 0
        self.wp_idx = 0
        self.start_x = self._update_progress_coord(qpos[:2])
        self.last_action = np.zeros(12)
        self.wall_hits = 0
        self.last_heading_err = None
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
        truncated = self.steps >= self.max_steps
        sections = int(sum(self.max_x > cx for cx in CHECKPOINT_X)) if self.arena == "course" else self.laps
        info = {"x": self.progress_s, "arena": self.arena, "start_x": self.start_x, "max_x": self.max_x,
                "difficulty": self.difficulty, "reached_goal": reached, "fell": fell,
                "sections_cleared": sections, "reward_terms": terms, **gait}
        if terminated or truncated:
            info["episode_sums"] = self.episode_sums
            if self.arena == "course":
                info["section_results"] = self._section_results()
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
        if self.terrain_aware_swing:
            # [C13] measure swing lift against the higher of the ground under the foot and 12 cm ahead
            #   of it, so "8 cm lift" means 8 cm above the NEXT step. Before, a rear foot over the lower
            #   step was rewarded for 8 cm above *that* step - not enough to clear a 9 cm riser, which
            #   fought the stumble penalty (C11/C12 stalled at the stairs, x = 15.1 m).
            c, sn = np.cos(yaw), np.sin(yaw)
            ahead = np.array([self._ground_height(feet_pos[i, 0] + 0.12 * c, feet_pos[i, 1] + 0.12 * sn)
                              for i in range(4)])
            lift_ahead = feet_pos[:, 2] - self.cfg["foot_radius"] - ahead
            lift = np.where(~foot_contact, np.minimum(lift, lift_ahead), lift)
        swing = ~want_down
        clearance = float(np.sum(np.clip(lift / self.swing_height, 0, 1) * swing) / max(swing.sum(), 1))
        # [E11] same lift curve for every swinging foot (uniform steps across the four legs)
        swing_prog = np.clip((foot_phase - 0.5) / 0.5, 0, 1)
        z_ref = self.swing_height * np.sin(np.pi * swing_prog)
        shape = float(np.sum(np.exp(-((lift - z_ref) ** 2) / 0.03 ** 2) * swing) / max(swing.sum(), 1))
        overshoot = float(np.sum(np.clip(lift - (self.swing_height + 0.02), 0, None) ** 2))
        stumble = self._feet_stumble() if self.w.get("feet_stumble", 0.0) else 0.0
        # [E11] stance feet under the hips (as in the standing pose), and no hip splay
        rel = self._feet_rel_hips(d) - self.nominal_foot_rel
        placement = float(np.sum(np.sum(rel ** 2, axis=1) * foot_contact))
        splay = float(np.sum((q[self.abd_idx] - self.default_q[self.abd_idx]) ** 2))

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
            # [ORIGINAL; FAILED v1 ring] uncapped progress + wide speed tracking -> sprinting/bounding:
            # "progress": max(0.0, s - self.max_x) / dt,
            # "velocity_tracking": np.exp(-((v_fwd - self.target_speed) ** 2) / 0.25),
            # [NEW v2] only new ground counts, never faster than the target speed; sharper tracking
            "progress": min(max(0.0, s - self.max_x) / dt, self.target_speed),
            "velocity_tracking": np.exp(-((v_fwd - self.target_speed) ** 2) / 0.1),
            "heading": np.cos(heading_err),
            "feet_air_time": air_reward,             # per touchdown (not a rate)
            "alive": 1.0,
            "trot": trot_match,
            "foot_clearance": clearance,
            "lin_vel_z": lin_vel[2] ** 2,
            "ang_vel_xy": float(np.sum(ang_vel[:2] ** 2)),
            # [ORIGINAL/E9] tilt relative to gravity. On slopes this forces the body horizontal: front
            #   legs stretched, rear legs crouched, rear shins hitting the ramp, calf motors at 100 %
            #   (C3-C5 stalled near the 9 deg ramp top).
            # "orientation": float(np.sum(grav[:2] ** 2)),
            # [C6, opt-in terrain_relative] tilt relative to the local ground slope along the heading
            "orientation": (self._terrain_relative_tilt(pos, yaw, grav) if self.terrain_relative
                            else float(np.sum(grav[:2] ** 2))),
            "base_height": (height - self.cfg["base_height"]) ** 2,
            "torque": float(np.sum(torque ** 2)),
            "joint_acc": float(np.sum(((qvel - self.last_qvel) / dt) ** 2)),
            "action_rate": float(np.sum((action - self.last_action) ** 2)),
            "joint_limit": limit_violation,
            "foot_slip": slip,
            "collision": float(n_collisions),
            "wall_contact": float(self.wall_hits),
            "wall_proximity": float(np.sum(np.clip(0.4 - lidar, 0, None) / 0.4)),
            "heading_progress": ((abs(self.last_heading_err) - abs(heading_err)) / dt
                                 if self.last_heading_err is not None
                                 and max(abs(heading_err), abs(self.last_heading_err)) > np.deg2rad(30)
                                 else 0.0),
            "turn_to_route": (float(np.clip(ang_vel[2] * np.sign(heading_err), -1, 1))
                              if abs(heading_err) > np.deg2rad(45) else 0.0),
            "body_alignment": (float(np.exp(-(((np.arctan2(d.qvel[1], d.qvel[0]) - yaw + np.pi) % (2 * np.pi) - np.pi)
                                              ** 2) / (2 * np.deg2rad(10) ** 2)))
                               if np.linalg.norm(d.qvel[:2]) > 0.2 else 0.0),
            "lateral_velocity": float(lin_vel[1] ** 2),
            "foot_placement": placement,
            "hip_abduction": splay,
            "swing_shape": shape,
            "swing_overshoot": overshoot,
            "feet_stumble": stumble,
            "track_following": (float(np.exp(-(np.linalg.norm(pos[:2] - np.array(course.RING_CENTER))
                                               - course.RING_TRACK_RADIUS) ** 2 / 0.25))
                                if self.arena == "ring" else 0.0),
            "checkpoint": 0.0, "goal": 0.0, "fall": 0.0,
        }
        if self.motion_gate:                         # [C14] no gait reward for trotting in place
            g = float(np.clip(v_fwd / (self.motion_gate * self.target_speed), 0.0, 1.0))
            for k in ("trot", "foot_clearance", "swing_shape", "feet_air_time", "heading"):
                terms[k] *= g
        self.max_x = max(self.max_x, s)
        self.last_heading_err = heading_err

        # --- one-off events (not scaled by dt)
        bonus = 0.0
        if self.arena == "course":
            for i, cx in enumerate(CHECKPOINT_X):
                if not self.checkpoints_done[i] and pos[0] > cx:
                    self.checkpoints_done[i] = True
                    bonus += w["checkpoint"]
                    self.episode_sums["checkpoint"] += w["checkpoint"]
            reached = bool(pos[0] > course.GOAL_X - 0.3 and abs(pos[1]) < 0.8)
        else:
            # [FAILED v1 ring] +10 bonus per completed lap. A 38 m lap takes ~63 s at the 0.6 m/s
            # target but episodes are 30 s, so only sprinting ever earned it -> taught bounding.
            # laps = int((self.max_x - self.start_x) // (2 * np.pi * course.RING_TRACK_RADIUS))
            # if laps > self.laps:
            #     self.laps = laps
            #     bonus += w["checkpoint"]
            #     self.episode_sums["checkpoint"] += w["checkpoint"]
            # [NEW v2] laps are only counted for logging
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
                "v_fwd": v_fwd, "wall_hits": self.wall_hits, "min_wall_dist": float(lidar.min()),
                "foot_rel_hip": rel + self.nominal_foot_rel, "nominal_foot_rel": self.nominal_foot_rel}
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
