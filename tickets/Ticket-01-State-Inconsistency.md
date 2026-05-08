# Ticket 001 - State Inconsistency

This investigation documents the decision chain used to resolve a Technical Support case, demonstrating proficiency in database transaction integrity and forensic reconciliation. The analysis explores a 'State Inconsistency' where successful financial authorizations failed to commit due to an unhandled exception.

`#Python3` `#PostgreSQL` `#FastAPI` `#SQLAlchemy` `#Docker-Compose` `#Manual-Data-Recovery` `#Defensive-Programming` `#Incident-Post-Mortem` `#Technical-Escalation` `#Customer-Communication`

## 1. Executive Summary

On March 10, 2026, a critical state inconsistency was identified where payments successfully authorized by the bank remained stuck in a "Processing" state within our database. Investigation revealed that the `processor` service encountered an unhandled `KeyError` when attempting to log metadata from bank response. Because this error occurred within an open database transaction but prior to the final commit, the financial action (charging the customer) succeeded, but the internal record-keeping failed. All affected transactions have been manually reconciled, and a code fix has been recommended to ensure robust handling of non-mandatory bank response fields.

## 2. Initial Ticket

|Key|Value|
|---|---|
|**From**|Alex Rivera (Abby_Labadie@hotmail.com)|
|**Shop ID**|shop_748376372|
| **Priority** | High |
| **Status** | Open |
| **Subject** | Major status discrepancy for order #ORD_KP4AK3CJ |
|**Message**|Hi Support Team, </br></br> I’m reaching out because we have a serious issue with a payment for one of our customers. </br></br>The customer attempted to buy a vintage workstation for **$77.77** (Order **#ORD_KP4AK3CJ**). On our Payment Gateway dashboard, the status has been stuck on **"Processing"** for over three hours now.</br></br> However, when I log into our **Merchant Bank Portal**, the transaction is showing as **"Succeeded"** and the funds are already authorized and held.</br></br>This is putting us in a difficult spot:</br></br>1. Our automated system won't release the shipping label because it thinks the payment hasn't finished.</br>2. The customer is asking why they haven't received a confirmation email yet.</br></br>I can’t manually mark it as "Paid" in your system, and I don't want to double-charge the customer. Can you look into your system and resolve it ASAP?</br></br>**Transaction Details:**</br>* **Order ID:** ORD_KP4AK3CJ</br>* **Payment ID:** `ad386e79-1612-430d-8469-252ecc0ade3f`</br>* **Amount:** $77.77</br>* **Timestamp:** Mar 10, 15:23 UTC</br></br>Please help us get this cleared so we can ship the order today.</br></br>Best,</br>Alex Rivera|

**Summary of a customer claims:** Payment `ad386e79-1612-430d-8469-252ecc0ade3f` has stuck at "Processing" status while Bank authorized the payment and funds entered the destination account.

## 3. Discovery & Forensics

### 3.1 Verifying the claim that payment is "processing"
We should check the status of the payment at 'payments' table using the provided Payment ID. We'll also gather some other information for further investigation:
```sql
SELECT 
	id,
	order_id,
	status,
	correlation_id,
	created_at
FROM payments WHERE id = 'ad386e79-1612-430d-8469-252ecc0ade3f';
```
</br>

Output:
|Key|Value|
|---|---|
|id|ad386e79-1612-430d-8469-252ecc0ade3f|
|order_id|ORD_KP4AK3CJ|
|status|processing|
|correlation_id|bd7590c4-2357-42a8-9ce2-366e0862a8dc|
|created_at|2026-03-10 15:23:41.70458+00|
</br>

Database output **confirms** that the status of transaction is "processing" and status persist much longer than it should be, which excludes the issue on customer side.

### 3.2 Verifying the claim that payment is authorized by bank
Bank API requests are logged. To verify the bank response, we should ceck up the payment in the `processor` logs. Let's use `correlation_id` and `id` to gather information from Processor logs:
```bash
$ grep -E "bd7590c4-2357-42a8-9ce2-366e0862a8dc|ad386e79-1612-430d-8469-252ecc0ade3f" ./logs/processor.log
```
</br>

Here's the raw JSON output:
```json
{"timestamp": "2026-03-10T15:23:42.745470", "level": "INFO", "message": "[CRUD] fetch_created_payment", "logger": "processor", "correlation_id": "bd7590c4-2357-42a8-9ce2-366e0862a8dc"}
{"timestamp": "2026-03-10T15:23:42.745581", "level": "INFO", "message": "Created payment found!", "logger": "processor", "correlation_id": "bd7590c4-2357-42a8-9ce2-366e0862a8dc", "payment_id": "ad386e79-1612-430d-8469-252ecc0ade3f"}
{"timestamp": "2026-03-10T15:23:42.746024", "level": "INFO", "message": "[CRUD] add_payment_event", "logger": "processor", "payment_id": "ad386e79-1612-430d-8469-252ecc0ade3f"}
{"timestamp": "2026-03-10T15:23:42.746701", "level": "INFO", "message": "DB changes committed at: run_forever", "logger": "processor", "correlation_id": "bd7590c4-2357-42a8-9ce2-366e0862a8dc"}
{"timestamp": "2026-03-10T15:23:42.746905", "level": "INFO", "message": "Starting payment processing", "logger": "processor", "correlation_id": "bd7590c4-2357-42a8-9ce2-366e0862a8dc"}
{"timestamp": "2026-03-10T15:23:42.792124", "level": "INFO", "message": "Payment authorization succeded", "logger": "processor", "status_code": 200, "correlation_id": "bd7590c4-2357-42a8-9ce2-366e0862a8dc"}
{"timestamp": "2026-03-10T15:23:42.792448", "level": "ERROR", "message": "Critical failure processing payment", "logger": "processor", "correlation_id": "bd7590c4-2357-42a8-9ce2-366e0862a8dc", "error_detail": "KeyError:'auth_code'", "payment_id": "ad386e79-1612-430d-8469-252ecc0ade3f"}
```
</br>

And the log from `2026-03-10T15:23:42.792124` signals that we got a `200` response status code, which **confirms** that payment was authorized by bank:
```json
{"timestamp": "2026-03-10T15:23:42.792124", "level": "INFO", "message": "Payment authorization succeded", "logger": "processor", "status_code": 200, "correlation_id": "bd7590c4-2357-42a8-9ce2-366e0862a8dc"}
```
</br>

## 4. Root Cause Analysis
Since database and logs confirmed that issue is not on client or bank side, we should look for root cause at the business logic of Procesor. The entry point for investigation will be the same Processor logs.

Here, log at `2026-03-10T15:23:42.792448` has `ERROR` level and outputs the error details: `KeyError:'auth_code'`. 
```json
{"timestamp": "2026-03-10T15:23:42.792448", "level": "ERROR", "message": "Critical failure processing payment", "logger": "processor", "correlation_id": "bd7590c4-2357-42a8-9ce2-366e0862a8dc", "error_detail": "KeyError:'auth_code'", "payment_id": "ad386e79-1612-430d-8469-252ecc0ade3f"}
```
</br>

First, let's follow the `'auth_code'` and take a closer look at the code snippet where worker crashed. We sould find out, where is it mentioned:
```bash
$ grep -rn "auth_code" ./processor
```
</br>

Output signals that `'auth_code'` lives in a `main.py`:
```bash
./processor/app/main.py:166:    bank_auth_code = bank_data['auth_code']
./processor/app/main.py:168:    add_payment_event(session, pid, "success", f"Auth Code: {bank_auth_code}")
```
</br>

Let's have a look at the code snippet:
```python
# [./processor/app/main.py] [lines 159-170]
     if response.status_code == 200:
            bank_data = response.json()
            logger.info("Payment authorization succeded", extra={
                    "correlation_id": str(payment.correlation_id),
                    "status_code": 200
                })
            bank_auth_code = bank_data['auth_code']
            update_payment_status(session, pid, "success", bank_data.get("bank_reference_id"))
            add_payment_event(session, pid, "success", f"Auth Code: {bank_auth_code}")
            event_type = "success"
            session.commit()
            session.close()
```
</br>

On the line 160, instead of safe `bank_data.get('auth_code')`, there was implemented `bank_data['auth_code']` that doesn't tolerates the absence of key and raises a `KeyError` exception.

Default payload that is returned from a Bank for authrozied payments include `bank_reference_id`, `status` and `auth_code`, but since error explicitly highlights absence of `auth_code`, we can assume that we deal with malfomed success payload.

**Conclusion on RCA:** The processor attempted to retrieve metadata from the bank's successful response. However, due to a combination of unsafe method usage and an unexpected content of success response, an error occurred, resulting in payment processing being interrupted. This incident resulted in data inconsistency and, as a result, the actual payment status not being displayed in the client's dashboard.

## 5. Reproduction
The `KeyError` theory is confimed by reproducing it in the local development environment using the system's hardcoded "Magic Amounts."

### 5.1 Setup The Environment
- Ensure all containers are running: `$ docker-compose up -d`
- Clear existing logs: `$ truncate -s 0 logs/processor.log`

### 5.2 Trigger the Edge Case
Initiate a payment via the Gateway using the `amount_minor: 7777`, which is configured in the Mock Bank to return a 200 OK response without an `auth_code` field. It can be done via API test tools like Insomnia/Postman or, alternatively, cURL:
```bash
curl -X POST http://localhost:8000/pay \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "ORD_RANDOM",
    "idempotency_key": "random-idempotency-key",
    "amount_minor": 7777,
    "currency": "USD",
    "description": "Mock Description",
    "customer_id": "shop_111111111",
    "customer_email": "mcok@email.com",
    "payment_token": "token_111111111111",
    "webhook_url": "http://webhook-sink:8080/success"
  }'
```
</br>

### 5.3 Result
- **Logs:** `processor.log` immediately shows `KeyError: 'auth_code'` following the successful bank response.
- **Database:** Status check on the new payment `id`, shows that payment is remained in `processing` status, confirming the database transaction was never committed.

**Result:** The system fails specifically when the third-party response is "Success" but lacks the expected metadata.

## 6. Resolution & Post-Mortem

### 6.1 Immediate Data Recovery (Manual Fix)
To unblock the merchant and allow the shipment of Order #ORD_KP4AK3CJ, I performed a manual reconciliation of the database state. This was executed within a single transaction block to ensure data integrity.
```sql
BEGIN;
UPDATE payments 
SET status = 'success', bank_txn_id = 'BANK-GHOST-999', updated_at = now() 
WHERE id = 'ad386e79-1612-430d-8469-252ecc0ade3f';
        
INSERT INTO payment_events (payment_id, from_status, to_status, actor, reason)
VALUES ('ad386e79-1612-430d-8469-252ecc0ade3f', 'processing', 'success', 'TSE_MANUAL_FIX', 'Manual recovery due to KeyError in Processor');
COMMIT;
```
Verification: Confirmed that the merchant dashboard now reflects the "Success" status.

### 6.2 Preventative Code Patch
The root cause was identified as "brittle" parsing of third-party API responses. I have submitted a Pull Request to transition from direct key access to safe dictionary polling.
```python
# [./processor/app/main.py] - Proposed Fix
# Before: bank_auth_code = bank_data['auth_code']
# After: Use .get() with a fallback to ensure the transaction survives missing metadata.

bank_auth_code = bank_data.get('auth_code', 'N/A')
```

### 6.3 Customer Communication

> **Subject:** Update regarding Order ORD_KP4AK3CJ </br></br>
> Hi Alex,</br></br>
> Thank you for your patience. We have personally investigated the discrepancy between our dashboard and your bank portal.</br></br>
> We have manually corrected this in our system, and you should see the order marked as "Paid" in your dashboard now. Your automated shipping workflow should resume immediately.</br></br>
> Our engineering team has been notified of the root cause to ensure this specific edge case is handled automatically in the future.</br></br>
> Best regards,</br>
> Technical Support Team

### 6.4 Lessons Learned
- **Defensive Parsing:** Never assume third-party API contracts are immutable; always use safe getters (.get()) for non-essential metadata.
- **Transaction Scoping:** Keep database transactions as small as possible. High-risk logic (like string parsing or logging) should not be able to roll back a successful financial state change.
- **Observability:** Our structured logging (JSON) and Correlation IDs were instrumental in reducing the "Mean Time to Recovery" (MTTR) to under 15 minutes once investigated.