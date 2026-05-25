import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import init_db
from api import (
    auth_router,
    business_tasks_router,
    conversations_router,
    instances_router,
    nodes_router,
    orders_router,
    routing_router,
    templates_router,
)
from services.scheduler import TaskScheduler, restore_pending_jobs

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting application...")
    await init_db()
    TaskScheduler.start()
    try:
        await restore_pending_jobs()
    except Exception:
        logger.exception("Failed to restore scheduled jobs on startup")
    yield
    logger.info("Shutting down application...")
    TaskScheduler.shutdown()


app = FastAPI(
    title="Task Manager",
    description="Docker DAG Task Orchestration System",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(nodes_router)
app.include_router(templates_router)
app.include_router(instances_router)
app.include_router(orders_router)
app.include_router(business_tasks_router)
app.include_router(auth_router)
app.include_router(conversations_router)
app.include_router(routing_router)


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
