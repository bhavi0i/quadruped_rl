# Progress report

Updated at every checkpoint review, about every 5M training steps. The newest report is at the
top. Earlier reports are kept below. The full methodology and every experiment are in
[EXPERIMENT_LOG.md](EXPERIMENT_LOG.md).

**Primary goal (Phase 1, stage 1: training ring).** The Go1 walks **naturally**: a steady
diagonal trot at about 0.6 m/s with no shin, knee or belly scraping and no falls. It **handles
walls**: it stops before hitting them and turns enough to keep walking. After that it moves on
to the obstacle course.

**Media.** Every review saves contact sheets of frames for all seeds, plus a walking video and
a head-on wall video (`.mp4` for presentations, `.gif` that plays here) for the best seed, in
`docs/media/review_<steps>M_<date>/`. Hand-made media for earlier stages is in `docs/media/`:
`world/`, `e6_ring_v1_sprinting/`, `report1/`, `report2/`.

### The training world

| Whole world: obstacle course (left) and training ring | Go1 robot dog |
|---|---|
| ![world overview](docs/media/world/overview.png) | ![Go1](docs/media/world/go1_closeup.png) |

| Rubble and hurdles | Ramp and stairs | Slalom gates and goal |
|---|---|---|
| ![](docs/media/world/course_rubble_hurdles.png) | ![](docs/media/world/course_ramp_stairs.png) | ![](docs/media/world/course_slalom_goal.png) |

**How each checkpoint is judged** (`obstacle_course/evaluate_policy.py`, deterministic policy):

| Goal | Measure | Pass if |
|---|---|---|
| natural pace | \|speed − 0.6 m/s\| | ≤ 0.15 |
| trotting | trot match (feet follow the diagonal-trot clock) | ≥ 0.75 |
| trotting | mean feet on the ground | 1.6 – 2.6 |
| clean gait | steps with shins, knees or belly touching the ground | ≤ 5 % |
| stable | falls | ≤ 5 % |
| walls | wall test: start 1 m from the wall facing it (6 trials); pass = no prolonged contact and walks ≥ 1.5 m away | ≥ 80 % of trials |

**Standing requirement: a natural look for a professional demo (added 2026-11-16).** Passing the
gait numbers is not enough. The dog must *look* natural: body pointing where it walks, level,
not leaning or crabbing. Every review now also measures:

| Goal | Measure | Pass if |
|---|---|---|
| no crabbing | crab angle (body heading vs direction of travel) | ≤ 10° |
| level body | roll (sideways lean) | ≤ 3° |
| level body | pitch (nose up/down) | ≤ 4° |

**Leg posture and step uniformity goals (added 2026-11-16):**

| Goal | Measure | Pass if |
|---|---|---|
| legs straight under the body | mean sideways stance-foot offset vs the standing pose | ≤ 5 cm |
| legs not trailing or reaching | mean fore-aft stance-foot offset vs the standing pose | ≤ 8 cm |
| uniform steps | (max − min) / mean of the four legs' step heights | ≤ 20 % |

**Stage 2 goal (obstacle course):** start at the beginning of the course and reach the goal pad
(goal rate ≥ 67 % over 3 runs), first at the curriculum difficulty, then at full difficulty
(1.0), while keeping the natural-gait goals.

**Decision rules for unattended tweaking:**
- **No restarts (2026-11-16, group decision).** Running jobs are never stopped or restarted
  from scratch. Reward or setting changes are applied after a run finishes, by **continuing
  training from its final policy** (`train.py --init-from`), so learned walking is kept.
- **Walls:** if wall pass rate is still < 50 % when the current runs finish (40M steps), continue
  from the best final policy with a "turn toward the route" reward (yaw rate toward the waypoint
  when it is > 45° off-heading) and turn-practice spawns raised from 25 % to 40 % (E8).
- **Shin contact:** if body contact is still > 5 % at the end of a run, raise the `collision`
  penalty in the continuation run, or check the calf collision geometry at the standing pose.
- **Pace or trot:** if they regress below goal for 2 seeds, raise the `trot` or
  `velocity_tracking` weight.
- **Falls:** if falls rise above 10 % after 10M steps, investigate before changing anything.
- **How changes are made:** one idea at a time. The old setting stays commented out in the
  code, failed runs are archived, and each change gets an entry in EXPERIMENT_LOG.md.

---

## Report 15: 2026-11-16, E11 too weak on leg posture → E12 (3–4× stronger) launched in parallel

| | Milestone 3 | E11 seeds (55–57M) | Goal |
|---|---|---|---|
| fore-aft foot offset | 11.3 cm | 8.2 / 10.2 / 10.1 cm | ≤ 8 |
| sideways foot offset | 5.0 cm | 5.2 / 4.4 / 4.5 cm | ≤ 5 |
| step-height spread | 87 % | 78 / 76 / 66 % | ≤ 20 % |
| step heights FR/FL/RR/RL | 15.5/10.0/9.3/6.5 | e.g. 15.4/8.1/9.0/7.8 cm | equal |
| walls / crab | 100 % / 0.1° | 100 / 83 / 67 % · 0.2–0.7° | ≥ 80 % / ≤ 10° |

- **Small improvement only.** The front-right leg still lifts about 14–15 cm while the others
  lift 7–9 cm. It is probably the outside leg on the counter-clockwise ring.
- **Why so slow:** the new terms are small next to the rest of the reward. A front leg at 15 cm
  instead of 8 costs only about 0.5 of about 8 reward per second.
- **Change: E12** (Amarel job 63984516, milestone 3 at 51M → 66M, in parallel with E11):
  - `foot_placement` −10 → −40
  - `hip_abduction` −2 → −6
  - `swing_shape` 1 → 3

  E11 keeps running untouched. The two runs together show the effect of the weight.

Media: `docs/media/review_55M_20261116_2343/`.

---

## Report 14: 2026-11-16, legs slanted and steps uneven → E11 launched; stage 2 prepared

### What the group noticed
Milestone 3 still walks "funny": the legs operate on a slant rather than perpendicular to the
ground and torso, and the cadence looks non-uniform.

### Measured on milestone 3 (front view below)

| Leg | Foot vs hip, sideways | Foot vs hip, fore-aft | Hip splay | Step height |
|---|---|---|---|---|
| front-right | 7.7 cm out | 4.9 cm behind | −5° | **15.5 cm** |
| front-left | 4.6 cm out | 8.5 cm behind | +3° | 10.0 cm |
| rear-right | **12.1 cm out** | **18.4 cm behind** | −3° | 9.3 cm |
| rear-left | **17.3 cm out** | **13.2 cm behind** | **+18°** | **6.5 cm** |

- **Slant:** the rear feet are planted wide and trail behind the hips. Against the new goals:
  fore-aft offset 11.3 cm ❌ (≤ 8), sideways splay 5.0 cm (borderline).
- **"Uneven cadence" is uneven legs, not timing.** Every leg steps exactly every 0.50 s (locked
  to the trot clock), but step heights range 6.5–15.5 cm (spread 87 % ❌, goal ≤ 20 %), so it
  looks like a slight limp.
- **Why:** nothing rewarded where the feet land, and `foot_clearance` only asks for *at least*
  8 cm of lift, so any mix of heights scored the same.

Front view of milestone 3 (legs angled outward, uneven lift):
![](docs/media/e11_before_leg_posture/front_view_milestone3.png)

### Change: E11 (Amarel job 63984256, 3 seeds, milestone 3 at 51M → 66M, no restart)
- `foot_placement` −10: stance feet back under the hips, where they sit in the standing pose.
- `hip_abduction` −2: no hip splay.
- `swing_shape` 1.0: every swinging foot follows the same smooth 8 cm lift curve, timed by the
  trot clock, so all four legs step alike.
- All E10 rewards and wall practice are kept.

### Stage 2 (obstacle course) prepared, starting after E11
- Group instruction: the **healthy** robot starts at the beginning of the course and learns to
  reach the end checkpoint.
- **Baseline:** the ring policy placed at the course start, even at difficulty 0, does not move
  (0.1 m) and falls in 3 of 3 runs. Walls on both sides of the lane look like "turn" situations
  from the ring.
  ![](docs/media/stage2_baseline_ring_policy_d0/course.gif)
- Fixes before training:
  - **Episodes 30 → 60 s.** 23.5 m at 0.6 m/s takes about 40 s, so the old episodes could never
    reach the goal.
  - **New course test** in the evaluator: run from the start; distance, sections cleared,
    goal reached, falls, time and full-run video.
- `amarel/course_ppo.slurm`:
  - continues from the best E11 policy
  - curriculum from difficulty 0 (+0.1 whenever the mean distance per episode exceeds 5 m)
  - spawns at random section starts so every obstacle type is practised
  - natural-gait rewards kept; `swing_shape` halved so it can lift higher for hurdles and steps

---

## Report 13: 2026-11-16, E10 late check: 2 seeds still perfect; seed 0's final eroded

| Run | Walls | Crab | Shin contact | Speed | Track error |
|---|---|---|---|---|---|
| E10 seed 0 **final** (59M) | ✅ 100 % | ✅ 1.4° | ❌ **18.6 %** | 0.48 m/s | 0.37 m |
| E10 seed 1 (58M) | ✅ 100 % | ✅ 0.6° | ✅ | ✅ 0.60 | ✅ 0.05 m |
| E10 seed 2 (56M) | ✅ 100 % | ✅ 0.1° | ✅ | ✅ 0.60 | ✅ 0.11 m |

- **Seeds 1 and 2 hold every goal** to the end of E10, a third consecutive pass.
- **Seed 0's last checkpoints eroded:** shins brushing the ground on 18.6 % of steps, and slower.
  This is the same late-training drift E7 seed 2 showed. It confirms the practice of picking
  policies **by evaluation (milestones)**, not by the last checkpoint. Milestone 3 (seed 1 at 51M)
  is unaffected.

Video of seed 1 at 58M (still perfect): ![](docs/media/review_56M_20261116_2305/ring_e10_seed1/wall.gif)

---

## Report 12: 2026-11-16, ✅ STAGE 1 COMPLETE: stable, natural trot with wall handling

**Stability confirmed.** At the second consecutive review (50–52M), every E10 seed still passes
all 9 goals.

| Run | Walls (44–46M → 50–52M) | Crab | Track error | Speed |
|---|---|---|---|---|
| E10 seed 0 (52M) | 100 → 100 % | 1.4° | 0.09 m | 0.60 m/s |
| **E10 seed 1 (51M)** | 100 → **100 %** | **0.1°** | 0.14 m | 0.59 m/s |
| E10 seed 2 (50M) | 100 → 83 % | 0.1° | 0.12 m | 0.59 m/s |

### Final stage 1 policy: milestone 3, [`progress/milestones/e10_seed1_51M_stage1_final/`](progress/milestones/e10_seed1_51M_stage1_final)
E10 seed 1 at 51M steps:

| Goal | Result |
|---|---|
| pace (target 0.6 m/s) | ✅ 0.59 m/s |
| trot match | ✅ 0.985 |
| feet on the ground | ✅ 1.96 |
| shin/knee/belly contact | ✅ 0.6 % |
| falls | ✅ 0 % |
| wall test | ✅ **100 %** (6/6) |
| crab (body vs. travel direction) | ✅ **0.1°** |
| roll / pitch | ✅ 0.3° / 2.3° |
| distance from the yellow line | 0.14 m |
| foot lift | 8.2 cm |

| Walking | Facing the wall: turns, rejoins the line, trots on |
|---|---|
| ![](progress/milestones/e10_seed1_51M_stage1_final/walk.gif) | ![](progress/milestones/e10_seed1_51M_stage1_final/wall.gif) |

Videos for slides: [walk.mp4](progress/milestones/e10_seed1_51M_stage1_final/walk.mp4) · [wall.mp4](progress/milestones/e10_seed1_51M_stage1_final/wall.mp4).
Frames: ![](progress/milestones/e10_seed1_51M_stage1_final/frames_wall.png)

Watch it in MuJoCo:
`cd obstacle_course && mjpython play.py ../progress/milestones/e10_seed1_51M_stage1_final/policy.zip --arena ring --wall-test --episodes 0`

### How we got here (summary for the presentation)

| Step | Problem | Change | Result |
|---|---|---|---|
| E6 | — | course reward in the ring | ❌ sprinting/bounding at 3 m/s (reward hack) |
| E7 | uncapped progress, lap bonus | capped progress, trot ×2 | ✅ natural trot; walls drift 0–83 % |
| E8 | walls | signed turn reward, line following | ❌ dog freezes at walls; ✅ on the line |
| E9 | 30° crab (body slanted) | body alignment, potential-based turning, closer target | ✅ crab 0.1°; walls drift again |
| E10 | "wrong-way" trap at walls | practise the exact wall situation (30 % of episodes) | ✅ **all goals, stable** |

Milestones kept along the way: `e7_seed0_34M_all_six_goals` (first wall-capable, but crabbing),
`e9_seed2_39M_all_nine_goals` (first natural posture), `e10_seed1_51M_stage1_final`.

### Next
- E10 finishes at 59M on its own (final review then).
- **Stage 2: obstacle course.** Continue from milestone 3 with the difficulty curriculum. It still
  needs a decision on when to start.
- Phase 1 baseline: injured-leg evaluation of the final healthy policy.

---

## Report 11: 2026-11-16, ✅ E10: every seed passes every goal, walls 100 % (first review; stability to confirm)

E10 at 44–46M steps (5–7M into the continuation from milestone 2):

| Run | Pace | Trot | Feet | Shin | Falls | Walls | Crab | Roll | Pitch | Track error |
|---|---|---|---|---|---|---|---|---|---|---|
| E10 seed 0 | ✅ 0.49 | ✅ 0.90 | ✅ 2.30 | ✅ 0.3 % | ✅ 0 % | ✅ **100 %** | ✅ 1.6° | ✅ 1.4° | ✅ 1.4° | 0.39 m |
| E10 seed 1 | ✅ 0.63 | ✅ 0.98 | ✅ 1.96 | ✅ 0.5 % | ✅ 0 % | ✅ **100 %** | ✅ 1.0° | ✅ 0.2° | ✅ 2.6° | 0.10 m |
| E10 seed 2 | ✅ 0.62 | ✅ 0.97 | ✅ 1.99 | ✅ 0.6 % | ✅ 0 % | ✅ **100 %** | ✅ 1.2° | ✅ 0.1° | ✅ 2.9° | 0.06 m |

**All 3 seeds pass all 9 goals, with walls at 100 %.** The wall-test-like spawns removed the
"wrong-way" trap. Every wall trial turns away and walks on, with no freezing.

For comparison, the E9 finals (54M): walls 67 % on all seeds, crab 0.1–0.7°, no falls. E9 is
superseded by E10.

| E10 walking | E10 facing the wall head-on |
|---|---|
| ![](docs/media/review_44M_20261116_2244/ring_e10_seed0/walk.gif) | ![](docs/media/review_44M_20261116_2244/ring_e10_seed0/wall.gif) |

Videos: [walk.mp4](docs/media/review_44M_20261116_2244/ring_e10_seed0/walk.mp4) · [wall.mp4](docs/media/review_44M_20261116_2244/ring_e10_seed0/wall.mp4)

**Still to confirm:** stability. E7 and E9 also hit 100 % once, then drifted. The success rule is
≥ 80 % on every seed at **consecutive** reviews, so the next review (about 50M) decides. If it
holds, stage 1 is done and the best E10 checkpoint becomes milestone 3.

Minor: E10 seed 0 walks a bit slow (0.49 m/s, within the ±0.15 tolerance).

---

## Report 10: 2026-11-16, E9 walls regress on 2 seeds → E10 launched (practise the exact wall situation)

| Run | Walls (39M → 43M → now) | Falls | Crab | Track error |
|---|---|---|---|---|
| E9 seed 0 (46M) | 100 → 67 → ✅ **100 %** | ❌ **20 %** (1 of 5 walking episodes) | ✅ 0.5° | 0.39 m |
| E9 seed 1 (50M) | 83 → 100 → ❌ **17 %** | ✅ 0 % | ✅ 0.5° | 0.13 m |
| E9 seed 2 (50M) | 100 → 0 → ❌ **0 %** | ✅ 0 % | ✅ 0.7° | 0.16 m |

**Still working:** the posture fix holds on every seed (crab ≤ 0.7°).

**Poor progress on walls → decision rule triggered** (2 seeds regressed).

**Diagnosis: the "wrong-way" trap.** At the wall the route is 90° to the dog's *left*. If a
policy turns *right* instead, it ends up facing backwards along the route. From there, turning
either way scores the same, and walking backwards along the route earns nothing, so it stands
still (seed 2's frames). Which way each seed turns flips between checkpoints because training
rarely recreates that exact moment: most turn-practice spawns are *not* facing the wall.

**Change: E10** (Amarel job 63983457, 3 seeds, from milestone 2 at 39M → 59M). One change:
`--wall-spawn 0.5`, so about 30 % of all training episodes start exactly like the wall test
(0.8–1.2 m from the wall, facing it within ±60°). Verified over 400 spawns: 33 %. All E9 rewards
are unchanged.

Also watching: seed 0's 20 % fall rate (new; the first falls since E6).

Media (seed 0, 46M, walls 100 %): [wall.mp4](docs/media/review_46M_20261116_2226/ring_e9_seed0/wall.mp4)
![](docs/media/review_46M_20261116_2226/ring_e9_seed0/wall.gif)

**Next:** review E10 every 5M. Success = walls ≥ 80 % on all seeds **at consecutive reviews**
(stability), plus all posture and walking goals. E9 finishes at 54M and is then closed out.

---

## Report 9: 2026-11-16, E9 at 41–44M: posture fix holds; wall skill drifts between checkpoints again

| Run | Walls (39M → now) | Crab | Pitch | Track error | Pace |
|---|---|---|---|---|---|
| E9 seed 0 (41M) | 100 % → **67 %** | ✅ 0.3° | ✅ 2.8° | 0.50 m | ✅ 0.53 m/s |
| E9 seed 1 (43M) | 83 % → ✅ **100 %** | ✅ 0.3° | ✅ 3.3° | ✅ 0.20 m | ✅ 0.60 m/s |
| E9 seed 2 (43M) | 100 % → ❌ **0 %** | ✅ 0.2° | ✅ 3.0° | ✅ 0.09 m | ✅ 0.61 m/s |

**What's working:** the anti-crab fix is stable. Crab is 0.2–0.3° on every seed, the body is
level, and the trot is clean.

**What's not:** wall turning drifts between checkpoints, just as in E7. Seed 2 now turns about
90° away from the wall and then **stands still** facing along the ring (it fell in 1 of 6
trials). Seed 0 fails at −30° and −60° (one turn direction again).
![](docs/media/review_41M_20261116_2215/ring_e9_seed2/frames_wall.png)

Best this review: seed 1 (walls 100 %, crab 0.3°, track 0.20 m). Video:
[wall.mp4](docs/media/review_41M_20261116_2215/ring_e9_seed1/wall.mp4), ![](docs/media/review_41M_20261116_2215/ring_e9_seed1/wall.gif)

**Decision:** no change yet. Only one seed regressed badly, seed 1 improved, and milestone 2
(E9 seed 2 at 39M, walls 100 %) is preserved from before the dip. E9 finishes at 54M.

**If the drift continues to the end of E9**, the next experiment (E10) targets wall
*consistency*:
- wall-test-like spawns (1 m from the wall, facing it) as a fixed share of training episodes
- a small "keep moving" term, so that turning then standing still is not a resting point

Separately, policies can be picked by evaluation rather than by last checkpoint. That is
already done via milestones.

---

## Report 8: 2026-11-16, ✅ E9 passes every goal: natural, straight, level trot that turns away from walls

### Status at a glance (E9, 4–5M steps into the continuation)

| Run | Pace | Trot | Feet | Shin | Falls | Walls | **Crab** | Roll | Pitch | Track error |
|---|---|---|---|---|---|---|---|---|---|---|
| E9 seed 0 (38M) | ✅ 0.63 | ✅ 0.98 | ✅ 1.93 | ✅ 0.3 % | ✅ 0 % | ✅ **100 %** | ✅ **0.2°** | ✅ 0.2° | ✅ 3.1° | 0.50 m |
| E9 seed 1 (39M) | ✅ 0.62 | ✅ 0.97 | ✅ 1.99 | ✅ 0.7 % | ✅ 0 % | ✅ **83 %** | ✅ **0.5°** | ✅ 0.4° | ✅ 3.3° | 0.28 m |
| E9 seed 2 (39M) | ✅ 0.63 | ✅ 0.98 | ✅ 1.96 | ✅ 0.5 % | ✅ 0 % | ✅ **100 %** | ✅ **0.1°** | ✅ 0.2° | ✅ 3.2° | 0.38 m |

**All 3 seeds pass all 9 goals.** Before E9, the best policy crabbed 31° and pitched 5.4°.

### Milestone 2 saved: [`progress/milestones/e9_seed2_39M_all_nine_goals/`](progress/milestones/e9_seed2_39M_all_nine_goals)
E9 seed 2 at 39M: walls 100 %, crab 0.1°, track error 0.38 m. Policy, metrics and videos.

| Walking: body points where it goes | Facing the wall: turns, returns to the line, carries on |
|---|---|
| ![](docs/media/review_38M_20261116_2207/ring_e9_seed0/walk.gif) | ![](docs/media/review_38M_20261116_2207/ring_e9_seed0/wall.gif) |

Videos (seed 0): [walk.mp4](docs/media/review_38M_20261116_2207/ring_e9_seed0/walk.mp4) · [wall.mp4](docs/media/review_38M_20261116_2207/ring_e9_seed0/wall.mp4).
Frames, wall test: ![](docs/media/review_38M_20261116_2207/ring_e9_seed0/frames_wall.png)

**Before vs. after (same camera, same test):**

| Milestone 1 (E7, crab 31°): body angled toward the ring centre | Milestone 2 (E9, crab 0.1°) |
|---|---|
| ![](progress/milestones/e7_seed0_34M_all_six_goals/walk.gif) | ![](progress/milestones/e9_seed2_39M_all_nine_goals/walk.gif) |

### What made the difference
1. **`body_alignment` + `lateral_velocity`** (anti-crab): crab 31° → 0.1–0.5° within about
   4M steps.
2. **`heading_progress`** (potential-based turning): walls held or improved (83 % → 83–100 %),
   with no freezing. It fixed E8's mistake: wobble nets zero, real turning pays.
3. **Ring look-ahead 0.6 → 0.25 rad**: removed the 17° inward pull of the steering target.
4. **`orientation` −30**: roll fell to 0.2–0.4°. Pitch is 3.1–3.3° (within ≤ 4°), so the nose is
   still slightly down; worth watching.
5. **Starting from the milestone, not E8**: kept the wall skill E8 had lost.

### E8 final (60M) for the record
Walls 17–50 %, crab 12–15° (it improved late even without an alignment reward), track error
0.07–0.10 m, walking perfect. Superseded by E9.

### Notes
- Track error is 0.28–0.50 m: good, but seed 0 is right at the 0.5 m limit. E9 trades a little
  line accuracy for the posture fix.
- Housekeeping: per-run evaluation videos are no longer committed under `progress/` (they
  duplicated `docs/media/`; about 30 MB per review). Milestone and best-seed videos are kept.

### Next
- E9 continues to 54M. The next reviews check that the gains hold (E7 showed skills can drift).
- **Stage 1 (training ring) is essentially complete.** Next is **stage 2: the obstacle course**,
  continuing from milestone 2 with the difficulty curriculum. That needs a decision on running
  it while E9 finishes, or after.

---

## Report 7: 2026-11-16, E8 backfired (dog freezes at walls); E9 launched from the milestone

### E8 at 50M steps

| Run | Pace | Trot | Shin | Falls | Walls | Track error | Crab | Roll | Pitch |
|---|---|---|---|---|---|---|---|---|---|
| E8 seed 0 (51M) | ✅ 0.60 | ✅ 1.00 | ✅ 0.1 % | ✅ 0 % | ❌ **0 %** | ✅ 0.11 m | ❌ 25° | ✅ 1.3° | ✅ 1.6° |
| E8 seed 1/2 (50M, identical runs) | ✅ 0.60 | ✅ 1.00 | ✅ 0.1 % | ✅ 0 % | ❌ **0 %** | ✅ 0.08 m | ❌ 27° | ✅ 1.6° | ✅ 1.7° |

Frames, facing the wall head-on: the dog **stands completely still** for the full 10 s.
![](docs/media/review_50M_20261116_2150/ring_e8_seed0/frames_wall.png)

**What went wrong.** E8's `turn_to_route` reward was +1 for turning toward the route and −1 for
turning away. Trotting in place makes the body wobble slightly in yaw, and half of that wobble
counted as "turning away". So the cheapest behaviour at a wall became **freezing**. Wall pass
rate fell from 17–83 % (E7) to 0 % everywhere.

**What E8 got right**
- `track_following` works: 1.2 m → **0.08–0.11 m** from the yellow line.
- Lean and tilt are now within the goals: roll 1.3–1.6°, pitch 1.6–1.7°.
- The crab improved slightly (31° → 25–27°), but nothing in E8 targets it directly.

### Change: E9 launched now, in parallel (E8 left running to finish, no restart)
- **Start point:** the E7 milestone policy (34M, walls 83 %), *not* E8. It keeps the best wall
  skill and adds the line and posture rewards on top.
- **New turn reward `heading_progress`** (potential-based) replaces `turn_to_route`. It is
  (|heading error| before − after) / dt while more than 30° off the route. Turning toward the
  route pays, and wobbling back and forth nets exactly zero, so freezing gains nothing. Unit
  test: turning for 1 s earns +0.86, standing still +0.01.
- Kept from E8: `track_following` 1.0, turn-practice 40 %.
- Posture (from report 6): `body_alignment` 1.5, `lateral_velocity` −2, `orientation` −30,
  ring look-ahead 0.25 rad.
- Amarel job 63983152, 3 properly seeded runs (seed fix verified), 34M → 54M steps (~45 min).

### Next
- Review E9 at 40M, 45M and 50M. Success: walls ≥ 80 %, crab ≤ 10°, roll ≤ 3°, pitch ≤ 4°,
  track error ≤ 0.5 m, and every walking goal.
- E8 finishes at 60M. Its final policies get reviewed, then it is closed out in the log.

---

## Report 6: 2026-11-16, the dog walks "slanted": crabbing found and E9 prepared; E8 at 45M

### What the group noticed
Watching the milestone policy, the body looked constantly slanted, with an odd drift: not
natural enough for a professional demonstration.

### What it is: crabbing (measured)
The dog walks diagonally. Its body is turned about **30° away from the direction it moves**,
with 0.4 m/s of sideways speed, and its nose is pitched down about 5°.

| Policy | Crab angle | Sideways speed | Roll | Pitch |
|---|---|---|---|---|
| E7 seed 1 at 6M (early) | −30° | −0.34 m/s | −0.9° | 0.0° |
| milestone (E7 seed 0, 34M) | **−31°** | −0.40 m/s | −2.8° | +5.4° |
| E7 seed 0 final (40M) | **−31°** | −0.40 m/s | 2.6° | 5.9° |
| E7 seed 1 final (E8 start) | **−33°** | −0.42 m/s | −2.0° | +1.5° |

It has been there since the earliest walking policies; we just never measured it. Against the new
posture goals, the milestone fails crab (31° vs ≤ 10°) and pitch (5.4° vs ≤ 4°).

**Why:**
1. No reward term checks which way the body points. Speed is measured along the direction of
   travel, so walking diagonally earns full reward. The heading term (+0.5) loses only about
   0.07/s for a 30° crab.
2. A design flaw in the ring steering target: it sits 0.6 rad ahead on the circle, about 17°
   *inward* of the travel direction, and the heading reward asks the body to face it. That pulls
   the body to angle inward.
3. The tilt penalty is too weak for small angles (5° costs about 0.008/s).

### Fix: E9 (continuation after E8, no restart)
- `body_alignment` reward 1.5: highest when the body points where it moves (10° tolerance).
- `lateral_velocity` penalty −2.0: no sideways or diagonal walking.
- `orientation` penalty −1 → −30: 5° of lean now costs about 0.23/s.
- Ring steering target 0.6 → 0.25 rad ahead: only about 7° inward.
- Keeps E8's turn reward, line following and 40 % wall practice.

A 30° crab now loses about 1.8 reward per second (of about 6.7 for a good trot).

### E8 at 45M steps (5M into the continuation)

| Run | Pace | Trot | Shin contact | Falls | Walls | Track error |
|---|---|---|---|---|---|---|
| E8 seed 0 (46M) | ✅ 0.62 | ✅ 1.00 | ✅ 0.1 % | ✅ 0 % | ❌ 0 % | ✅ **0.11 m** |
| E8 seed 1 (45M) | ✅ 0.61 | ✅ 1.00 | ✅ 0.1 % | ✅ 0 % | ❌ 33 % | ✅ **0.27 m** |
| E8 seed 2 (45M) | identical to seed 1 (see bug below) | | | | | |

(The E8 evaluations ran just before the posture metrics were added, so crab, roll and pitch will
appear from the next review.)

- **Line-following works:** distance from the yellow line fell from 1.2 m to 0.1–0.3 m within 5M
  steps.
- **Walls:** no improvement yet (0–33 %). Too early to judge E8's turn reward.
- **Bug found: E8 seeds 1 and 2 are the same run** (identical training stats). Continuations
  restored the saved random seed and ignored `--seed`. Fixed for E9 (`set_random_seed` after
  loading; verified that two seeds now train to different weights). E8 is left running
  (no-restart rule) as effectively 2 runs.

Media: E7 seed 0 final at 40M: [walk.gif](docs/media/review_39M_20261116_2143/ring_seed0/walk.gif) ·
[wall.gif](docs/media/review_39M_20261116_2143/ring_seed0/wall.gif) · [walk.mp4](docs/media/review_39M_20261116_2143/ring_seed0/walk.mp4). The crab is visible:
the body points to the inside of the ring while the dog travels along it.

![](docs/media/review_39M_20261116_2143/ring_seed0/walk.gif)

### Next
- E8 finishes at 60M (about 30 min). Then **E9** continues from the best E8 policy:
  `amarel/ring_e9.slurm`, 3 properly-seeded runs, to 80M.
- E9 success: all gait goals **and** crab ≤ 10°, roll ≤ 3°, pitch ≤ 4°, walls ≥ 80 %, track
  error ≤ 0.5 m.

---

## Report 5: 2026-11-16, E7 finished (seeds 1 and 2) + first all-goals policy + E8 launched

### Milestone: first policy that meets every Phase 1 ring goal 🎉
**E7 seed 0 at 34M steps** passes all six goals. It is saved as
[`progress/milestones/e7_seed0_34M_all_six_goals/`](progress/milestones/e7_seed0_34M_all_six_goals)
(policy + normalisation stats + metrics + videos).

| Pace | Trot | Feet down | Shin contact | Falls | Walls | Track error |
|---|---|---|---|---|---|---|
| ✅ 0.59 m/s | ✅ 0.99 | ✅ 2.0 | ✅ 0.6 % | ✅ 0 % | ✅ **83 %** (5/6) | 1.21 m (not a goal) |

Wall trials: head-on twice, +30°, −30° and +60° all passed. It turned away within about 1 s and
walked 4.1–6.1 m along the ring, never touching the wall (closest 0.64 m). It turns **both ways**
now. It failed only −60° (stuck, 0.35 m).

| Walking | Facing the wall head-on: turns away and walks off |
|---|---|
| ![](docs/media/review_34M_20261116_2128/ring_seed0/walk.gif) | ![](docs/media/review_34M_20261116_2128/ring_seed0/wall.gif) |

Videos: [walk.mp4](docs/media/review_34M_20261116_2128/ring_seed0/walk.mp4), [wall.mp4](docs/media/review_34M_20261116_2128/ring_seed0/wall.mp4).
Frames: ![](docs/media/review_34M_20261116_2128/ring_seed0/frames_wall.png)

Caveat: after turning, it walks alongside the outer wall instead of returning to the yellow
line (track error 1.2 m).

### E7 final results (40M steps)

| Run | Pace | Trot | Shin contact | Falls | Walls | Track error | Note |
|---|---|---|---|---|---|---|---|
| seed 0 | (still training, 34M → 40M) | | | | | | milestone above |
| seed 1 final | ✅ 0.59 | ✅ 1.00 | ✅ 0.1 % | ✅ 0 % | ❌ 17 % | 1.17 m | best walker, stuck at walls |
| seed 2 final | ✅ 0.48 | ✅ 0.92 | ❌ 10 % | ✅ 0 % | ❌ 17 % | 0.45 m | walking slipped late in training |

Media: `docs/media/e7_final/seed1`, `docs/media/e7_final/seed2`.

**What this tells us**
- The same reward gives very different wall behaviour per seed and per checkpoint. The skill
  appears and disappears (seed 0: 33 → 17 → 17 → 83 %; seed 1: 17 → 67 → 0 → 17 %).
  "Stop and wait at the wall" and "turn and go" earn similar reward in E7, so training drifts
  between them. A direct turning reward should make "turn and go" clearly better: that is E8.
- Long training can also erode walking (seed 2: shin contact 0.5 % → 10 % from 27M to 40M).
  Keeping milestone snapshots matters.

### What changed
- **E8 launched** (Amarel job 63982746, 3 seeds, 40M → 60M steps). It continues from **E7
  seed 1 final**, the best walker, which was stuck at walls and off the line:
  - `turn_to_route` reward 1.0
  - `track_following` reward 1.0
  - wall/turn-practice spawns 25 % → 40 %
  - walking rewards unchanged
- Fixed `--init-from` continuations keeping the 40M step count (it would have restarted the
  counter).

### Next
- Review E8 at each 5M milestone. Success: walls ≥ 80 % in both turn directions, track error
  ≤ 0.5 m, and the walking goals still passing.
- E7 seed 0 finishes 40M untouched.
- Once a policy meets all goals including track error, move to **stage 2: the obstacle
  course**, continuing from it.

---

## Report 4: 2026-11-16, ring v2 (E7) at 21–27M steps

**Status at a glance** (new column: track error = average distance from the yellow line)

| Run | Steps (eval ckpt) | Pace | Trot | Feet down | Shin contact | Falls | Walls | Track error | Overall |
|---|---|---|---|---|---|---|---|---|---|
| seed 0 | 20.9M (21M) | ✅ 0.59 m/s | ✅ 1.00 | ✅ 2.00 | ✅ 0.3 % | ✅ 0 % | ❌ 17 % | 1.14 m | walks perfectly, stuck at walls, off the line |
| seed 1 | 27.5M (27M) | ✅ 0.61 m/s | ✅ 0.99 | ✅ 2.00 | ✅ 0.2 % | ✅ 0 % | ❌ 0 % | 1.00 m | walks perfectly, stuck at walls, off the line |
| seed 2 | 27.7M (27M) | ✅ 0.60 m/s | ✅ 0.99 | ✅ 2.02 | ✅ 0.5 % | ✅ 0 % | ❌ 17 % | 0.23 m | walks perfectly on the line, stuck at walls |

**Media** (seed 0, 21M; video: [walk.mp4](docs/media/review_20M_20261116_2054/ring_seed0/walk.mp4), [wall.mp4](docs/media/review_20M_20261116_2054/ring_seed0/wall.mp4))

| Walking | Facing the wall head-on: stops about 1 m short and trots in place |
|---|---|
| ![](docs/media/review_20M_20261116_2054/ring_seed0/walk.gif) | ![](docs/media/review_20M_20261116_2054/ring_seed0/wall.gif) |

**What changed since report 3**
- No training changes (no restarts).
- E8 extended (still opt-in, off for running jobs): added a `track_following` reward after the
  group noticed later policies walking off the yellow line. Measured: seeds 0 and 1 walk
  1.0–1.4 m *outside* the line, seed 2 stays within 0.2–0.4 m.

**What's working**
- **Walking is perfect and stable on all 3 seeds:** trot match 0.99–1.00, exactly 2 feet down,
  0.59–0.61 m/s, shin contact ≤ 0.5 %, no falls.
- **No wall collisions** in the head-on, ±30° and −60° trials. The dog always stops about 1 m
  short.

**What's not working (poor progress, so tweaking)**
- **Wall turning is getting worse with training:** 33/17/67 % (report 2) → 17/67/17 %
  (report 3) → **17/0/17 %** now. The only pass left is the +60° glancing angle.
  - The policies have converged on "stop at the wall and trot in place". In E7 that is a safe
    local optimum: it keeps the alive, trot and heading rewards and avoids the wall penalties.
    Turning around has no direct payoff.
  - Seen in the viewer for seed 0 (10M): at +60° it scrapes along the wall (6–9 touches) instead
    of turning away.
- **Track drift** on seeds 0 and 1 (about 1 m outside the line). Nothing rewards being on the line.

**Next: E8 (automatic, as soon as seeds 1 and 2 finish 40M, about 25 min)**
- Continue from the best E7 final policy with no restart:
  - `turn_to_route` reward 1.0
  - `track_following` reward 1.0
  - turn-practice spawns 40 %
- Success: wall pass rate ≥ 80 % and track error ≤ 0.5 m, with all walking goals still passing.

---

## Report 3: 2026-11-16, ring v2 (E7) at 16–21M steps

**Status at a glance**

| Run | Steps (eval ckpt) | Pace | Trot | Feet down | Shin contact | Falls | Walls | Overall |
|---|---|---|---|---|---|---|---|---|
| seed 0 | 16.0M (16M) | ✅ 0.59 m/s | ✅ 0.99 | ✅ 1.98 | ✅ 0.2 % | ✅ 0 % | ❌ 17 % | 5 of 6 goals |
| seed 1 | 21.1M (21M) | ✅ 0.60 m/s | ✅ 1.00 | ✅ 2.00 | ✅ 0.4 % | ✅ 0 % | 🟡 67 % | 5 of 6 goals, best at walls |
| seed 2 | 21.2M (21M) | ✅ 0.58 m/s | ✅ 0.99 | ✅ 2.02 | ✅ 0.4 % | ✅ 0 % | ❌ 17 % | 5 of 6 goals |

**Media** (best seed: seed 1, 21M steps; video: [walk.mp4](docs/media/review_15M_20261116_2042/ring_seed1/walk.mp4),
[wall.mp4](docs/media/review_15M_20261116_2042/ring_seed1/wall.mp4))

| Walking (trot match 1.00) | Facing the wall head-on: turns away and walks off |
|---|---|
| ![](docs/media/review_15M_20261116_2042/ring_seed1/walk.gif) | ![](docs/media/review_15M_20261116_2042/ring_seed1/wall.gif) |

- seed 1 at the wall (turns): ![](docs/media/review_15M_20261116_2042/ring_seed1/frames_wall.png)
- seed 2 at the wall (now stuck; it was turning at 14M): ![](docs/media/review_15M_20261116_2042/ring_seed2/frames_wall.png)

**What changed since report 2**
- No training changes (no restarts).
- Tooling:
  - `play.py --wall-test` replays the wall test in the MuJoCo viewer.
  - Reviews now save media automatically.
- **Prepared, not yet used:** E8. An opt-in `turn_to_route` reward plus a
  `--turn-practice` spawn share (see EXPERIMENT_LOG). It is off by default, so the running jobs are unaffected.

**What's working**
- **Walking is essentially perfect on all 3 seeds:**
  - trot match 0.99–1.00, exactly about 2 feet down (a clean diagonal pair)
  - pace within 0.02 m/s of target, shin contact < 0.5 %, no falls
- **Never touching walls.** In all 18 trials the dog stopped before the wall.

**What's not working**
- **Turning away from walls is unstable.** The pass rate swaps between seeds from one
  checkpoint to the next:

  | Seed | 10–14M | 16–21M |
  |---|---|---|
  | 0 | 33 % | 17 % |
  | 1 | 17 % | 67 % |
  | 2 | 67 % | 17 % |

  Each policy learns to turn one way, then drifts. More training alone is not settling it: turning
  is paid only indirectly (heading +0.5), and only about 25 % of episodes practise it.
- Seeds 0 and 1 drift about 1 m off the track line while still walking well (track error
  1.1–1.2 m vs 0.3 m for seed 2). This is minor and not a goal yet.

**Next**
- E7 finishes at 40M steps (seeds 1 and 2 in about 25 min; seed 0 is on a slower node).
- Then, per the decision rules (wall pass rate < 50 % for most seeds), run **E8 as a
  continuation** from the best E7 final policy:
  - `turn_to_route` = 1.0 (reward for turning toward the route when facing more than 45° away)
  - turn-practice spawns 25 % → 40 %
  - walking rewards unchanged

---

## Report 2: 2026-11-16, ring v2 (E7) at 10–14M steps

**Status at a glance**

| Run | Steps (eval ckpt) | Pace | Trot | Feet down | Shin contact | Falls | Walls | Overall |
|---|---|---|---|---|---|---|---|---|
| seed 0 | 10.7M (10M) | ✅ 0.60 m/s | ✅ 0.97 | ✅ 1.88 | ✅ 0.3 % | ✅ 0 % | ❌ 33 % | 5 of 6 goals |
| seed 1 | 14.1M (14M) | ✅ 0.62 m/s | ✅ 0.97 | ✅ 1.88 | ✅ 0.3 % | ✅ 0 % | ❌ 17 % | 5 of 6 goals |
| seed 2 | 14.3M (14M) | ✅ 0.60 m/s | ✅ 0.98 | ✅ 1.92 | ✅ 0.2 % | ✅ 0 % | 🟡 67 % | 5 of 6 goals, walls close |

**Media** (best seed: seed 2, 14M steps; full-quality video:
[walk.mp4](docs/media/report2/seed2/walk.mp4), [wall.mp4](docs/media/report2/seed2/wall.mp4))

| Walking: natural trot at 0.6 m/s | Facing the wall head-on: stops, turns, walks away |
|---|---|
| ![seed 2 walking](docs/media/report2/seed2/walk.gif) | ![seed 2 wall](docs/media/report2/seed2/wall.gif) |

Frame sequences (left to right, top to bottom):
- seed 2 walking: ![](docs/media/report2/seed2/frames_walk.png)
- seed 2 at the wall (turns around): ![](docs/media/report2/seed2/frames_wall.png)
- seed 0 at the wall (stops but stays stuck): ![](docs/media/report2/seed0/frames_wall.png)

**For comparison, the failed sprinting policy (E6, ring v1 at 7M steps):** it bounds at
2.7 m/s with about 1.3 feet down and shins scraping. Video:
[walk.mp4](docs/media/e6_ring_v1_sprinting/walk.mp4)

![E6 sprinting](docs/media/e6_ring_v1_sprinting/walk.gif)

**What changed since report 1**
- No reward or setting changes. Training simply continued (no restarts, per the group decision).
- Tooling:
  - `play.py` now plays policies at real time in a loop, for watching the gait.
  - Checkpoint reviews now trigger when the slowest run passes a milestone.
- Hardware decided: keep 32-core CPU nodes. 64 cores gave the same speed (EXPERIMENT_LOG H1).

**What's working**
- **Natural walking is solved for all 3 seeds:**
  - pace within 0.02 m/s of the 0.6 m/s target
  - trot match 0.97–0.98, about 1.9 feet down (a clean diagonal pair)
  - shin contact down from 11–12 % to 0.2–0.3 %
  - 9–11 cm foot lift and no falls
- **Walls: "stop before the wall" is solved.** Across all 18 wall trials the dog never touched
  the wall once. It always stops about 1 m short.
- **Walls: "turn and keep going" is emerging on its own.** Seed 2 turns around from a head-on
  start and trots away along the track in 4 of 6 trials (`progress/ppo_ring_seed2/eval/frames_wall.png`):
  it faces the wall, turns in place for about 2 s, then walks off.

**What's not working yet**
- **Turning is still unreliable.** Seeds 0 and 1 often stand and trot in place when facing the
  wall (33 % and 17 %). Each seed tends to turn only one way: seed 1 passed only the −60° trial,
  and seed 0 only +30° and +60°. When the "easy" turn direction is the wrong one, it gets stuck.

**Next**
- Training continues to 40M steps (about 25 more minutes). Walls are improving without changes,
  so no tweak yet.
- At 40M, by the decision rules: if wall pass rate is < 50 % for the best seed, continue from
  that policy with the "turn toward the route" reward (E8).
- If the walls pass (seed 2 is close), next comes stage 2: the obstacle course, continuing from
  the best ring policy.

---

## Report 1: 2026-11-16, ring v2 (E7) at about 5M steps

**Status at a glance**

| Run | Steps | Pace | Trot | Feet down | Shin contact | Falls | Walls | Overall |
|---|---|---|---|---|---|---|---|---|
| seed 0 | 3.7M (eval of the 3M ckpt) | ❌ 0.12 m/s | ✅ 0.79 | ❌ 2.75 | ✅ 2 % | ✅ 0 % | ❌ 0 % | still learning to move |
| seed 1 | 5.3M | ✅ 0.55 m/s | ✅ 0.84 | ✅ 2.28 | ❌ 12 % | ✅ 0 % | ❌ 0 % | 4 of 6 goals |
| seed 2 | 5.2M | ✅ 0.51 m/s | ✅ 0.87 | ✅ 2.09 | ❌ 11 % | ✅ 0 % | ❌ 17 % | 4 of 6 goals |

**Media** (frames at 5M steps; no videos were recorded yet at this stage)

| Seed 2 walking | Seed 2 facing a wall: stops, then trots in place |
|---|---|
| ![](docs/media/report1/seed2/frames_walk.png) | ![](docs/media/report1/seed2/frames_wall.png) |

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
- Let E7 run to 40M steps (no restart), then apply the decision rules above (walls first).
- **Hardware:** benchmarked 32 vs 64 CPU cores: same speed (about 8,900 steps/s), because the
  network update is the bottleneck. Decision: keep 32-core CPU nodes (EXPERIMENT_LOG H1).
