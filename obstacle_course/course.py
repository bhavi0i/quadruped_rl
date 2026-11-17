"""
course.py - builds the MuJoCo world (quadruped robot + obstacle course) as an MJCF string.

The course runs along the +x axis inside a 3 m wide walled lane:

    x:  0 ─ 2.5   start pad (flat)  (lane is closed by walls at both ends)
        2.5 ─ 5.5 rubble field      (random small blocks)
        6.0 ─ 9.0 hurdles           (3 bars across the lane)
        9.6 ─ 13.6 ramp             (up, 1 m plateau, down)
       14.6 ─ 17.0 stairs           (up 3 steps, landing, down 3 steps)
       19.2 ─ 21.6 slalom gates     (barriers from alternating walls to weave around)
       23.5        goal pad

Beside the course is a flat, walled training ring (RING_CENTER, RING_RADIUS) where the robot
first learns to walk by doing laps before it is sent onto the obstacles.

`difficulty` in [0, 1] scales obstacle heights / slopes so you can run a curriculum.
Every section starts on flat ground at z = 0, so the robot can also be spawned at
the start of any section (see SECTION_STARTS) to speed up training.
"""
import os
import warnings

import mujoco
import numpy as np

GO1_XML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "robots", "unitree_go1", "go1.xml")

LANE_HALF_WIDTH = 1.5

# Training ring: a flat, walled circular arena beside the course where the robot first learns
# to walk (and turn) before it is sent onto the obstacles. It walks laps on the track circle.
# RING_CENTER, RING_RADIUS, RING_TRACK_RADIUS = (12.0, -8.0), 4.0, 2.5
#   [REPLACED 2026-11-16] first ring: 16 m lap meant constant tight turning; enlarged so walking
#   is nearly straight while still practising steering.
RING_CENTER = (12.0, -11.5)
RING_RADIUS = 8.0          # inner face of the ring wall (m)
RING_TRACK_RADIUS = 6.0    # the circle the robot is steered around (38 m lap)
GOAL_X = 23.5
SECTION_STARTS = {"start": 0.0, "rubble": 2.2, "hurdles": 5.7, "ramp": 9.2,
                  "stairs": 14.2, "slalom": 18.7}

# ----------------------------------------------------------------------------------
# Robot: 12-DoF quadruped (hip abduction, hip flexion, knee per leg), ~9 kg.
# Robot geoms live in geom group 1 so the height-scan rays (group 0 only) ignore them.
# ----------------------------------------------------------------------------------
LEGS = {  # name: (x, y) of hip relative to torso centre
    "FL": (0.19, 0.11), "FR": (0.19, -0.11),
    "RL": (-0.19, 0.11), "RR": (-0.19, -0.11),
}
DEFAULT_POSE = {"abd": 0.0, "hip": 0.7, "knee": -1.4}   # standing posture (rad)
JOINT_NAMES = [f"{leg}_{j}" for leg in LEGS for j in ("abd", "hip", "knee")]
FOOT_GEOMS = [f"{leg}_foot" for leg in LEGS]
THIGH_LEN = CALF_LEN = 0.2


def _leg_xml(leg, x, y):
    return f"""
      <body name="{leg}_hip" pos="{x} {y} 0">
        <joint name="{leg}_abd" axis="1 0 0" range="-0.6 0.6"/>
        <geom type="cylinder" size="0.035 0.025" euler="90 0 0" mass="0.4" rgba="0.2 0.2 0.25 1"/>
        <body name="{leg}_thigh" pos="0 {0.05 if y > 0 else -0.05} 0">
          <joint name="{leg}_hip" axis="0 1 0" range="-0.8 2.0"/>
          <geom name="{leg}_thigh_geom" type="capsule" fromto="0 0 0 0 0 -{THIGH_LEN}"
                size="0.022" mass="0.6" rgba="0.9 0.45 0.1 1"/>
          <body name="{leg}_calf" pos="0 0 -{THIGH_LEN}">
            <joint name="{leg}_knee" axis="0 1 0" range="-2.6 -0.4"/>
            <geom name="{leg}_calf_geom" type="capsule" fromto="0 0 0 0 0 -{CALF_LEN}"
                  size="0.016" mass="0.25" rgba="0.25 0.25 0.3 1"/>
            <geom name="{leg}_foot" type="sphere" pos="0 0 -{CALF_LEN}" size="0.025"
                  mass="0.05" friction="1.2 0.02 0.01" rgba="0.1 0.1 0.1 1"/>
            <site name="{leg}_foot_site" pos="0 0 -{CALF_LEN}" size="0.01"/>
          </body>
        </body>
      </body>"""


def robot_xml():
    legs = "".join(_leg_xml(n, x, y) for n, (x, y) in LEGS.items())
    return f"""
    <body name="torso" pos="0.8 0 0.36" childclass="robot">
      <freejoint name="root"/>
      <camera name="track" mode="trackcom" pos="-1.2 -1.6 0.9" xyaxes="0.8 -0.6 0 0.25 0.33 0.9"/>
      <geom name="torso_geom" type="box" size="0.24 0.1 0.05" mass="5.5" rgba="0.95 0.6 0.15 1"/>
      <geom name="head" type="box" pos="0.25 0 0.02" size="0.03 0.07 0.035" mass="0.3" rgba="0.15 0.15 0.2 1"/>
      <site name="imu" pos="0 0 0"/>
      {legs}
    </body>"""


def actuators_xml(kp=45.0, kv=1.2, effort=30.0):
    # Position servos: the policy outputs target joint angles (offsets from DEFAULT_POSE).
    lines = [f'<position name="{j}_act" joint="{j}" kp="{kp}" kv="{kv}" '
             f'forcerange="-{effort} {effort}" ctrlrange="-3 3"/>' for j in JOINT_NAMES]
    return "\n      ".join(lines)


# ----------------------------------------------------------------------------------
# Obstacle course
# ----------------------------------------------------------------------------------
def _box(name, pos, size, rgba="0.55 0.55 0.6 1", euler=None):
    e = f' euler="{euler[0]:.4f} {euler[1]:.4f} {euler[2]:.4f}"' if euler else ""
    return (f'<geom name="{name}" type="box" pos="{pos[0]:.3f} {pos[1]:.3f} {pos[2]:.4f}" '
            f'size="{size[0]:.3f} {size[1]:.3f} {size[2]:.4f}"{e} rgba="{rgba}" group="0"/>')


def course_xml(difficulty=1.0, seed=0):
    d = float(np.clip(difficulty, 0.0, 1.0))
    rng = np.random.default_rng(seed)
    g = []
    W = LANE_HALF_WIDTH

    # side walls + goal pad
    L = GOAL_X + 1.5
    g.append(_box("wall_L", (L / 2 - 0.5, W + 0.05, 0.15), (L / 2 + 0.5, 0.05, 0.15), "0.3 0.35 0.45 0.4"))
    g.append(_box("wall_R", (L / 2 - 0.5, -W - 0.05, 0.15), (L / 2 + 0.5, 0.05, 0.15), "0.3 0.35 0.45 0.4"))
    g.append(_box("wall_back", (-0.55, 0, 0.15), (0.05, W, 0.15), "0.3 0.35 0.45 0.4"))
    g.append(_box("wall_end", (L - 0.45, 0, 0.15), (0.05, W + 0.1, 0.15), "0.3 0.35 0.45 0.4"))
    g.append(f'<geom name="goal" type="cylinder" pos="{GOAL_X} 0 0.001" size="0.6 0.001" '
             f'rgba="0.1 0.85 0.3 0.6" contype="0" conaffinity="0" group="2"/>')

    # 1) rubble: random low blocks, height 1-2 cm at d=0 up to 1-7 cm at d=1
    for i in range(int(18 + 22 * d)):
        x, y = rng.uniform(2.6, 5.4), rng.uniform(-W + 0.1, W - 0.1)
        h = rng.uniform(0.01, 0.02 + 0.05 * d)
        sx, sy = rng.uniform(0.06, 0.18, size=2)
        g.append(_box(f"rubble_{i}", (x, y, h / 2), (sx, sy, h / 2), "0.5 0.45 0.4 1",
                      euler=(0, 0, rng.uniform(0, np.pi))))

    # 2) hurdles: bars across the lane, 3 cm -> 11 cm tall
    hh = 0.03 + 0.08 * d
    for i, x in enumerate((6.5, 7.5, 8.5)):
        g.append(_box(f"hurdle_{i}", (x, 0, hh / 2), (0.05, W, hh / 2), "0.85 0.2 0.2 1"))

    # 3) ramp: incline 5 deg -> 15 deg, 1 m plateau, then decline
    ang = np.deg2rad(5 + 10 * d)
    run = 1.5
    rise = run * np.tan(ang)
    slab = 0.05
    half_len = run / np.cos(ang) / 2
    x0 = 9.6
    # up-slope: tilted slab whose top surface goes from (x0, 0) to (x0+run, rise)
    cx, cz = x0 + run / 2, rise / 2
    nx, nz = -np.sin(ang), np.cos(ang)       # top-surface normal
    g.append(_box("ramp_up", (cx - nx * slab, 0, cz - nz * slab), (half_len, W, slab),
                  "0.4 0.55 0.7 1", euler=(0, -ang, 0)))
    g.append(_box("ramp_top", (x0 + run + 0.5, 0, rise / 2), (0.5, W, rise / 2), "0.4 0.55 0.7 1"))
    x1 = x0 + run + 1.0
    cx = x1 + run / 2
    g.append(_box("ramp_down", (cx + nx * slab, 0, cz - nz * slab), (half_len, W, slab),
                  "0.4 0.55 0.7 1", euler=(0, ang, 0)))

    # 4) stairs: 3 up, landing, 3 down; step height 3 cm -> 9 cm, tread 0.3 m
    sh, tread = 0.03 + 0.06 * d, 0.3
    xs = 14.6
    for k in range(3):                                   # up
        h = sh * (k + 1)
        g.append(_box(f"step_up_{k}", (xs + tread * k + tread / 2, 0, h / 2), (tread / 2, W, h / 2), "0.6 0.5 0.75 1"))
    land = xs + 3 * tread
    g.append(_box("landing", (land + 0.4, 0, 3 * sh / 2), (0.4, W, 3 * sh / 2), "0.6 0.5 0.75 1"))
    xd = land + 0.8
    for k in range(3):                                   # down
        h = sh * (2 - k)
        if h > 0:
            g.append(_box(f"step_dn_{k}", (xd + tread * k + tread / 2, 0, h / 2), (tread / 2, W, h / 2), "0.6 0.5 0.75 1"))

    # 5) slalom: staggered barriers sticking out from alternating walls. At d=0 they stop
    #    short of the centre line (straight path works); at d=1 they cross it by 0.3 m,
    #    so the robot has to weave left/right to get through.
    edge = 0.6 - 0.9 * d          # inner edge of a barrier, measured from the centre line
    for i, x in enumerate((19.3, 20.4, 21.5)):
        side = 1 if i % 2 == 0 else -1
        y_in, y_out = side * edge, side * W
        cy, hy = (y_in + y_out) / 2, abs(y_out - y_in) / 2
        g.append(_box(f"slalom_{i}", (x, cy, 0.2), (0.08, hy, 0.2), "0.2 0.6 0.55 1"))
    return "\n    ".join(g)


def ring_xml():
    """Walled circular arena (flat floor), wall segments tangent to a circle."""
    cx, cy = RING_CENTER
    # n = 96 segments [REPLACED]: each wall geom slows the height-scan/lidar ray casts; 64 still
    # looks round at this radius.
    n, r, t = 64, RING_RADIUS + 0.05, 0.05
    half_len = (r + t) * np.tan(np.pi / n) + 0.01
    g = []
    for k in range(n):
        a = 2 * np.pi * k / n
        g.append(_box(f"ring_wall_{k}", (cx + r * np.cos(a), cy + r * np.sin(a), 0.15),
                      (t, half_len, 0.15), "0.3 0.35 0.45 0.4", euler=(0, 0, a)))
    # painted track circle (visual only, no collision, not seen by the height scan)
    g.append(f'<geom name="ring_track" type="cylinder" pos="{cx} {cy} 0.001" size="{RING_TRACK_RADIUS + 0.06} 0.0005" '
             f'rgba="0.95 0.75 0.2 0.5" contype="0" conaffinity="0" group="2"/>')
    g.append(f'<geom name="ring_inner" type="cylinder" pos="{cx} {cy} 0.0015" size="{RING_TRACK_RADIUS - 0.06} 0.0005" '
             f'rgba="0.78 0.8 0.82 1" contype="0" conaffinity="0" group="2"/>')
    return "\n    ".join(g)


def build_mjcf(difficulty=1.0, seed=0, kp=45.0):
    return f"""
<mujoco model="quadruped_obstacle_course">
  <compiler angle="radian" autolimits="true"/>
  <option timestep="0.005" integrator="implicitfast"/>
  <visual><global offwidth="1280" offheight="720"/><quality shadowsize="4096"/></visual>
  <default>
    <geom contype="1" conaffinity="1" friction="1.0 0.02 0.01" solref="0.01 1"/>
    <joint damping="0.4" armature="0.01"/>
    <default class="robot"><geom group="1"/></default>
  </default>
  <asset>
    <texture name="grid" type="2d" builtin="checker" rgb1="0.82 0.84 0.86" rgb2="0.72 0.74 0.77" width="512" height="512"/>
    <material name="grid" texture="grid" texrepeat="40 40" reflectance="0.05"/>
    <texture name="sky" type="skybox" builtin="gradient" rgb1="0.55 0.7 0.9" rgb2="0.95 0.97 1" width="512" height="512"/>
  </asset>
  <worldbody>
    <light pos="10 -4 8" dir="-0.3 0.3 -1" directional="true" castshadow="true"/>
    <geom name="floor" type="plane" size="40 40 0.1" material="grid" group="0"/>
    {course_xml(difficulty, seed)}
    {ring_xml()}
    {robot_xml()}
  </worldbody>
  <actuator>
      {actuators_xml(kp=kp)}
  </actuator>
  <sensor>
    <framequat name="torso_quat" objtype="body" objname="torso"/>
    <gyro name="gyro" site="imu"/>
    <velocimeter name="vel" site="imu"/>
  </sensor>
</mujoco>"""


def build_model(difficulty=1.0, seed=0, robot="go1", friction_model="pyramidal"):
    """Compile the course with the chosen robot.

    robot="go1":    Unitree Go1 from MuJoCo Menagerie (robots/unitree_go1), attached into the course.
    robot="custom": the original hand-built 12-DoF quadruped defined above.
    """
    if robot == "custom":
        return mujoco.MjModel.from_xml_string(build_mjcf(difficulty, seed))
    world = f"""
<mujoco model="go1_obstacle_course">
  <compiler angle="radian" autolimits="true"/>
  <option timestep="0.005" integrator="implicitfast"/>
  <visual><global offwidth="1280" offheight="720"/><quality shadowsize="4096"/></visual>
  <default><geom contype="1" conaffinity="1" friction="1.0 0.02 0.01" solref="0.01 1"/></default>
  <asset>
    <texture name="grid" type="2d" builtin="checker" rgb1="0.82 0.84 0.86" rgb2="0.72 0.74 0.77" width="512" height="512"/>
    <material name="grid" texture="grid" texrepeat="40 40" reflectance="0.05"/>
    <texture name="sky" type="skybox" builtin="gradient" rgb1="0.55 0.7 0.9" rgb2="0.95 0.97 1" width="512" height="512"/>
  </asset>
  <worldbody>
    <light pos="10 -4 8" dir="-0.3 0.3 -1" directional="true" castshadow="true"/>
    <geom name="floor" type="plane" size="40 40 0.1" material="grid" group="0"/>
    {course_xml(difficulty, seed)}
    {ring_xml()}
  </worldbody>
</mujoco>"""
    spec = mujoco.MjSpec.from_string(world)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        go1 = mujoco.MjSpec.from_file(GO1_XML)
        # [FAILED, used for E1-E13 and C1-C4] copy the course's pyramidal cone / impratio 1 into the Go1
        #   spec to avoid a merge warning. Contacts became slippery: a Go1 standing on the 9 deg ramp
        #   slid 56 cm in 3 s (1 cm/s even at rest). Flat-ground training was barely affected, but the
        #   course policies could not climb the ramp.
        # [NEW, friction_model="elliptic"] use the Menagerie Go1 settings (elliptic cone, impratio 100):
        #   3.5 cm settle, then stable, at the same simulation speed.
        if friction_model == "elliptic":
            spec.option.cone = mujoco.mjtCone.mjCONE_ELLIPTIC
            spec.option.impratio = 100.0
        go1.option.impratio, go1.option.cone = spec.option.impratio, spec.option.cone  # no merge conflict
        spec.worldbody.add_frame().attach_body(go1.body("trunk"), "go1/", "")
        return spec.compile()
