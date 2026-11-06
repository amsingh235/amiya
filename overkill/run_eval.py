"""Entry point.  python run_eval.py --pipeline rules

Run ONE pipeline per invocation: a rate limit on the fourth must not throw away the first three.
Each run merges into results.json under its own key and re-publishes the dashboard data in web/.
"""
from __future__ import annotations

import argparse
import json
import sys

from harness.data import load_eval
from harness.run import preflight, publish, run_pipeline
from pipelines import PIPELINE_IDS, get_pipeline


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Overkill eval harness")
    ap.add_argument("--pipeline", "-p", choices=PIPELINE_IDS, help="which pipeline to run")
    ap.add_argument("--split", choices=["all", "dev", "test"], default="all",
                    help="run only these cases (tune on dev; report test)")
    ap.add_argument("--limit", type=int, help="run at most N new cases (smoke test)")
    ap.add_argument("--fresh", action="store_true", help="ignore checkpointed rows and re-run everything")
    ap.add_argument("--yes", "-y", action="store_true", help="proceed even if the run exceeds a day of free-tier quota")
    ap.add_argument("--estimate", action="store_true", help="print the call/token/day estimate and exit")
    ap.add_argument("--publish", action="store_true", help="re-copy results + data into web/ and exit")
    args = ap.parse_args(argv)

    if args.publish:
        publish()
        print("published web/")
        return 0
    if not args.pipeline:
        ap.print_help()
        return 2
    if args.estimate:
        cases, _ = load_eval()
        todo = [c for c in cases if args.split in ("all", c["split"])][: args.limit or None]
        print(json.dumps(preflight(get_pipeline(args.pipeline), todo), indent=2))
        return 0
    entry = run_pipeline(args.pipeline, split=args.split, limit=args.limit, fresh=args.fresh, yes=args.yes)
    return 0 if entry else 1


if __name__ == "__main__":
    sys.exit(main())
