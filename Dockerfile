FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ripgrep \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["tail", "-f", "/dev/null"]
