FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY delivery_note ./delivery_note

EXPOSE 8000
CMD ["uvicorn", "delivery_note.web.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
