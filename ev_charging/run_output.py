"""One folder per run: outputs/runX_[parameters]/

Every runner script creates a new numbered folder for each run, named after
the settings that matter, e.g.

    outputs/run3_greedy-vs-always_evs-10_chargers-3_days-7_start-2025-07-07_no-home-share-0.3/

The name always includes the runner's main settings (`always`), plus any other
option changed from its default. Inside the folder:
  - summary.txt   everything the run printed
  - params.json   every option, its value, and the exact command
  - the charts / animations asked for (dashboard PNGs, GIFs)
X counts up across all runners, so the newest run has the highest number.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, Optional

# options that only change what is drawn or where it goes, not the simulation itself
OUTPUT_OPTIONS = {"plot", "animate", "show", "out", "every", "anim_days"}
MAX_NAME = 150          # keep paths well under Windows' 260-character limit
_RUN_RE = re.compile(r"^run(\d+)(?:_|$)")


def _fmt(value) -> str:
    if isinstance(value, float):
        value = f"{value:g}"
    elif isinstance(value, Path):
        value = value.name
    return re.sub(r"[^A-Za-z0-9.+-]+", "-", str(value)).strip("-")


def run_parameters(args: argparse.Namespace, parser: argparse.ArgumentParser,
                   always: Iterable[str] = (), skip: Iterable[str] = ()) -> list[str]:
    """`key-value` pieces for the folder name: the `always` options first, then
    every other option that differs from its default (flags as just `key`)."""
    skip = set(skip) | OUTPUT_OPTIONS
    always = [k for k in always if k not in skip]
    keys = always + [a.dest for a in parser._actions
                     if a.dest not in always and a.dest not in skip and a.dest != "help"
                     and getattr(args, a.dest, a.default) != a.default]
    parts = []
    for k in keys:
        v = getattr(args, k, None)
        key = k.replace("_", "-")
        if v is True:
            parts.append(key)
        elif v is False or v is None:
            continue
        else:
            parts.append(f"{key}-{_fmt(v)}")
    return parts


def next_run_number(root: Path) -> int:
    nums = [int(m.group(1)) for p in root.iterdir() if p.is_dir() and (m := _RUN_RE.match(p.name))] \
        if root.exists() else []
    return max(nums, default=0) + 1


def new_run_dir(root: Path, label: str, parameters: list[str]) -> Path:
    """Create outputs/run{X}_{label}_{parameters} and return it."""
    root.mkdir(parents=True, exist_ok=True)
    tail = "_".join([label] + parameters)
    while True:
        name = f"run{next_run_number(root)}_{tail}"
        if len(name) > MAX_NAME:
            name = name[:MAX_NAME].rstrip("_-")
        path = root / name
        try:
            path.mkdir()
            return path
        except FileExistsError:       # another run grabbed this number; try the next
            continue


class _Tee:
    def __init__(self, *streams) -> None:
        self.streams = streams

    def write(self, text: str) -> int:
        for s in self.streams:
            s.write(text)
        return len(text)

    def flush(self) -> None:
        for s in self.streams:
            s.flush()


@contextlib.contextmanager
def run_folder(args: argparse.Namespace, parser: argparse.ArgumentParser, label: str,
               always: Iterable[str] = (), skip: Iterable[str] = (),
               root: Optional[Path] = None) -> Iterator[Path]:
    """Make the run's folder, save params.json, and copy everything printed
    inside the `with` block to summary.txt. Sets args.run_dir."""
    root = Path(root or args.out)
    path = new_run_dir(root, label, run_parameters(args, parser, always, skip))
    args.run_dir = path
    params = {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()}
    (path / "params.json").write_text(json.dumps({
        "command": " ".join([Path(sys.argv[0]).name] + sys.argv[1:]),
        "started": datetime.now().isoformat(timespec="seconds"),
        "options": params,
    }, indent=2), encoding="utf-8")
    with open(path / "summary.txt", "w", encoding="utf-8") as f, \
            contextlib.redirect_stdout(_Tee(sys.stdout, f)):
        print(f"Run folder: {path}")
        yield path
