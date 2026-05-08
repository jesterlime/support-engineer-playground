from contextlib import contextmanager
import asyncio
import signal
from datetime import datetime
from db import SessionLocal, engine
from logger_setup import logger
import httpx
import json
from config import BANK_HOST, BANK_PORT, BANK_AUTH
from crud import (
    fetch_created_payment, 
    add_payment_event, 
    update_payment_status, 
    add_webhook_attempt, 
    update_webhook_attempt 
    )

connections = []

class PaymentProcessor:
    def __init__(self, db_pool, bank_url: str):
        self.db_factory = db_pool
        self.bank_url = bank_url
        self.client = None
        self.db = None

    async def __aenter__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            logger.error(f"Processor exiting due to error: {exc_val}")
        if self.client:
            await self.client.aclose()
            logger.info("HTTP connection pool closed successfully.")
        logger.info("PaymentProcessor cleanup complete.")

    async def run_forever(self, stop_event: asyncio.Event):
        logger.info("Processor is waking up... Start polling for created payments")
        while not stop_event.is_set():
            payment = None
            with self.db_factory() as session:
                logger.info("DB session opens at: run_forever")
                try:
                    payment = fetch_created_payment(session)
                    if payment:
                        logger.info("Created payment found!", extra={
                            "correlation_id": str(payment.correlation_id),
                            "payment_id": str(payment.id)
                        })
                        print(f"Created payment found! {str(payment.id)}")
                        add_payment_event(session, str(payment.id), "processing")
                        session.commit()
                        logger.info("DB changes committed at: run_forever", extra={"correlation_id": str(payment.correlation_id)})
                    else:
                        print(f"No payments with 'created' status found. Next polling in 5s.")
                        try:
                            logger.info("No payments with 'created' status found. Next polling in 5s.")
                            await asyncio.wait_for(stop_event.wait(), timeout=5.0)
                        except asyncio.TimeoutError:
                            pass
                except Exception as e:
                    logger.error("Falied to connect to databse. Retry in 10s.", extra={
                        "error_detail": e
                    })
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=10.0)
                    except asyncio.TimeoutError:
                        pass
                finally:
                    self.db = None
                    logger.info("DB session closes at: run_forever")

            if payment:
                try:
                    await self.process_payment(payment)
                except Exception as e:
                    logger.error("Critical failure processing payment", extra={
                        "payment_id": str(payment.id),
                        "correlation_id": str(payment.correlation_id),
                        "error_detail": str(f"{type(e).__name__}:{e}")
                    })

    async def call_bank(self, payment):
        payload = {
            "idempotency_key": str(payment.idempotency_key),
            "amount_minor": payment.amount_minor,
            "currency": payment.currency,
            "payment_token": payment.payment_token,
            "metadata": {
                "order_id": payment.order_id,
                "description": payment.description,
                "customer_email": payment.customer_email
            }
        }
        
        try:
            response = await self.client.post(
                f"{self.bank_url}/v1/authorize", 
                json=payload,
                headers={"X-Authorization-Key": BANK_AUTH}
            )
            return response
        except httpx.TimeoutException:
            return "TIMEOUT"
        except Exception as e:
            return "ERROR"

    async def process_payment(self, payment):
        pid = str(payment.id)
        logger.info("Starting payment processing", extra={
                        "correlation_id": str(payment.correlation_id)
                    })
        response = await self.call_bank(payment)

        event_type = None

        session = engine.connect()
        connections.append(session)

        logger.info("DB session opens at: process_payment")

        # Handle Timeout
        if response == "TIMEOUT":
            logger.warning("Connection timeout when requesting the Bank", extra={
                    "correlation_id": str(payment.correlation_id)
                })
            update_payment_status(session, pid, "retry")
            add_payment_event(session, pid, "retry", f"Timeout")
            session.commit()
            session.close()
            return
        
        # Handle Network Failure/Other
        if response == "ERROR":
            logger.error("Critical error when requesting the Bank", extra={
                    "correlation_id": str(payment.correlation_id)
                })
            update_payment_status(session, pid, "retry")
            add_payment_event(session, pid, "retry", f"Critical error")
            session.commit()
            session.close()
            return
        
        # Handle Bank Side Errors (500)
        if response.status_code == 500:
            logger.warning("Internal Server Error from Bank", extra={
                    "correlation_id": str(payment.correlation_id),
                    "status_code": 500
                })
            update_payment_status(session, pid, "retry")
            add_payment_event(session, pid, "retry", "500 Bank Internal Error")
            session.commit()
            session.close()
            return
        
        # Handle Success (201)
        if response.status_code == 200:
            bank_data = response.json()
            logger.info("Payment authorization succeded", extra={
                    "correlation_id": str(payment.correlation_id),
                    "status_code": 200
                })
            bank_auth_code = bank_data['auth_code']
            update_payment_status(session, pid, "success", bank_data.get("bank_reference_id"))
            add_payment_event(session, pid, "success", f"Auth Code: {bank_auth_code}")
            event_type = "success"
            session.commit()
            session.close()

        # Handle Rejections (4xx)
        else:
            error_detail = response.json()
            logger.info("Payment authorization failed", extra={
                    "correlation_id": str(payment.correlation_id),
                    "status_code": response.status_code,
                    "error_detail": error_detail
                })
            
            update_payment_status(session, pid, "failed")
            add_payment_event(session, pid, "failed", f"Bank declined: {error_detail}")
            event_type = "failed"
            session.commit()
            return
        logger.info("DB changes committed at: process_payment", extra={"correlation_id": str(payment.correlation_id)})
        logger.info("DB session closes at: process_payment")

        if event_type:
            await self.send_webhook(payment, event_type)

    async def send_webhook(self, payment, event_type):
        logger.info("Proceeding to send a webhook", extra={
                        "correlation_id": str(payment.correlation_id),
                    })
        if not payment.webhook_url:
            logger.warning("No webhook link provided", extra={
                        "correlation_id": str(payment.correlation_id),
                    })
            return
        
        payload = {
            "order_id": payment.order_id,
            "amount_minor": payment.amount_minor,
            "currency": payment.currency,
            "status": event_type,
            "customer_email": payment.customer_email,
            "created_at": payment.created_at.isoformat()
        }

        with self.db_factory() as session:
            logger.info("DB session opens at: send_webhook")
            add_webhook_attempt(session, payment)
            session.commit()
            logger.info("DB changes committed at: send_webhook", extra={"correlation_id": str(payment.correlation_id)})
            logger.info("DB session closes at: send_webhook")

        try:
            response = await self.client.post(
                payment.webhook_url, 
                json=payload,
                headers={"X-Correlation-ID": str(payment.correlation_id)}
            )   
            status, body = response.status_code, response.text[:200]

            if 200 <= status < 300:
                logger.info("Webhook delivered.", extra={
                        "correlation_id": str(payment.correlation_id),
                        "status_code": status
                    })
            elif 400 <= status < 500:
                logger.warning("Webhook REJECTED", extra={
                        "correlation_id": str(payment.correlation_id),
                        "status_code": status,
                        "error_detail": body
                    })
            else:
                logger.warning("Webhook server error", extra={
                        "correlation_id": str(payment.correlation_id),
                        "status_code": status,
                        "error_detail": body
                    })
        except httpx.TimeoutException:
            status, body = 0, "TIMEOUT"
            logger.error("Webhook TIMEOUT - User server unresponsive", extra={
                        "correlation_id": str(payment.correlation_id)
                    })
        except Exception as e:
            status, body = 0, str(e)[:200]
            logger.error("Webhook FAILED - Network/DNS error", extra={
                        "correlation_id": str(payment.correlation_id),
                        "error_detail": str(e)[:200]
                    })
        
        with self.db_factory() as session:
            logger.info("DB session opens at: send_webhook")
            update_webhook_attempt(session, str(payment.id), status, body)
            session.commit()
            logger.info("DB changes committed at: send_webhook", extra={"correlation_id": str(payment.correlation_id)})
            logger.info("DB session closes at: send_webhook")


@contextmanager
def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

async def main():
    processor_instance = PaymentProcessor(get_db, f"http://{BANK_HOST}:{BANK_PORT}")
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: stop_event.set())

    async with processor_instance as processor:
        await processor.run_forever(stop_event)

if __name__ == "__main__":
    asyncio.run(main())