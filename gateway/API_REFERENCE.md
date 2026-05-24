## Gateway API Reference

Base URL: `http://localhost/api`

---

### POST /pay
Create a new payment transaction.

**Request** `http://localhost/api/pay`
```json
{
  "order_id": "ORD_086JO0Z6",
  "idempotency_key": "a819038c-4b36-46f2-ae2a-ae69b0b60da7",
  "amount_minor": 42511,
  "currency": "USD",
  "description": "Barba textor pecco.",
  "customer_id": "shop_731666184",
  "customer_email": "Thaddeus.Hoeger@hotmail.com",
  "payment_token": "token_a413cb0d2464",
  "webhook_url": "http://reverse-proxy/webhook/success"
}
```

| Field | Type | Description |
|---|---|---|
| `order_id` | string | Your internal order reference |
| `idempotency_key` | UUID | Unique key to prevent duplicate processing |
| `amount_minor` | integer | Amount in minor currency units (cents) |
| `currency` | string | ISO 4217 currency code |
| `description` | string | Human-readable payment description |
| `customer_id` | string | Merchant identifier |
| `customer_email` | string | Customer email |
| `payment_token` | string | Payment method token |
| `webhook_url` | string | URL to receive the payment result |

---

### GET /status
Check the status of an existing order.

**Request** `http://localhost/api/status`
```json
{
  "order_id": "ORD_7ZPANFWL"
}
```

**Response**
```json
{
  "order_id": "ORD_7ZPANFWL",
  "status": "success",
  "created_at": "2026-03-23 11:17:23.238331+00:00"
}
```

| Status | Meaning |
|---|---|
| `created` | Payment record written, awaiting processing |
| `processing` | Picked up by processor, bank request in progress |
| `success` | Bank authorized, webhook delivered |
| `failed` | Bank declined or internal error |

---

### GET /reports/transactions
Retrieve all transactions for a merchant within a date range.

**Request** `http://localhost/api/reports/transactions`
```json
{
  "shop_id": "shop_478746974",
  "from_date": "2026-03-14",
  "to_date": "2026-05-11"
}
```

**Response**
```json
{
  "shop_id": "shop_478746974",
  "range": {
    "from": "2026-03-14",
    "to": "2026-05-11"
  },
  "count": 1,
  "transactions": [
    {
      "id": "1140b581-0591-47ed-82ad-e31c94d3c40b",
      "amount_minor": 94276,
      "currency": "USD",
      "status": "success",
      "created_at": "2026-03-23T11:17:22.697865+00:00"
    }
  ]
}
```

---

### GET /health
Verify the gateway is reachable and operational.

**Request** `http://localhost/api/health`

**Response**
```json
{
  "status": "ok"
}
```