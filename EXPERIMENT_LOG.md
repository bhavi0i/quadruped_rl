# Experiment log

A record of the method and of every change to the robot, the world, the reward and the
training setup. Each entry says what was tried and what happened, and whether it was kept.
Nothing is deleted: replaced code stays in the source as commented-out blocks tagged
`[FAILED]`, `[REPLACED]` or `[ORIGINAL]`, next to the current version.

Status tags used here and in the code:
- **WORKS:** verified good in training
- **FAILED:** tried and caused a problem; kept for the record
- **NEW:** added but not yet verified
- **SUPERSEDED:** still works, but no longer the main approach

---

## Methodology

**Goal (Phase 1).** Train a healthy quadruped to walk with a natural, dog-like gait. Train it
until it can cross the obstacle course to the finish line. Save that policy. It is the starting
point for Phase 2 (adaptation) and the "no adaptation" baseline. Then measure how much worse it
does with an injured leg.

**Robot.** Unitree Go1 robot dog from MuJoCo Menagerie: 12 position-controlled motors, 3 per
leg (hip abduction, thigh, calf).

**World** (`obstacle_course/course.py`):
- a flat, walled **training ring** (8 m radius, 6 m lap track)
- a walled **obstacle course** lane: rubble, hurdles, ramp, stairs, slalom gates, goal pad. A
  difficulty setting from 0 to 1 scales every obstacle.

**Training stages:**
1. **Ring.** Learn to walk: natural trot, steady speed, steering, turning away from walls.
2. **Course.** Continue from the ring policy. A curriculum raises obstacle difficulty from 0 to 1
   whenever the robot reliably makes progress.

**Algorithm.** PPO (Stable-Baselines3) with about 30 parallel simulations per run on Amarel
(Rutgers HPC), about 8,800 steps/s per run. Observation and reward are normalised (VecNormalize).
Runs checkpoint every 1M steps and resume automatically after preemption. Each setting is run
with 3 seeds.

**How results are judged.** Every reward change is checked by measurements and by video, not
just by the return. RL finds loopholes ("reward hacking"), so a high return can hide a bad gait.

| Measure | What a natural trot looks like |
|---|---|
| speed | about the 0.6 m/s target |
| trot match (feet follow the diagonal-trot clock) | > 0.8 (0.5 = chance) |
| feet on the ground | about 2 (one diagonal pair) |
| body contact rate (shins, knees, belly) | about 0 |
| falls | about 0 % |
| wall contacts | about 0 |

Every checkpoint review also saves pictures and videos for the presentation:
- contact sheets for all seeds
- for the best seed, a walking video and a head-on wall video (mp4 and gif)

They go in `docs/media/review_<steps>M_<date>/`, and PROGRESS_REPORT.md embeds them.

Training writes these to `progress.json` in each run folder. Every 5M steps,
`tools/push_progress.py` pushes them and the latest policy to `progress/` on GitHub.

**Rules for changes:**
1. Change one idea at a time when possible. Log it here before launching.
2. Keep failed settings, commented out with the reason.
3. Archive failed runs instead of deleting them (`obstacle_course/runs_archive/` on Amarel).

---

## Experiments

### E1: Ant-v5, SAC, default reward (flat ground). SUPERSEDED
- **Date:** 2026-11-16
- **Setup:** Gymnasium Ant-v5 with the standard reward. SAC, 3 seeds, 3M steps on Amarel `main`.
- **Result:** started walking. Seed 2 had an eval return of about 2,050 at 0.5M steps; seeds
  varied a lot. Snapshots are in `progress/phase1_sac_seed1`, `seed2`.
- **Why stopped:** the group wanted a realistic robot dog, not the spider-like Ant.

### E2: Go1 flat ground, SAC, "move forward, don't fall" reward. FAILED (gait)
- **Date:** 2026-11-16
- **Setup:** Go1 in Ant-v5. Reward = 2 × forward speed + alive − small action, drift and tilt
  penalties.
- **Result:** walked fast early (0.73 m/s, no falls at 150k steps). Trot match stayed at 0.51,
  which is chance.
- **Lesson:** a speed reward alone does not give a natural gait. The policy needs an explicit
  gait signal (a clock) and a gait reward.
- **Where:** commented summary at the top of `Go1Control` history in `injury_wrapper.py`.

### E3: Go1 flat ground, SAC, trot-shaped reward (A: base, B: trot weight ×2). SUPERSEDED
- **Date:** 2026-11-16
- **Setup:**
  - Gait clock in the observation.
  - Rewards: track 0.8 m/s, trot match, swing foot clearance.
  - Penalties: slip, height, tilt, bounce, body contact, torque.
  - Two versions: A (3 seeds) and B with stronger trot and clearance weights (2 seeds).
- **Result:** cancelled early, at about 0.1–0.2M steps. SAC was too slow for the obstacle course:
  about 150 steps/s, so 50M+ steps would take about 4 days.
- **Lesson:** use PPO with many parallel simulations, which is the standard for legged robots.

### E4: World with the Go1 in the obstacle course, plus a training ring. WORKS
- **Date:** 2026-11-16
- **Change:** attached the Menagerie Go1 into the original course world. Added a walled flat ring
  beside the course and closed the course lane at both ends.
- **Ring size:**
  - First version: 4 m radius, 2.5 m track. **REPLACED:** a 16 m lap meant constant tight turning.
  - Now: 8 m radius, 6 m track (38 m lap).
- **Verified:** the Go1 stands still for a full 30 s episode on the course and in the ring. A
  paralysed front-right leg makes it fall in about 1.3 s.

### E5: Wall awareness. NEW
- **Date:** 2026-11-16
- **Change:**
  - Sensing: 9 horizontal range rays (−90° to +90°, 3 m) and a "touching a wall" flag in the
    observation.
  - Penalties: `wall_contact` −2 and `wall_proximity` −1 (inside 0.4 m).
  - Practice: 25 % of spawns face a random direction, often into a wall.
- **Verified in a unit test:** at 0.3 m from the wall the rays read 0.30–0.39 m, and driving the
  dog into the wall sets the flag and the penalty.
- **Still to verify:** that trained policies turn away and keep walking.

### E6: Ring v1, PPO. FAILED (reward hack: sprinting and bounding)
- **Media:** `docs/media/e6_ring_v1_sprinting/` (walk.gif / walk.mp4: the bounding gait)
- **Date:** 2026-11-16
- **Run:** Amarel job 63980991, 3 seeds. Archived on Amarel as
  `obstacle_course/runs_archive/ring_v1_sprinting_seed*`.
- **Reward:** the original course reward (progress 2.0 uncapped, velocity tracking 1.0 with
  σ² = 0.25), plus trot 1.0, foot clearance 0.5, collision −1, and a +10 bonus per lap.
- **Result at 7.4M steps (16 min):**

  | | Target | Measured |
  |---|---|---|
  | speed | 0.6 m/s | 2.2–3.0 m/s |
  | distance | — | 85–121 m per 30 s episode |
  | feet on the ground | ~2 | ~1.1 (bounding) |
  | trot match | > 0.8 | 0.52 |
  | shin contact | ~0 | ~30 % of steps (FR and RR calves) |
  | falls | ~0 % | 11–14 % |

  Video frames showed a hunched, bounding gallop.
- **Cause:**
  - Progress paid for every extra metre, so 3 m/s earned 5× the reward of 0.6 m/s.
  - The lap bonus could only be earned by sprinting: a lap takes about 63 s at 0.6 m/s, but
    episodes last 30 s.
  - Speed tracking (maximum 1.0 per second) was too weak to compete.
- **Lesson:** every distance-based reward must be capped at the target speed. Bonuses must be
  reachable at the intended pace.

### E7: Ring v2, PPO, capped progress and stronger trot. NEW (running)
- **Date:** 2026-11-16
- **Run:** Amarel job 63981178, 3 seeds, 40M steps (about 75 min).
- **Changes from E6:**

  | Setting | E6 | E7 |
  |---|---|---|
  | progress | uncapped | capped at 0.6 m/s |
  | lap bonus | +10 per lap | none (laps logged only) |
  | velocity tracking | weight 1.0, σ² = 0.25 | weight 2.0, σ² = 0.1 |
  | trot | 1.0 | 2.0 |
  | collision (shins, knees, belly) | −1 | −2 |

- **Expected reward per second:**
  - natural trot at 0.6 m/s: about 6.7
  - standing still: about 2
  - sprinting at 3 m/s: about 3
- **Interim result at 5M steps:** WORKS for gait.
  - Seeds 1 and 2: 0.51–0.55 m/s, trot match 0.84–0.87, about 2 feet down, no falls.
  - Still failing: shin contact 11–12 % and the wall test (0–17 %). The dog stops before the wall
    but does not turn.
  - Seed 0 is behind (0.12 m/s).
  - Details: PROGRESS_REPORT.md, report 1.
- **Result at 10–14M steps:** WORKS for natural walking on all 3 seeds.
  - 0.60–0.62 m/s, trot match 0.97–0.98, shin contact 0.2–0.3 %, no falls.
  - Walls: the dog never touches the wall (it stops about 1 m short). Turning away is emerging
    without reward changes (seed 2: 67 %; seeds 0 and 1: 33 % and 17 %, each favouring one turn
    direction).
  - Details: PROGRESS_REPORT.md, report 2.
- **Result at 16–21M steps:**
  - Walking near perfect: trot match 0.99–1.00, 2.0 feet down, 0.58–0.60 m/s, shin contact
    < 0.5 %, no falls.
  - Walls unstable: the per-seed pass rate swaps between checkpoints (seed 0 33→17 %, seed 1
    17→67 %, seed 2 67→17 %). It never touches the wall.
  - Details: PROGRESS_REPORT.md, report 3.
- **Result at 21–27M steps:**
  - Walking still perfect (trot 0.99–1.00).
  - Walls regressing: 17/0/17 %. The policies converged on "stop at the wall and trot in place".
  - Track error: seeds 0 and 1 at 1.0–1.1 m (off the line); seed 2 at 0.23 m.
  - Lesson: indirect rewards (heading +0.5) are not enough to learn turning around. A safe
    "wait" behaviour that keeps the dense trot and alive rewards beats it. E8 adds a direct
    turning payoff.
  - Details: PROGRESS_REPORT.md, report 4.
- **Result at 34–40M steps:**
  - **Seed 0 at 34M is the first all-goals policy.** Walls 83 %, turning both ways, never touching
    the wall; walking perfect; track error 1.21 m. Saved to
    `progress/milestones/e7_seed0_34M_all_six_goals/`.
  - Seed 1 final (40M): walking perfect, walls 17 %, track error 1.17 m.
  - Seed 2 final (40M): walking slipped (shin contact 10 %, 0.48 m/s); walls 17 %.
  - **Status: WORKS for walking. Walls inconsistent across seeds and checkpoints.**
  - Lessons:
    - Wall skill drifts in and out without a direct reward.
    - Long training can erode a good gait.
    - Keep milestone snapshots.

### E8: Ring continuation with an explicit turn reward. RUNNING (Amarel job 63982746, from E7 seed 1 final, 40M → 60M)
- **Why:** in E7 the wall turning is unstable. Turning is only rewarded indirectly (heading +0.5)
  and only practised in 25 % of episodes.
- **Change** (one idea plus more practice of it):
  - new `turn_to_route` reward, weight 1.0. When the dog faces more than 45° away from the route,
    it earns clip(yaw rate × sign(heading error), −1, 1): positive for turning toward the route,
    negative for turning away.
  - turn-practice spawns 25 % → 40 %.
  - new `track_following` reward, weight 1.0 (ring only): exp(−d² / 0.25), where d is the
    distance from the yellow track line. Added after the group noticed later policies walking
    off the line. Measured on the newest checkpoints: seeds 0 and 1 (18M, 23M) walk 1.1–1.4 m
    *outside* the line, while seed 2 (24M) stays within 0.4 m. Nothing in E7 rewarded staying
    on the line (steering aims at a point ahead on the line, but walking a slightly bigger circle
    costs nothing). This is a second idea in the same continuation; it is logged separately so
    its effect can be judged with the track-error metric.
- **How:** continue from the best E7 final policy (`train.py --init-from ... --reward-weights
  '{"turn_to_route": 1.0, "track_following": 1.0}' --turn-practice 0.4`). No restart from scratch.
- **Success:** wall pass rate ≥ 80 % with all walking goals still passing.

### H1: Hardware for RL training (CPU vs GPU on Amarel). DECIDED: keep 32 CPU cores
- **Date:** 2026-11-16
- **Question:** which Amarel node type trains fastest?
- **Setup:** the same 2M-step ring PPO run (`amarel/bench.slurm`) on different nodes.
- **Result:**

  | Setup | Speed | Time for 2M steps |
  |---|---|---|
  | 32 CPU cores, 2 update threads (current) | 8,924 steps/s | 227 s |
  | 64 CPU cores, 2 update threads | 8,905 steps/s | 228 s |

- **Finding:** doubling the cores gave no gain. The bottleneck is the PPO network-update phase
  (2 torch threads), not the physics simulation.
- **Not tested:** more update threads (16 or 32) and 1 GPU + 32 cores. These were cancelled and
  the setup left as is, at the group's request. The GPU environment `rlq-gpu` exists on Amarel
  if this is revisited.
- **Decision:** keep 32-core CPU nodes (`amarel/ring_ppo.slurm`). Training takes about 75–90 min
  per 40M-step run.

---

## Open questions and ideas
- If the trot match stays low in E7, raise `trot` further or add a feet-down-count term (2 feet).
- Shin contact: if it persists, check the calf collision capsules against the ground clearance
  at the default pose.
- Course stage: start from the best ring policy. Watch whether the trot clock helps or hurts on
  stairs and hurdles; the gait period may need to vary.
- Phase 2: injured-leg evaluation on the course. Distance reached, finish rate and falls per
  injured leg.
