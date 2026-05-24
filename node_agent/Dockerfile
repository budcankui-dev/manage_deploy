FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi "uvicorn[standard]" docker httpx pydantic pydantic-settings

COPY pyproject.toml .
COPY config.py .
COPY docker_handler.py .
COPY health_checks.py .
COPY main.py .

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]