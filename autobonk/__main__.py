"""`python -m autobonk`: open PokéBonk in Chrome and run the autopilot."""

import argparse
import logging
from pathlib import Path

from autobonk.app import run


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="autobonk", description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("autobonk.toml"), help="Config file path")
    parser.add_argument("--open-dashboard", action="store_true", help="Open web dashboard in browser on start")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    run(config_path=args.config, open_dashboard=args.open_dashboard)


if __name__ == "__main__":
    main()
