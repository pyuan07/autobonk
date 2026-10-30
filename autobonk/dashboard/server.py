"""Local web server for the dashboard and card/target weight editor."""

import json
import socket
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from autobonk.dashboard.hub import hub
from autobonk.dashboard.toml_store import (
    _boss_from,
    _ends,
    _numeric,
    _target_weights,
    build_full_card_list,
    read_target_weights,
    save_config_weights,
    save_target_weights,
)
from autobonk.game import ALTAR, BOSS
from autobonk.perception.icons import ICON_DIR, ITEM_ICONS, POKEMON_ICONS
from autobonk.perception.minimap import ALTAR_TEMPLATE

_PKG_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _PKG_DIR.parent
UI_HTML_PATH = _PKG_DIR / "editor_ui.html" if (_PKG_DIR / "editor_ui.html").exists() else _ROOT_DIR / "editor_ui.html"
TARGETS_HTML_PATH = _PKG_DIR / "targets_ui.html" if (_PKG_DIR / "targets_ui.html").exists() else _ROOT_DIR / "targets_ui.html"

TARGET_GROUPS: list[tuple[str, dict[str, Path]]] = [
    ("祭坛", {ALTAR: ALTAR_TEMPLATE}),
    ("物品与设施", {name: ICON_DIR / file for name, file in ITEM_ICONS.items() if name != BOSS}),
    ("宝可梦（商店、教学、头目）", {name: ICON_DIR / file for name, file in POKEMON_ICONS.items()}),
]
TARGET_IMAGES = {name: path for _, icons in TARGET_GROUPS for name, path in icons.items()}
TARGET_IMAGES[BOSS] = ICON_DIR / ITEM_ICONS[BOSS]


def target_list(toml_path: Path) -> dict[str, Any]:
    weights, boss = read_target_weights(toml_path)

    def icon(name: str) -> dict[str, Any]:
        start, end = _ends(weights.get(name, 0))
        return {"name": name, "start": start, "end": end}

    return {
        "groups": [{"title": title, "icons": [icon(name) for name in icons]} for title, icons in TARGET_GROUPS],
        "boss": {"name": BOSS, "levels": list(boss.levels), "minutes_left": list(boss.minutes_left)},
    }


def make_handler(config_path: Path):
    class WeightEditorHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def log_request(self, code: Any = "-", size: Any = "-") -> None:
            pass

        def _send(self, status: HTTPStatus, content_type: str, body: str | bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8" if isinstance(body, str) else content_type)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body.encode("utf-8") if isinstance(body, str) else body)

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                self._send(HTTPStatus.OK, "text/html", UI_HTML_PATH.read_text(encoding="utf-8"))
            elif path == "/targets":
                self._send(HTTPStatus.OK, "text/html", TARGETS_HTML_PATH.read_text(encoding="utf-8"))
            elif path == "/api/targets":
                data = target_list(config_path)
                data["config_path"] = str(config_path)
                self._send(HTTPStatus.OK, "application/json", json.dumps(data, ensure_ascii=False))
            elif path.startswith("/icons/") and unquote(path[len("/icons/"):]) in TARGET_IMAGES:
                self._send(HTTPStatus.OK, "image/png", TARGET_IMAGES[unquote(path[len("/icons/"):])].read_bytes())
            elif path == "/api/data":
                data = build_full_card_list(config_path)
                data["config_path"] = str(config_path)
                self._send(HTTPStatus.OK, "application/json", json.dumps(data, ensure_ascii=False))
            elif path == "/api/status":
                self._send(HTTPStatus.OK, "application/json", json.dumps(hub.get_snapshot(), ensure_ascii=False))
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def _same_origin(self) -> bool:
            server_port = self.server.server_address[1] if isinstance(self.server.server_address, tuple) else 0
            host = f"127.0.0.1:{server_port}"
            origin = self.headers.get("Origin")
            return (
                self.headers.get("Content-Type", "").startswith("application/json")
                and self.headers.get("Host") == host
                and origin in (None, f"http://{host}")
            )

        def do_POST(self) -> None:
            if self.path not in ("/api/save", "/api/targets", "/api/control"):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length > 0 else b""
            if not self._same_origin():
                self._send(
                    HTTPStatus.FORBIDDEN,
                    "application/json",
                    json.dumps({"status": "error", "error": "cross-origin save refused"}),
                )
                return
            try:
                data = json.loads(body.decode("utf-8"))
                if self.path == "/api/control":
                    action = str(data.get("action", ""))
                    if action in ("start", "pause", "toggle_pause"):
                        hub.request_action(action)
                        self._send(HTTPStatus.OK, "application/json", json.dumps({"status": "ok", "action": action}))
                        return
                    raise ValueError(f"unknown action: {action}")
                if self.path == "/api/targets":
                    save_target_weights(
                        config_path, _target_weights(data.get("weights", {})), _boss_from(data.get("boss", {}))
                    )
                    self._send(HTTPStatus.OK, "application/json", json.dumps({"status": "ok"}))
                    return
                baseline_weights = data.get("baseline_weights", {})
                if not baseline_weights and "weights" in data:
                    baseline_weights = data["weights"]
                profiles = data.get("pokemon_profiles") or {}
                if not isinstance(profiles, dict):
                    raise ValueError("pokemon_profiles must be an object")

                save_config_weights(
                    config_path,
                    baseline_weights=_numeric(baseline_weights),
                    rarity_order=[str(r) for r in data.get("rarity_order", [])],
                    active_pokemon=data.get("active_pokemon") or None,
                    pokemon_profiles={str(p): _numeric(w) for p, w in profiles.items()},
                )
                res = {"status": "ok"}
                status = HTTPStatus.OK
            except Exception as exc:
                res = {"status": "error", "error": str(exc)}
                status = HTTPStatus.BAD_REQUEST
            self._send(status, "application/json", json.dumps(res, ensure_ascii=False))

    return WeightEditorHandler


def find_free_port(preferred_port: int) -> int:
    for port in range(preferred_port, preferred_port + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return preferred_port


def run_editor(config_path: Path, port: int = 8080, open_browser: bool = True) -> HTTPServer:
    config_path = Path(config_path).resolve()
    actual_port = find_free_port(port)
    server_address = ("127.0.0.1", actual_port)
    handler_class = make_handler(config_path)
    httpd = HTTPServer(server_address, handler_class)

    url = f"http://127.0.0.1:{actual_port}/"
    print("\n=======================================================")
    print("  PokéBonk Dashboard & Editor running: (cards /, map targets /targets)")
    print(f"  Config: {config_path}")
    print(f"  Open in browser: {url}")
    print("  Press Ctrl+C to stop the server.")
    print("=======================================================\n")

    if open_browser:
        webbrowser.open(url)

    return httpd
