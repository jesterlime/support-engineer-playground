import asyncio
import signal
import aio_pika
import httpx
from mq import RabbitMQManager
from config import MQ_HOST, MQ_PASSWORD, MQ_USER
from db import DATABASE_URL
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
import json
from crud import ( fetch_payment, add_webhook_attempt, update_webhook_attempt )
from logger_setup import logger
from webhook_service import send_webhook

RABBITMQ_URL = f"amqp://{MQ_USER}:{MQ_PASSWORD}@{MQ_HOST}/"
QUEUE_NAME = "notifications"

async def main():
    logger.info("Notification service is starting up")

    mq = RabbitMQManager(RABBITMQ_URL, QUEUE_NAME)
    await mq.connect()
    logger.info("RabbitMQ connection created")

    http_client = httpx.AsyncClient(timeout=30.0)
    logger.info("HTTPX client created")

    engine = create_async_engine(
        DATABASE_URL,
        pool_size=5,
        max_overflow=2
    )
    AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    logger.info("PostgreSQL connection created")

    logger.info("Notification service is ready for new messages...")

    stop_event = asyncio.Event()

    async def process_message(payment_id, correlation_id, message_id):
        logger.info("Notification message consumed", extra={"mq_message_id": message_id, "payment_id": payment_id, "correlation_id": correlation_id})

        # Business logic
        # Get payment from database
        async with AsyncSessionLocal() as session:
            async with session.begin():
                payment = await fetch_payment(session, payment_id, correlation_id)

        # Add webhook attempt
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await add_webhook_attempt(session, payment)

        # Send reuqest
        status_code, body = await send_webhook(http_client, payment, payment_id, correlation_id)

        # Update webhook attempt
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await update_webhook_attempt(session, payment_id, correlation_id, status_code, body)
        

    async def on_message(message: aio_pika.IncomingMessage):
        message_body = json.loads(message.body.decode())
        payment_id = message_body.get("payment_id")
        correlation_id = message_body.get("correlation_id")
        message_id = message.info().get('message_id')
        try:
            await process_message(payment_id, correlation_id, message_id)
            await message.ack()
            logger.info("Task completed", extra={
                "mq_message_id": message_id, 
                "payment_id": payment_id, 
                "correlation_id": correlation_id
                })
        except asyncio.CancelledError:
            logger.warning("Task cancelled — nacking message for requeue", extra={
                "mq_message_id": message_id, 
                "payment_id": payment_id, 
                "correlation_id": correlation_id
                })
            await message.nack(requeue=True)
            raise
        except Exception as e:
            logger.error("Processing failed — nacking message.", extra={
                "mq_message_id": message_id, 
                "payment_id": payment_id, 
                "correlation_id": correlation_id, 
                "error_msg":str(e)[:200]})
            await message.nack(requeue=False)

    def ask_exit():
        logger.info("Shutdown signal received...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, ask_exit)

    queue = await mq.channel.get_queue(mq.queue_name)
    consumer_tag = await queue.consume(on_message, no_ack=False)

    await stop_event.wait()

    # Graceful shutdown — no need to wait for active_tasks, on_message is already done
    logger.info("Stopping message consumer...")
    await queue.cancel(consumer_tag)

    await http_client.aclose()
    logger.info("HTTPX connection closed")

    await engine.dispose()
    logger.info("PostgreSQL connection pool closed")

    await mq.close()
    logger.info("RabbitMQ connection closed")

    logger.info("Notification service shut down cleanly...")

if __name__ == "__main__":
    asyncio.run(main())