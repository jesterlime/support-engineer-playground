# Tciket 003 - Timezone Logic

This investigation documents the decision chain used to resolve a Technical Support case, demonstrating proficiency in globalization, SQL logic, and the nuances of multi-tenant reporting. This incident explores a logical discrepancy where naive date-casting in a UTC-normalized database results in "phantom" data loss for international merchants. It highlights the distinction between data dtorage and data presentation.

`#SQL-Globalization` `#PostgreSQL` `#UTC-Normalization` `#Data-Forensics` `#ISO-8601` `#Multi-Tenant-Reporting` `#Temporal-Logic`

## 1. Executive Summary

On March 14, 2026, a high-value merchant based in Sydney, Australia (AEDT, UTC+11) reported a discrepancy in their daily transaction reports. While the merchant possessed 25 physical receipts for the day, the system-generated report only returned 19 records. Investigation revealed a Temporal Logic Flaw in the reporting engine: the SQL query didn't consider the casting against the database's UTC timestamps. This caused the first 11 hours of the merchant's business day to be shunted into the previous calendar day in the database's view. 

Immedate respond delivered quick solution, ensuring that reporting tool delivers value for customer. Recommendations for enhancing user experience were forwared to development department: refactoring the reporting query to utilize explicit timezone offsets, ensuring that records are displayes according the merchant's local time.


## 2. Initial Ticket

|Key|Value|
|---|---|
|**From**|Lachlan Murray (lockie_m@outbackstationery.au)|
|**Shop ID**|shop_131613894|
|**Priority**|Medium|
|**Status**|Open|
|**Subject**|Missing sales in "Saturday" report - urgent accounting issue|
|**Message**|G'day Support,</br>I’m trying to close out my books for Saturday (March 14th), but your reporting tool is having a shocker.</br></br>According to my POS system and my physical receipts, I did 25 transactions on Saturday. However, when I run your "Daily Transactions" report for the 14th, it only shows 19 orders.</br></br>The weird part is that all the missing ones seem to be from the morning. Anything I sold before about 11 AM isn't showing up on the list at all. I can see the payments went through in my live feed, so I know the money is there, but the report is useless for my accounting if it keeps "forgetting" my morning coffee rush.</br></br>Can you fix this before my Sunday rush starts? I can't be manually cross-referencing every single order.</br></br>Cheers,</br></br>Lachlan|

**Summary of a customer claims:** Customer claims that 6 of his 25 orders at Match 14 are missing at transaction report. Preliminary, all missing orders were made before 11 AM of March 14

## 3. Discovery & Forensics

### 3.1 Initial Database Inspection

To investigate the reported discrepancy, a query was executed to retrieve the latest 25 transactions for the merchant, from the time when support ticket was created.

```sql
SELECT *
FROM payments 
WHERE customer_id = 'shop_131613894' 
AND created_at <= '2026-03-14 13:55:00'
ORDER BY created_at DESC
LIMIT 25
```

**Observation:** The result set returned a continuous stream of transactions. Notably, the sequence of orders spanned across March 14th and the late hours of March 13th UTC with consistent time gaps (averaging 15–30 minutes). This pattern suggests a single, uninterrupted business day from the merchant's perspective, despite the change in calendar date within the database.

### 3.2 Identification of Missing Records

To confirm if the reporting tool was specifically excluding these early-morning orders, the merchant provided the IDs for the six transactions that were absent from their "Saturday" report.

Cross-Reference Results:
A manual cross-reference was performed between the merchant's missing IDs and the records retrieved in step 3.1.

Query to retrive 6 payments that are missing report, with timestamp convertion from UTC to AEDT:
```sql
SELECT 
	payments.id,
	payments.created_at as utc_timezone,
	payments.created_at AT TIME ZONE 'Australia/Sydney' as aedt_timezone
FROM payments 
WHERE customer_id = 'shop_131613894' 
  AND created_at <= '2026-03-13 23:59:59'
ORDER BY created_at DESC
LIMIT 6
```

| "id" | "utc_timezone" | "aedt_timezone" |
|---|---|---|
| "dc4fae10-4b06-4c07-90cf-d627d87fb707" | "2026-03-13 23:55:01.99821+00" | "2026-03-14 10:55:01.99821" |
| "fd7d413f-f3e1-4021-b506-df0e50d917fd" | "2026-03-13 23:11:33.12345+00" | "2026-03-14 10:11:33.12345" |
| "2b910bd3-4735-4308-b21b-5ad3962a91f6" | "2026-03-13 22:30:45.55678+00" | "2026-03-14 09:30:45.55678" |
| "d11ac68d-4127-4b4e-93f5-65f9cdd5f08d" | "2026-03-13 22:02:15.00912+00" | "2026-03-14 09:02:15.00912" |
| "d9050673-108b-4514-83fe-3256cfe4773c" | "2026-03-13 21:44:08.81234+00" | "2026-03-14 08:44:08.81234" |
| "28ab7172-d68f-4cb8-af14-b530799df0e1" | "2026-03-13 21:15:22.42991+00" | "2026-03-14 08:15:22.42991" |

The data confirms a 100% match between the "missing" records and the transactions recorded in the final three hours of March 13th UTC.

**Conclusion:** The transactions are not missing from the database, nor was there a failure in the payment ingestion process. The issue is strictly a **Timezone Misclassification** within the Gateway's reporting route. Because the merchant is located in Sydney (UTC+11), their morning business hours occur while the database is still technically recording data for the previous UTC day.

## 4. Root Cause Analysis

The investigation traced the data flow from the Gateway API entry point down to the database execution layer.

- API Entry Point: The `/reports/transactions` route in the Gateway. Endpoint accepts `from_date` and `to_date` as `ISO-8601` strings (e.g., "2026-03-14").
- Service Layer: These strings are passed directly into the CRUD utility function without any timezone context or offset metadata.
- Data Access Layer: The logic concludes in a raw SQL execution within the PostgreSQL environment.

### 4.1 Technical Root Cause: No UTC Casting
The fundamental failure is located in the SQL Comparison Logic. The `created_at` column is stored as TIMESTAMPTZ (Timestamp with Time Zone) and the database is normalized to UTC, but the engine doesn't performs a cast on the incoming date strings.

```sql
-- [./gateway/app/crud.py] [lines: 139-149]
SELECT 
    id, 
    amount_minor, 
    currency, 
    status, 
    created_at 
FROM payments 
WHERE customer_id = :shop_id 
AND created_at >= :from_date 
AND created_at <= :to_date
ORDER BY created_at DESC
```

Because the application assumes that passed dates are the same for every user globally, it creates a temporal blind spot.

**Root Cause:** The system lacks timezone awareness. It fails to translate the merchant's local time into the database's UTC resulting in data misclassification during the retrieval phase.

## 5. Resolution

### 5.2 Implementation of timezone awareness
The solution involves refactoring the query to move away from implicit date casting. The database now shifts the stored UTC timestamps into the merchant's specific timezone context before the filter is applied:

```python
# [./gateway/app/crud.py] [lines: 139-149] [PATCH]
res = db_session.execute(text(
            """
            SELECT id, amount_minor, status, created_at 
            FROM payments 
            WHERE customer_id = :shop_id 
            AND created_at >= (:from_date || ' 00:00:00 ' || :merchant_tz)::timestamptz
            AND created_at <= (:to_date || ' 23:59:59 ' || :merchant_tz)::timestamptz
            ORDER BY created_at DESC;
            """),
            {
                "shop_id": report_request.shop_id ,
                "from_date": from_date,
                "to_date": to_date
                "merchant_tz": report_request.tz
            }
        )
```
</br>

Mandatory timezone identifier field also should be added to request model for transaction reprt route in Gateway API:
```python
# [./gateway/app/models.py] [lines: 28-31] [PATCH]
class ReportRequest(BaseModel):
    shop_id: str
    from_date: str
    to_date: str
    tz: str
```


### 5.3 Customer Communication

> **To:** Lachlan Murray (lockie_m@outbackstationery.au)</br>
**Subject:** Update: Update for March 14th Transaction Reporting Issue</br></br>
Hello Lachlan,</br>Thank you for your patience, our Support Team investigated the reported transaction discrepancy for March 14th:</br></br>1. We are happy to tell that records before 11AM of March 14 are not missing. What happend is that reporting tool takes UTC time as input and due the 11 hour gap with Your local time, records that are done at March 14 by Sydney/Australia timezone are recorded at the late hours of May 13 by UTC.</br></br>2. You can retrive the report with all 25 records for May 14 by adjusting the time to UTC time zone:</br>- From date: 2026-03-13 13:00:00</br>- To date: 2026-03-14 13:00:00</br></br>3. Our developer team is working on enhancing of user experience so you won't need to adjsut time to UTC manually anymore. Feature will be shipped in near updates and will be active immedately.</br></br>{{Company Name}} Support Team
