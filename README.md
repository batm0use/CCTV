# CCTV

Self-hosted CCTV system on a Raspberry Pi 4B. 24/7 H.264/H.265 recording, web footage browser, motion detection with push notifications, and optional backup sync to a laptop.

## Hardware

| Component | Why this choice |
|-----------|----------------|
| **Raspberry Pi 4B** | Four Cortex-A72 cores and 1–8 GB RAM handle continuous recording, FFmpeg post-processing, the web server, and the MJPEG stream simultaneously without contention. The 3B+ (1 GB RAM) degrades noticeably under load when a footage download and a live stream are both active. The RPi 5 works but costs more and draws more power for a device that runs 24/7. |
| **IMX219 camera (e.g. Freenove 8MP)** | The IMX219 is the same sensor as the official Raspberry Pi Camera Module v2. It is natively supported by libcamera with a single `dtoverlay=imx219` line — no calibration files, no driver compilation. At 720p the 8 MP sensor applies 2×2 pixel binning, which improves low-light performance. Any IMX219-based camera (official Pi cam v2, Arducam 8MP, Freenove) works identically. |
| **microSD card (64 GB or larger)** | At the default 200 Kbps bitrate, one day of continuous footage takes ~2.2 GB. A 64 GB card holds approximately 26 days before the storage manager starts cycling old recordings; a 256 GB card gives ~118 days. Size matters less than speed class: use an **A1 or A2 rated card** (e.g. SanDisk Endurance, Kingston Canvas Go). The recorder writes many small segment files rather than one sequential stream — A1/A2 cards are optimised for this random-write pattern and are significantly more durable for a 24/7 workload than cheaper cards. |
| **Raspberry Pi OS Bookworm 64-bit, headless** | 64-bit is required for Docker. The `python3-picamera2` apt package is maintained exclusively for Raspberry Pi OS — on other distros you would need to build picamera2 from source. Bookworm (Debian 12) is the current stable release. The headless image omits the desktop environment, saving ~1 GB of storage and reducing idle CPU and RAM usage. |

## Repository layout

```
rpi/      — everything that runs on the Raspberry Pi (recorder + web server + storage manager)
laptop/   — laptop sync agent (downloads footage from RPi via HTTP)
```

Each directory is an independent deployable with its own `Dockerfile`, `docker-compose` file, `requirements.txt`, and config example. They share no Python code.

---

> **Security warning** — The web interface has no login. Anyone who can reach port 8080 can browse, stream, download, and delete all footage. **Never port-forward port 8080 directly to the internet.** For remote access, use RPi Connect (see [Remote access](#remote-access)), a VPN, or a reverse proxy with authentication in front.

---

## RPi setup

### Hardware requirements

- Raspberry Pi 4B (2 GB RAM or more recommended)
- IMX219-based camera module (see [Hardware](#hardware))
- 64 GB microSD card, A1/A2 rated (see [Hardware](#hardware))
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
git clone https://github.com/batm0use/CCTV.git ~/CCTV
cd ~/CCTV/rpi
cp cctv.conf.example cctv.conf
```

Edit `cctv.conf` to suit your setup. The defaults record at 720p 15 fps at 200 Kbps (~2.2 GB/day). See [Configuration](#configuration) for all options.

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

## Web UI

Open `http://<rpi-ip>:8080/footage` in a browser on the same network. Find your RPi's IP with `hostname -I` on the Pi.

| URL | What you get |
|-----|-------------|
| `http://<rpi-ip>:8080/footage` | Paginated footage browser with in-browser video playback |
| `http://<rpi-ip>:8080/live` | MJPEG live view (updates every ~200 ms) |
| `http://<rpi-ip>:8080/api/status` | JSON — disk usage and unsynced segment count |

### Remote access

RPi Connect provides a secure HTTPS tunnel with no port forwarding or VPN required.

1. Install and enable RPi Connect on the RPi:
   ```bash
   sudo apt install rpi-connect
   rpi-connect on
   ```

2. Sign in:
   ```bash
   rpi-connect signin
   ```
   This prints a URL — open it in your browser and sign in with your Raspberry Pi account.

3. Open [connect.raspberrypi.com](https://connect.raspberrypi.com). Your Pi appears in the device list. Use **Remote shell** for a terminal, or **Port forwarding** (forward port `8080`) to access the web UI from anywhere over HTTPS.

---

## Configuration

Copy `cctv.conf.example` to `cctv.conf` and edit. The file is gitignored and never committed. Key options:

### Recording bitrate and encoder

```toml
[recording]
bitrate_bps = 200000   # 200 Kbps — see storage table below
encoder = "h264"       # "h264" or "h265"
```

`h264` plays back in every browser with no plugins. `h265` gives noticeably better quality at the same bitrate (or equivalent quality at roughly half the bitrate), but Firefox support is partial and older Android devices may not decode it. Test `h265` on real hardware before a long unattended deployment.

### Storage and retention

```toml
[storage]
delete_threshold_pct = 90            # delete oldest segments when disk exceeds this %
require_synced_for_deletion = false  # true  = only delete after laptop confirms download
                                     # false = standalone mode, delete by age
```

Set `require_synced_for_deletion = false` if you are **not** running the laptop sync agent. In standalone mode the storage manager deletes the oldest recordings by age once the disk threshold is reached. With `true` (default), segments are never deleted until the laptop agent confirms it downloaded a copy — useful when you want a guarantee that every segment is backed up before it disappears.

**Storage sizing**

| Bitrate | GB/day | 64 GB card | 256 GB card |
|---------|--------|-----------|------------|
| 100 Kbps | ~1.1 | ~52 days | ~210 days |
| 150 Kbps | ~1.6 | ~35 days | ~145 days |
| 200 Kbps (default) | ~2.2 | ~26 days | ~105 days |
| 1 Mbps | ~10.8 | ~5 days | ~21 days |

*Days are calculated at the 90% disk threshold. Actual compression varies with scene complexity — a static indoor shot compresses much better than outdoors with wind-moved foliage.*

---

## Motion detection and push notifications

Motion detection runs on the existing 640×360 lores preview stream — no additional camera resources are consumed.

### Enable in `cctv.conf`

```toml
[motion]
enabled = true
pixel_diff_threshold = 25      # per-pixel luminance change that counts as movement (0–255)
                               # 25 works well indoors; raise to ~40 outdoors to reduce
                               # false positives from shifting natural light or wind
motion_ratio_threshold = 0.02  # fraction of pixels that must change (0.02 = 2%)
cooldown_seconds = 60          # minimum seconds between notifications
ntfy_topic = "my-cctv-home"   # your chosen topic name — keep it unguessable
ntfy_server = "https://ntfy.sh"
```

After editing, restart the containers:

```bash
sudo docker compose -f docker-compose.rpi.yml restart
```

### Receiving notifications

[ntfy.sh](https://ntfy.sh) is a free, no-account push notification service. You subscribe to a topic by name — anyone who knows the topic name can publish to it, so treat it like a password and pick something unguessable (e.g. `home-cctv-a7f2k9`).

**iOS / Android** — install the [ntfy app](https://ntfy.sh/#subscribe-phone), tap **+**, enter your topic name. Notifications appear as push alerts.

**macOS / desktop** — open `https://ntfy.sh/<your-topic>` in Chrome or Firefox and click **Allow** when the browser asks for notification permission. You can also install the page as a PWA (Chrome: address bar → install icon). Notifications arrive as system banners.

Notifications work from any network — the RPi posts to ntfy.sh over the internet, and your phone or laptop receives them via the ntfy service regardless of which network either device is on.

### How detection works

Every preview frame (~5× per second) the Y-plane (luminance) of the lores frame is compared to the previous one using numpy. If more than `motion_ratio_threshold` of pixels changed by more than `pixel_diff_threshold` intensity units, motion is declared and a notification is sent — at most once per `cooldown_seconds`, regardless of how much motion continues.

---

## Managing footage

### Footage browser

The footage browser at `/footage` shows all completed recordings newest-first with in-browser playback. When recordings exist, a **Delete all footage from RPi** button appears at the top. A confirmation dialog appears before anything is deleted.

Deleting footage from the RPi does **not** affect videos already downloaded to the laptop — the laptop stores its own copy independently.

### Footage volume

Footage is stored in a named Docker volume at `/var/lib/cctv/footage/YYYY/MM/DD/`. To inspect it from the host:

```bash
sudo docker run --rm -v rpi_footage_data:/footage debian:bookworm-slim ls /footage
```

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

### Camera check (outside Docker)

```bash
rpicam-still --list-cameras        # verify camera is detected
rpicam-still -o /tmp/test.jpg      # capture a test frame
```

---

## Laptop sync (`laptop/`)

The sync agent polls the RPi API, downloads new segments via HTTP, and marks them as synced. No SSH is required.

```bash
cd /path/to/CCTV/laptop
cp sync.conf.example sync.conf
# Edit sync.conf — set rpi_base_url and local_footage_dir

docker compose -f docker-compose.laptop.yml up -d       # start
docker compose -f docker-compose.laptop.yml logs -f     # follow logs
docker compose -f docker-compose.laptop.yml down        # stop
```

The agent polls every 5 minutes (configurable). When more than 50 segments are unsynced it downloads up to 20 per cycle; when nearly caught up it downloads 1 per cycle. Batch size is also capped by available disk space.

If you are not running the laptop sync agent, set `require_synced_for_deletion = false` in `cctv.conf` so the storage manager can cycle old recordings. See [Configuration](#configuration).

### macOS with Colima

Colima does not bundle the Docker Compose plugin. Install it once:

```bash
brew install docker-compose
mkdir -p ~/.docker/cli-plugins
ln -sfn $(brew --prefix)/opt/docker-compose/bin/docker-compose ~/.docker/cli-plugins/docker-compose
```

Verify with `docker compose version`, then run the commands above normally.

---

## Troubleshooting

**`IsADirectoryError: /app/cctv.conf`** — Docker created a directory because `cctv.conf` was missing when the container first started:

```bash
sudo docker compose -f docker-compose.rpi.yml down
rm -rf ~/CCTV/rpi/cctv.conf
cp ~/CCTV/rpi/cctv.conf.example ~/CCTV/rpi/cctv.conf
sudo docker compose -f docker-compose.rpi.yml up -d
```

**`IndexError: list index out of range` in Picamera2** — libcamera cannot see the camera. Check on the host first:

```bash
rpicam-still --list-cameras
```

If it shows the camera on the host but not inside Docker, ensure `docker-compose.rpi.yml` mounts `/dev` and `/run/udev` (already the case in the current config).

**`ImportError: cannot import name 'H265Encoder'`** — the apt-installed picamera2 version on your RPi is older and does not export `H265Encoder`. Set `encoder = "h264"` in `cctv.conf` (the default). H.265 requires a newer picamera2 build.

**`sqlite3.OperationalError: unable to open database file`** — volume permission issue. The container must run as root — check there is no `USER` directive in the Dockerfile.

**`permission denied while trying to connect to the Docker API`** — prefix with `sudo`, or ensure your user is in the `docker` group:

```bash
sudo usermod -aG docker $USER
newgrp docker
```

**Old code still running after `git pull`** — force a full rebuild:

```bash
sudo docker compose -f docker-compose.rpi.yml build --no-cache
sudo docker compose -f docker-compose.rpi.yml up -d
```

**Motion notifications stopped arriving** — check the logs for ntfy errors:

```bash
sudo docker compose -f docker-compose.rpi.yml logs cctv-main | grep ntfy
```

Common causes: the RPi lost internet access (restart containers once the network is back), or ntfy.sh is rate-limiting the topic (increase `cooldown_seconds`).

---

## License

MIT — see [LICENSE](LICENSE).
