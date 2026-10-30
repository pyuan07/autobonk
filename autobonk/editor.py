"""Local web GUI for viewing and editing PokéBonk card weights and map target weights in autobonk.toml."""

from autobonk.dashboard.editor import main
from autobonk.dashboard.server import (
    TARGET_GROUPS,
    TARGET_IMAGES,
    make_handler,
    run_editor,
    target_list,
)
from autobonk.dashboard.toml_store import (
    CATALOG_PATH,
    DEFAULT_RARITY_ORDER,
    DEFAULT_TARGET_WEIGHTS,
    ROOT_DIR,
    build_full_card_list,
    load_catalog,
    read_config_weights,
    read_target_weights,
    save_config_weights,
    save_target_weights,
)
from autobonk.game import ALTAR as ALTAR_NAME

__all__ = [
    "main",
    "make_handler",
    "run_editor",
    "target_list",
    "build_full_card_list",
    "load_catalog",
    "read_config_weights",
    "read_target_weights",
    "save_config_weights",
    "save_target_weights",
    "DEFAULT_RARITY_ORDER",
    "DEFAULT_TARGET_WEIGHTS",
    "TARGET_GROUPS",
    "TARGET_IMAGES",
    "ALTAR_NAME",
    "CATALOG_PATH",
    "ROOT_DIR",
]

if __name__ == "__main__":
    main()
