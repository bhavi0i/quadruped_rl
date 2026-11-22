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
- **Final (60M):** walls 17–50 %, crab 12–15°, track error 0.07–0.10 m. SUPERSEDED by E9.
- **At 50M: FAILED for walls.**
  - Wall pass rate 0 % on every run. The dog freezes facing the wall.
  - Cause: the −1 side of `turn_to_route` punished the yaw wobble of trotting in place, so
    standing still became optimal.
  - Kept from E8: `track_following` WORKS (track error 0.08–0.11 m). Roll and pitch now pass
    (≤ 1.7°). Crab 25–27° (still fails).
  - Lesson: never penalise "turning the wrong way" with a signed rate. Use potential-based
    progress, where oscillation nets zero.
- **At 45M:**
  - **Track error fell from 1.2 m to 0.1–0.3 m:** `track_following` WORKS.
  - Walls 0–33 %, not improved yet.
  - Walking still perfect.
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

### E9: Natural posture + potential-based turning. WORKS (Amarel job 63983152, from E7 milestone 34M → 54M)
- **Result at 38–39M (4–5M steps in): every goal passes on all 3 seeds.**
  - crab 0.1–0.5° (from 31°), walls 83–100 %, roll 0.2–0.4°, pitch 3.1–3.3°
  - trot 0.97–0.98, 0.62–0.63 m/s, track error 0.28–0.50 m
  - Milestone 2: `progress/milestones/e9_seed2_39M_all_nine_goals/`.
  - **At 41–44M:** posture holds on all seeds (crab 0.2–0.3°). Walls drift: seed 0 100 → 67 %,
    seed 1 83 → 100 %, seed 2 100 → 0 %. Seed 2 turns away, then stands still. The wall skill
    is still not stable across checkpoints (same as E7). Candidate E10: wall-test-like spawns
    plus a "keep moving" term.
  - **At 46–50M:** walls 100 / 17 / 0 %, and seed 0 falls in 20 % of walking episodes. Posture
    still holds. This triggered E10.
  - **Finals (54M):** walls 67 % on all seeds, crab 0.1–0.7°, no falls. SUPERSEDED by E10.
  - What worked:
    - the alignment reward plus the lateral-velocity penalty (anti-crab)
    - potential-based heading progress (no freezing)
    - the closer look-ahead
    - starting from the wall-capable milestone
- **Updated plan:** E9 starts from the E7 milestone (walls 83 %), not from E8, which froze at
  walls. `turn_to_route` is replaced by `heading_progress` (potential-based, 0.5).
- **Date:** 2026-11-16
- **Why:** the group saw the walk looked slanted and unnatural.
- **Measured:** every E7 policy crabs about 30° (body turned away from the direction of travel,
  0.4 m/s sideways), with pitch up to 5–6°. This was present from the first walking policies.
- **Causes:**
  - no reward term on body direction
  - the ring steering target sits about 17° inward of travel, and the heading reward pulls the
    body toward it
  - the tilt penalty is too weak for small angles
- **New standing goals** (in `evaluate_policy.py`): crab ≤ 10°, roll ≤ 3°, pitch ≤ 4°.
- **Change:**
  - `body_alignment` +1.5: exp(−crab² / (2 × 10°²))
  - `lateral_velocity` −2.0: body-frame sideways speed²
  - `orientation` −1 → −30
  - `--ring-lookahead` 0.6 → 0.25 rad
  - keeps the E8 changes
- **How:** continue from the best E8 final policy (`amarel/ring_e9.slurm`), 3 seeds, to 80M.
- **Also fixed before E9:** continuation runs ignored `--seed` (E8 seeds 1 and 2 identical).
  `train.py` now re-seeds after loading.

### Note on E8 (bug)
E8 seeds 1 and 2 are identical runs: PPO.load restored the saved seed. E8 is effectively 2
independent runs, not 3. It was left running (no-restart rule).

### E10: Practise the exact wall situation. WORKS: STAGE 1 COMPLETE (Amarel job 63983457, from milestone 2 at 39M → 59M)
- **Date:** 2026-11-16
- **Why:** E9 walls drifted. At 46–50M: seed 0 100 %, seed 1 17 %, seed 2 0 %.
  - Trap: turning right at the wall leaves the dog facing backwards along the route, where it
    stands still.
  - The decision at the wall is rarely practised: turn-practice spawns face random directions.
- **Change (one idea):** `--wall-spawn 0.5`, so about 30 % of all episodes start 0.8–1.2 m from
  the ring wall, facing it within ±60°. All E9 rewards are unchanged.
- **Success:** walls ≥ 80 % on all seeds at consecutive reviews (stable), all other goals passing.
- **At 44–46M (first review):** all 3 seeds pass all 9 goals, with walls 100 % on every seed and
  crab 1.0–1.6°. Stability check pending at the next review.
- **At 50–52M (second review): STABLE. WORKS.**
  - All seeds still pass all 9 goals (walls 100 / 100 / 83 %).
  - **Stage 1 complete.** Final policy = milestone 3:
    `progress/milestones/e10_seed1_51M_stage1_final/`
    - walls 100 %, crab 0.1°, roll 0.3°, pitch 2.3°, trot 0.985, 0.59 m/s
    - shin contact 0.6 %, no falls, track error 0.14 m
- **Late check (56–59M):** seeds 1 and 2 still pass everything. Seed 0's final eroded (shin
  contact 18.6 %, 0.48 m/s). Lesson confirmed: select policies by evaluation (milestones), not by
  the last checkpoint.

### E11: Leg posture + uniform steps. RUNNING (Amarel job 63984256, milestone 3 at 51M → 66M)
- **Date:** 2026-11-16
- **Why:** the group saw slanted legs and uneven cadence.
- **Measured on milestone 3:**
  - stance feet 5–17 cm outside and 5–18 cm behind the hips
  - rear-left hip splayed 18°
  - step heights 15.5 / 10.0 / 9.3 / 6.5 cm, all steps timed exactly to the 0.5 s clock
- **New goals:** sideways foot offset ≤ 5 cm, fore-aft ≤ 8 cm, step-height spread ≤ 20 %.
  Milestone 3 scores 5.0 / 11.3 / 87 %.
- **Change** (E10 rewards plus three terms):
  - `foot_placement` −10 (stance feet vs the standing-pose position under the hip)
  - `hip_abduction` −2
  - `swing_shape` 1.0 (shared lift curve 8 cm × sin(π × swing progress))

- **E11 at 55–57M (4–6M in):** WEAK. fore-aft 8.2–10.2 cm, spread 66–78 %, FR still lifts
  14–15 cm. Walls 67–100 %, crab ≤ 0.7°. The terms are too small relative to the total reward.

### E12: Stronger leg-posture weights. RUNNING (Amarel job 63984516, milestone 3 at 51M → 66M, parallel to E11)
- **Change vs E11:** `foot_placement` −40, `hip_abduction` −6, `swing_shape` 3.0. Everything
  else is identical, so this is a clean comparison of the weights.

- **E12 at 55M (4M in):** WORKS for foot placement on 2 of 3 seeds (fore-aft 6.9–7.3 cm, sideways
  3.5–3.6 cm, walls 100 %). Step spread still 58–69 %: the FR leg alone lifts 13–15 cm.
  - Lesson: a bell-curve tracking reward has no gradient far from target. Pair it with a
    penalty that keeps growing.
- **E11 at 62–66M:** fore-aft 8.0–9.9 cm, spread 25–62 %. Seed 0's final falls 40 %.

### E13: Swing-overshoot penalty. RUNNING (Amarel job 63984883, from E12 seed 2 at 55M → 70M)
- **Change vs E12:** `swing_overshoot` −1000: sum of max(0, lift − 10 cm)² over the feet. It keeps
  growing (about 1.25/s at 15 cm) where `swing_shape` has no gradient.

- **E12 at 62–63M:** seeds 0 and 1 pass all 12 goals (fore-aft 5.1 cm, spread 11–13 %). The FR
  high-step faded with more training. Seed 2 falls 20 %.
- **E13 at 60–63M: WORKS.** Step spread 6–8 % on every seed. Seed 2 at 63M passes all 12 goals
  (fore-aft 4.3 cm, splay 2.2 cm, spread 6 %, walls 100 %, roll 0.8°, pitch 0.6°). Seed 1 falls
  40 %. Stability check pending.

- **Stability review (65–69M):** all 6 E12/E13 runs pass all 12 goals. **Milestone 4 = E12 seed 1
  final (66M)**, `progress/milestones/e12_seed1_66M_final_walking/` (passed at two consecutive
  reviews). **Walking stage COMPLETE.**

### C1: Stage 2, obstacle course (healthy robot). RUNNING (Amarel job 63985544, from milestone 4 at 66M → 126M)
- **First review (67–68M, difficulty 0):**
  - Clears rubble and hurdles (9.5 m) in most runs from the start (baseline 0.1 m).
  - Stops at x ≈ 9.2–9.5 m, before the ramp: turns 45° and stands. Not touching a wall.
  - Gait degraded on the course (roll/pitch 8–12°, shin contact 22–32 %).
  - Distance per episode 3.4 m (< 5 m threshold), difficulty 0.
  - Candidate tweak if it persists: pre-ramp and pre-stairs spawns.
- **At 70M (4–5M in):** still stuck at the ramp foot in every run. Rubble and hurdles reliable (no
  falls). Gait on the course: trot 0.66, shin contact 24 %, roll/pitch up to 8–9°.

### C2: Course with run-up spawns (bug fix). RUNNING (Amarel job 63985737, from C1 seed 1 at 70M → 130M)
- **Bug (original course code):** spawn = section start + 0.8 m put ramp and stairs spawns *on*
  the obstacle (10.0 vs ramp foot 9.6; 15.0 vs first step 14.6). Stepping onto them from flat
  ground was never trained.
- **Change (one idea):** `--spawn-offset 0.15`. All feet are on the flat run-up before each
  obstacle (verified). Rewards are unchanged from C1.
- **At 76–80M:** C1 and C2 all stop at x = 9.61–9.69 m (ramp foot). Spawns alone did not help.
  - Investigation (see PROGRESS_REPORT report 21) ruled out: ramp geometry, reward balance
    (walking 6.3/s vs stuck 2.5/s), determinism, observation saturation and action saturation.
  - **Root cause: exploration collapse** (log std about −2.8, i.e. ±0.06; `ent_coef` was 0).

### C3: Exploration reset. RUNNING (Amarel job 63986078, from C2 seed 1 at 86M → 140M)
- **Change:** `--reset-log-std -1.2` (noise about ±0.3) and `--ent-coef 0.002`. Everything else as C2.
- **Note:** the init file is named `c2s1_78M.zip` on Amarel but is the 86M checkpoint (the newest at
  copy time).
- **Lesson:** with `ent_coef = 0`, long PPO training makes the policy nearly deterministic. New
  skills in a later stage need exploration restored.
- **At 89M (3M in):**
  - Training falls 100 % → 18–27 % after the reset; goal reached in 12–14 % of training
    episodes.
  - Course from the start: 9.8–10.1 m. It now steps onto the ramp (C1/C2 stuck at 9.6–9.7).
  - log std about −1.28 (holding).
- **At 90M: FIRST COURSE COMPLETION.**
  - C3 seed 1 reaches the goal from the start 3/3 (44.7–55.5 s, no falls) at difficulty 0.
  - Milestone: `progress/milestones/c3_seed1_90M_first_course_completion/`.
  - Gait on the course: crab 2.4°, roll/pitch ≤ 1.5°, feet under hips ✅. Shin contact 46 % and
    step spread 93 % ❌.
  - Curriculum advanced to difficulty 0.2.
  - C1/C2 mostly still stuck (C2 seeds 1–2 reach 10.3–10.9 m).
  - **The exploration reset was decisive.**
- **At 100M:**
  - C3 curriculum at 0.3.
  - C3 seed 1: goal 1/3 at its difficulty; it falls at the first stair in 2/3.
  - Seeds 0 and 2 stall on the steeper ramp.
  - Shin contact rising to 49–62 %; training falls 18–30 %.
  - No change yet (curriculum dip). Candidate: course-gait tweak (obstacle swing height, or a
    shin-edge collision penalty).
- **At 111M:**
  - Difficulty 0.3–0.4. Seed 0 reaches the stairs 3/3 (14.9–17.3 m) but stalls or falls.
  - No completions; shin contact 46–66 %. This triggered C4.

### C4: Course gait for obstacles. RUNNING (Amarel job 63986196, from C3 seed 0 at 111M → 170M)
- **Changes:** `--swing-height 0.10` (8 → 10 cm) and `collision` −2 → −4. Ent 0.002 kept, no reset.
- **Note:** the curriculum restarted at 0 (job default); `DIFF` was added for future continuations.
- **At 115–124M:**
  - C4 re-climbed to difficulty 0.4. Evaluation stalls at the rubble end, the upper ramp or the
    first stair; random actions stall too (10.4–10.9 m).
  - Trace: the dog slides backwards on the 9° ramp (speed +0.45 / −0.65 m/s).

### BUG: Contact friction (affects E1–E13 and C1–C4)
- **Cause:** the E4 merge copied the course's pyramidal cone / impratio 1 into the Go1 spec,
  overriding the Menagerie elliptic / impratio 100.
- **Measured:** a Go1 standing on the 9° ramp slides 56 cm in 3 s (pyramidal) vs 3.5 cm then
  stable (elliptic). Same sim speed.
- **Fix:** `friction_model` option (course.py, env, train, evaluate); `elliptic` from C5 on.
  The default is kept as `pyramidal` so running jobs stay consistent. The old line is kept with a
  `[FAILED]` note in `course.py`.
- **Impact:** walking results are on flat ground and effectively unaffected. Course climbing was
  blocked by it.

### C5: Realistic friction. RUNNING (Amarel job 63987102, from C4 seed 1 at 124M → 190M)
- **Changes:** `--friction-model elliptic`, curriculum starting at `DIFF=0.4`. Otherwise as C4.
- **At 131–135M (about 7M in):** still stalls about 10.75 m (upper ramp). Shin contact 63–78 %,
  crab 19–26°. Pitch only 1.5–2.6° on a 9° ramp: the body is held level.

### C6: Terrain-relative body tilt. RUNNING (Amarel job 63987272, from C5 seed 1 at 135M → 195M)
- **Cause:** E9's `orientation` penalty (−30) is relative to gravity. On slopes it forces a
  horizontal body (front legs long, rear legs crouched), so rear shins hit the ramp and calf
  motors saturate.
- **Change (one idea):** `--terrain-relative-tilt`. Penalise roll² + (pitch − ground pitch)², with
  the ground pitch from heights ±0.3 m along the heading. Verified 0 for "parallel to ground" on
  up, flat and down slopes.
- Everything else as C5.
- **At 141–148M:** crab back under 10° (2–8°). Still stalls at 10.74–10.86 m (upper 9° ramp) like
  C3–C5.
  - Trace: rocking ±0.5 m/s per half-stride. Geometry, friction, motor load, reward balance and
    exploration all checked and fine.

### C7: Per-section curriculum. RUNNING (Amarel job 63987554, from C6 seed 1 at 149M → 209M)
- **Why:**
  - The global curriculum (+0.1 when mean distance > 5 m) stalled at 0.4 for 35M steps. The ramp
    alone froze every section.
  - 8° → 9° was too big a step.
- **Change:** `--section-curriculum`.
  - Separate difficulty per section; ±0.05 by clear rate over the last 100 attempts (≥ 60 % up,
    < 20 % down).
  - `course.course_xml` accepts a per-section dict.
  - The env reports `section_results` at episode end; evaluation accepts a JSON difficulty.
- Otherwise as C6.
- **At about 152–155M:**
  - Section levels: rubble/hurdles 0.6–0.75 ↑, slalom 0.45–0.5, ramp 0.05–0.2 ↓ (clear 0–13 %),
    stairs 0.15–0.25 ↓ (clear 0–5 %).
  - Trace: stalls 0.5 m below the crest even at 5.5°.

### FINDING: Wrong parent branch for C4–C7
- C4 continued from C3 seed 0 (chosen because it "reached the stairs" at the 111M review). It
  never mastered the ramp.
- C3 seed 1 final (140M) clears the ramp at 5/7/9° (2/2 each with slippery physics; with
  realistic friction 2/2, 2/2, 1/2). It reaches the goal at difficulty 0.3, and gets past the 15°
  ramp at difficulty 1.0 once.
- Lesson: choose continuation parents by targeted skill tests.

### C8: Climbing lineage + verified fixes. RUNNING (Amarel job 63987675, from C3 seed 1 final at 140M → 210M)
- **Fixes applied:** elliptic friction, terrain-relative tilt, section curriculum (start 0.3).
- **Not applied:** C4's swing 0.10 and collision −4.
- Ent 0.002, run-up spawns.
- **At about 148–152M (8–12M in): WORKS.**
  - Seed 0 levels: hurdles, ramp and slalom 1.0; rubble 0.75–0.85; stairs 0.5–0.55.
  - From the start at those levels: goal 1/3 in 55.2 s.
  - Milestone: `progress/milestones/c8_seed0_152M_full_ramp_hurdles_slalom/`.
  - Remaining issues: rubble-entrance stalls, stairs height, shin contact about 72 %.
- **At 161–169M:** rubble, hurdles and slalom 1.0 on all seeds. Ramp 0.25–0.7 (oscillating),
  stairs 0.15–0.45.
  - **Eval fix:** course test over 6 rubble layouts (one fixed layout was misleading: the same
    policy reached the goal on layout 3 and fell early on 0 and 2).
  - Reviews evaluate only active prefixes (`runs/_active_prefixes.json` = `["course_c8"]`).
- **At 160–171M (6-layout test):** seed 1 reaches the slalom 2/6 and the stairs 3/6, no falls.
  - With 120 s: rubble about 7 s, hurdles about 15 s, then the ramp takes 40–100 s or never
    crests (11.0 m). The ramp crest (11° at level 0.6) is the bottleneck.
  - Candidate C9: mid-ramp spawns.
- **At 165–182M:** the ramp level oscillates (e.g. seed 0: 0.3 → 1.0 → 0.45; seed 1: 0.7 → 0.2 →
  0.85). Course runs mostly stop at the crest. This triggered C9.

### C9: Mid-ramp spawns (crest practice). RUNNING (Amarel job 63988748, from C8 seed 1 at 182M → 242M)
- **Change (one idea):** `--ramp-spawn 0.25`, 25 % of spawns at x ∈ [10.0, 11.4] on the ramp,
  pitched to the slope. They are not counted as ramp attempts by the section curriculum.
- **Start levels:** C8 seed 1's {rubble 1, hurdles 1, ramp 0.85, stairs 0.55, slalom 1}.
- **Infra:** `--difficulty` accepts JSON; the job script quotes `$DIFF` (the first launch failed
  on word-splitting).
- **At about 186–191M:** ramp level 0.85 → 0.45–0.6. Benchmark 0.5: seed 2 0/6 (crest stalls). No
  benefit yet.

### METHOD FIX: Course evaluation at a fixed benchmark
- At the curriculum frontier each section clears about 60 %, so a whole-course run succeeds about
  8 % by design. Reviews now evaluate course runs at a fixed `COURSE_BENCH` (0.5) over 6 layouts.
- **Ramp diagnosis:**
  - C8 seed 1 clears 5/7/9/11° ramps 3/3 from the run-up, and 19/20 from off-centre or yawed
    starts.
  - Crest stalls were frontier/variance effects.
- **C8 seed 1 at 193M on the benchmark:** goal 2/6 (39.6 s, 49.7 s); rubble stalls 3/6.
  Milestone `progress/milestones/c8_seed1_193M_bench05_2of6/`.

### C9 result: no benefit
- At about 193–195M on the benchmark: 0/6 on all seeds, mostly stalling at the ramp crest.
- Mid-ramp spawns did not transfer to cresting from a full climb. FAILED (kept as an option).

### C10: Weighted section practice. RUNNING (Amarel job 63989189, from C8 seed 1 at 195M → 255M)
- **Why:** on the benchmark, C8 seed 1 stops at the stairs 3/6 and the rubble 1/6.
- **Change (one idea):** `--section-weights {"stairs": 3, "rubble": 2}` (verified about 35 % stairs,
  20 % rubble spawns).
- Start levels: C8 seed 1's {rubble 1, hurdles 1, ramp 0.65, stairs 0.55, slalom 1}.
- **At 200–206M (5–10M in): WORKS (best line).**
  - Benchmark: seed 1 2/6 (55.2, 56.8 s), seed 2 1/6 (34.7 s), seed 0 0/6 → 3/18. C8 and C9:
    0/36.
  - Milestone: `progress/milestones/c10_seed1_200M_bench05_2of6/`.
  - Note: C8 seed 1 final (210M) fell to 0/6 (late drift).
- **At 205–214M review:** 0/18 (checkpoint variance).
- **Sweep of 54 checkpoints (196–218M):** max 2/6 (6 checkpoints), 1/6 ×7, 0/6 ×41.
  - Goals on every layout.
  - Non-goal stops: ramp 127, stairs 106, rubble 48.
  - Best checkpoints stop at the stairs (15.15 m): rear feet stub into the riser.

### TOOL: Checkpoint sweep
- `tools/checkpoint_sweep.py` + `amarel/sweep.slurm`: parallel benchmark evaluation of every k-th
  checkpoint (32 cores, about 10 min for 54 checkpoints).
- Use it to pick final policies (late drift and checkpoint variance make single reviews
  unreliable).

### C11: Feet-stumble penalty. RUNNING (Amarel job 63989827, from C10 seed 0 at 198M → 258M)
- **Change (one idea):** `feet_stumble` −1.0 (feet with |F_xy| > 2 |F_z| and > 1 N).
- Unit test: 0 on flat ground, 2 when front feet are pushed into the riser.
- First version subtracted the number of feet without contact (bug); fixed before launch.
- **At 200–207M (2–4M in): WORKS.**
  - Levels: ramp 0.7–0.95, stairs 0.6–0.75 (C10: 0.3–0.65 / 0.3–0.55). Stairs clear 51–58 %.
    Goal rate 30–33 %.
  - Benchmark: seed 2 2/6 (32.8 s, 50.1 s). 6/18 C11 runs reach the slalom.
  - New bottleneck: the slalom (possible stage-1 "stop at walls" habit). Training falls up to
    38–46 %.
  - Milestone: `progress/milestones/c11_seed2_200M_bench05_2of6/`.
- **At 206–212M:**
  - Seed 0 **3/6** (43.3/46.7/54.3 s); seeds 1–2 1/6 each → 5/18. Stops: stairs ×8, rubble ×3,
    slalom ×1.
  - Training falls 16–33 %.
  - Milestone: `progress/milestones/c11_seed0_212M_bench05_3of6/`.
  - Slalom tweak (C12) deferred: C11 is still improving.
- **Sweep of 65 checkpoints (199–225M, benchmark 0.5, 6 layouts):** 5/6 ×2, 4/6 ×15, 3/6 ×11,
  ≤ 2 ×37.
  - All seeds peaked at about 202–214M; seeds 0 and 1 collapsed to 0/6 after about 212–214M.
- **Validation on 12 layouts:**
  - C11 seed 2 at 214M: 9/12 at 0.5, 1/12 at 0.75, 0/12 at 1.0.
  - C11 seed 0 at 207M: 8/12, 2/12, 0/12.
- **STAGE 2 BENCHMARK MET** (≥ 67 % at 0.5).
  - Milestone: `progress/milestones/STAGE2_c11_seed2_214M_bench05_9of12/` (fastest crossing
    31.1 s).
  - Full difficulty not met: stops at the full stairs and the 15° ramp.

### C12: Lower learning rate for the full-difficulty push. RUNNING (Amarel job 63990557, from the stage-2 milestone at 214M → 274M)
- **Change (one idea):** `--learning-rate 1e-4` (from 3e-4), against the post-peak collapse.
- Curriculum starts at the milestone's levels {ramp 1.0, stairs 0.75, others 1.0}. Otherwise as
  C11.
- **At 220–228M:** benchmark 5/18 then 4/18 (best seed 2: 3/6, then 2/6). No collapse so far.
  11/14 failures stop at the stairs (15.1 m).

### C13: Terrain-aware swing lift. RUNNING (Amarel job 63991604, from C12 seed 2 at 232M → 292M)
- **Why:** `swing_shape` measured lift above the ground under the foot. Near a riser the old reading
  was 11.5 cm, but relative to the next step it was only 2.5 cm (48 % under 3 cm), so the reward
  fought `feet_stumble`.
- **Change (one idea):** `--terrain-aware-swing`. Swing lift = foot height − max(ground under foot,
  ground 12 cm ahead along the heading).
- Learning rate 1e-4; otherwise as C12.
- **At 235–237M (3–5M in):**
  - Seed 0 **4/6** (31.9–51.3 s), seed 1 2/6, seed 2 0/6 (stairs ×4).
  - Milestone: `progress/milestones/c13_seed0_237M_bench05_4of6/`. Sweep at 0.5/0.75/1.0
    pending.
- **At 240–246M:**
  - Results: seed 0 2/6, seed 1 1/6, seed 2 1/6. 13 of 18 runs stopped at the first stairs
    steps (x ≈ 15.15).
  - Training stairs clear rate 0.26–0.31 at stairs difficulty 0.65–0.7.
  - Peak-then-drop again, so pick by sweep. Next lever if flat: stair-step spawns /
    terrain-relative body height.
- **At 253M:**
  - Seed 0 **5/6** (stairs 5/5; one rubble stall), seed 1 1/6, seed 2 0/6.
  - Milestone: `progress/milestones/c13_seed0_253M_bench05_5of6/`.
  - Validation at 0.5/0.75/1.0 (12 layouts) and a full C13 sweep:
    `amarel/validate_c13.slurm`, job 63992889.
- **Validation result (12 layouts):**
  - Best 5/12 at 0.5, ≤ 1/12 at 0.75, 0/12 at 1.0. The 253M "5/6" scored 3/12.
  - **FAILED to beat the stage-2 milestone (9/12).**
  - Single 6-layout reviews are too noisy to pick policies; use validation.

### C14: Motion-gated gait rewards + double progress. RUNNING (Amarel job 63993445, from the stage-2 milestone C11 seed 2 at 214M → 274M)
- **Why (diagnosis, `tools/stall_diagnosis.py`):** at full difficulty the policy trots in place
  halfway up the 15° ramp. That earns +0.053/step vs +0.013/step for walking over rough
  ground.
  - trot, heading, foot_clearance, swing_shape and feet_air_time were paid at zero speed.
  - Orientation and collision costs only apply when moving.
  - Not slipping, not torque-limited (4 % saturation).
  - Stalling at any hard obstacle was a stable local optimum. This explains the plateau since
    C8.
- **Change:**
  - `--motion-gate 0.5`: the five gait terms are scaled by
    `clip(v_fwd / (0.5·target_speed), 0, 1)`.
  - `progress` 2 → 4 (still capped at target speed). With the gate alone the stall still paid
    +0.007 vs +0.003 walking.
- **Unchanged:** as C13 (terrain-aware swing, lr 1e-4, section weights stairs 3 / rubble 2,
  ent_coef 0.002, start difficulty ramp 0.85 / stairs 0.65 / others 1.0).
- **Success test:** validation (12 layouts) beats 9/12 at 0.5, and > 0/12 at 0.75 and 1.0,
  with the trot and posture goals intact.
- **At 222–227M (8–13M in):**
  - The curriculum reached **ramp 1.0 and stairs 1.0 on all seeds** within ~2M steps (stuck
    at ramp ≤ 0.95 / stairs ≤ 0.75 since C8).
  - Training goal rate 0.39–0.53 (was 0.15–0.25); speed 0.30–0.35 m/s (was 0.13).
  - Costs: fall rate 0.38–0.49 (was 0.20), trot 0.72–0.73 (was 0.82).
  - Benchmark 0.5: 4/6, 2/6, 4/6.
  - **Stall fix CONFIRMED in training.** Validation job 63994608 (`amarel/validate.slurm`,
    0.5/0.75/1.0 × 12 layouts).
- **Validation (job 63994608, 12 layouts):**
  - Seed 0 222M: **11/12 · 9/12 · 7/12** at 0.5 · 0.75 · 1.0.
  - Seed 1 226M: 8 · 7 · **9/12**. Seed 2 228M: 10 · 9 · 7.
  - **First full-difficulty crossings of the project. SUCCESS.**
  - New stage-2 milestone: `progress/milestones/STAGE2b_c14_seed0_222M_full_course_7of12/`.
  - Remaining full-difficulty failures, all checkpoints: stairs 53, rubble 51, slalom 25,
    hurdles 19, ramp 9.
  - Gait on the course: trot 0.71, contact 0.50, fore-aft 11 cm. A quality pass is needed.
  - Lesson: **a reward paid at zero speed creates a stall attractor.** One diagnosis
    (`tools/stall_diagnosis.py`) beat ~100M steps of curriculum and spawn tweaks (C8–C13).
- **At 230–240M:**
  - Benchmark 0.5: 4/6, 5/6, 4/6.
  - Training at full difficulty: goal 0.58–0.65, falls 0.28–0.36 (falling), stairs 0.76–0.80.

### METRIC BUG: "body contact" counted foot-adjacent calf grazes (affects all E and C runs)
- **Found by** `tools/contact_audit.py`: the Menagerie Go1 lower calf capsule ends ~1 cm from
  the foot sphere, ~3 mm above the ground with the foot planted.
- **Grazes** (calf contact < 4 cm from a foot): rubble 0.96, other sections ~0.2, stage-1 policy
  on flat ground 0.11.
- **Real shin/thigh/torso hits:** hurdles 0.11, stairs 0.01, else 0. Overall 0.4 %.
- **Fix:**
  - metric `shin_contact_rate` replaces the `body_contact_rate` goal; the old metric is kept and
    commented
  - env option `foot_graze_radius` (default 0 = old behaviour) excludes grazes from the
    collision penalty
  - env info `shin_contacts`

### C15: Ignore foot-adjacent calf grazes in the collision penalty. RUNNING (Amarel job 63995150, from STAGE2b milestone C14 seed 0 at 222M → 282M)
- **Why:**
  - The collision penalty charged ~−2.6/s for unavoidable grazes in rubble, the largest single
    reward term while walking there.
  - Rubble is the #2 full-difficulty failure.
  - The long fore-aft stance (11 cm) may be graze avoidance.
- **Change (one idea):** `--foot-graze-radius 0.04`. Everything else as C14, curriculum starting
  at 1.0.
- **Success test:**
  - validation at 1.0 > 7/12, fewer rubble failures
  - trot ≥ 0.75, fore-aft ≤ 8 cm, shin contact ≤ 0.05

### C16: Course-adaptive reward (group request). RUNNING (Amarel job 63995822, from STAGE2b milestone C14 seed 0 at 222M → 282M)
- **Why:**
  - Group feedback: the crossing looks aimless.
  - `tools/path_audit.py` on the stage-2 policy at 1.0: rubble 30.7 s/run with 70 % hesitation,
    32 % backing up and a path 3.3× the forward distance.
  - Hurdles and stairs: about a third hesitating, a fifth backing up.
  - Hind-knee bend −80 to −84° on every section (no adaptation).
  - Friction ruled out: μ 0.8/1.0, elliptic; no sliding in the ramp trace.
- **Changes (a package, by group decision; C15 = graze-only control):**
  - `--obstacle-style 0.25`: trot, swing_shape, swing_overshoot, foot_placement, hip_abduction,
    base_height, lin_vel_z and ang_vel_xy at ¼ weight for 2.2 ≤ x < 18.7.
  - `alive` −0.5 (time cost).
  - New `backward` term −2.0.
  - `feet_stumble` −3, `wall_proximity` −2.
  - `--foot-graze-radius 0.04`.
  - Section weights rubble 3 / stairs 3 / hurdles 2; ent_coef 0.003.
  - Curriculum from 1.0.
- **Success test:**
  - path audit: rubble < 10 s; hesitation and backing < 15 % per section; path ratio < 1.3;
    hind-knee adaptation
  - validation at 1.0 ≥ 7/12; shin contact ≤ 0.05; trot ≥ 0.75 on flat sections
- **At 225–228M (3–6M in), path audit of seed 0 vs baseline:**
  - rubble 17.0 s vs 30.7 s; backing up 12 % vs 32 %; path ratio 1.39 vs 3.29
  - stairs 3.7 s vs 6.6 s
  - hind knee −90° on the ramp vs −82° on flat ground: first per-section adaptation
  - Worse: ramp time 6.9 s, hurdle hesitation 35 %, slalom wall touches 1.8 %, training falls
    0.40–0.49.
  - Benchmark 0.5: 3/6, 4/6, 1/6.
- **C15 at 227–235M:**
  - Seed 1 **5/6, trot 0.761** (the first course policy to pass the trot goal).
  - Rubble 18.7 s, path ratio 1.54; stairs worse (12.5 s).
- **Finals (282M) / latest, benchmark 0.5:**
  - C16: seed 1 **6/6**, seed 0 5/6, seed 2 2/6 at 273M.
  - C15: seeds 0/1/2 3/6, 4/6, 4/6.
  - Training falls: C15 0.27–0.28, C16 0.39–0.47.
  - Validation job 64000968 (`results/validate_c15_c16.json`).
- **Validation result:**
  - C16 s1 281M **9/10/9**; C15 s2 239M 9/8/**12**; C16 s1 266M 9/11/8; C15 s0 248M 10/8/9
    (of 12 at 0.5/0.75/1.0).
  - **New course policy: C16 seed 1 at 281M** (`progress/milestones/STAGE2c_c16_seed1_281M_full_9of12/`).
- **Path audit vs baseline (rubble):** 16.0 s vs 30.7 s; backing up 10 % vs 32 %; path ratio
  1.36 vs 3.29.
- **Not met:**
  - per-section posture (hind-knee range ≤ 7°)
  - hesitation on hurdles and stairs 30–40 %
  - course gait: trot 0.72, crab 10.3°
- **Conclusion:** relaxing the style terms reduced aimless shuffling (PARTIAL SUCCESS) but did
  not by itself produce section-specific gaits.

### METHOD: cross-platform non-determinism
- The same checkpoint, layouts and seeds give different outcomes on Amarel (x86) vs the Mac
  (ARM): C16 s1 281M 5/6 vs 2/6 on layouts 0–5.
- Chaotic contact dynamics amplify floating-point differences.
- **Rule:** success rates only from many episodes on Amarel; local runs for videos and path
  shape.

### C17a / C17b: slower, longer stride + foot-level sensing (+ robustness in C17b). RUNNING (Amarel jobs 64147223 / 64147224, from C16 seed 1 at 281M → 341M)
- **Why (group review 2026-11-22 + path audit with cadence/stub counts):**
  - 12–15 touchdowns/s vs 8 expected; strides 10–20 cm on obstacles.
  - Foot stubs: 27/s on stairs, 2.2/s at hurdles.
  - The body-centred height scan cannot locate the feet relative to edges.
  - Brittle outcomes (report 52); no domain randomization.
- **Changes:**
  - `--gait-period 0.7` (was 0.5), `--target-speed 0.5` (was 0.6).
  - `--foot-scan`: +16 obs; network expanded with zero-weight columns by `tools/expand_obs.py`,
    actions identical at start.
  - C17b adds `--randomize`: friction ×U(0.7, 1.3), torso payload U(−0.5, 1.5) kg, motor
    strength ×U(0.9, 1.1), 0.3 m/s shove every 150–300 steps.
  - Otherwise C16 settings.
- **Evaluation tools** now read `gait_period`, `target_speed` and `foot_scan` from the run config.
- **Success test:**
  - flat touchdowns ≤ 7/s; strides ≥ 30 cm on flat ground, ≥ 25 cm at hurdles
  - hurdle stubs < 0.5/s, stair stubs < 5/s; hesitation and backing < 15 %
  - validation at 1.0 ≥ 9/12

### C18: Soft, damped joints by schedule (+ all of C17b). RUNNING (Amarel job 64147596, from C16 seed 1 at 281M, foot-scan-expanded → 351M)
- **Why:**
  - The Menagerie Go1 actuators are kp 100, kd 0 (passive damping 1–2).
  - Gain test on the course policy: touchdowns 12.7/s at kp 100 vs 9.5 at kp 50 and 6.5 at
    kp 35, but the policy falls at kp ≤ 50 because it was trained stiff.
  - Real Go1 walking controllers use kp 20–40, kd 0.5–1.
- **Change:** `--pd-schedule 281e6,30e6,100,40,0,1.0`.
  - `PDScheduleCallback` calls `env.set_pd()` each rollout.
  - The gains survive model rebuilds.
  - Randomization multiplies them ×0.9–1.1.
- **Evaluation:** tools use `pd_for(cfg, checkpoint)` to apply the matching gains.
- **Success test:** the C17 tests, plus touchdowns ≤ 7/s and visibly smoother legs in the viewer.

- **Group instruction:** start at the beginning of the course and learn to reach the end
  checkpoint.
- **Baseline:** the ring policy at the course start (difficulty 0) moves 0.1 m and falls 3/3.
- **Prerequisite fixes:**
  - course episodes 60 s (`--max-steps 3000`)
  - course test in `evaluate_policy.py` (goal rate, progress, sections, video)
  - reviews evaluate course runs at their curriculum difficulty
- **Setup:**
  - `amarel/course_ppo.slurm`: curriculum from difficulty 0, +0.1 when mean distance > 5 m
  - random section-start spawns
  - gait rewards kept, `swing_shape` 0.5

---

## Open questions and ideas
- If the trot match stays low in E7, raise `trot` further or add a feet-down-count term (2 feet).
- Shin contact: if it persists, check the calf collision capsules against the ground clearance
  at the default pose.
- Course stage: start from the best ring policy. Watch whether the trot clock helps or hurts on
  stairs and hurdles; the gait period may need to vary.
- Phase 2: injured-leg evaluation on the course. Distance reached, finish rate and falls per
  injured leg.
