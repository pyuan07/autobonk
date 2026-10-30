"""CLI entry point for running the dashboard and weight editor standalone."""

import argparse
from pathlib import Path

from autobonk.dashboard.server import run_editor
from autobonk.dashboard.toml_store import ROOT_DIR


def main() -> None:
    parser = argparse.ArgumentParser(description="PokéBonk Card Weight Editor GUI")
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT_DIR / "autobonk.toml",
        help="Path to autobonk.toml",
    )
    parser.add_argument(
        "--port", type=int, default=8080, help="Local server port (default: 8080)"
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="Don't open browser automatically"
    )
    args = parser.parse_args()

    httpd = run_editor(config_path=args.config, port=args.port, open_browser=not args.no_browser)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
