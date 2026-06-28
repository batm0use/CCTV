# CCTV

Self-hosted CCTV system on a Raspberry Pi 4B. 24/7 H.264 recording, MJPEG live stream, web footage browser, and automatic backup sync to a laptop.

## Repository layout

```
rpi/      — everything that runs on the Raspberry Pi (recorder + web server + storage manager)
laptop/   — laptop sync agent (downloads footage from RPi via HTTP)
```

Each directory is an independent deployable with its own `Dockerfile`, `docker-compose` file, `requirements.txt`, and config example. They share no Python code.

---

## RPi setup (`rpi/`)

### Prerequisites
- Raspberry Pi OS Bookworm 64-bit, headless
- Docker and Docker Compose installed
- `dtoverlay=imx219` in `/boot/firmware/config.txt`
- Camera enabled and verified with `rpicam-hello`

### Deploy

```bash
git clone git@github.com:batm0use/CCTV.git /home/pi/cctv
cd /home/pi/cctv/rpi

cp cctv.conf.example cctv.conf
# Edit cctv.conf — set resolution, fps, and storage thresholds

docker compose -f docker-compose.rpi.yml up -d
```

Logs: `docker compose -f docker-compose.rpi.yml logs -f`

### Access
- Live view: `http://<rpi-ip>:8080/live`
- Footage browser: `http://<rpi-ip>:8080/footage`
- Status JSON: `http://<rpi-ip>:8080/api/status`

Via RPi Connect: use the URL provided in your RPi Connect dashboard.

### Storage
Footage is stored in a named Docker volume at `/var/lib/cctv/footage/YYYY/MM/DD/`.

Default config records at 720p 15fps (~8.6 GB/day). At 90% disk usage (~57 GB on a 64 GB card) the storage manager begins deleting the oldest segments that have been confirmed synced by the laptop agent.

---

## Laptop setup (`laptop/`)

The sync agent polls the RPi API, downloads new segments via HTTP, and confirms receipt. No SSH server is needed on the laptop.

### Deploy

```bash
cd /path/to/cctv/laptop

cp sync.conf.example sync.conf
# Edit sync.conf — set rpi_base_url and local_footage_dir

# Set your local footage backup directory
export LOCAL_FOOTAGE_DIR=/Users/yourname/cctv-backup

docker compose -f docker-compose.laptop.yml up -d
```

The agent runs every 5 minutes (configurable). When more than 50 segments are unsynced it downloads up to 20 per cycle; when caught up it downloads 1 per cycle.

---

## Branch strategy

| Branch | Purpose |
|--------|---------|
| `main` | Stable — only updated from `triage` after system testing |
| `triage` | Integration — features merge here frequently |
| `feature/*` | One branch per feature; merged into `triage` |
