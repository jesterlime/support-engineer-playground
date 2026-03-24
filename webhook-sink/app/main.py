from fastapi import FastAPI, Request, Response
import asyncio
from logger_setup import logger

app = FastAPI()

@app.post("/success")
async def success_sink(request: Request):
    payload = await request.json()
    correlation_id = request.headers.get("X-Correlation-ID")
    log_payload(f"[SUCCESS] Received webhook", payload, correlation_id)
    return {"status": "ok"}

@app.post("/client-error")
async def client_error_sink(request: Request):
    payload = await request.json()
    correlation_id = request.headers.get("X-Correlation-ID")
    log_payload(f"[400] Simulating Client Error (Bad Request)", payload, correlation_id)
    return Response(
        content='{"error": "Invalid payload format"}', 
        status_code=400, 
        media_type="application/json"
    )

@app.post("/server-error")
async def server_error_sink(request: Request):
    payload = await request.json()
    correlation_id = request.headers.get("X-Correlation-ID")
    log_payload("[500] Simulating Server Crash", payload, correlation_id)
    return Response(
        content="Internal Server Error: Database Connection Failed", 
        status_code=500
    )

@app.post("/slow-poke")
async def slow_sink(request: Request):
    payload = await request.json()
    correlation_id = request.headers.get("X-Correlation-ID")
    log_payload("[TIMEOUT] Received request, holding for 45 seconds...", payload, correlation_id)
    await asyncio.sleep(45)
    return {"status": "finally_done"}

def log_payload(message, payload, correlation_id):
    logger.info(message, extra={
        "correlation_id": correlation_id,
        "order_id": payload.get('order_id'),
        "amount_minor": payload.get('amount_minor'),
        "currency": payload.get('currency'),
        "status": payload.get('status'),
        "customer_email": payload.get('customer_email'),
        "created_at": payload.get('created_at'),
    })