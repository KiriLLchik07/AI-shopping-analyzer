from redis import Redis
from rq import Queue

from backend.app.core.config import setting

queue_connection = Redis.from_url(
    setting.redis_url,
    decode_responses=False,
)

receipt_queue = Queue(
    "receipts",
    connection=queue_connection,
    default_timeout=300,
)
