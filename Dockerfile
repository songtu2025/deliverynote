FROM python:3.11-slim@sha256:e41613d42d4891e4930f79523f93f81bbc7632584ec65e36ab055f41a800b41e

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY delivery_note ./delivery_note

EXPOSE 8000
CMD ["uvicorn", "delivery_note.web.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
