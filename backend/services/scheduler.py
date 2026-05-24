import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

from config import settings

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=settings.apscheduler_timezone)

_task_executor = None


def set_task_executor(executor):
    global _task_executor
    _task_executor = executor


class TaskScheduler:
    _db_factory = None

    @classmethod
    def set_db_factory(cls, db_factory):
        cls._db_factory = db_factory

    @staticmethod
    def start():
        if not scheduler.running:
            scheduler.start()
            logger.info("Task scheduler started")

    @staticmethod
    def shutdown():
        if scheduler.running:
            scheduler.shutdown()
            logger.info("Task scheduler shutdown")

    async def schedule_task_start(
        self, instance_id: str, run_time: datetime
    ) -> bool:
        job_id = f"start_{instance_id}"
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)

        def _run_start():
            import asyncio
            from database import async_session_maker
            from services.dag_executor import DAGExecutor

            async def _do_start():
                async with async_session_maker() as db:
                    executor = DAGExecutor(db)
                    await executor.execute_dag_start(instance_id)

            asyncio.create_task(_do_start())

        scheduler.add_job(
            _run_start,
            trigger=DateTrigger(run_date=run_time),
            id=job_id,
            replace_existing=True,
        )
        logger.info(f"Scheduled task start for {instance_id} at {run_time}")
        return True

    async def schedule_task_end(
        self, instance_id: str, end_time: datetime
    ) -> bool:
        job_id = f"end_{instance_id}"
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)

        def _run_stop():
            import asyncio
            from database import async_session_maker
            from services.dag_executor import DAGExecutor

            async def _do_stop():
                async with async_session_maker() as db:
                    executor = DAGExecutor(db)
                    await executor.execute_dag_stop(instance_id)

            asyncio.create_task(_do_stop())

        scheduler.add_job(
            _run_stop,
            trigger=DateTrigger(run_date=end_time),
            id=job_id,
            replace_existing=True,
        )
        logger.info(f"Scheduled task end for {instance_id} at {end_time}")
        return True

    async def cancel_scheduled_start(self, instance_id: str) -> None:
        job_id = f"start_{instance_id}"
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)

    async def cancel_scheduled_end(self, instance_id: str) -> None:
        job_id = f"end_{instance_id}"
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)

    async def cancel_all_schedules(self, instance_id: str) -> None:
        await self.cancel_scheduled_start(instance_id)
        await self.cancel_scheduled_end(instance_id)
