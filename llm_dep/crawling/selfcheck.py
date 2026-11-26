"""Regression check: recompute `versions` of the existing O/U samples with signature.compatible."""
import argparse
import collections
import json
from pathlib import Path

from .evolution import LIBS, Evolution
from .signature import compatible


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--lenient-starred", action="store_true",
                    help="check calls with *args/**kwargs with the lenient rule of the signature branch")
    args = ap.parse_args()
    ev = Evolution(Path(args.data))
    agree = dis = und = 0
    ex = collections.defaultdict(list)
    for lib in LIBS:
        for kind in "OU":
            samples = json.load(open(Path(args.data) / lib / f"{kind}_modified.json", encoding="utf-8"))
            for i, s in enumerate(samples):
                paths = [p for d in s["deprecated api"]
                         if (p := ev.by_deprecated.get(d)) and p.replacement_api == s["replacement api"]]
                target = paths[0].deprecated_api if kind == "O" else s["replacement api"]
                pred, undecidable = set(), False
                for p in paths:
                    for v in p.milestones:
                        r = compatible(s["api_call"], target, p.state(v, target), lenient_starred=args.lenient_starred)
                        if r is None:
                            undecidable = True
                        elif r:
                            pred.add(v)
                if undecidable:
                    und += 1
                    continue
                if pred == set(s["versions"]):
                    agree += 1
                else:
                    dis += 1
                    if len(ex[(lib, kind, target)]) < 2:
                        ex[(lib, kind, target)].append((i, s["api_call"][:80], sorted(set(s["versions"]) - pred), sorted(pred - set(s["versions"]))))
    print(f"agree={agree} disagree={dis} undecidable={und}")
    for k, v in ex.items():
        print(k, v)


if __name__ == "__main__":
    main()
