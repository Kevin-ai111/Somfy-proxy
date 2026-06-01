FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    wget gnupg \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libasound2 \
    libpango-1.0-0 libcairo2 libx11-6 libxext6 \
    libxrender1 libxi6 libxtst6 \
    fonts-liberation fonts-dejavu-core \
    --no-install-recommends && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Chromium ohne --with-deps (Deps bereits oben installiert)
RUN playwright install chromium

COPY server.py .

CMD ["python", "server.py"]
