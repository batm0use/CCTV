FROM python:3.11-slim-bookworm

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd -r sync-agent
USER sync-agent

CMD ["python3", "manage.py", "run-sync"]
