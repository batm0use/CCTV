FROM debian:bookworm-slim AS base

# Add the Raspberry Pi package repository — picamera2/libcamera are not in
# standard Debian repos, only in the RPi archive.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
    && curl -fsSL https://archive.raspberrypi.com/debian/raspberrypi.gpg.key \
       | gpg --dearmor -o /usr/share/keyrings/raspberrypi-archive-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/raspberrypi-archive-keyring.gpg] \
       http://archive.raspberrypi.com/debian/ bookworm main" \
       > /etc/apt/sources.list.d/raspberrypi.list \
    && apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-picamera2 \
        python3-libcamera \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies into the system Python (no venv because
# picamera2 is only available as a system package and must be importable).
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["python3", "manage.py", "run-main"]
