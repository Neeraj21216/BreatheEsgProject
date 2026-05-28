# Build the frontend first
FROM node:20-bullseye AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# Build the backend container
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist
ENV PYTHONPATH=/app/BreathESG
ENV DJANGO_SETTINGS_MODULE=settings
RUN python BreathESG/manage.py collectstatic --noinput
EXPOSE 10000
CMD ["sh", "-c", "python BreathESG/manage.py migrate --noinput && gunicorn breathesg.wsgi:application --bind 0.0.0.0:${PORT:-10000}"]
