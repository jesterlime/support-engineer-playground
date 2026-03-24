# Tciket 002 - Resource Exhaustion

This investigation documents the decision chain used to resolve a Technical Support case, demonstrating proficiency in architectural troubleshooting, bottleneck identification, and system-wide resource analysis. Unlike a crash, this incident explores head-of-line blocking (HOL blocking), where a single high-latency downstream merchant causes systemic congestion and a total delivery backlog for all other users. Entry point of investigation - the internal ticked, escalated from Tier 1 team.

## 1. Executive Summary

On March 11, 2026, the Payment Gateway experienced a significant degradation in webhook delivery performance, with delays exceeding 30 minutes. Investigation revealed that the system was suffering from Head-of-Line Blocking. Because the processor service operates on a synchronous loop, a single merchant (shop_628808701) with a 45-second webhook server timeout flooded the worker thread with slow responses. This forced healthy merchants to wait in a linear queue for the "slow" merchant's timeouts to clear. The resolution recommendations include aggressive timeouts and implementation of an asynchronous task queue architecture.

## 2. Initial Ticket

|Key|Value|
|---|---|
|Ticket ID| #DIS-9902 |
|Internal Message| Hey, I've had like 5 different shops calling in the last hour saying their webhooks are "stuck." </br></br>One guy from `Fast Wheels Shop` was literally yelling because his customers aren't getting emails. I checked the dashboard and the payments are all green (Success), so the API isn't down. I told him it's probably his own server lag but he didn't buy it.</br></br>I checked one log for him and it looks like the webhook eventually sent, but it took like one hour. I don't see any errors in the Gateway so it's probably a Processor thing? I'm heading to my 2 PM lecture now. GL.</br></br>**Sample Order with lag:** `ORD_2R6L7U8W`</br>**Merchant ID:** `shop_481711449`|

**Summary of a customer claims:** Customers experiencing unusually high delay between sending the payment and receiving the webhook, although their servers are responsive.

## 3. Discovery & Forensics
The investigation began by analyzing the "Victim" merchant (shop_481711449) mentioned in the ticket.

### 3.1 Analyzing the Latency Delta
Let's run a SQL query to compare the time when payment was created vs. when the webhook was actually delivered for the order in the ticket:
```sql
SELECT
	payments.customer_id,
	payments.order_id,
	payments.created_at,
	payment_events.created_at as processed_at,
	webhook_deliveries.delivered_at,
	(webhook_deliveries.delivered_at - payments.created_at) as delivery_time
FROM payments
INNER JOIN webhook_deliveries on payments.id = webhook_deliveries.payment_id
INNER JOIN payment_events on payments.id = payment_events.payment_id
WHERE customer_id = 'shop_481711449' AND payment_events.from_status = 'created'
```

Output:

|Key|Value|Comment|
|---|---|---|
|customer_id|shop_481711449|-|
|order_id|ORD_2R6L7U8W|-|
|created_at|2026-03-11 19:23:30.641883+00|Timestamp when the payment was created|
|processed_at|2026-03-11 20:33:50.360081+00|Timestamp when payment started processing|
|delivered_at|2026-03-11 20:33:50.5128+00|Timestamp when the webhook was delivered|
|delivery_time|01:10:19.870917|Total time from payment creation to webhook delivery|

Result: The payment was hanging in "created" state for 1 hour 10 minutes, and processing (bank authorization and webhook delivery) took only 0.1528s, which signals that: 
1. Bank API is up and has normal latency
2. Client's webhook server is up and responded quickly. 
3. Database handles I/O quickly and properly

In this case, the only option left is a webhook delivery inside of Processor. Webhook delivery is network I/O operation that depends on liveness and latency of customer's server, and due to synchronious architecture of Processor realistically may slow down it's work.


### 3.2 Identifying the bottleneck
Since the bottleneck is likely to be the webhook delivery stage, we should analyze the delivery duration for all stores for the day when users started reporting delays in webhook delivery.

We should take information about all shops that has done payments at day of incident, and check their average time of webhook delivery:

```sql
SELECT
	payments.customer_id,
	AVG(webhook_deliveries.delivered_at - payments.updated_at) AS avg_delay, -- get an avg time between payment authorization and webhook delivery
	COUNT(*) as payments_total -- get a total amount of payments per shop
FROM payments
INNER JOIN webhook_deliveries on payments.id = webhook_deliveries.payment_id
WHERE payments.created_at > '2026-03-11' -- only retrieve data for day of incident
GROUP BY payments.customer_id -- aggregate data by shop
ORDER BY avg_delay DESC -- check who has the highest delay among customers
```

Output:

| cutomer_id | avg_delay | payments_total |
|---|---|---|
| "shop_628808701" | "00:01:35.523825" | 69 |
| "shop_235530884" | "00:00:00.017931" | 121 |
| "shop_774819463" | "00:00:00.014019" | 43 |
| "shop_484174639" | "00:00:00.013607" | 18 |
| "shop_717975811" | "00:00:00.01306" | 22 |

Result: Cutomer "shop_628808701" was identified to have abnormally high average webhook delivery time of 1 minute 35 seconds, probably due to extreme latency of a webhook server. Multiplied by total amount of payments, it floods the payments queue with slow transactions that creates cummulative effect for all other customers.

To back up the conclusion and take a closer look at what exactly happened, we should look at the logs, with sample of payment and correlation ID of reviewed user:
```bash
$ grep -E "13e4931d-3de8-4d9f-a66a-be2d237c44ea|1d9b6150-7ad6-4659-92b2-08f017f32169" ./logs/processor.log
```

Output:
```json
...
{"timestamp": "2026-03-11T19:25:02.408392", "level": "INFO", "message": "[CRUD] add_webhook_attempt", "logger": "processor", "payment_id": "13e4931d-3de8-4d9f-a66a-be2d237c44ea"}
{"timestamp": "2026-03-11T19:25:32.414452", "level": "ERROR", "message": "Webhook TIMEOUT - User server unresponsive", "logger": "processor", "correlation_id": "1d9b6150-7ad6-4659-92b2-08f017f32169"}
...
```

Conclusion: Logs output confirms that user `shop_628808701` webhook server are unresponsive and wait time hit's `30s` timeout and triggers an error.


## 4. Root Cause Analysis

The root cause is an architectural solution implemented in Procesor worker. It sequentially fetches payments, requests bank authorization and sends a webhook. And since the flow is sunchronous, the entire system is limited by its slowest component. When a merchant's server (like `shop_628808701`) has high latency or down entirely, it pauses the entire system just to process one slow webhook (or any I/O operation).

While hardcoded 30s timeout may work for edge cases, the repetative inclusion of slow transaction to queue creates cummulative effect, impacting all customers:

```python
# [./processor/app/main.py]

20  class PaymentProcessor:
##  
##    ...
##
27    async def __aenter__(self):
28        self.client = httpx.AsyncClient(timeout=30.0) # <-- 30s timeout setup
29        return self
```

Conclusion: The failure is due to an architectural fragility. The Processor system's design assumes "Happy Path" - network conditions where all downstream sinks respond instantly. It lacks the defensive infrastructure (Timeouts, Retries, and Task Queues) required to isolate the performance failures of third-party integrations.

## 5. Reproduction

To validate the Head-of-Line Blocking theory, let's conduct a controlled experiment in the staging environment. The goal is to demonstrate that a single high-latency merchant could systematically degrade the performance of a system for a "Healthy" merchants.

### 5.1 Setup The Environment
- Ensure all containers are running: `$ docker-compose up -d`
- Clear existing logs: `$ truncate -s 0 logs/processor.log`

### 5.2 Simulation Parameters
The experiment utilized two distinct mock merchants to simulate resource contention:
- Merchant A (The Bottleneck): Configured to point to a `/slow-poke` endpoint, hardcoded to return a 45-second response delay.
  ```bash
  curl -X POST http://localhost:8000/pay \
  -H "Content-Type: application/json" \
  -d '{
    # ...other parameters...
    "customer_id": "shop_SLOW",
    "webhook_url": "http://webhook-sink:8080/slow-poke"
  }'
  ```
- Merchant B (The Victim): Configured to point to a standard `/success` endpoint with a nominal <100ms response time.
  ```bash
  curl -X POST http://localhost:8000/pay \
  -H "Content-Type: application/json" \
  -d '{
    # ...other parameters...
    "customer_id": "shop_HEALTHY",
    "webhook_url": "http://webhook-sink:8080/success"
  }'
  ```

### 5.2 Step-by-Step Execution

1. Queue saturation with slow clients: Initiate ten (10) consecutive payments as **Merchant A**. 
2. Target injection: Right after the initial saturation, initiate one (1) payment for **Merchant B**.

Note: *it's recommended to use API testing tools like Insomnia or Postman.*

### 5.3 Observation & Results

Let's retrive data for each payment with checkpoint timestamps and total waiting time. Query is pretty similar to the one in [3.1 Analyzing the Latency Delta](#31-analyzing-the-latency-delta):
```sql
SELECT
	payments.customer_id,
	payments.order_id,
	payments.created_at,
	payment_events.created_at as processed_at,
	webhook_deliveries.delivered_at,
	(webhook_deliveries.delivered_at - payments.created_at) as delivery_time
FROM payments
INNER JOIN webhook_deliveries on payments.id = webhook_deliveries.payment_id
INNER JOIN payment_events on payments.id = payment_events.payment_id
WHERE payment_events.from_status = 'created'
```

Result:
| customer_id | order_id | created_at | processed_at | delivered_at | delivery_time |
|---|---|---|---|---|---|
| shop_SLOW | ORD_J58TOCAA | 2026-03-13 09:11:40 | 2026-03-13 09:11:42 | 2026-03-13 09:12:12 | 00:00:32 |
| shop_SLOW | ORD_1442909G | 2026-03-13 09:11:41 | 2026-03-13 09:12:12 | 2026-03-13 09:12:43 | 00:01:01 |
| shop_SLOW | ORD_2459278K | 2026-03-13 09:11:42 | 2026-03-13 09:12:43 | 2026-03-13 09:13:13 | 00:01:31 |
| shop_SLOW | ORD_966L6D7R | 2026-03-13 09:11:43 | 2026-03-13 09:13:13 | 2026-03-13 09:13:43 | 00:02:00 |
| shop_SLOW | ORD_937QXASW | 2026-03-13 09:11:44 | 2026-03-13 09:13:43 | 2026-03-13 09:14:13 | 00:02:29 |
| shop_SLOW | ORD_ECOAITX7 | 2026-03-13 09:11:45 | 2026-03-13 09:14:13 | 2026-03-13 09:14:43 | 00:02:58 |
| shop_SLOW | ORD_EP1XQ1RU | 2026-03-13 09:11:46 | 2026-03-13 09:14:43 | 2026-03-13 09:15:14 | 00:03:27 |
| shop_SLOW | ORD_KFXTGI2K | 2026-03-13 09:11:47 | 2026-03-13 09:15:14 | 2026-03-13 09:15:44 | 00:03:57 |
| shop_SLOW | ORD_4W6Y9KUX | 2026-03-13 09:11:48 | 2026-03-13 09:15:44 | 2026-03-13 09:16:14 | 00:04:26 |
| shop_SLOW | ORD_OZZNZR5P | 2026-03-13 09:11:49 | 2026-03-13 09:16:14 | 2026-03-13 09:16:44 | 00:04:55 |
| shop_HEALTHY | ORD_L6M2JFVA | 2026-03-13 09:11:53 | 2026-03-13 09:16:44 | 2026-03-13 09:16:44 | 00:04:50 |

And this table shows that healthy merchant has symptoms similar to live customer from ticket. Every time slow merchant adds transaction, it delays processing of helthy merchant by 30s. As result, 10 slow payments turned into 4:50 minutes of delay for helthy merchant.

## 6. Resolution

### 6.1 Immedate Code Patch

The quick solution that could reduce latency for healthy merchants is:
1. **More aggressive timeouts:** Reducing the timeout from 30s to 5s.
    ```python
    # [./processor/app/main.py]

    #     [BEFORE]
    27    async def __aenter__(self):
    28        self.client = httpx.AsyncClient(timeout=30.0) # <-- 30s timeout 
    29        return self

    #     [AFTER]
    27    async def __aenter__(self):
    28        self.client = httpx.AsyncClient(timeout=5.0) # <-- 5s timeout 
    29        return self

    ```
2. **Horizaontal scaling:** Deploy more Processor workers as load grows.
    ```bash
    $ docker compose up -d --scale processor=5
    ```

While this approach partially solves problem right in the moment, it doesn't eliminates the root cause - Processor still syncroniously performs webhook delivery that depends on the end user servers which may be slow or down, creating surface for similar failures

### 6.2 Architectural Solution

To solve the root cause (Resource Contention) a transition to an Asynchronous Task Queue is required.

The Proposed Architecture:

- Message Broker (RabbitMQ/Redis): Instead of the Processor taking care of payment authorization and sending webhooks in a single loop, it will publish a "Webhook Task" to a queue for separate workers, specially designed for this job.

- Decoupled Workers: Multiple independent worker processes will subscribe to the queue. If Worker A is occupied by a 45-second response from slow merchant, Worker B remains available to pick up and immediately deliver a task for a healthy merchant.

- Isolation (Bulkheading): The system can implement "priority queues" or "per-merchant queues." This ensures that a surge in traffic or latency from one specific merchant cannot physically occupy the resources reserved for others.

### 6.3 Customer Communication

  > To: All affected customers</br>
  > Subject: Technical Update: Enhanced Webhook Reliability and Performance</br>
  >
  > ---
  > Hi {{Customer Name}},</br>
  > We are reaching out to provide an update regarding the intermittent delays in webhook notifications observed earlier today.</br>
  > #### What Happened:
  > Our monitoring systems identified a period of increased latency in our notification delivery service. During this window, some merchants experienced a delay in receiving automated payment confirmations.
  > #### Our Response:
  > Our engineering team has implemented a series of infrastructure optimizations to improve delivery speed. These updates are designed to maintain high performance and consistent delivery times, regardless of external network conditions.
  > #### Status:
  > All systems are now operating at full capacity, and the delivery backlog has been fully cleared. You should see all transaction statuses reflected accurately in your system.
  > We understand how critical real-time data is to your operations and are committed to providing the most reliable experience possible. We appreciate your patience as we worked to resolve this.</br></br>
  > Best regards,</br>
  > The {{Company Name}} Technical Support Team