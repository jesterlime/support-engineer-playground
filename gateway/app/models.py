from pydantic import BaseModel, Field
from typing import Optional

class PaymentCreate(BaseModel):
    order_id: str
    idempotency_key: str
    amount_minor: int
    currency: str = Field(..., min_length=3, max_length=3)
    description: Optional[str]
    customer_id: str
    customer_email: Optional[str]
    payment_token: str
    webhook_url: str

class PaymentCheck(BaseModel):
    order_id: str

class PaymentStatus(BaseModel):
    order_id: str
    status: str
    created_at: str

class PaymentResponse(BaseModel):
    payment_id: str
    correlation_id: str
    status: str

class ReportRequest(BaseModel):
    shop_id: str
    from_date: str
    to_date: str