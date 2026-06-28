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

### Hardware requirements

- Raspberry Pi 4B
- Freenove 8MP IMX219 camera module
- 64 GB microSD (or larger)
- Raspberry Pi OS Bookworm 64-bit, headless

### 1 — OS preparation

Enable the IMX219 camera by adding this line to `/boot/firmware/config.txt`:

```
dtoverlay=imx219
```

Reboot, then verify the camera is detected:

```bash
rpicam-still --list-cameras
# Expected output: "0 : imx219 [3280x2464 ...]"
```

### 2 — Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
```

Verify:

```bash
docker --version
docker compose version
```

### 3 — Clone and configure

```bash
git clone git@github.com:batm0use/CCTV.git ~/CCTV
cd ~/CCTV/rpi
cp cctv.conf.example cctv.conf
```

Edit `cctv.conf` as needed. Defaults record at 720p 15fps (~8.6 GB/day, 7 days on a 64 GB card).

### 4 — Start

```bash
sudo docker compose -f docker-compose.rpi.yml up -d
```

On first run Docker builds the image (~5 minutes, downloads picamera2 and dependencies from the Raspberry Pi apt repository).

### 5 — Check logs

```bash
sudo docker compose -f docker-compose.rpi.yml logs -f
```

Expected output once running:

```
cctv-storage-1  | INFO storage.manager: Storage manager started (delete threshold: 90%)
cctv-main-1     | INFO:     Uvicorn running on http://0.0.0.0:8080
cctv-main-1     | INFO recorder.recorder: Camera started at (1280, 720)
cctv-main-1     | INFO recorder.recorder: Started segment 2026-06-28_22-00-00.mp4
```

### Access

| URL | Description |
|-----|-------------|
| `http://<rpi-ip>:8080/live` | MJPEG live stream |
| `http://<rpi-ip>:8080/footage` | Recorded footage browser |
| `http://<rpi-ip>:8080/api/status` | JSON status (disk, unsynced count) |

Via RPi Connect: use the HTTPS URL from your RPi Connect dashboard — no port forwarding needed.

### Stop / restart

```bash
sudo docker compose -f docker-compose.rpi.yml down   # stop
sudo docker compose -f docker-compose.rpi.yml up -d  # start
```

After a `git pull` that changes the `Dockerfile` or Python code, add `--build` to force a rebuild:

```bash
sudo docker compose -f docker-compose.rpi.yml up -d --build
```

Containers restart automatically on reboot (`restart: unless-stopped`).

### Storage

Footage is stored in a named Docker volume at `/var/lib/cctv/footage/YYYY/MM/DD/`.

At 90% disk usage (~57 GB on a 64 GB card) the storage manager deletes the oldest segments that have already been confirmed synced by the laptop agent. Segments not yet synced are never deleted regardless of disk pressure.

### Troubleshooting

**`IsADirectoryError: /app/cctv.conf`** — Docker created a directory because `cctv.conf` was missing on the host when the container started:

```bash
sudo docker compose -f docker-compose.rpi.yml down
rm -rf ~/CCTV/rpi/cctv.conf
cp ~/CCTV/rpi/cctv.conf.example ~/CCTV/rpi/cctv.conf
sudo docker compose -f docker-compose.rpi.yml up -d
```

**`IndexError: list index out of range` in Picamera2** — libcamera can't enumerate cameras inside the container. Verify the camera works on the host first:

```bash
rpicam-still --list-cameras
```

If the camera appears on the host but not in Docker, ensure the compose file mounts `/dev` and `/run/udev` (already the case in the current `docker-compose.rpi.yml`).

**`sqlite3.OperationalError: unable to open database file`** — the container can't write to the `state_data` volume. The container must run as root (already the case); check that no `USER` directive is set in the Dockerfile.

**`docker: command not found`** — Docker is not installed. Follow step 2 above.

**`permission denied while trying to connect to the Docker API`** — run with `sudo`, or add your user to the `docker` group (step 2) and open a new shell.

---

## Laptop setup (`laptop/`)

The sync agent polls the RPi API, downloads new segments via HTTP, and confirms receipt. No SSH server is needed on the laptop.

### Deploy

```bash
cd /path/to/CCTV/laptop
cp sync.conf.example sync.conf
# Edit sync.conf — set rpi_base_url and local_footage_dir

docker compose -f docker-compose.laptop.yml up -d
```

The agent runs every 5 minutes (configurable). When more than 50 segments are unsynced it downloads up to 20 per cycle; when caught up it downloads 1 per cycle. Batch size is capped by available disk space.
