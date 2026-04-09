#!/usr/bin/env python3
"""
Create a local raw JSONL sample for development from a large OpenFoodFacts export.

Typical usage:
  python scripts/create_local_bronze_sample.py \
    --input data/bronze/openfood/full/_downloads/openfoodfacts-products.jsonl.gz \
    --output data/bronze/dev/openfood_raw_sample_5000.jsonl \
    --sample-size 5000 \
    --mode random

The sample is intentionally extracted without project filtering criteria.
It is meant to provide a stable raw Bronze-like dataset for local testing.
"""

from __future__ import annotations

import argparse
import gzip
import json
import random
from pathlib import Path


DEFAULT_INPUT_PATH = "data/bronze/openfood/full/_downloads/openfoodfacts-products.jsonl.gz"
DEFAULT_OUTPUT_PATH = "data/bronze/dev/openfood_raw_sample_5000.jsonl"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Create a local raw JSONL sample from a large OpenFoodFacts export."
    )
    parser.add_argument(
        "--input",
        default=DEFAULT_INPUT_PATH,
        help="Path to a local source file (.jsonl or .jsonl.gz).",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT_PATH,
        help="Path to the local JSONL sample to create.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=5000,
        help="Number of raw JSON lines to keep in the sample.",
    )
    parser.add_argument(
        "--mode",
        choices=["random", "first"],
        default="random",
        help="Sampling strategy: first N lines or random reservoir sampling.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed used in random mode.",
    )
    parser.add_argument(
        "--strict-json",
        action="store_true",
        help="When enabled, only keep lines that decode into JSON objects.",
    )
    return parser.parse_args()


def open_text_stream(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("r", encoding="utf-8", errors="replace")


def is_valid_json_object(line: str) -> bool:
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return False
    return isinstance(obj, dict)


def first_n_sample(
    source_path: Path,
    sample_size: int,
    strict_json: bool,
) -> tuple[list[str], dict[str, int]]:
    rows: list[str] = []
    stats = {"lines_read": 0, "lines_kept": 0, "invalid_json_lines": 0, "empty_lines": 0}

    with open_text_stream(source_path) as stream:
        for raw_line in stream:
            line = raw_line.strip()
            if not line:
                stats["empty_lines"] += 1
                continue

            stats["lines_read"] += 1
            if strict_json and not is_valid_json_object(line):
                stats["invalid_json_lines"] += 1
                continue

            rows.append(line)
            stats["lines_kept"] += 1
            if len(rows) >= sample_size:
                break

    return rows, stats


def reservoir_sample(
    source_path: Path,
    sample_size: int,
    strict_json: bool,
    seed: int,
) -> tuple[list[str], dict[str, int]]:
    rng = random.Random(seed)
    reservoir: list[str] = []
    stats = {"lines_read": 0, "lines_kept": 0, "invalid_json_lines": 0, "empty_lines": 0}

    with open_text_stream(source_path) as stream:
        for raw_line in stream:
            line = raw_line.strip()
            if not line:
                stats["empty_lines"] += 1
                continue

            if strict_json and not is_valid_json_object(line):
                stats["invalid_json_lines"] += 1
                continue

            stats["lines_read"] += 1
            if len(reservoir) < sample_size:
                reservoir.append(line)
            else:
                idx = rng.randint(0, stats["lines_read"] - 1)
                if idx < sample_size:
                    reservoir[idx] = line

    stats["lines_kept"] = len(reservoir)
    return reservoir, stats


def write_jsonl(output_path: Path, rows: list[str]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(row)
            fh.write("\n")


def main():
    args = parse_args()
    source_path = Path(args.input)
    output_path = Path(args.output)

    if args.sample_size <= 0:
        raise ValueError("--sample-size must be greater than 0")
    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    if args.mode == "first":
        rows, stats = first_n_sample(
            source_path=source_path,
            sample_size=args.sample_size,
            strict_json=args.strict_json,
        )
    else:
        rows, stats = reservoir_sample(
            source_path=source_path,
            sample_size=args.sample_size,
            strict_json=args.strict_json,
            seed=args.seed,
        )

    write_jsonl(output_path, rows)

    print(
        "Local Bronze sample created: "
        f"output={output_path}, mode={args.mode}, lines_kept={stats['lines_kept']}, "
        f"lines_read={stats['lines_read']}, invalid_json_lines={stats['invalid_json_lines']}, "
        f"empty_lines={stats['empty_lines']}"
    )


if __name__ == "__main__":
    main()
