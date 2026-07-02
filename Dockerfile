FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VIDEOFLOW_HOSTED=1 \
    PORT=5000 \
    DENO_INSTALL=/usr/local \
    VIDEOFLOW_DISABLE_HARDWARE_ENCODERS=1 \
    VIDEOFLOW_MIRROR_THREADS=1 \
    VIDEOFLOW_MIRROR_PRESET=ultrafast

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deno.land/install.sh | sh \
    && deno --version

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["sh", "-c", "waitress-serve --listen=0.0.0.0:${PORT:-5000} app:app"]
