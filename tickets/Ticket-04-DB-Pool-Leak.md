# Tciket 004 - Database Pool Leak

This investigation documents the decision chain used to resolve a Technical Support case, demonstrating proficiency in scalability challenge, where a minor logic flaw, previously masked by low traffic and maintenance schedules, becomes a systemic failure under the pressure of business growth. It highlights the transition from managing a "stable" system to maintaining a high-velocity production environment where resource management is no longer optional.

`#SQLAlchemy` `#PostgreSQL` `#ResourceManagement` `#Scalability` `#Docker` `#IncidentResponse`

## 1. Executive Summary

Over the past week, the Payment Gateway experienced recurring daily service outages, resulting in `500 Internal Server Error` responses and a total cessation of payment processing during peak hours. Investigation revealed a database connection leak within the background processor’s error-handling logic specifically triggered by `402 Insufficient Funds` responses from the bank. 

While the system’s scheduled 24-hour container restarts previously acted as an unintentional "garbage collection" for these orphaned sessions, a 5x surge in transaction volume over the last month caused the PostgreSQL connection limit to be reached within hours, exhausting all available slots for both the Gateway and the Processor.

The root cause was identified as poor management of database session in a specific code branch where an early return statement bypassed the `session.close()` call, leaving "Zombie" connections in an idle state for every failed transaction attempt. While manual container resets provided immediate temporary relief, the failure led to significant operational overhead and increased merchant churn risk. The investigation has been escalated to the Engineering Department with a formal recommendation to refactor the processor logic.

## 2. Initial Ticket

|Key|Value|
|---|---|
|**From**|Elena Rossi (elena@bloomandsend.it)|
| **Priority** | High |
| **Status** | Open |
| **Subject** | EVERYTHING IS BROKEN AGAIN — THIRD TIME THIS WEEK!!! |
|**Message**|Is anyone actually looking at this??</br></br>I am currently sitting in my shop with three customers waiting and the payment screen is just showing "500 Internal Server Error" over and over. I tried refreshing. I tried clearing my cache. I even restarted my laptop. Nothing works.</br></br>This is the third afternoon in a row where the system just gives up around 4:30 PM. Yesterday, I called your support line and they "reset something" and it started working again, but this is not a solution! I can't call you every single day just to take a payment.</br></br>My customers are walking out and going to the florist down the street because I can't process their cards. I’m paying for a "Premium Gateway" but I’m getting a broken toy. If this isn't fixed permanently by tomorrow, I’m cancelling my subscription and moving to a competitor. I am losing hundreds of euros every hour this stays down.</br></br>FIX IT!!!|

**Summary of a customer claims:** Customer claims that service is down and returns 500 Internal Server Error on regular basis.

## 3. Discovery & Forensics

### 3.1 Gateway Log Analysis

Initial triage focuses on the **Gateway** logs, as this is the primary point of failure reported by merchants. A search for error-level events within the log files provides the first concrete evidence of a system-wide failure.

**Diagnostic Command:**
```bash
grep "ERROR" ./logs/gateway.log
```

**Output:**
```bash
sqlalchemy.exc.OperationalError: (psycopg2.OperationalError) connection to server at "db" (172.18.0.2), port 5432 failed: FATAL:  sorry, too many clients already
```

### 3.2 Error Context and External Research

The message **"FATAL: sorry, too many clients already"** points toward a resource constraint at the database layer. To confirm the specific behavior of this PostgreSQL error, technical documentation and developer community resources (such as [StackOverflow - org.postgresql.util.PSQLException: FATAL: sorry, too many clients already](https://stackoverflow.com/questions/2757549/org-postgresql-util-psqlexception-fatal-sorry-too-many-clients-already)) were consulted.

The research establishes several facts regarding PostgreSQL connection management:

* **Strict Limits:** Database connections are finite. Once the configured limit (100 connections by default) is reached, the database rejects all further attempts to connect (and sequently make any CRUD operations).
* **Manual Lifecycle Management:** In many programming environments, connections must be explicitly closed via commands like `conn.close()`.
* **The "Restart" Effect:** These connections are typically tied to the application process. When a container is restarted, the process is killed, and the database automatically clears those slots. This explains why manual restarts provided temporary relief but did not solve the underlying issue.
* **Diagnostic Toolkit:** PostgreSQL provides built-in commands for monitoring connection health:
    * `SHOW max_connections;` — To verify the total allowed slots.
    * `SELECT COUNT(*) FROM pg_stat_activity;` — To see how much of slots are currently taken.
    * `SELECT * FROM pg_stat_activity;` — To audit which users/services are holding connections.


### 3.3 Database State Investigation

With the diagnostic commands identified, an investigation into the live database state was performed via **pgAdmin** to identify the "owner" of the excess connections.

**Diagnostic Query:**
```sql
SELECT pid, usename, datname, backend_type, query 
FROM pg_stat_activity;
```

**Output:**
| "pid" | "usename" | "datname" | "backend_type" | "state" | "backend_start" |
|---|---|---|---|---|---|
| 31  | null | null | "autovacuum launcher" | null | "2026-03-16 00:00:25.990403+00" |
| 32  | "gateway_user" | null | "logical replication launcher" | null | "2026-03-16 00:00:25.990522+00" |
| 33  | "gateway_user" | "payments" | "client backend" | "idle" | "2026-03-16 00:08:26.171258+00" |
| 56  | "processor_user" | "payments" | "client backend" | "idle" | "2026-03-16 03:12:31.619062+00" |
| 74  | "processor_user" | "payments" | "client backend" | "idle" | "2026-03-16 05:53:32.208721+00" |
| 81  | "processor_user" | "payments" | "client backend" | "idle" | "2026-03-16 05:55:45.410159+00" |
| 109 | "processor_user" | "payments" | "client backend" | "idle" | "2026-03-16 07:21:54.640564+00" |
| 115 | "processor_user" | "payments" | "client backend" | "idle" | "2026-03-16 08:00:23.904949+00" |
| 117 | "processor_user" | "payments" | "client backend" | "idle" | "2026-03-16 09:15:44.960193+00" |
| 123 | "processor_user" | "payments" | "client backend" | "idle" | "2026-03-16 11:31:02.132729+00" |
| 125 | "processor_user" | "payments" | "client backend" | "idle" | "2026-03-16 13:43:30.182526+00" |
| 127 | "processor_user" | "payments" | "client backend" | "idle" | "2026-03-16 14:22:08.233323+00" |
| 129 | "processor_user" | "payments" | "client backend" | "idle" | "2026-03-16 15:02:44.28571+00" |
| 131 | "processor_user" | "payments" | "client backend" | "idle" | "2026-03-16 15:04:23.338843+00" |
| 140 | "processor_user" | "payments" | "client backend" | "idle in transaction" | "2026-03-16 15:08:38.83448+00" |
| 148 | "gateway_user" | "payments" | "client backend" | "active" | "2026-03-16 15:08:41.033094+00" |
| 28 | null | null | "background writer" | null | "2026-03-16 00:00:25.981267+00" |
| 27 | null | null | "checkpointer" | null | "2026-03-16 00:00:25.980391+00" |
| 30 | null | null | "walwriter" | null | "2026-03-16 00:00:25.990246+00" |

**Observation:**
The query results show a significant discrepancy in resource usage. While the system background processes and `gateway_user` accounts maintain a minimal footprint (2–5 connections), the `processor_user` accountable for the vast majority of the entries. Specifically, dozens of connections are identified in an `idle` state originating from the Processor service. This number continues to rise over time, signaling that the system will inevitably reach the 100-connection limit.

### 3.4 Forensic Conclusion

The nature of the issue is confirmed as a **Database Connection Leak**.

* The system is not crashing due to heavy load, but rather "suffocating" as the **Processor** creates new sessions and fails to properly close them.
* The investigation has shifted from the Gateway to the Processor to identify the specific logic branch where these connections are being orphaned.

## 4. Root Cause Analysis

### 4.1 Temporal Correlation of "Zombie" Processes

A key finding in the database audit was the `backend_start` column within `pg_stat_activity`, which provides the exact millisecond a process was initiated. By extracting a sample timestamp from an idle connection—`2026-03-16 14:22:08.233323+00`—the investigation focused on correlating this event with the **Processor** application logs.

To account for slight formatting variations in the JSON logs, the timestamp was converted to the application's standard ISO format: `2026-03-16T14:22:08.233323`.

### 4.2 Log Forensics

Searching the processor logs for the specific second of the leak reveals a clear sequence of events. Since millisecond precision can vary between the database and application layer, a broadened search for the prefix `2026-03-16T14:22:08.23` was performed.

**Command:**
`grep "2026-03-16T14:22:08.23" ./logs/processor.log`

**Result:**

```json
{"timestamp": "2026-03-16T14:22:08.236322", "level": "INFO", "message": "DB session opens at: process_payment", "logger": "processor"}
{"timestamp": "2026-03-16T14:22:08.236439", "level": "INFO", "message": "Payment authorization failed", "logger": "processor", "status_code": 402, "correlation_id": "acb631a4-d6aa-4db1-b683-9e2498c65b11", "error_detail": {"status": "rejected", "error": "insufficient_funds"}}
{"timestamp": "2026-03-16T14:22:08.237159", "level": "INFO", "message": "[CRUD] update_payment_status", "logger": "processor", "payment_id": "b12efecf-3409-4ea3-967d-bf93de35f69e"}
{"timestamp": "2026-03-16T14:22:08.237698", "level": "INFO", "message": "[CRUD] add_payment_event", "logger": "processor", "payment_id": "b12efecf-3409-4ea3-967d-bf93de35f69e"}
{"timestamp": "2026-03-16T14:22:08.238046", "level": "INFO", "message": "DB session opens at: run_forever", "logger": "processor"}

```

**Observation:**
The logs confirm a repetitive pattern. Every time a payment fails with a **402 Insufficient Funds** error, the expected "DB session closes" log entry is missing. Instead, the service immediately moves to the next polling cycle (`run_forever`), leaving the previous session in an orphaned, `idle` state.

### 4.3 Code Review: Manual Session Mismanagement

Following the string "Payment authorization failed" into the source code at `./processor/app/main.py` reveals a critical inconsistency in how bank responses are handled.

The logic branch for **Rejections (4xx)** manages the session manually but lacks a termination instruction:

```python
# [./processor/app/main.py] [lines 173-185]
# Handle Rejections (4xx)
else:
    error_detail = response.json()
    logger.info("Payment authorization failed", extra={
            "correlation_id": str(payment.correlation_id),
            "status_code": response.status_code,
            "error_detail": error_detail
        })
    
    update_payment_status(session, pid, "failed")
    add_payment_event(session, pid, "failed", f"Bank declined: {error_detail}")
    event_type = "failed"
    session.commit()
    return  # <--- Logic exits function here; session.close() is never reached.
```

In contrast, the **Success (200)** branch correctly implements the closure:

```python
# [./processor/app/main.py] [lines 158-170]
# Handle Success (200)
if response.status_code == 200:
    # ... logic for success ...
    session.commit()
    session.close()  # <--- Connection is successfully released back to the pool.

```

### 4.4 Conclusion

The root cause is a **Resource Leak via Early Return**. In the specific branch, the Processor worker utilizes manual database connection management rather than sfer context managers. And in part of the code responsible for handling 4xx bank rejections, the `return` statement is executed after the database commit but before the connection is closed.

Under the recent 5x increase in transaction volume, these orphaned connections accumulate rapidly, eventually saturating the 100-connection PostgreSQL limit and causing a total system lockout.

## 5. Reproduction

To validate the connection leak and confirm the impact of the logic flaw, a controlled reproduction of the failure was performed. The following steps allow the engineering team to observe the rapid saturation of database resources under simulated load.

### 5.1 Establishing the environment

First, the environment is restored to a clean state to establish a "normal" connection count for comparison.

1. **Ensure all containers are operational:**
`$ docker-compose up -d`
2. **Submit standard transactions:**
Send 3–5 payment requests with standard payloads (e.g., `amount_minor: 1000`) via Insomnia or cURL.
    ```bash
    curl -X POST http://localhost:8000/pay \
    -H "Content-Type: application/json" \
    -d '{
        "order_id": "ORD_RANDOM",
        "idempotency_key": "random-idempotency-key",
        "amount_minor": 1000,
        "currency": "USD",
        "description": "Mock Description",
        "customer_id": "shop_111111111",
        "customer_email": "mcok@email.com",
        "payment_token": "token_111111111111",
        "webhook_url": "http://webhook-sink:8080/success"
    }'
    ```
3. **Audit initial connections:**
Verify the count of open connections. For those without access to **pgAdmin**, the following command can be executed within the database container terminal:
```bash
# Command to check connection count via terminal
docker exec -it pay_db psql -U gateway_user -d payments -c "SELECT COUNT(*) FROM pg_stat_activity;"
```

**Observation:** Under normal conditions, the count should remain stable between **5 and 8** connections, reflecting the background processes, active worker threads and the gateway pool.


### 5.2 Triggering the Saturation

The "magic number" behavior is utilized to force the system into the flawed code branch repeatedly.

1. **Generate "Insufficient Funds" traffic:**
Submit a batch of 15–20 payment requests using `amount_minor: 4002` in request body. This triggers the `402` response from the Bank Mock service and activates the manual session logic in the Processor.
2. **Re-audit connection state:**
Repeat the connection count command:
```bash
docker exec -it pay_db psql -U gateway_user -d payments -c "SELECT COUNT(*) FROM pg_stat_activity;"
```

**Observation:** Every request submitted with the `4002` amount results in the connection count increasing by exactly **+1**. These connections do not terminate after the transaction is "failed."

### 5.3 Validation

By checking the state of these new connections, it is confirmed that they are definitively leaked sessions:

```sql
SELECT pid, usename, datname, backend_type, query 
FROM pg_stat_activity;
```

## 6. Resolution

### 6.1 Immediate Operational Mitigation

Until a permanent code fix is deployed, the system is being managed in a **"Degraded but Functional"** state. To prevent a total lockout of the Gateway, the following operational adjustments have been implemented:

* **Worker Rotation (Manual Garbage Collection):** The `processor` service has been scaled to multiple instances. These containers are being restarted on a staggered, high-frequency schedule. By forcing the termination of the worker processes, the "Zombie" connections are released before they can aggregate to the 100-connection limit.
* **Active Monitoring:** Support is monitoring the `pg_stat_activity` count in real-time. If the `idle` connection count from the `processor_user` exceeds 80% of capacity, an immediate manual flush of the container stack is triggered.

### 6.2 Engineering Escalation & Permanent Fix

The investigation has been escalated to the Development Team with **Highest Priority (P0)**. The formal request includes the following:

- **Immediate Patch:** Insertion of the `session.close()` instruction within the 4xx/402 rejection branch to ensure connections are released before the function returns.
- **Architectural Recommendation:** Shift from manual session management (manual `.commit()` and `.close()` calls) to **Context-Driven Management**. Utilizing Python’s `with` statement (context managers) ensures that sessions are closed automatically by the interpreter, even in the event of an early `return` or an unhandled exception.

## 7. Communication Strategy

### 7.1 Customer Communication (External)

The priority is transparency to preserve merchant trust while the final patch is being verified in the staging environment.

**Draft: Email to Affected Merchants**

> **To: All affected users**</br>
> **Subject: Update regarding recent service interruptions**</br></br>
> Dear {{Merchant Name}},</br></br>
> We are writing to formally apologize for the service interruptions you may have experienced during peak processing hours over the last few days.</br></br>
> Our engineering team has identified a resource bottleneck caused by a recent surge in transaction volumes. We are currently performing active maintenance to keep the system stable while a permanent fix is being finalized. You may notice brief, intermittent periods of unavailability as we rotate our internal services to ensure continued performance.</br></br>
> We expect a full resolution to be deployed within {{Timeframe}}. We value your business and appreciate your patience as we scale our infrastructure to meet your growing needs.</br></br>
> Sincerely,</br>
> The {{Company Name}} Support Team

### 7.2 Internal Stakeholder Guidance (Customer Success)

To mitigate churn, the Customer Success department requires a clear "Recovery Playbook" for high-value accounts like *Bloom & Send*.

**Draft: Internal Memo to Customer Success**

> **Subject: Ticket 04 Recovery – Churn Mitigation Strategy**
> **Issue:** A database connection leak triggered by rapid scaling.
> **Status:** Mitigation in progress; permanent fix pending deployment.
> **Action Plan:**
> 1. **Admit the Issue:** When speaking with clients, acknowledge the specific stability issues without over-complicating the technical details.
> 2. **Proactive Outreach:** For merchants who reported "500 Errors" or total downtime during peak hours, please reach out directly to confirm service has been stabilized.
> 3. **Compensation:** We have authorized a "Retention Credit" for high-risk accounts. You are empowered to offer **two months of free subscription** or a **15% discount** for the next quarter to merchants who experienced significant loss of trade or are threatening to move to a competitor.
> 4. **Feedback Loop:** Please report any further instances of "500 Errors" to Support immediately, as this indicates our manual rotation schedule needs to be tightened.
> 
>