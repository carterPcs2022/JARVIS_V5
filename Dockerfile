# Upgrade to 3.13-slim to match your runtime telemetry
FROM python:3.13-slim

WORKDIR /app

# Consolidated system dependencies (added gcc/make/python3-dev for psutil compilation if needed)
# curl is required for the Docker healthcheck in docker-compose.yml
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    libffi-dev \
    libssl-dev \
    libsndfile1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency matrix early to leverage build caching
COPY requirements.txt .

# Upgrade pip and install directly into the container environment
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Create necessary directories
RUN mkdir -p memory data backups config logs

# Aligned with your system logs (Port 8080 / app.py entrypoint)
EXPOSE 8080

# Calling your actual app script which handles the uvicorn.run mapping
CMD ["python", "app.py"]