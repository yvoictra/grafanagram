# Grafanagram

Herramienta en Python para renderizar paneles individuales de **Grafana** en alta resolución mediante `grafana-image-renderer` y enviarlos agrupados como álbum a canales o chats de **Telegram**.

Diseñado para ejecutarse de forma desatendida desde `cron` o `systemd`, soportando múltiples dashboards y destinos mediante un fichero de configuración declarativo (`targets.json`).

---

## Características

* **Arquitectura multi-target:** Gestiona múltiples dashboards, canales de Telegram y listas de paneles desde un único archivo `targets.json`.
* **Renderizado concurrente:** Descarga paneles en paralelo mediante `ThreadPoolExecutor` manteniendo el orden exacto definido en la configuración.
* **Gestión segura de credenciales:** Carga variables de entorno desde `.env` sin dependencias externas ni secretos en el código.
* **Limpieza automática:** Utiliza directorios temporales aislados (`tempfile`) que se eliminan automáticamente al finalizar, evitando colisiones entre ejecuciones simultáneas.
* **Soporte nativo para límites de Telegram:** Divide automáticamente los envíos en lotes de hasta 10 imágenes (`sendMediaGroup`).
* **Modo de prueba (`--dry-run`):** Permite validar el renderizado contra Grafana sin enviar mensajes reales a Telegram.

---

## Requisitos

* **Python 3.10+**
* Librería `requests`:
  ```bash
  pip install requests
  ```
* Instancia de **Grafana** con el servicio **`grafana-image-renderer`** (v4.0+ recomendado) operativo y configurado.
* Un **Service Account Token** de Grafana con permisos de lectura sobre los dashboards a exportar.
* Un **Bot de Telegram** creado con [@BotFather](https://t.me/BotFather) y añadido como administrador en los canales/grupos de destino.

---

## Estructura del proyecto

```text
/opt/grafanagram/
├── grafanagram.py           # Script principal
├── targets.json             # Configuración de dashboards y paneles (ignorado en git)
├── targets.example.json     # Plantilla de ejemplo para targets.json
├── .env                     # Tokens y variables privadas (ignorado en git)
├── .env.example             # Plantilla de variables de entorno
└── .gitignore
```

---

## Instalación y configuración

1. **Clona el repositorio en `/opt` y ajusta los permisos:**
   ```bash
   sudo git clone [https://github.com/yvoictra/grafanagram.git](https://github.com/yvoictra/grafanagram.git) /opt/grafanagram
   sudo chown -R $USER:$USER /opt/grafanagram
   cd /opt/grafanagram
   chmod +x grafanagram.py
   ```

2. **Configura las variables de entorno:**
   ```bash
   cp .env.example .env
   chmod 600 .env
   ```
   Edita `.env` con tus credenciales:
   ```env
   GRAFANA_URL="[http://127.0.0.1:3000](http://127.0.0.1:3000)"
   GRAFANA_TOKEN="glsa_xxxxxxxxxxxxxxxxxxxxxxxxxxxx"
   TELEGRAM_BOT_TOKEN="123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
   ```

3. **Define tus objetivos en `targets.json`:**
   ```bash
   cp targets.example.json targets.json
   ```
   Edita `targets.json` adaptando los UIDs de dashboard, IDs de panel y canales de Telegram:
   ```json
   {
     "nodo_principal": {
       "title": "Servidor Principal - Monitorización",
       "dashboard_uid": "abc123xyz",
       "dashboard_slug": "system-metrics",
       "chat_id": "@mi_canal_telegram",
       "panel_ids": [1, 2, 4, 8],
       "width": 1200,
       "height": 600,
       "scale": 2
     }
   }
   ```

   > **Nota:** Si deseas utilizar un bot de Telegram distinto para un target concreto, añade la clave opcional `"bot_token_env": "OTRA_VARIABLE_EN_ENV"` dentro de su bloque en `targets.json`.

---

## Uso

### Comandos disponibles

```bash
# Ejecutar un target específico con el rango por defecto (6h)
/opt/grafanagram/grafanagram.py --target nodo_principal

# Ejecutar un target especificando el rango temporal (ej. últimas 24h o 7 días)
/opt/grafanagram/grafanagram.py --target nodo_principal --range 24h
/opt/grafanagram/grafanagram.py --target nodo_principal --range 7d

# Ejecutar todos los targets definidos en targets.json
/opt/grafanagram/grafanagram.py --all --range 24h

# Probar el renderizado sin enviar nada a Telegram
/opt/grafanagram/grafanagram.py --all --range 6h --dry-run
```

### Opciones CLI

| Argumento | Descripción | Valor por defecto |
| :--- | :--- | :--- |
| `-t`, `--target` | Nombre del target definido en `targets.json`. | *Requerido (o `--all`)* |
| `--all` | Procesa secuencialmente todos los targets de `targets.json`. | `False` |
| `-r`, `--range` | Ventana de tiempo hacia atrás (`6h`, `12h`, `24h`, `7d`, `30d`). | `6h` |
| `-c`, `--config` | Ruta alternativa al fichero de configuración JSON. | `./targets.json` |
| `--dry-run` | Renderiza las imágenes pero omite el envío a Telegram. | `False` |

---

## Automatización con Cron y Journald

El script carga automáticamente el archivo `.env` ubicado en su mismo directorio. Para evitar archivos de log manuales sin rotación y facilitar la recolección centralizada (por ejemplo, con **Promtail** / **Loki**), se recomienda redirigir la salida a `syslog`/`journald` mediante `logger`:

```cron
# Resumen cada hora de las últimas 24 horas
0 * * * * /usr/bin/python3 /opt/grafanagram/grafanagram.py --all --range 24h 2>&1 | logger -t grafanagram

# Resumen semanal a las 10:30, 16:30 y 22:30
30 10,16,22 * * * /usr/bin/python3 /opt/grafanagram/grafanagram.py --all --range 7d 2>&1 | logger -t grafanagram

# Resumen mensual a 23:45
45 23 * * * /usr/bin/python3 /opt/grafanagram/grafanagram.py --all --range 30d 2>&1 | logger -t grafanagram
```

Para consultar los registros de ejecución en el sistema:

```bash
journalctl -t grafanagram -n 30 --no-pager
```

---

## Despliegue de `grafana-image-renderer` (Docker)

Ejemplo de configuración recomendada en `docker-compose.yml` para dar soporte al renderizado en alta resolución (`scale=2`):

```yaml
services:
  grafana-renderer:
    image: grafana/grafana-image-renderer:latest
    container_name: grafana-renderer
    restart: unless-stopped
    ports:
      - "8081:8081"
    environment:
      - TZ=Europe/Madrid
    volumes:
      - /etc/timezone:/etc/timezone:ro
      - /etc/localtime:/etc/localtime:ro
    shm_size: "1gb"
```

---

## Plantillas de configuración incluidas

### `.gitignore`

```gitignore
.env
targets.json
__pycache__/
*.py[cod]
*.log
```

### `.env.example`

```env
GRAFANA_URL="[http://127.0.0.1:3000](http://127.0.0.1:3000)"
GRAFANA_TOKEN="glsa_your_grafana_service_account_token"
TELEGRAM_BOT_TOKEN="123456789:your_telegram_bot_token"
```

### `targets.example.json`

```json
{
  "home_assistant": {
    "title": "Home Assistant - Estadísticas",
    "dashboard_uid": "your_dashboard_uid",
    "dashboard_slug": "home-assistant",
    "chat_id": "@your_telegram_channel",
    "panel_ids": [1, 2, 3, 4],
    "width": 1200,
    "height": 600,
    "scale": 2
  }
}
```

---

## Licencia

MIT
