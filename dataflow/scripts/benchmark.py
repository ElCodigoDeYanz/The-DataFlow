"""Run one isolated process per size. RSS includes interpreter and input buffers."""

import argparse
import csv
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import resource
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dataflow.database import Database
from dataflow.pipeline import import_csv
from scripts.generate_demo import generate, HEADERS


def worker(count):
    baseline = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    try:
        rows, expected = generate(count)
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(HEADERS)
        writer.writerows(rows)
        content = output.getvalue().encode()
        with tempfile.TemporaryDirectory() as temp:
            db = Database(Path(temp) / "bench.db")
            start = time.perf_counter()
            result = import_csv(db, content, "synthetic.csv", {k: k for k in HEADERS})
            elapsed = time.perf_counter() - start
            with db.connect() as con:
                total = con.execute(
                    "SELECT COALESCE(SUM(amount_cents),0) FROM sales"
                ).fetchone()[0]
            correct = (
                all(
                    result[k] == expected[k]
                    for k in ("accepted", "rejected", "duplicated")
                )
                and total == expected["total_cents"]
            )
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return {
                "rows": count,
                "input_bytes": len(content),
                "seconds": round(elapsed, 4),
                "baseline_rss_mib": round(baseline / 1024, 2),
                "peak_rss_mib": round(peak / 1024, 2),
                "memory_method": "Linux getrusage ru_maxrss (KiB)",
                "correct": correct,
                "counts": {
                    k: result[k]
                    for k in ("total", "accepted", "rejected", "duplicated")
                },
                "expected_total_cents": expected["total_cents"],
                "actual_total_cents": total,
            }
    finally:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=int)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.worker)))
    else:
        runs = [
            json.loads(
                subprocess.check_output(
                    [sys.executable, __file__, "--worker", str(n)], cwd=ROOT
                )
            )
            for n in (1000, 10000, 50000)
        ]
        report = {
            "environment": {
                "python": platform.python_version(),
                "os": platform.platform(),
                "logical_cpus": os.cpu_count(),
                "visible_ram_mib": round(
                    os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1048576
                ),
                "scope": "shared execution environment, NOT user's laptop",
                "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            "method": "single run per size; time measures import only; OS high-water RSS in isolated Linux process includes generated input, baseline and DB; no load test or production SLA",
            "runs": runs,
        }
        (ROOT / "evidence/benchmark.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
        print(json.dumps(report, indent=2))
        if not all(r["correct"] for r in runs):
            sys.exit(1)
