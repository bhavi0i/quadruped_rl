"""
show_world.py - look at the training world in the MuJoCo viewer.

    python show_world.py                       # static world, Go1 standing in the training ring
    python show_world.py --arena course        # Go1 at the start of the obstacle course
    mjpython show_world.py --sensors           # live: training spawns + what the robot senses
    mjpython show_world.py --sensors --arena course --difficulty 0.3

--sensors replays training-style episodes (random spawns, including the 25 % "turn practice"
spawns that face a random way, often into a wall) and draws what the policy observes:
  * red/green lines: the 9 wall-distance rays (red = within 0.4 m of a wall)
  * small blue dots: the 11x5 terrain height scan ahead of the robot
No policy is loaded, so the robot just holds its standing pose. On macOS the live mode needs
`mjpython` (installed with mujoco: .venv/bin/mjpython).

Viewer controls: left-drag rotate, right-drag pan, scroll zoom, Ctrl+right-drag pushes the robot.
"""
import argparse
import time

import mujoco
import mujoco.viewer
import numpy as np

from quadruped_env import (LIDAR_ANGLES, LIDAR_RANGE, SCAN_X, SCAN_Y, QuadrupedCourseEnv)


def draw_sensors(viewer, env):
    scn = viewer.user_scn
    scn.ngeom = 0
    d = env.data
    _, _, _, _, yaw = env._body_frame()
    pos = d.qpos[:3].copy()
    lidar = env._lidar(pos, yaw)
    origin = pos - np.array([0, 0, 0.1])
    for a, dist in zip(LIDAR_ANGLES, lidar):
        end = origin + dist * np.array([np.cos(yaw + a), np.sin(yaw + a), 0.0])
        rgba = np.array([0.9, 0.1, 0.1, 1] if dist < 0.4 else [0.1, 0.8, 0.2, 0.8], np.float32)
        g = scn.geoms[scn.ngeom]
        mujoco.mjv_initGeom(g, mujoco.mjtGeom.mjGEOM_CAPSULE, np.zeros(3), np.zeros(3), np.zeros(9), rgba)
        mujoco.mjv_connector(g, mujoco.mjtGeom.mjGEOM_CAPSULE, 0.006, origin, end)
        scn.ngeom += 1
    c, s = np.cos(yaw), np.sin(yaw)
    for dx in SCAN_X:
        for dy in SCAN_Y:
            x, y = pos[0] + c * dx - s * dy, pos[1] + s * dx + c * dy
            z = env._ground_height(x, y) + 0.01
            g = scn.geoms[scn.ngeom]
            mujoco.mjv_initGeom(g, mujoco.mjtGeom.mjGEOM_SPHERE, np.array([0.012, 0, 0]),
                                np.array([x, y, z]), np.eye(3).ravel(), np.array([0.2, 0.4, 1, 1], np.float32))
            scn.ngeom += 1


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--arena", choices=["ring", "course"], default="ring")
    p.add_argument("--difficulty", type=float, default=1.0)
    p.add_argument("--robot", choices=["go1", "custom"], default="go1")
    p.add_argument("--sensors", action="store_true", help="live training spawns + sensor drawing")
    p.add_argument("--episode-sec", type=float, default=4.0, help="seconds per demo spawn")
    a = p.parse_args()

    env = QuadrupedCourseEnv(difficulty=a.difficulty, arena=a.arena, robot=a.robot,
                             random_start=a.sensors)
    env.reset(seed=0)
    if not a.sensors:
        mujoco.viewer.launch(env.model, env.data)
        return

    with mujoco.viewer.launch_passive(env.model, env.data) as viewer:
        viewer.cam.type = mujoco.mjtCamera.mjCAMERA_TRACKING
        viewer.cam.trackbodyid = env.torso_id
        viewer.cam.distance, viewer.cam.elevation = 3.0, -25
        seed, t0 = 0, time.time()
        while viewer.is_running():
            step_start = time.time()
            _, _, term, trunc, info = env.step(np.zeros(12))
            if term or trunc or time.time() - t0 > a.episode_sec:
                seed += 1
                env.reset(seed=seed)
                t0 = time.time()
                print(f"spawn {seed}: nearest wall {info['min_wall_dist']:.2f} m")
            draw_sensors(viewer, env)
            viewer.sync()
            time.sleep(max(0.0, 0.02 - (time.time() - step_start)))


if __name__ == "__main__":
    main()
