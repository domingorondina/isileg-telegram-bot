# Imagen base liviana de Python
FROM python:3.13-slim

WORKDIR /app

# Instalar certificados CA
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copiar requerimientos e instalar dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código del bot
COPY . .

ENV PORT=8080
EXPOSE 8080

CMD ["python", "bot.py"]
