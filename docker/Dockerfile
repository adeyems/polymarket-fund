FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create data and logs directories
RUN mkdir -p sovereign_hive/data sovereign_hive/logs

# Default command (overridden per service in docker-compose)
CMD ["python", "-u", "sovereign_hive/run_simulation.py"]
