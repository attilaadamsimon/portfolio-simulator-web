FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home appuser && mkdir -p /app/.cache && chown -R appuser:appuser /app
USER appuser
ENV PORT=8050 DEMO_ONLY=1
EXPOSE 8050
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-8050} --workers 1 --threads 8 --timeout 180 app:app"]
