# Small, production-friendly image with the libs WeasyPrint needs
FROM python:3.11-slim

# System packages for WeasyPrint (HTML → PDF)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 libffi8 libxml2 libxslt1.1 \
    fonts-dejavu-core fonts-noto-core fonts-noto-cjk \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
