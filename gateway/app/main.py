import time, uuid
from fastapi import FastAPI, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from db import SessionLocal
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from models import PaymentCreate, PaymentResponse, PaymentCheck, PaymentStatus, ReportRequest
from errors import DuplicatePaymentError, NotFoundError
from crud import create_payment, check_payment, get_report
from logger_setup import logger
import aio_pika
from mq import mq_service

@asynccontextmanager
async def lifespan(app: FastAPI):
    await mq_service.connect()
    yield
    await mq_service.disconnect()

app = FastAPI(lifespan=lifespan)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.middleware("http")
async def middleware(request: Request, call_next):
    req_start = time.perf_counter()
    corr_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    request.state.correlation_id = corr_id
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - req_start) * 1000, 3)
    logger.info("New request", extra={
        "correlation_id": corr_id,
        "method": request.method,
        "path": request.url.path,
        "status_code": response.status_code,
        "duration_ms": duration_ms,
        "client_ip": request.client.host if request.client else "unknown"
    })
    response.headers["X-Correlation-ID"] = corr_id
    return response

@app.post("/pay", response_model=PaymentResponse, status_code=201)
async def create_payment_endpoint(
    request: Request, 
    payment: PaymentCreate, 
    db: Session = Depends(get_db),
    channel: aio_pika.abc.AbstractChannel = Depends(mq_service.get_channel)
    ):
    
    corr_id = request.state.correlation_id
    logger.info("Payment request received", extra={
        "correlation_id": corr_id,
        "order_id": payment.order_id,
        "idempotency_key": payment.idempotency_key,
        "metadata": {
            "amount": payment.amount_minor,
            "currency": payment.currency,
            "customer": payment.customer_id
        }
    })

    try:
        idempotency_hit, payment_id, correlation_id = create_payment(db, payment, corr_id)
        if not idempotency_hit:
            await mq_service.publish_task(channel, {
                "payment_id": payment_id,
                "correlation_id": correlation_id
                })
            logger.info("Task published for processor queue", extra={
                "payment_id": payment_id,
                "correlation_id": correlation_id,
                })
        else:
            logger.info("Idempotency Hit - Returning existing payment", extra={"payment_id": payment_id, "correlation_id": correlation_id})

    except Exception as e:
        logger.error("Unexpected error when creating payment", extra={
            "correlation_id": corr_id,
            "error_detail": str(e)[:200]
        })
        raise HTTPException(status_code=500, detail="Internal Server Error")
    
    return PaymentResponse(
        payment_id=payment_id,
        correlation_id=correlation_id,
        status="created"
    )

@app.get("/status")
def check_payment_status(request: Request, payment_data: PaymentCheck, db: Session = Depends(get_db)):

    corr_id = request.state.correlation_id
    logger.info("Payment status request", extra={
        "correlation_id": corr_id,
        "order_id": payment_data.order_id
    })
    try:
        payment_info = check_payment(db, payment_data, corr_id)
    except NotFoundError as e:
        logger.warning("Payment not found", extra={ "correlation_id": corr_id })
        raise HTTPException(status_code=404, detail={ "message": e.message })
    except Exception as e:
        logger.error("Unexpected error occured", extra={ "correlation_id": corr_id, "error_detail": str(e)[:200] })
        raise HTTPException(status_code=500, detail="Internal Server Error")
    return PaymentStatus(
            order_id=str(payment_info[0]),
            status=str(payment_info[1]),
            created_at=str(payment_info[2])
        )

@app.get("/reports/transactions")
async def get_shop_report(request: Request, report_req_data: ReportRequest, db: Session = Depends(get_db)):
    corr_id = request.state.correlation_id
    logger.info("Transaction report request", extra={
        "correlation_id": corr_id,
        "shop_id": report_req_data.shop_id
    })
    try:
        result = get_report(db, report_req_data, request.state.correlation_id)
        transactions = [dict(row) for row in result.mappings()]

        return {
            "shop_id": report_req_data.shop_id,
            "range": {"from": report_req_data.from_date, "to": report_req_data.to_date},
            "count": len(transactions),
            "transactions": transactions
        }
    except Exception as e:
        logger.error("Unexpected error occured", extra={ "correlation_id": corr_id, "error_detail": str(e)[:200] })
        raise HTTPException(status_code=500, detail="Internal Server Error")
    

@app.get("/health")
def health():
    logger.info("Service health check")
    return {"status": "ok"}