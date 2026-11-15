#!/usr/bin/env python3
import os
import sys
import json
import logging
import argparse
import tempfile
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = BASE_DIR / "targets.json"
DEFAULT_ENV_PATH = BASE_DIR / ".env"

ORG_ID = 1
TIMEZONE = "Europe/Madrid"
MAX_WORKERS = 3
TELEGRAM_BATCH_SIZE = 10

def load_env_file(env_path: Path) -> None:
    """Carga variables desde .env limpiando comentarios inline y espacios."""
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        # Si está entre comillas, extraer solo lo de dentro; si no, quitar comentarios #
        if (value.startswith('"') and '"' in value[1:]):
            value = value[1:value.index('"', 1)]
        elif (value.startswith("'") and "'" in value[1:]):
            value = value[1:value.index("'", 1)]
        else:
            value = value.split("#", 1)[0].strip()
        os.environ.setdefault(key, value)


def load_targets(config_path: Path) -> dict:
    if not config_path.is_file():
        raise FileNotFoundError(f"No se encuentra el archivo de configuración: {config_path}")
    with config_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Exporta paneles de Grafana a Telegram por target.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-t", "--target", help="Nombre del target definido en targets.json (ej: firo, medusa)")
    group.add_argument("--all", action="store_true", help="Ejecuta todos los targets definidos en targets.json")

    parser.add_argument("-r", "--range", default="6h", help="Rango temporal (ej: 6h, 24h, 7d). Default: 6h")
    parser.add_argument("-c", "--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Ruta a targets.json")
    parser.add_argument("--dry-run", action="store_true", help="Renderiza las imágenes pero no las envía a Telegram")
    return parser.parse_args()


def render_panel(
    session: requests.Session,
    grafana_url: str,
    target_cfg: dict,
    panel_id: int,
    time_range: str,
    temp_dir: Path
) -> tuple[int, Path | None]:
    params = {
        "orgId": target_cfg.get("org_id", ORG_ID),
        "panelId": panel_id,
        "from": f"now-{time_range}",
        "to": "now",
        "width": target_cfg.get("width", 1200),
        "height": target_cfg.get("height", 600),
        "tz": TIMEZONE,
        "render": 1,
        "scale": target_cfg.get("scale", 2),
    }
    url = f"{grafana_url}/render/d-solo/{target_cfg['dashboard_uid']}/{target_cfg['dashboard_slug']}"
    output_path = temp_dir / f"panel_{panel_id}.png"

    try:
        resp = session.get(url, params=params, timeout=60)
        if resp.status_code == 200 and resp.headers.get("Content-Type", "").startswith("image/"):
            output_path.write_bytes(resp.content)
            logger.info(f"Panel {panel_id} OK ({len(resp.content) // 1024} KB)")
            return panel_id, output_path

        logger.error(f"Panel {panel_id} falló con HTTP {resp.status_code}: {resp.text[:200]}")
    except requests.RequestException as exc:
        logger.error(f"Error de red en panel {panel_id}: {exc}")

    return panel_id, None


def send_telegram_album(bot_token: str, target_cfg: dict, image_paths: list[Path], time_range: str) -> bool:
    telegram_url = f"https://api.telegram.org/bot{bot_token}/sendMediaGroup"
    timestamp = datetime.now().strftime("%H:%M:%S")
    title = target_cfg.get("title", "Estadísticas de Grafana")
    caption = f"{title} - Hora: {timestamp} (Últimos {time_range})"
    all_ok = True

    for batch_idx in range(0, len(image_paths), TELEGRAM_BATCH_SIZE):
        batch = image_paths[batch_idx:batch_idx + TELEGRAM_BATCH_SIZE]
        media_group = []
        files = {}

        try:
            for idx, path in enumerate(batch):
                media_item = {"type": "photo", "media": f"attach://{path.name}"}
                if batch_idx == 0 and idx == 0:
                    media_item["caption"] = caption
                media_group.append(media_item)
                files[path.name] = open(path, "rb")

            resp = requests.post(
                telegram_url,
                data={"chat_id": target_cfg["chat_id"], "media": json.dumps(media_group)},
                files=files,
                timeout=60
            )
            if resp.status_code == 200:
                logger.info(f"Álbum enviado a {target_cfg['chat_id']} ({len(batch)} imágenes).")
            else:
                logger.error(f"Error API Telegram ({resp.status_code}): {resp.text}")
                all_ok = False
        except requests.RequestException as exc:
            logger.error(f"Excepción al enviar a Telegram: {exc}")
            all_ok = False
        finally:
            for f in files.values():
                f.close()

    return all_ok


def process_target(name: str, target_cfg: dict, grafana_url: str, grafana_token: str, args: argparse.Namespace) -> bool:
    panel_ids = target_cfg["panel_ids"]
    bot_env_var = target_cfg.get("bot_token_env", "TELEGRAM_BOT_TOKEN")
    bot_token = os.getenv(bot_env_var)

    if not bot_token and not args.dry_run:
        logger.error(f"[{name}] Falta variable de entorno '{bot_env_var}'")
        return False

    logger.info(f"[{name}] Iniciando exportación de {len(panel_ids)} paneles (rango: {args.range})")

    with tempfile.TemporaryDirectory(prefix=f"grafana_{name}_") as tmp_dir_str:
        temp_dir = Path(tmp_dir_str)
        results: dict[int, Path] = {}

        with requests.Session() as session:
            session.headers.update({"Authorization": f"Bearer {grafana_token}"})

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {
                    executor.submit(render_panel, session, grafana_url, target_cfg, pid, args.range, temp_dir): pid
                    for pid in panel_ids
                }
                for future in as_completed(futures):
                    pid, path = future.result()
                    if path:
                        results[pid] = path

        ordered_images = [results[pid] for pid in panel_ids if pid in results]
        if not ordered_images:
            logger.error(f"[{name}] No se descargó ninguna imagen. Se cancela el envío.")
            return False

        if args.dry_run:
            logger.info(f"[{name}] --dry-run completado ({len(ordered_images)}/{len(panel_ids)} paneles OK).")
            return True

        return send_telegram_album(bot_token, target_cfg, ordered_images, args.range)


def main() -> int:
    load_env_file(DEFAULT_ENV_PATH)
    args = parse_args()

    grafana_url = os.getenv("GRAFANA_URL", "http://127.0.0.1:3000").rstrip("/")
    grafana_token = os.getenv("GRAFANA_TOKEN")

    if not grafana_token:
        logger.critical("Falta GRAFANA_TOKEN en el entorno o en .env")
        return 1

    try:
        targets = load_targets(args.config)
    except Exception as exc:
        logger.critical(f"Error leyendo configuración: {exc}")
        return 1

    if args.all:
        selected = list(targets.keys())
    else:
        if args.target not in targets:
            logger.critical(f"Target '{args.target}' no existe. Disponibles: {', '.join(targets.keys())}")
            return 1
        selected = [args.target]

    all_success = True
    for target_name in selected:
        if not process_target(target_name, targets[target_name], grafana_url, grafana_token, args):
            all_success = False

    return 0 if all_success else 1


if __name__ == "__main__":
    sys.exit(main())
