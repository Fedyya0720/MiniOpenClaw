FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    # Core agent dependencies
    ripgrep \
    git \
    curl \
    ca-certificates \
    # Build toolchain for Python packages with C extensions
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["tail", "-f", "/dev/null"]
