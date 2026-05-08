from sqlalchemy.orm import Session
from sqlalchemy import text
from logger_setup import logger

def fetch_created_payment(db_session: Session):
    try:
        res = db_session.execute(text(
            """
            UPDATE payments 
            SET status = 'processing', updated_at = NOW()
            WHERE id = (
                SELECT id FROM payments 
                WHERE status = 'created' 
                ORDER BY created_at ASC 
                FOR UPDATE SKIP LOCKED 
                LIMIT 1
            )
            RETURNING *;
            """)
        ).first()
        if res:
            logger.info("[CRUD] fetch_created_payment", extra={"correlation_id":str(res.correlation_id)})
        else:
            logger.info("[CRUD] fetch_created_payment")
        return res
    except Exception as e:
        logger.error("Error happened when trying to fetch_created_payment", extra={"error_detail":str(e)})
        raise

def update_payment_status(db_session: Session, payment_id, status, bank_txn_id = None):
    try:
        db_session.execute(text(
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
        logger.info("[CRUD] update_payment_status", extra={"payment_id":str(payment_id)})
    except Exception as e:
        logger.error("Error happened when trying to update_payment_status", extra={
            "payment_id": payment_id,
            "error_detail":str(e)
        })
        raise

def add_payment_event(db_session: Session, payment_id, new_status, reason = None):
    try:
        db_session.execute(text(
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
            {"payment_id": payment_id, "new_status": new_status, "reason": reason}
        )
        logger.info("[CRUD] add_payment_event", extra={"payment_id":str(payment_id)})
    except Exception as e:
        logger.error("Error happened when trying to add_payment_event", extra={
            "payment_id": payment_id,
            "error_detail":str(e)
        })
        raise
    
def add_webhook_attempt(db_session: Session, payment):
    try:
        db_session.execute(text(
            """
            INSERT INTO webhook_deliveries (payment_id, attempt_no, target_url, delivered_at)
            VALUES (:payment_id, '0', :target_url, NOW())
            """),
            {"payment_id": str(payment.id), "target_url": payment.webhook_url}
        )
        logger.info("[CRUD] add_webhook_attempt", extra={"payment_id":str(payment.id)})
    except Exception as e:
        logger.error("Error happened when trying to add_webhook_attempt", extra={
            "payment_id": str(payment.id),
            "error_detail":str(e)
        })
        raise

def update_webhook_attempt(db_session: Session, payment_id, status_code, response_body):
    try:
        db_session.execute(text(
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
        logger.info("[CRUD] update_webhook_attempt", extra={"payment_id":str(payment_id)})
    except Exception as e:
        logger.error("Error happened when trying to update_webhook_attempt", extra={
            "payment_id": payment_id,
            "error_detail":str(e)
        })
        raise