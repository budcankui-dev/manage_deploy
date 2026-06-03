import logging
from datetime import datetime, UTC

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import select
from sqlalchemy.orm import selectinload

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

        async def _run_start():
            from database import async_session_maker
            from services.dag_executor import DAGExecutor

            async with async_session_maker() as db:
                executor = DAGExecutor(db)
                await executor.execute_dag_start(instance_id)

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

        async def _run_stop():
            from database import async_session_maker
            from models import TaskInstance
            from services.dag_executor import DAGExecutor
            from services.instance_lifecycle import auto_cleanup_instance
            from services.order_sync import mark_orders_completed_for_instance

            async with async_session_maker() as db:
                try:
                    executor = DAGExecutor(db)
                    await executor.execute_dag_stop(instance_id)

                    result = await db.execute(
                        select(TaskInstance)
                        .options(selectinload(TaskInstance.nodes))
                        .where(TaskInstance.id == instance_id)
                    )
                    instance = result.scalar_one_or_none()
                    if instance is None:
                        return

                    await mark_orders_completed_for_instance(db, instance_id)
                    if not instance.keep_after_stop:
                        await auto_cleanup_instance(db, instance)
                    await db.commit()
                except Exception:
                    logger.exception(
                        "schedule_task_end._run_stop failed for %s", instance_id
                    )
                    try:
                        await db.rollback()
                    except Exception:
                        logger.exception("rollback failed")

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


async def restore_pending_jobs(session_maker=None) -> None:
    """backend 启动时扫描 SCHEDULED/RUNNING/STARTING 实例，重注册未到期的 start/end job。

    APScheduler 是内存调度，重启后丢失 jobs；此函数保证 SCHEDULED 模式的到期收尾不会因为
    backend 重启而失效。

    session_maker 可选注入：默认使用全局 `async_session_maker`，测试时可以注入隔离 engine。
    """
    if session_maker is None:
        from database import async_session_maker as session_maker  # type: ignore
    from enums import TaskStatus
    from models import TaskInstance
    from sqlalchemy import select

    now = datetime.now(UTC).replace(tzinfo=None)
    scheduler_inst = TaskScheduler()
    restored_starts = 0
    restored_ends = 0

    async with session_maker() as db:
        result = await db.execute(
            select(TaskInstance).where(
                TaskInstance.status.in_(
                    [
                        TaskStatus.PENDING,
                        TaskStatus.SCHEDULED,
                        TaskStatus.STARTING,
                        TaskStatus.RUNNING,
                    ]
                ),
                TaskInstance.scheduled_end_time.isnot(None),
            )
        )
        for inst in result.scalars():
            try:
                if (
                    inst.scheduled_start_time is not None
                    and inst.scheduled_start_time > now
                    and inst.status in (TaskStatus.PENDING, TaskStatus.SCHEDULED)
                ):
                    await scheduler_inst.schedule_task_start(inst.id, inst.scheduled_start_time)
                    restored_starts += 1
                if inst.scheduled_end_time is not None and inst.scheduled_end_time > now:
                    await scheduler_inst.schedule_task_end(inst.id, inst.scheduled_end_time)
                    restored_ends += 1
            except Exception:
                logger.exception("Failed to restore schedule for instance %s", inst.id)

    logger.info(
        "Restored scheduled jobs: starts=%d, ends=%d", restored_starts, restored_ends
    )
