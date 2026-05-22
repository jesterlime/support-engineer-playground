import httpx
from config import BANK_AUTH, BANK_HOST
from logger_setup import logger
from crud import update_payment_status, add_payment_event
import time

BANK_URL = f"http://{BANK_HOST}"

async def call_bank(http_client, payment):
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
    req_start = time.perf_counter()
    response = await http_client.post(
        f"{BANK_URL}/v1/authorize",
        json=payload,
        headers={"X-Authorization-Key": BANK_AUTH}
    )
    duration_ms = round((time.perf_counter() - req_start) * 1000, 3)
    return response, duration_ms

async def authorize_payment(db_session, http_client, payment):
    payment_id = str(payment.id)
    correlation_id = str(payment.correlation_id)

    try:
        response, duration_ms = await call_bank(http_client, payment)
        response.raise_for_status()

    except httpx.TimeoutException:
        logger.warning("Bank request timed out", extra={
            "payment_id": payment_id, 
            "correlation_id": correlation_id,
            "duration_ms": duration_ms
            })
        await update_payment_status(db_session, payment_id, correlation_id, "retry")
        await add_payment_event(db_session, payment, "retry", correlation_id, "Timeout")
        return

    except httpx.HTTPStatusError as e:
        status_code = e.response.status_code

        if status_code >= 500:
            logger.warning("Bank returned server error", extra={
                "payment_id": payment_id, 
                "correlation_id": correlation_id,
                "duration_ms": duration_ms, 
                "status_code": status_code
            })
            await update_payment_status(db_session, payment_id, correlation_id, "retry")
            await add_payment_event(db_session, payment, "retry", correlation_id, f"{status_code} Bank Server Error")

        else:  # 4xx — bank declined
            error_detail = e.response.json()
            logger.info("Payment declined by bank", extra={
                "payment_id": payment_id,
                "correlation_id": correlation_id,
                "duration_ms": duration_ms,
                "status_code": status_code,
                "error_detail": error_detail
            })
            await update_payment_status(db_session, payment_id, correlation_id, "failed")
            await add_payment_event(db_session, payment, "failed", correlation_id, f"Bank declined: {error_detail}")

        return

    except httpx.RequestError as e:
        # Network-level failure — DNS, connection refused, etc.
        logger.error("Network error contacting bank", extra={
            "payment_id": payment_id, 
            "correlation_id": correlation_id,
            "duration_ms": duration_ms, 
            "error": str(e)[:200]
        })
        await update_payment_status(db_session, payment_id, correlation_id, "retry")
        await add_payment_event(db_session, payment, "retry", correlation_id, "Network error")
        return

    # Happy path — 2xx
    bank_data = response.json()
    bank_auth_code = bank_data["auth_code"]
    logger.info("Payment authorized successfully", extra={
        "payment_id": payment_id,
        "correlation_id": correlation_id, 
        "status_code": response.status_code,
        "duration_ms": duration_ms
    })
    await update_payment_status(
        db_session, 
        payment_id, 
        correlation_id, 
        "success", 
        bank_data.get("bank_reference_id"))
    await add_payment_event(
        db_session, 
        payment, 
        "success", 
        correlation_id, 
        f"Auth Code: {bank_auth_code}")