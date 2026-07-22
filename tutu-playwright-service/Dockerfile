FROM mcr.microsoft.com/playwright/python:v1.54.0-jammy
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV PORT=8000 TUTU_PLAYWRIGHT_ENABLED=false TUTU_PLAYWRIGHT_HEADLESS=true
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
