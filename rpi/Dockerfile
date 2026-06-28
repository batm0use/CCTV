FROM debian:bookworm-slim AS base

# Install system deps: libcamera/picamera2 (must come from apt, not pip)
# and Python 3.11 which ships with Bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-picamera2 \
        python3-libcamera \
        python3-kms++ \
        python3-pyqt5 \
        libcamera-tools \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies into the system Python (venv not used because
# picamera2 is only available as a system package)
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

COPY . .

# Run as non-root where possible; camera group grants /dev/video* access
RUN groupadd -r cctv && useradd -r -g cctv -G video cctv
USER cctv

EXPOSE 8080

CMD ["python3", "manage.py", "run-main"]
