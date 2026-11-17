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
                "squeue -u bpa29 -h -o %j | grep -c ppo; cd rl_quadruped/obstacle_course/runs 2>/dev/null && "
                "for d in */; do python3 -c \"import json,sys; h=json.load(open(sys.argv[1]))['history']; "
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
        if running is not None:
            due = [r for r, s in steps.items() if s // MILESTONE > state.get(r, 0)]
            if due or running == 0:
                for r, s in steps.items():
                    state[r] = s // MILESTONE
                os.makedirs(os.path.dirname(STATE), exist_ok=True)
                json.dump(state, open(STATE, "w"))
                return steps, running
        time.sleep(poll_min * 60)


def review():
    pp.pull_ppo()
    rows = {}
    for run in sorted(os.listdir(pp.PPO_CACHE)):
        src = os.path.join(pp.PPO_CACHE, run)
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
            rows[run] = dict(steps=hist[-1]["timesteps"] if hist else 0, checkpoint=os.path.basename(model),
                             goals={k: v for k, v in m["goals"].items()},
                             swing_lift_cm=m["swing_lift_cm"], speed=m["speed"],
                             wall_trials=m.get("wall_trials"))
    json.dump({"time": time.strftime("%Y-%m-%d %H:%M"), "runs": rows},
              open(os.path.join(pp.PROGRESS, "latest_review.json"), "w"), indent=1)
    return rows


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--wait", action="store_true")
    a = p.parse_args()
    if a.wait:
        steps, running = wait_for_milestone()
        print(f"milestone reached: {steps} (ppo jobs running: {running})")
    review()
