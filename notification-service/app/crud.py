from sqlalchemy.orm import Session
from sqlalchemy import text
from logger_setup import logger

async def fetch_payment(db_session: Session, payment_id, correlation_id):
    try:
        res = await db_session.execute(text(
            """SELECT * FROM payments WHERE id = :payment_id"""),
            {"payment_id": payment_id}
        )
        res = res.first()
        if res:
            logger.info("Payment fetched", extra={"payment_id": str(res.id), "correlation_id":correlation_id})
        else:
            logger.warning("Payment ID not found", extra={"payment_id":payment_id, "correlation_id":correlation_id})
        return res
    except Exception as e:
        logger.error("Error when fetching payment", extra={"payment_id": payment_id, "correlation_id":correlation_id, "error_detail":str(e)})
        raise

async def add_webhook_attempt(db_session: Session, payment):
    try:
        await db_session.execute(text(
            """
            INSERT INTO webhook_deliveries (payment_id, attempt_no, target_url, delivered_at)
            VALUES (:payment_id, '0', :target_url, NOW())
            """),
            {"payment_id": str(payment.id), "target_url": payment.webhook_url}
        )
        logger.info("Webhook delivery attempt added", extra={"payment_id":str(payment.id), "correlation_id":str(payment.correlation_id)})
    except Exception as e:
        logger.error("Error happened when trying to add delivery attempt", extra={
            "payment_id": str(payment.id),
            "correlation_id":str(payment.correlation_id),
            "error_detail":str(e)
        })
        raise

async def update_webhook_attempt(db_session: Session, payment_id, correlation_id, status_code, response_body):
    try:
        await db_session.execute(text(
            """
            UPDATE webhook_deliveries 
            SET http_status = :http_status, attempt_no = 1, response_body = :response_body, delivered_at = NOW()
            WHERE payment_id = (
                SELECT payment_id FROM webhook_deliveries 
                WHERE payment_id = :payment_id 
                FOR UPDATE SKIP LOCKED 
                LIMIT 1
            )
            """),
            {"payment_id": payment_id, "http_status": status_code, "response_body": response_body}
        )
        logger.info("Webhook delivery attempt status updated", extra={
            "payment_id":payment_id,
            "correlation_id":correlation_id,
            "status_code": status_code
            })
    except Exception as e:
        logger.error("Error happened when trying to update_webhook_attempt", extra={
            "payment_id": payment_id,
            "error_detail":str(e)
        })
        raise