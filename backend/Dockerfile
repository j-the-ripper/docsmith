FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# System deps:
#   * WeasyPrint runtime: pango / cairo / gdk-pixbuf / harfbuzz / ffi
#   * fonts-noto-core: provides "Noto Sans Gujarati" (resolved by name via fontconfig)
#   * tesseract + guj/eng language data: OCR fallback for legacy-font / scanned pages
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libpangoft2-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libffi8 \
        libharfbuzz0b \
        fonts-noto-core \
        tesseract-ocr \
        tesseract-ocr-guj \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Extra document fonts bundled with the repo (e.g. Rasa, OFL-licensed) —
# installed system-wide so fontconfig/WeasyPrint resolve them by family name.
COPY fonts/ /usr/share/fonts/truetype/docsmith/
RUN fc-cache -f

COPY app ./app

RUN mkdir -p /data
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
