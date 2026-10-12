# Pinned by digest so every build starts from the same image; Dependabot proposes updates.
FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY content ./content

# Run as a non-root user; deploy/install.sh gives this UID ownership of the data folder.
RUN useradd --uid 1000 --no-create-home --shell /usr/sbin/nologin app
USER 1000

# Commit being deployed, reported by /health (set by deploy/update.sh).
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

VOLUME ["/data"]
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
