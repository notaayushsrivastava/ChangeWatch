# The official Playwright image includes a compatible Chromium build and Linux dependencies.
FROM node:20-alpine AS assets
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build:css

FROM mcr.microsoft.com/playwright/python:v1.63.0-noble AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --upgrade pip && python -m pip install -r requirements.txt

COPY . .
COPY --from=assets /app/app/static/dist/app.css /app/app/static/dist/app.css

RUN mkdir -p /app/data/artifacts
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
