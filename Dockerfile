FROM python:3.11-slim

# System-Abhängigkeiten für Playwright/Chromium
RUN apt-get update && apt-get install -y \
    wget curl gnupg \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libasound2 \
    libpango-1.0-0 libcairo2 libx11-6 libxext6 \
    libxrender1 libxi6 libxtst6 fonts-liberation \
    --no-install-recommends && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium --with-deps

COPY server.py .

CMD ["python", "server.py"]
