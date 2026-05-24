FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi "uvicorn[standard]" sqlalchemy pydantic pydantic-settings apscheduler docker alembic python-multipart httpx aiomysql PyMySQL

COPY pyproject.toml .
COPY *.py .
COPY agents/ agents/
COPY api/ api/
COPY models/ models/
COPY schemas/ schemas/
COPY services/ services/

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]