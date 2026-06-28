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
# Expected: "0 : imx219 [3280x2464 ...]"
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
cd ~/CCTV/rpi
sudo docker compose -f docker-compose.rpi.yml up -d
```

On first run Docker builds the image (~5 minutes, downloads picamera2 and dependencies from the Raspberry Pi apt repository).

### 5 — Verify

```bash
sudo docker compose -f docker-compose.rpi.yml logs -f
```

Expected output once healthy:

```
cctv-storage-1  | INFO storage.manager: Storage manager started (delete threshold: 90%)
cctv-main-1     | INFO:     Uvicorn running on http://0.0.0.0:8080
cctv-main-1     | INFO recorder.recorder: Camera started at (1280, 720)
cctv-main-1     | INFO recorder.recorder: Started segment 2026-06-28_23-02-49.mp4
```

---

## Accessing the web UI

### On the local network

| URL | What you get |
|-----|-------------|
| `http://<rpi-ip>:8080/live` | MJPEG live stream |
| `http://<rpi-ip>:8080/footage` | Paginated footage browser with video playback |
| `http://<rpi-ip>:8080/api/status` | JSON — disk usage + unsynced segment count |
| `http://<rpi-ip>:8080/api/all_segment` | JSON — list of unsynced segments |
| `http://<rpi-ip>:8080/api/all_segment/count` | JSON — `{"count": N}` |

Find your RPi's IP with `hostname -I` on the Pi.

### Via RPi Connect (remote access from anywhere)

RPi Connect provides a secure HTTPS tunnel to your Pi with no port forwarding or VPN required.

1. On the RPi, install and enable RPi Connect:
   ```bash
   sudo apt install rpi-connect
   rpi-connect on
   ```

2. Sign in with your Raspberry Pi ID:
   ```bash
   rpi-connect signin
   ```
   This prints a URL — open it in your browser and sign in.

3. Open [connect.raspberrypi.com](https://connect.raspberrypi.com) in any browser. Your Pi appears in the device list.

4. Click **Remote shell** to get a terminal, or use the **Port forwarding** feature to access the web UI:
   - Under your device, add a remote port forward for port `8080`
   - The dashboard gives you a unique HTTPS URL like `https://connect.raspberrypi.com/v/xxxxx`
   - Open that URL to reach `/live`, `/footage`, and the API from anywhere

RPi Connect uses your Raspberry Pi account as authentication — no extra credentials to manage.

---

## Day-to-day commands (run on the RPi)

### Start / stop

```bash
cd ~/CCTV/rpi

sudo docker compose -f docker-compose.rpi.yml up -d      # start in background
sudo docker compose -f docker-compose.rpi.yml down       # stop
sudo docker compose -f docker-compose.rpi.yml restart    # restart both containers
```

### Logs

```bash
sudo docker compose -f docker-compose.rpi.yml logs -f              # follow all logs
sudo docker compose -f docker-compose.rpi.yml logs -f cctv-main    # recorder + web only
sudo docker compose -f docker-compose.rpi.yml logs -f cctv-storage # storage manager only
sudo docker compose -f docker-compose.rpi.yml logs --tail 50       # last 50 lines
```

### Update code

```bash
cd ~/CCTV/rpi
git pull
sudo docker compose -f docker-compose.rpi.yml up -d --build
```

If the Dockerfile changed (new apt packages, etc.) add `--no-cache` to force a full rebuild:

```bash
sudo docker compose -f docker-compose.rpi.yml build --no-cache
sudo docker compose -f docker-compose.rpi.yml up -d
```

### Container status

```bash
sudo docker compose -f docker-compose.rpi.yml ps        # running containers
sudo docker stats                                        # live CPU / RAM / network
```

### Inspect footage volume

```bash
sudo docker run --rm -v rpi_footage_data:/footage debian:bookworm-slim ls /footage
```

### Camera check (outside Docker)

```bash
rpicam-still --list-cameras        # verify camera is detected
rpicam-still -o /tmp/test.jpg      # capture a test frame
```

---

## Storage

Footage is stored in a named Docker volume at `/var/lib/cctv/footage/YYYY/MM/DD/`.

At 90% disk usage (~57 GB on a 64 GB card) the storage manager deletes the oldest segments already confirmed synced by the laptop agent. Segments not yet synced are never deleted regardless of disk pressure.

---

## Troubleshooting

**`IsADirectoryError: /app/cctv.conf`** — Docker created a directory because `cctv.conf` was missing when the container first started:

```bash
sudo docker compose -f docker-compose.rpi.yml down
rm -rf ~/CCTV/rpi/cctv.conf
cp ~/CCTV/rpi/cctv.conf.example ~/CCTV/rpi/cctv.conf
sudo docker compose -f docker-compose.rpi.yml up -d
```

**`IndexError: list index out of range` in Picamera2** — libcamera can't see the camera. Check host first:

```bash
rpicam-still --list-cameras
```

If it shows the camera on the host but not in Docker, ensure `docker-compose.rpi.yml` mounts `/dev` and `/run/udev` (already the case in current config).

**`sqlite3.OperationalError: unable to open database file`** — volume permission issue. The container must run as root — check there is no `USER` directive in the Dockerfile.

**`permission denied while trying to connect to the Docker API`** — prefix with `sudo`, or ensure your user is in the `docker` group:

```bash
sudo usermod -aG docker $USER
newgrp docker
```

**Old code still running after `git pull`** — force a rebuild:

```bash
sudo docker compose -f docker-compose.rpi.yml build --no-cache
sudo docker compose -f docker-compose.rpi.yml up -d
```

---

## Laptop sync (`laptop/`)

The sync agent polls the RPi API, downloads new segments via HTTP, and confirms receipt. No SSH server is needed on the laptop.

```bash
cd /path/to/CCTV/laptop
cp sync.conf.example sync.conf
# Edit sync.conf — set rpi_base_url and local_footage_dir

docker compose -f docker-compose.laptop.yml up -d
```

The agent runs every 5 minutes (configurable). When more than 50 segments are unsynced it downloads up to 20 per cycle; when caught up it downloads 1 per cycle. Batch size is capped by available disk space.
