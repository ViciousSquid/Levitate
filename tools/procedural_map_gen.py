#!/usr/bin/env python3
"""Command-line random maze generator.

    python tools/procedural_map_gen.py out.json --world frost --cols 10 --rows 8

Writes a new Levitate! maze as a Fio map. The same generator as the editor's
(editor/procedural_generator.py) and the launcher's Random maze
(game/random_maze.py).
"""

import argparse
import json
import os
import random
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from game import random_maze  # noqa: E402


def generate_map_to_file(params, output_file):
    """Generate a maze from *params* and save it as JSON."""
    map_data = random_maze.generate(params)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(map_data, f, indent=2)
    print(f"Map saved to {output_file}")


def run_cli(argv=None):
    parser = argparse.ArgumentParser(description="Generate a random Levitate! maze.")
    parser.add_argument("output", nargs="?", default="random_maze.json",
                        help="the map file to write (default: random_maze.json)")
    parser.add_argument("--world", default=random_maze.RANDOM_WORLD,
                        choices=[random_maze.RANDOM_WORLD, *random_maze.WORLDS],
                        help="the world to build in (default: any)")
    for name, (low, high) in random_maze.LIMITS.items():
        parser.add_argument(f"--{name.replace('_', '-')}", type=int,
                            default=random_maze.DEFAULTS[name],
                            help=f"{low}..{high} (default: %(default)s)")
    args = parser.parse_args(argv)
    params = {name: getattr(args, name) for name in random_maze.LIMITS}
    params["world"] = args.world
    random.seed()
    generate_map_to_file(params, args.output)


if __name__ == "__main__":
    run_cli()
