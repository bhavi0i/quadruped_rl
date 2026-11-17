"""Every few minutes, pull small training artifacts from Amarel and push a progress
snapshot to GitHub each time a run passes another 500k-step milestone.

python tools/push_progress.py                       # loop forever (Ctrl-C to stop)
python tools/push_progress.py --once                # single check

Per run, progress/<run>/ gets: best_model.zip, config.json, evaluations.npz,
learning_curve.csv, gait.json (healthy gait + speed of the current best policy) and,
when training has finished, healthy_policy.zip and the damage evaluation JSON.
Replay buffers and checkpoints stay on Amarel (too large for GitHub).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

import numpy as np

REMOTE = "bpa29@amarel.rutgers.edu"
REMOTE_DIR = "rl_quadruped"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "runs", "_amarel")
PROGRESS = os.path.join(ROOT, "progress")
MILESTONE = 500_000
PY = sys.executable


def sh(*cmd, check=True, **kw):
    return subprocess.run(cmd, check=check, text=True, capture_output=True, cwd=ROOT, **kw)


def pull():
    os.makedirs(CACHE, exist_ok=True)
    sh("rsync", "-a", "--prune-empty-dirs",
       "--include=phase1_*/", "--include=best_model.zip", "--include=healthy_policy.zip",
       "--include=config.json", "--include=evaluations.npz", "--exclude=*",
       f"{REMOTE}:{REMOTE_DIR}/runs/", CACHE + "/", check=False)
    sh("rsync", "-a", f"{REMOTE}:{REMOTE_DIR}/results/", os.path.join(CACHE, "_results") + "/", check=False)


def check_run(run):
    src, dst = os.path.join(CACHE, run), os.path.join(PROGRESS, run)
    ev = os.path.join(src, "evaluations.npz")
    if not os.path.exists(ev) or not os.path.exists(os.path.join(src, "best_model.zip")):
        return None
    d = np.load(ev)
    steps = int(d["timesteps"][-1])
    finished = os.path.exists(os.path.join(src, "healthy_policy.zip"))
    state_f = os.path.join(dst, "state.json")
    state = json.load(open(state_f)) if os.path.exists(state_f) else {"milestone": 0, "finished": False}
    milestone = steps // MILESTONE
    if milestone <= state["milestone"] and finished <= state["finished"]:
        return None

    os.makedirs(dst, exist_ok=True)
    for f in ("best_model.zip", "config.json", "evaluations.npz", "healthy_policy.zip"):
        if os.path.exists(os.path.join(src, f)):
            shutil.copy2(os.path.join(src, f), dst)
    rewards, lengths = d["results"].mean(1), d["ep_lengths"].mean(1)
    with open(os.path.join(dst, "learning_curve.csv"), "w") as f:
        f.write("timesteps,eval_return,eval_episode_length\n")
        f.writelines(f"{t},{r:.1f},{l:.0f}\n" for t, r, l in zip(d["timesteps"], rewards, lengths))
    dmg = os.path.join(CACHE, "_results", f"{run}_damage_eval.json")
    if os.path.exists(dmg):
        shutil.copy2(dmg, dst)

    gait_f = os.path.join(dst, "gait.json")
    out = sh(PY, "evaluate.py", os.path.join(dst, "best_model.zip"), "--healthy-only",
             "--episodes", "3", "--out", gait_f, check=False)
    g = json.load(open(gait_f))["results"]["healthy"] if out.returncode == 0 else {}
    summary = (f"{run} @ {steps / 1e6:.2f}M steps: best eval return {rewards.max():.0f}"
               + (f", {g['speed_mean']:.2f} m/s, trot match {g.get('trot_match', float('nan')):.2f}, "
                  f"falls {g['fall_rate']:.0%}" if g else "")
               + (" [FINISHED]" if finished else ""))
    json.dump({"milestone": milestone, "finished": finished, "steps": steps}, open(state_f, "w"))
    return summary


def git_push(summaries):
    sh("git", "add", "progress")
    if sh("git", "diff", "--cached", "--quiet", check=False).returncode == 0:
        return
    msg = "Training progress: " + "; ".join(s.split(":")[0] for s in summaries) + "\n\n" + "\n".join(summaries)
    sh("git", "commit", "-m", msg + "\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>")
    r = sh("git", "push", "origin", "main", check=False)
    print("pushed" if r.returncode == 0 else f"push failed: {r.stderr.strip()}")


def once():
    pull()
    runs = sorted(r for r in os.listdir(CACHE) if r.startswith("phase1_") and not r.endswith(("_1", "_2")))
    summaries = [s for s in (check_run(r) for r in runs) if s]
    for s in summaries:
        print(time.strftime("%H:%M"), s)
    if summaries:
        git_push(summaries)
    return summaries


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true")
    p.add_argument("--every-min", type=float, default=10)
    a = p.parse_args()
    while True:
        try:
            once()
        except Exception as e:  # keep looping through network hiccups
            print(time.strftime("%H:%M"), "error:", e)
        if a.once:
            break
        time.sleep(a.every_min * 60)
