import json
from typing import AsyncGenerator
import aio_pika
from config import MQ_HOST, MQ_USER, MQ_PASSWORD
from logger_setup import logger

# Config Constants
RABBITMQ_URL = f"amqp://{MQ_USER}:{MQ_PASSWORD}@{MQ_HOST}/"
QUEUE_NAME = "processor"

class RabbitMQService:
    def __init__(self, url: str, queue_name: str):
        self.url = url
        self.queue_name = queue_name
        self.connection: aio_pika.abc.AbstractRobustConnection | None = None

    async def connect(self):
        try:
            self.connection = await aio_pika.connect_robust(self.url)
            logger.info("RabbitMQ connection created")
        except Exception as e:
            logger.error("Failed to create RabbitMQ connection")

    async def disconnect(self):
        if self.connection:
            await self.connection.close()
            logger.info("RabbitMQ connection closed...")

    async def get_channel(self) -> AsyncGenerator[aio_pika.abc.AbstractChannel, None]:
        if not self.connection or self.connection.is_closed:
            logger.error("RabbitMQ connection is missing.")
            raise RuntimeError("RabbitMQ connection is missing.")
            
        async with self.connection.channel() as channel:
            await channel.declare_queue(self.queue_name, durable=True)
            yield channel

    async def publish_task(self, channel: aio_pika.abc.AbstractChannel, payload: dict) -> None:
        message_bytes = json.dumps(payload).encode("utf-8")
        
        await channel.default_exchange.publish(
            aio_pika.Message(
                body=message_bytes,
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                content_type="application/json"
            ),
            routing_key=self.queue_name
        )

# Global service instance

logger.info("Inititalizing RabbitMQ service")
mq_service = RabbitMQService(url=RABBITMQ_URL, queue_name=QUEUE_NAME)
