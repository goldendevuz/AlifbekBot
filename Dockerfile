FROM python:3.12-slim

# Prevent python from writing .pyc files and enable unbuffered output for real-time logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Create non-root system user and prepare /data directory for SQLite persistence
RUN groupadd -r appuser && useradd -r -u 1000 -g appuser -d /app appuser && \
    mkdir -p /data && \
    chown -R appuser:appuser /app /data

# Copy requirements separately to maximize Docker layer caching
COPY requirements.txt .

# Install dependencies cleanly without caching wheels
RUN pip install --no-cache-dir -r requirements.txt

# Copy application modules, static assets, and entrypoint
COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser static/ ./static/
COPY --chown=appuser:appuser bot.py .

# Switch to non-root user
USER appuser

EXPOSE 8000

# Healthcheck checking the FastAPI /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1

CMD ["python", "bot.py"]
