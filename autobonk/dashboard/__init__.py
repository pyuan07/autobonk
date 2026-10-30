"""Dashboard subpackage: web UI, hub, and TOML persistence."""

from autobonk.dashboard.hub import BotState, DashboardHub, hub
from autobonk.dashboard.server import make_handler, run_editor
from autobonk.dashboard.toml_store import (
    build_full_card_list,
    load_catalog,
    read_config_weights,
    read_target_weights,
    save_config_weights,
    save_target_weights,
)

__all__ = [
    "BotState",
    "DashboardHub",
    "hub",
    "make_handler",
    "run_editor",
    "build_full_card_list",
    "load_catalog",
    "read_config_weights",
    "read_target_weights",
    "save_config_weights",
    "save_target_weights",
]
