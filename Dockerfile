FROM python:3.11-slim

WORKDIR /app

# System dependencies for pycryptodome
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files
COPY . .

# Render uses PORT env var (default 10000)
EXPOSE 10000

# Start bot + dashboard
CMD ["python", "krll3.py"]