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
                "squeue -u bpa29 -h -o %j | grep -c ring; cd rl_quadruped/obstacle_course/runs 2>/dev/null && "
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
        # [NEW] min over runs still training (remote_status skips runs with final.zip)
        if running is not None and (steps or running == 0):
            low = min(steps.values()) // MILESTONE if steps else 10 ** 6
            if low > state.get("_min", 0) or running == 0:
                state["_min"] = low
                os.makedirs(os.path.dirname(STATE), exist_ok=True)
                json.dump(state, open(STATE, "w"))
                return steps, running
        time.sleep(poll_min * 60)


def review():
    pp.pull_ppo()
    rows = {}
    done_f = os.path.join(ROOT, "runs", "_reviewed_finals.json")
    reviewed = set(json.load(open(done_f))) if os.path.exists(done_f) else set()
    for run in sorted(os.listdir(pp.PPO_CACHE)):
        src = os.path.join(pp.PPO_CACHE, run)
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
        r = subprocess.run([PY, "evaluate_policy.py", os.path.abspath(model), "--out",
                            os.path.join(dst, "eval")], cwd=os.path.join(ROOT, "obstacle_course"),
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
    best = max(rows, key=score)
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
