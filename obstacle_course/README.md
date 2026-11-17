# Quadruped obstacle course – MuJoCo + RL

A 12-DoF quadruped (hip abduction, hip flexion, knee per leg, ~9 kg) learns with PPO to walk
down a 24 m walled lane full of obstacles.

```
pip install mujoco gymnasium stable-baselines3 tensorboard imageio imageio-ffmpeg
python train.py --envs 8                          # train (watch: tensorboard --logdir runs)
python play.py runs/ppo_quadruped/final.zip       # watch it in the MuJoCo viewer
python play.py runs/ppo_quadruped/final.zip --injury FL_knee=0.0   # test with a limp knee
```

| File | What it is |
|---|---|
| `course.py` | Builds the MJCF: robot + obstacle course. `difficulty` (0–1) scales every obstacle. |
| `quadruped_env.py` | Gymnasium env: observations, actions, rewards, termination, injuries. |
| `train.py` | PPO (Stable-Baselines3) with observation normalisation and an automatic curriculum. |
| `play.py` | Run a trained policy in the viewer or record an mp4. |

## The obstacle course

| Section | x (m) | Easy (difficulty 0) | Hard (difficulty 1) |
|---|---|---|---|
| Start pad | 0 – 2.5 | flat | flat |
| Rubble field | 2.5 – 5.5 | 18 blocks, 1–2 cm | 40 blocks, 1–7 cm |
| Hurdles | 6.5, 7.5, 8.5 | 3 cm bars | 11 cm bars |
| Ramp | 9.6 – 13.6 | 5° slope | 15° slope (0.4 m high) |
| Stairs | 14.6 – 17.0 | 3 cm steps | 9 cm steps, 3 up / 3 down |
| Slalom gates | 19.3, 20.4, 21.5 | barriers stop short of centre | barriers cross centre, must weave |
| Goal pad | 23.5 | | |

Every section begins on flat ground, so with `random_start=True` the robot is spawned at the
start of a random section. That way it practises stairs without first having to master
the rubble.

## What the robot sees (104 numbers)
Body-frame linear and angular velocity, gravity direction (tilt), height above the ground,
12 joint angles and 12 velocities, the previous action, the direction to the next waypoint,
the target speed, and an 11 × 5 **height scan** of the terrain from 0.2 m behind to 0.8 m
ahead. Without the scan it would be blind to hurdles and steps.

## What it controls (12 numbers)
Target joint angles as offsets from a standing pose (±0.5 rad), tracked by PD servos.
Policy runs at 50 Hz, physics at 200 Hz.

## Rewards and punishments
Every per-step term is multiplied by dt (0.02 s), so weights are "per second". All weights
are in `DEFAULT_REWARD_WEIGHTS` and can be overridden through `reward_weights={...}`.

**Rewards: what we want**

| Term | Weight | Formula / meaning |
|---|---|---|
| progress | +2.0 | metres of *new* ground gained in x (no credit for going back and forth) |
| velocity_tracking | +1.0 | `exp(-(v_fwd − 0.6)² / 0.25)`, speed toward the next waypoint vs. 0.6 m/s |
| heading | +0.5 | `cos(angle to next waypoint)`, steers it through the slalom |
| feet_air_time | +5.0 | at each touchdown: `air_time − 0.25 s`, rewards real steps, punishes shuffling |
| alive | +0.5 | per step upright |
| checkpoint | +10 | one-off, for clearing each section |
| goal | +100 | one-off, for reaching the goal pad (episode ends) |

**Punishments: what we don't want**

| Term | Weight | Penalises |
|---|---|---|
| fall | −50 | one-off: torso touches ground, tilt > 60°, or body < 12 cm above terrain (episode ends) |
| collision | −1.0 | each contact between torso/thigh/calf and terrain (should step *over* hurdles, not drag across) |
| base_height | −10 | `(height above local terrain − 0.31)²`, crouching or rearing |
| orientation | −1.0 | body roll/pitch (horizontal part of gravity vector) |
| lin_vel_z | −2.0 | bouncing up and down |
| ang_vel_xy | −0.05 | wobbling (roll/pitch rate) |
| foot_slip | −0.1 | feet sliding while in contact |
| joint_limit | −5.0 | joints within 0.1 rad of their limits |
| torque | −2e-4 | Σ torque², energy use |
| joint_acc | −2.5e-7 | jerky joint motion |
| action_rate | −0.01 | Σ (aₜ − aₜ₋₁)², jittery commands (very important for sim-to-real) |

The big positive drivers (progress, speed, checkpoints, goal) tell the robot *what* to do.
The small shaping penalties shape *how* it does it: a smooth, efficient, upright gait. If the
penalties are too strong, the robot learns that standing still is safest. If you see that,
lower `torque`/`action_rate`/`collision` first.

## Curriculum
`train.py` starts at difficulty 0. Every 200 episodes, if the mean distance travelled is more
than 3 m, difficulty increases by 0.1. Watch `curriculum/difficulty` in TensorBoard.

## Injuries (for the damage-adaptation part of the project)
`QuadrupedCourseEnv(injury={"FL_knee": 0.0})` makes a joint limp. `{"RR_hip": 0.3}` gives it 30 %
strength. `injury="random"` weakens a random joint in every episode. Ways to use it:
- Train healthy, then test injured. This is the baseline that shows the problem.
- Train with `--injury random`. The policy must be robust to any one damaged joint (domain
  randomisation, paper 12).
- Add the injury vector, or a learned latent estimated from recent history, to the
  observation. That's the RMA / online system-ID approach (papers 9, 10).

## Expected training cost
About 1,500–2,000 env steps/s per CPU core. Walking on flat ground usually emerges after
roughly 5–10 M steps. Clearing the full hard course takes something like 30–100 M steps.
Use as many `--envs` as you have cores.
