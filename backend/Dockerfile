# 1. Python base image
FROM python:3.11-slim

# 2. Sistem paketlerini kur (ffmpeg dahil)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 3. Çalışma dizini
WORKDIR /app

# 4. Python bağımlılıkları
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Projeyi kopyala
COPY . .

# 6. Uygulama başlatma komutu
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "$PORT"]