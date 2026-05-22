import aio_pika
from typing import Optional
import json

class RabbitMQManager:
    def __init__(self, amqp_url: str, queue_name: str):
        self.amqp_url = amqp_url
        self.queue_name = queue_name
        self.connection: Optional[aio_pika.RobustConnection] = None
        self.channel: Optional[aio_pika.RobustChannel] = None

    async def connect(self):
        self.connection = await aio_pika.connect(self.amqp_url)
        self.channel = await self.connection.channel()
        await self.channel.set_qos(prefetch_count=1)
        await self.channel.declare_queue(self.queue_name, durable=True)

    async def declare_queue(self, queue_name: str):
        await self.channel.declare_queue(queue_name, durable=True)

    async def publish(self, queue_name: str, body: dict):
        await self.channel.default_exchange.publish(
            aio_pika.Message(
                body = json.dumps(body).encode(),
                delivery_mode = aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key = queue_name,
        )

    async def close(self):
        if self.connection:
            await self.connection.close()