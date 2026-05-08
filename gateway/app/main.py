import time, uuid
from fastapi import FastAPI, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from db import SessionLocal
from models import PaymentCreate, PaymentResponse, PaymentCheck, PaymentStatus, ReportRequest
from errors import DuplicatePaymentError, NotFoundError
from crud import create_payment, check_payment, get_report
from logger_setup import logger

app = FastAPI()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    start_time = time.time()
    corr_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    request.state.correlation_id = corr_id
    response = await call_next(request)
    duration = round(time.time() - start_time, 4)
    logger.info("middleware", extra={
        "correlation_id": corr_id,
        "method": request.method,
        "path": request.url.path,
        "status_code": response.status_code,
        "duration_s": duration,
        "client_ip": request.client.host if request.client else "unknown"
    })
    response.headers["X-Correlation-ID"] = corr_id
    return response

@app.post("/pay", response_model=PaymentResponse, status_code=201)
def create_payment_endpoint(request: Request, payment: PaymentCreate, db: Session = Depends(get_db)):
    
    corr_id = request.state.correlation_id
    logger.info("payment_request_received", extra={
        "correlation_id": corr_id,
        "event": "create_payment_endpoint",
        "order_id": payment.order_id,
        "idempotency_key": payment.idempotency_key,
        "metadata": {
            "amount": payment.amount_minor,
            "currency": payment.currency,
            "customer": payment.customer_id
        }
    })

    try:
        payment_id, correlation_id = create_payment(db, payment, corr_id)
    except DuplicatePaymentError as e:
        raise HTTPException(status_code=409, detail={
            "message": e.message,
            "payment_id": e.payment_id, 
            "correlation_id": e.correlation_id
            })
    except Exception as e:
        logger.error("payment_request_error", extra={
            "correlation_id": corr_id,
            "event": "create_payment_endpoint",
            "error_detail": str(e)
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
    logger.info("payment_check_request", extra={
        "correlation_id": corr_id,
        "event": "check_payment_status",
        "order_id": payment_data.order_id
    })

    try:
        payment_info = check_payment(db, payment_data, corr_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail={ "message": e.message })
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal Server Error")
    return PaymentStatus(
            order_id=str(payment_info[0]),
            status=str(payment_info[1]),
            created_at=str(payment_info[2])
        )

@app.get("/reports/transactions")
async def get_shop_report(request: Request, report_req_data: ReportRequest, db: Session = Depends(get_db)):
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
        raise HTTPException(status_code=500, detail="Internal Server Error")
    

@app.get("/health")
def health():
    return {"status": "ok"}