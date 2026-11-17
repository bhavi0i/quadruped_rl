"""
review_checkpoint.py - checkpoint review for the PPO runs on Amarel.

    python tools/review_checkpoint.py                 # pull newest checkpoints + evaluate each run
    python tools/review_checkpoint.py --wait          # block until a run passes its next 5M milestone
                                                      # (or all jobs end), then review

For every run in obstacle_course/runs/ on Amarel it copies progress.json, config.json and the
newest checkpoint into progress/ppo_<run>/, runs obstacle_course/evaluate_policy.py on it
(gait + wall tests, contact-sheet frames), and writes progress/ppo_<run>/eval/. It prints a
table, and writes progress/latest_review.json. The PROGRESS_REPORT.md narrative and the git
commit/push are done afterwards (by Claude) so every push carries a written report.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import push_progress as pp  # noqa: E402

MILESTONE = 5_000_000
STATE = os.path.join(ROOT, "runs", "_review_state.json")
PY = sys.executable


def remote_status():
    out = pp.sh("ssh", "-o", "ConnectTimeout=20", pp.REMOTE,
                "squeue -u bpa29 -h -o %j | grep -cE 'ring|course'; cd rl_quadruped/obstacle_course/runs 2>/dev/null && "
                "for d in */; do test -f $d/final.zip && continue; "   # only runs still training
                "python3 -c \"import json,sys; h=json.load(open(sys.argv[1]))['history']; "
                "print(sys.argv[1].split('/')[0], h[-1]['timesteps'] if h else 0)\" $d/progress.json 2>/dev/null; done",
                check=False).stdout.split()
    if not out:
        return None, {}
    running = int(out[0])
    steps = {out[i]: int(out[i + 1]) for i in range(1, len(out) - 1, 2)}
    return running, steps


def wait_for_milestone(poll_min=3):
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    while True:
        running, steps = remote_status()
        # [FAILED] min over all runs: finished runs never advance, so reviews stopped once any run ended
        # [FAILED] min over runs still training: runs that continue from a later policy (E8 at 50M)
        #   hide runs at lower step counts (E9 at 34M), and runs without a progress file yet are
        #   invisible, so reviews fired on the wrong runs
        # [NEW] per-run milestones: review when every active run has passed a new 5M mark of its
        #   own since its last review (new runs get a baseline when first seen)
        if running is not None and (steps or running == 0):
            per_run = state.setdefault("runs", {})
            for r, s in steps.items():
                per_run.setdefault(r, s // MILESTONE)
            due = steps and all(s // MILESTONE > per_run[r] for r, s in steps.items())
            os.makedirs(os.path.dirname(STATE), exist_ok=True)
            if due or running == 0:
                for r, s in steps.items():
                    per_run[r] = s // MILESTONE
                json.dump(state, open(STATE, "w"))
                return steps, running
            json.dump(state, open(STATE, "w"))
        time.sleep(poll_min * 60)


def review():
    pp.pull_ppo()
    rows = {}
    done_f = os.path.join(ROOT, "runs", "_reviewed_finals.json")
    reviewed = set(json.load(open(done_f))) if os.path.exists(done_f) else set()
    active_f = os.path.join(ROOT, "runs", "_active_prefixes.json")   # e.g. ["course_c8"]
    active = json.load(open(active_f)) if os.path.exists(active_f) else None
    for run in sorted(os.listdir(pp.PPO_CACHE)):
        src = os.path.join(pp.PPO_CACHE, run)
        if active and not any(run.startswith(a) for a in active):
            continue                              # superseded line: skip the (slow) evaluation
        if run in reviewed:                       # finished run already evaluated on its final policy
            continue
        ckpts = sorted((f for f in os.listdir(src) if f.startswith("ckpt_") and f.endswith(".zip")
                        and "vecnormalize" not in f), key=lambda f: int(f.split("_")[1]))
        model = os.path.join(src, "final.zip") if os.path.exists(os.path.join(src, "final.zip")) else \
            (os.path.join(src, ckpts[-1]) if ckpts else None)
        if not model:
            continue
        dst = os.path.join(pp.PROGRESS, "ppo_" + run)
        os.makedirs(dst, exist_ok=True)
        pp.check_ppo_run(run, force=True)   # copies latest.zip / progress.json / config.json into dst
        extra = []
        cfg_f = os.path.join(src, "config.json")
        if os.path.exists(cfg_f) and json.load(open(cfg_f)).get("arena") == "course":
            # [REPLACED] evaluated at the run's *current* curriculum level. With the per-section
            #   curriculum every section sits at its ~60 % clear-rate frontier, so a full course run
            #   succeeds only ~0.6^5 = 8 % of the time by design - not comparable across reviews.
            # extra = ["--arena", "course", "--difficulty", json.dumps(prog.get("difficulty", 0.0))]
            # [NEW] fixed benchmark: every section at 0.5, 6 rubble layouts (comparable over time).
            extra = ["--arena", "course", "--difficulty", os.environ.get("COURSE_BENCH", "0.5")]
        r = subprocess.run([PY, "evaluate_policy.py", os.path.abspath(model), "--out",
                            os.path.join(dst, "eval")] + extra, cwd=os.path.join(ROOT, "obstacle_course"),
                           capture_output=True, text=True)
        print(f"== {run}  ({os.path.basename(model)})\n{r.stdout}{r.stderr[-800:] if r.returncode else ''}")
        mfile = os.path.join(dst, "eval", "metrics.json")
        if os.path.exists(mfile):
            m = json.load(open(mfile))
            hist = json.load(open(os.path.join(src, "progress.json")))["history"]
            if os.path.basename(model) == "final.zip":
                reviewed.add(run)
                json.dump(sorted(reviewed), open(done_f, "w"))
            rows[run] = dict(steps=hist[-1]["timesteps"] if hist else 0, checkpoint=os.path.basename(model),
                             goals={k: v for k, v in m["goals"].items()},
                             swing_lift_cm=m["swing_lift_cm"], speed=m["speed"],
                             wall_trials=m.get("wall_trials"))
    json.dump({"time": time.strftime("%Y-%m-%d %H:%M"), "runs": rows},
              open(os.path.join(pp.PROGRESS, "latest_review.json"), "w"), indent=1)
    save_media(rows)
    return rows


def save_media(rows):
    """Keep this review's evidence for the report: contact sheets for every seed, videos
    (mp4 + gif) for the best seed only, in docs/media/review_<steps>M_<date>/."""
    if not rows:
        return
    score = lambda r: (sum(g["passed"] for g in rows[r]["goals"].values()),
                       rows[r]["goals"].get("wall_pass_rate", {}).get("value", 0))
    course_runs = [r for r in rows if r.startswith("course")]
    # [FAILED] ranking course runs by gait goals passed picked a run stuck at the ramp for the videos
    # [NEW] course runs: rank by goal rate, then distance reached from the start
    def course_score(r):
        m = json.load(open(os.path.join(pp.PROGRESS, "ppo_" + r, "eval", "metrics.json")))
        return (m.get("goal_rate", 0), m.get("mean_progress_m", 0))
    best = max(course_runs, key=course_score) if course_runs else max(rows, key=score)
    tag = f"review_{min(r['steps'] for r in rows.values()) // 1_000_000}M_{time.strftime('%Y%m%d_%H%M')}"
    out = os.path.join(ROOT, "docs", "media", tag)
    for run in rows:
        src = os.path.join(pp.PROGRESS, "ppo_" + run, "eval")
        dst = os.path.join(out, run)
        os.makedirs(dst, exist_ok=True)
        for f in os.listdir(src):
            if f.endswith((".png", ".json")) or (run == best and f.endswith((".mp4", ".gif"))):
                shutil.copy2(os.path.join(src, f), dst)
    json.dump({"best_run": best, "runs": rows}, open(os.path.join(out, "summary.json"), "w"), indent=1)
    print(f"media saved to {os.path.relpath(out, ROOT)} (videos: {best})")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--wait", action="store_true")
    a = p.parse_args()
    if a.wait:
        steps, running = wait_for_milestone()
        print(f"milestone reached: {steps} (ppo jobs running: {running})")
    review()
