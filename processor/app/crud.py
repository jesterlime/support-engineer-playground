from sqlalchemy.orm import Session
from sqlalchemy import text
from logger_setup import logger

async def fetch_created_payment(db_session: Session, payment_id, correlation_id):
    try:
        res = await db_session.execute(text(
            """
            UPDATE payments 
            SET status = 'processing', updated_at = NOW()
            WHERE id = :payment_id
            RETURNING *;
            """),
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

async def update_payment_status(db_session: Session, payment_id, corelation_id, status, bank_txn_id = None):
    try:
        await db_session.execute(text(
            """
            UPDATE payments 
            SET status = :new_status, updated_at = NOW(), bank_txn_id = :bank_txn_id
            WHERE id = (
                SELECT id FROM payments 
                WHERE id = :payment_id 
                FOR UPDATE SKIP LOCKED 
                LIMIT 1
            )
            """),
            {"new_status": status, "payment_id": payment_id, "bank_txn_id": bank_txn_id}
        )
        logger.info("Payment status updated", extra={"new_status":status, "payment_id":str(payment_id), "correlation_id":str(corelation_id)})
    except Exception as e:
        logger.error("Error when updating payment status", extra={
            "payment_id": payment_id,
            "corelation_id":corelation_id,
            "error_detail":str(e)
        })
        raise

async def add_payment_event(db_session: Session, payment, new_status, correlation_id, reason = None):
    try:
        await db_session.execute(text(
            """
            INSERT INTO payment_events(payment_id, from_status, to_status, reason, actor)
            SELECT 
                payment_id, 
                to_status, 
                :new_status,
                :reason,
                'processor'
            FROM payment_events
            WHERE payment_id = :payment_id
            ORDER BY created_at DESC
            LIMIT 1;
            """),
            {"payment_id": payment.id, "new_status": new_status, "reason": reason}
        )
        logger.info("Payment event added", extra={"new_status":new_status, "payment_id":str(payment.id), "correlation_id":correlation_id})
    except Exception as e:
        logger.error("Error when adding payment event", extra={
            "payment_id": str(payment.id),
            "correlation_id":correlation_id,
            "error_detail":str(e)[:200]
        })
        raise