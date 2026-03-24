import uuid
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import text
from errors import DuplicatePaymentError, NotFoundError
from logger_setup import logger

def create_payment(db_session: Session, payment_data, corr_id):
    payment_id = str(uuid.uuid4())
    correlation_id = corr_id
    now = datetime.now()
 
    # Validate the idempotency_key
    try:
        res = db_session.execute(text(
            """
            SELECT payments.id, payments.correlation_id
            FROM payments
            WHERE payments.idempotency_key = :_idempotency_key
            """),
            {
                "_idempotency_key": payment_data.idempotency_key
            }
        )
    except Exception as e:
        logger.error("database_read_failed", extra={
            "correlation_id": correlation_id,
            "event": "create_payment",
            "error_detail": str(e),
        })
        raise

    res = res.first()
    if res is not None:
        logger.warning("idempotency_hit", extra={
            "correlation_id": str(res[1]),
            "event": "create_payment",
            "payment_id": str(res[0])
        })
        return str(res[0]), str(res[1])


    # Insert new payment to 'payments' and 'payment-events' in one transction
    try:
        with db_session.begin_nested():
            db_session.execute(text(
            """
            INSERT INTO payments(id, order_id, amount_minor, currency, status,
                                description, customer_id, customer_email, payment_token, 
                                idempotency_key, webhook_url, correlation_id, created_at, 
                                updated_at)
            VALUES (:id, :order_id, :amount_minor, :currency, 'created',
                    :description, :customer_id, :customer_email, :payment_token, 
                    :idempotency_key, :webhook_url,:correlation_id, :created_at, :updated_at)
            """),
            {
                "id": payment_id,
                "order_id": payment_data.order_id,
                "amount_minor": payment_data.amount_minor,
                "currency": payment_data.currency,
                "description": payment_data.description,
                "customer_id": payment_data.customer_id,
                "customer_email": payment_data.customer_email,
                "payment_token": payment_data.payment_token,
                "idempotency_key": payment_data.idempotency_key,
                "webhook_url": payment_data.webhook_url,
                "correlation_id": correlation_id,
                "created_at": now,
                "updated_at": now,
            }
        )
        
        db_session.execute(text(
            """
            INSERT INTO payment_events(payment_id, from_status, to_status, reason, actor)
            VALUES (:payment_id, NULL, 'created', 'payment_received', 'gateway')
            """),
            {"payment_id": payment_id}
        )

        db_session.commit()

        logger.info("payment_record_created", extra={
            "correlation_id": correlation_id,
            "payment_id": payment_id,
            "event": "create_payment"
        })
    except Exception as e:
        db_session.rollback()
        logger.error("database_transaction_failed", extra={
            "correlation_id": correlation_id,
            "error_detail": str(e),
            "event": "create_payment"
        })
    
    return payment_id, correlation_id

def check_payment(db_session: Session, payment_data, corr_id):
    try:
        res = db_session.execute(text(
            """
            SELECT 
                payments.order_id,
                payment_events.to_status,
                payment_events.created_at
            FROM payments
            LEFT JOIN payment_events ON payments.id = payment_events.payment_id
            WHERE order_id = :_order_id
            ORDER BY payment_events.created_at DESC
            LIMIT 1
            """),
            {
                "_order_id": payment_data.order_id
            }
        )
    except Exception as e:
        logger.error("database_read_failed", extra={
            "correlation_id": corr_id,
            "event": "check_payment",
            "error_detail": str(e),
        })
        raise

    res = res.first()
    if res is None:
            logger.warning("payment_not_found", extra={
                "correlation_id": corr_id,
                "event": "check_payment"
            })
            raise NotFoundError()
    return res

def get_report(db_session: Session, report_request, corr_id):
    from_date = report_request.from_date + " 00:00:00" if report_request.from_date == report_request.to_date else report_request.from_date
    to_date = report_request.to_date + " 23:59:59" if report_request.from_date == report_request.to_date else report_request.to_date
    try:
        res = db_session.execute(text(
            """
            SELECT 
                id, 
                amount_minor, 
                currency, 
                status, 
                created_at 
            FROM payments 
            WHERE customer_id = :shop_id 
            AND created_at >= :from_date 
            AND created_at <= :to_date
            ORDER BY created_at DESC
            """),
            {
                "shop_id": report_request.shop_id ,
                "from_date": from_date,
                "to_date": to_date
            }
        )
    except Exception as e:
        logger.error("database_read_failed", extra={
            "correlation_id": corr_id,
            "event": "check_payment",
            "error_detail": str(e),
        })
        raise
    return res
