FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Run as a non-root user; deploy/install.sh gives this UID ownership of the data folder.
RUN useradd --uid 1000 --no-create-home --shell /usr/sbin/nologin app
USER 1000

# Commit being deployed, reported by /health (set by deploy/update.sh).
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

VOLUME ["/data"]
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
