FROM python:3.12-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1

CMD ["sh", "-c", "atlas ui --port ${PORT:-8080} --no-browser"]