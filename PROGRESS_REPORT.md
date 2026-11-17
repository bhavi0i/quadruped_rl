# Progress report

Updated at every checkpoint review, about every 5M training steps. The newest report is at the
top. Earlier reports are kept below. The full methodology and every experiment are in
[EXPERIMENT_LOG.md](EXPERIMENT_LOG.md).

**Primary goal (Phase 1, stage 1: training ring).** The Go1 walks **naturally**: a steady
diagonal trot at about 0.6 m/s with no shin, knee or belly scraping and no falls. It **handles
walls**: it stops before hitting them and turns enough to keep walking. After that it moves on
to the obstacle course.

**How each checkpoint is judged** (`obstacle_course/evaluate_policy.py`, deterministic policy):

| Goal | Measure | Pass if |
|---|---|---|
| natural pace | \|speed − 0.6 m/s\| | ≤ 0.15 |
| trotting | trot match (feet follow the diagonal-trot clock) | ≥ 0.75 |
| trotting | mean feet on the ground | 1.6 – 2.6 |
| clean gait | steps with shins, knees or belly touching the ground | ≤ 5 % |
| stable | falls | ≤ 5 % |
| walls | wall test: start 1 m from the wall facing it (6 trials); pass = no prolonged contact and walks ≥ 1.5 m away | ≥ 80 % of trials |

**Decision rules for unattended tweaking:**
- **Walls:** if wall pass rate is still < 50 % at 15M steps, add a "turn toward the route"
  reward (yaw rate toward the waypoint when it is > 45° off-heading) and raise turn-practice
  spawns from 25 % to 40 %.
- **Shin contact:** if body contact is still > 5 % at 20M steps, raise the `collision`
  penalty, or check the calf collision geometry at the standing pose.
- **Pace or trot:** if they regress below goal for 2 seeds, raise the `trot` or
  `velocity_tracking` weight.
- **Falls:** if falls rise above 10 % after 10M steps, investigate before changing anything.
- **How changes are made:** one idea at a time. The old setting stays commented out in the
  code, failed runs are archived, and each change gets an entry in EXPERIMENT_LOG.md.

---

## Report 1: 2026-11-16, ring v2 (E7) at about 5M steps

**Status at a glance**

| Run | Steps | Pace | Trot | Feet down | Shin contact | Falls | Walls | Overall |
|---|---|---|---|---|---|---|---|---|
| seed 0 | 3.7M (eval of the 3M ckpt) | ❌ 0.12 m/s | ✅ 0.79 | ❌ 2.75 | ✅ 2 % | ✅ 0 % | ❌ 0 % | still learning to move |
| seed 1 | 5.3M | ✅ 0.55 m/s | ✅ 0.84 | ✅ 2.28 | ❌ 12 % | ✅ 0 % | ❌ 0 % | 4 of 6 goals |
| seed 2 | 5.2M | ✅ 0.51 m/s | ✅ 0.87 | ✅ 2.09 | ❌ 11 % | ✅ 0 % | ❌ 17 % | 4 of 6 goals |

Evidence: `progress/ppo_ring_seed*/eval/` holds `metrics.json`, `frames_walk.png` (walking) and
`frames_wall.png` (facing a wall).

**What changed since the last run**
- Fixed the sprinting reward hack from ring v1 (E6):
  - progress is capped at the target speed
  - the lap bonus is removed
  - speed tracking is stronger, trot ×2, shin-contact penalty ×2
- Added the goal-based checkpoint evaluation (`evaluate_policy.py`) and the review tool
  (`tools/review_checkpoint.py`).

**What's working**
- **The gait fix worked.** v1 bounded at about 3 m/s with a trot match of 0.52. v2 seeds 1 and 2
  now trot at the target pace (0.51–0.55 m/s) with a trot match of 0.84–0.87, about 2 feet down,
  9–11 cm foot lift and no falls, after only about 5M steps (about 10 minutes).
- The frames show a level body with diagonal legs alternating.

**What's not working yet**
- **Walls (main gap).** Facing a wall from 1 m, the dog stops short without touching it, which
  is good, but then trots in place instead of turning. It only gets away when the wall is at a
  shallow angle (60°).
- **Shin contact 11–12 %.** Seeds 1 and 2 occasionally brush a calf on the ground.
- **Seed 0** is behind: it stands and trots in place (0.12 m/s). It may catch up; seeds vary.

**Next**
- Let E7 continue to the 15M checkpoint, then apply the decision rules above (walls first).
- **Hardware benchmark** (in progress): the same training on 32 CPU cores, 64 CPU cores, and
  1 GPU + 32 cores. The fastest becomes the default.
