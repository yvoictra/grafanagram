# Grafanagram

Herramienta en Python para renderizar paneles individuales de **Grafana** en alta resolución mediante `grafana-image-renderer` y enviarlos agrupados como álbum a canales o chats de **Telegram**, con soporte opcional para notificaciones **Push** (Uptime Kuma, Cronitor, Healthchecks, etc.).

Diseñado para ejecutarse de forma desatendida desde `cron` o `systemd`, soportando múltiples dashboards y destinos mediante un fichero de configuración declarativo (`targets.json`).

---

## Características

* **Arquitectura multi-target:** Gestiona múltiples dashboards, canales de Telegram y listas de paneles desde un único archivo `targets.json`.
* **Renderizado concurrente:** Descarga paneles en paralelo mediante `ThreadPoolExecutor` manteniendo el orden exacto definido en la configuración.
* **Monitorización Push (0 a X endpoints):** Permite notificar opcionalmente a una o varias instancias de **Uptime Kuma**, **Cronitor** o servicios compatibles tras cada envío exitoso a Telegram.
* **Gestión segura de credenciales:** Carga variables de entorno desde `.env` sin dependencias externas ni secretos expuestos en el código o en los logs.
* **Limpieza automática:** Utiliza directorios temporales aislados (`tempfile`) que se eliminan automáticamente al finalizar, evitando colisiones entre ejecuciones simultáneas.
* **Soporte nativo para límites de Telegram:** Divide automáticamente los envíos en lotes de hasta 10 imágenes (`sendMediaGroup`).
* **Modo de prueba (`--dry-run`):** Permite validar el renderizado contra Grafana sin enviar mensajes reales a Telegram ni disparar pings de monitorización.

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
   Edita `.env` con tus credenciales y URLs de push (si las utilizas):
   ```env
   GRAFANA_URL="[http://127.0.0.1:3000](http://127.0.0.1:3000)"
   GRAFANA_TOKEN="glsa_xxxxxxxxxxxxxxxxxxxxxxxxxxxx"
   TELEGRAM_BOT_TOKEN="123456789:ABCdefGHIjklMNOpqrsTUVwxyz"

   # Opcional: URLs de monitorización Push (Uptime Kuma, Cronitor, etc.)
   UPTIME_KUMA_1="[https://status1.example.com/api/push/xxxxxxxx?status=up&msg=OK&ping=](https://status1.example.com/api/push/xxxxxxxx?status=up&msg=OK&ping=)"
   UPTIME_KUMA_2="[https://status2.example.com/api/push/yyyyyyyy?status=up&msg=OK&ping=](https://status2.example.com/api/push/yyyyyyyy?status=up&msg=OK&ping=)"
   CRONITOR_URL="[https://cronitor.link/p/zzzzzzzz/grafana-export](https://cronitor.link/p/zzzzzzzz/grafana-export)"
   ```

3. **Define tus objetivos en `targets.json`:**
   ```bash
   cp targets.example.json targets.json
   ```
   Edita `targets.json` adaptando los UIDs de dashboard, IDs de panel, canales de Telegram y variables de push opcionales:
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
       "scale": 2,
       "push_urls_env": [
         "UPTIME_KUMA_1",
         "UPTIME_KUMA_2",
         "CRONITOR_URL"
       ]
     }
   }
   ```

   > **Notas opcionales:**
   > * `push_urls_env` admite de `0` a `N` nombres de variables definidas en `.env`. Si se omite o se deja vacío (`[]`), no se enviará ninguna notificación push.
   > * Si deseas utilizar un bot de Telegram distinto para un target concreto, añade `"bot_token_env": "OTRA_VARIABLE_EN_ENV"` dentro de su bloque en `targets.json`.

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

# Probar el renderizado sin enviar nada a Telegram ni ejecutar pushes
/opt/grafanagram/grafanagram.py --all --range 6h --dry-run
```

### Opciones CLI

| Argumento | Descripción | Valor por defecto |
| :--- | :--- | :--- |
| `-t`, `--target` | Nombre del target definido en `targets.json`. | *Requerido (o `--all`)* |
| `--all` | Procesa secuencialmente todos los targets de `targets.json`. | `False` |
| `-r`, `--range` | Ventana de tiempo hacia atrás (`6h`, `12h`, `24h`, `7d`, `30d`). | `6h` |
| `-c`, `--config` | Ruta alternativa al fichero de configuración JSON. | `./targets.json` |
| `--dry-run` | Renderiza las imágenes pero omite el envío a Telegram y los pings push. | `False` |

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

## Licencia

MIT
