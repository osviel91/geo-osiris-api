FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY publisher.py ./

# Non-root runtime; stdlib only, so no dependency install is needed.
RUN useradd --create-home --uid 10002 publisher

USER publisher

ENTRYPOINT ["python", "/app/publisher.py"]
