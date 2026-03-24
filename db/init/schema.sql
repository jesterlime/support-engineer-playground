CREATE USER processor_user WITH PASSWORD 'processor_pass';
GRANT CONNECT ON DATABASE payments TO processor_user;
GRANT USAGE ON SCHEMA public TO processor_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO processor_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO processor_user;

create extension if not exists "uuid-ossp";

create table payments (
  id uuid primary key,
  order_id text not null,
  amount_minor integer not null check (amount_minor > 0),
  currency char(3) not null,
  status text not null,
  description text,
  customer_id text,
  customer_email text,
  customer_ip inet,
  payment_token text,
  idempotency_key text not null unique,
  webhook_url text,
  correlation_id uuid not null,
  bank_txn_id text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index idx_payments_order_id on payments(order_id);
create index idx_payments_status on payments(status);

create table payment_events (
  id bigserial primary key,
  payment_id uuid not null references payments(id),
  from_status text,
  to_status text not null,
  reason text,
  actor text not null,
  created_at timestamptz not null default now()
);

create index idx_events_payment_id on payment_events(payment_id);

create table webhook_deliveries (
  id bigserial primary key,
  payment_id uuid not null references payments(id),
  attempt_no integer not null,
  target_url text not null,
  http_status integer,
  response_body text,
  next_retry_at timestamptz,
  delivered_at timestamptz
);

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO processor_user;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO processor_user;
