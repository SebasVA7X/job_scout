FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libssl-dev \
    libxml2-dev \
    libxslt1-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY JobScout_Docker .

RUN mkdir -p /app/data /app/logs \
    && useradd -m -u 1000 scraper \
    && chown -R scraper:scraper /app

USER scraper

CMD ["python", "-m", "scheduler.main"]