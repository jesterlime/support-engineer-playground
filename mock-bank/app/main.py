from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional
from random import randint, choices
from asyncio import sleep
from os import getenv

app = FastAPI()
processed_keys = {}
auth_key = getenv("API_KEY", "PROCESSOR-BANK-SECRET")

class Metadata(BaseModel):
    order_id: Optional[str]
    description: Optional[str]
    customer_email: Optional[str]

class PaymentCreate(BaseModel):
    idempotency_key: str
    amount_minor: int
    currency: str = Field(..., min_length=3, max_length=3)
    payment_token: str
    metadata: Optional[Metadata]

def generate_hex_16():
    return ''.join(choices('0123456789abcdef', k=16))

@app.post("/v1/authorize")
async def authorize(request: Request, payment: PaymentCreate):
    try:
        # Validate Auth
        client_key = request.headers.get("X-Authorization-Key")
        if client_key != auth_key:
            return Response(status_code=401, content='{"error": "failed_auth"}')

        # Idempotency Hit
        if payment.idempotency_key in processed_keys:
            return processed_keys[payment.idempotency_key]

        amount = payment.amount_minor

        # High Latency
        if amount == 9999:
            await sleep(randint(1, 3))

        # Decline case
        if amount == 4002:
            return Response(status_code=402, content='{"status": "rejected", "error": "insufficient_funds"}')

        # Internal Server
        if amount == 5000:
            return Response(status_code=500, content='{"Internal Server Error"}')

        # Malformed Success
        if amount == 7777:
            return JSONResponse(
                status_code=200,
                content={
                    "bank_auth_id": "BANK-GHOST-999",
                    "status": "APPROVED"
                }
            )

        # Normal latency
        await sleep(randint(50, 200)/1000) 

        # Standard success response
        response_data = {
            "bank_reference_id": f"bank_ref_{generate_hex_16()}",
            "status": "authorized",
            "auth_code": generate_hex_16()
        }
        
        processed_keys[payment.idempotency_key] = response_data
        return response_data

    except Exception as e:
        print(e)

