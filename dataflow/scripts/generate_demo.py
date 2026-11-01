"""Deterministic synthetic fixtures; never represent client records."""

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADERS = ["sale_id", "branch", "sale_date", "amount", "currency", "description"]


def generate(count):
    rows = []
    expected = {"accepted": 0, "rejected": 0, "duplicated": 0, "total_cents": 0}
    for i in range(count):
        branch = ["Lima", "Arequipa", "Trujillo"][i % 3]
        row = [
            f"S-{i:07d}",
            branch,
            "2026-10-15",
            f"{10 + i % 200}.25",
            "PEN",
            f"Venta sintética {i}",
        ]
        if i % 20 == 0:
            row[2] = "2026-02-30"
            expected["rejected"] += 1
        elif i % 17 == 0:
            row = rows[
                -1
            ].copy()  # predecessor is valid for these deterministic positions
            if row[2] == "2026-02-30":
                # i=221 etc: make a distinct invalid record, keeping the oracle explicit.
                expected["rejected"] += 1
            else:
                expected["duplicated"] += 1
        else:
            expected["accepted"] += 1
            expected["total_cents"] += (10 + i % 200) * 100 + 25
        rows.append(row)
    return rows, expected


if __name__ == "__main__":
    ROOT.joinpath("demo").mkdir(exist_ok=True)
    rows, expected = generate(60)
    for name, values in (("01-ventas.csv", rows[:30]), ("02-ventas.csv", rows[30:])):
        with ROOT.joinpath("demo", name).open(
            "w", encoding="utf-8", newline=""
        ) as file:
            writer = csv.writer(file)
            writer.writerow(HEADERS)
            writer.writerows(values)
    ROOT.joinpath("demo/expected.json").write_text(
        json.dumps(expected, indent=2) + "\n"
    )
