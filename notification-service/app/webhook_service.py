import httpx
from logger_setup import logger
import time

async def send_webhook(client, payment, payment_id, correlation_id):
    try:
        payload = {
            "order_id": payment.order_id,
            "amount_minor": payment.amount_minor,
            "currency": payment.currency,
            "status": payment.status,
            "customer_email": payment.customer_email,
            "created_at": payment.created_at.isoformat()
        }

        req_start = time.perf_counter()
        response = await client.post(
            payment.webhook_url, 
            json=payload,
            headers={"X-Correlation-ID": correlation_id}
        )   
        status, body = response.status_code, response.text[:200]
        duration_ms = round((time.perf_counter() - req_start) * 1000, 3)

        if 200 <= status < 300:
            logger.info("Webhook delivered", extra={
                    "payment_id": payment_id,
                    "correlation_id": correlation_id,
                    "status_code": status,
                    "duration_ms": duration_ms
                })
        elif 400 <= status < 500:
            logger.warning("Webhook REJECTED", extra={
                    "payment_id": payment_id,
                    "correlation_id": correlation_id,
                    "status_code": status,
                    "error_detail": body,
                    "duration_ms": duration_ms
                })
        else:
            logger.warning("Webhook server error", extra={
                    "payment_id": payment_id,
                    "correlation_id": correlation_id,
                    "status_code": status,
                    "error_detail": body,
                    "duration_ms": duration_ms
                })
    except httpx.TimeoutException:
        status, body = 0, "TIMEOUT"
        logger.error("Webhook Timeout - User server unresponsive", extra={
                    "payment_id": payment_id,
                    "correlation_id": correlation_id,
                    "duration_ms": duration_ms
                })
    except Exception as e:
        status, body = 0, str(e)[:200]
        logger.error("Webhook Failed - Network/DNS error", extra={
                    "payment_id": payment_id,
                    "correlation_id": correlation_id,
                    "duration_ms": duration_ms,
                    "error_detail": str(e)[:200]
                })
        
    return status, body