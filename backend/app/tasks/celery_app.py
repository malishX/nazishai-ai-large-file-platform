from celery import Celery
from app.core.config import get_settings

settings = get_settings()
celery_app = Celery(
    "nazishai",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.upload_tasks"],
)
celery_app.conf.task_track_started = True
celery_app.conf.task_acks_late = True
celery_app.conf.worker_prefetch_multiplier = 1
