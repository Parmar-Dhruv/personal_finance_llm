from celery import Celery

from app.core.config import settings

# Valkey speaks the same RESP protocol Redis does, so the standard
# redis:// broker/backend URL scheme and the redis-py-based transport
# both work unmodified against a Valkey instance.
celery_app = Celery(
    "finsight",
    broker=settings.valkey_url,
    backend=settings.valkey_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

# Task modules are registered here as pipeline stages are built.
celery_app.autodiscover_tasks(["app.pipeline"])
