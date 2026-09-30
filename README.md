# EVE Healthcare — Diagnostics Booking API

A backend service for diagnostic test bookings and simulated payments, built with
**FastAPI**, **SQLAlchemy 2.0 (async)**, **PostgreSQL** and **Alembic**.

The interesting part of this assignment is not the CRUD — it is the payment
webhook, which must stay correct when the provider delivers the same event five
times, delivers events out of order, or delivers one for a booking the patient
has already cancelled. That logic lives in
[`app/services/payment_service.py`](app/services/payment_service.py) and is
covered end to end by
[`tests/test_webhook_idempotency.py`](tests/test_webhook_idempotency.py).

```
133 tests, 96% coverage (100% on every service module)
```

---

## Contents

- [Quick start](#quick-start)
- [API reference](#api-reference)
- [A complete walkthrough with curl](#a-complete-walkthrough-with-curl)
- [Database design](#database-design)
- [Booking state machine](#booking-state-machine)
- [How the webhook stays idempotent](#how-the-webhook-stays-idempotent)
- [Edge cases](#edge-cases)
- [Tests](#tests)
- [Assumptions](#assumptions)
- [What I would improve with more time](#what-i-would-improve-with-more-time)

---

## Quick start

### With Docker (recommended)

```bash
cp .env.example .env          # optional; compose sets its own values
docker compose up --build
```

This starts PostgreSQL 16 and the API. The API container waits for the database
healthcheck, runs `alembic upgrade head`, seeds a demo catalogue, and serves on
**http://localhost:8000**.

- **Demo UI: <http://localhost:8000/>** — see below
- Swagger UI: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>
- Health: <http://localhost:8000/healthz>

> **Disclosure:** Docker was not installed on the machine this was developed on,
> so the `Dockerfile` and `docker-compose.yml` are written from the same
> commands that were verified locally, but the image build itself is unverified.
> The local path below was run end to end.

### Without Docker

Requires Python 3.11+. PostgreSQL is optional — the app runs on SQLite too.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

cp .env.example .env               # then edit DATABASE_URL if you have Postgres

alembic upgrade head               # create the schema
python -m scripts.seed             # demo user + 3 centres + 6 tests

uvicorn app.main:app --reload
```

Defaults to `sqlite+aiosqlite:///./eve.db`. To use PostgreSQL, set:

```bash
DATABASE_URL=postgresql+asyncpg://eve:eve@localhost:5432/eve_diagnostics
```

The seed creates **`asha@example.com` / `password123`**.

### Demo UI

Open **<http://localhost:8000/>** once the server is running. It is a small
dependency-free page (plain HTML/CSS/JS in [`app/static/`](app/static/), served
by FastAPI at `/ui/`, no build step) that walks through the whole flow:

- **Book a test** — browse centres by city, see per-centre prices, book a slot.
- **My bookings** — pay (instantly, forced decline, or async via webhook) and
  cancel, with the booking state machine drawn and the current state lit up.
- **Webhook lab** — act as the payment provider: deliver the same event three
  times, send a late out-of-order event, or settle a cancelled booking, and see
  the `outcome` of each delivery.

A panel on the right shows every request and response live. It signs in as the
seeded demo patient by default.

### Run the tests

```bash
pytest                              # 133 tests
pytest --cov --cov-report=term      # with coverage
```

The suite needs no database server: each test gets its own temporary SQLite
file.

---

## API reference

All endpoints are under `/api/v1`. Authenticated routes take
`Authorization: Bearer <token>`.

| Method | Path | Auth | Purpose |
|---|---|:--:|---|
| `POST` | `/auth/signup` | — | Register; returns a token |
| `POST` | `/auth/login` | — | Exchange credentials for a token |
| `GET` | `/auth/me` | ✓ | Current user |
| `GET` | `/centres` | — | List centres; `?city=`, `?test_code=`, paged |
| `POST` | `/centres` | ✓ | Create a centre |
| `GET` | `/centres/{id}` | — | Centre with the tests it offers |
| `GET` | `/centres/{id}/tests` | — | Offerings with prices |
| `POST` | `/centres/{id}/tests` | ✓ | Offer a test at a price |
| `GET` | `/tests` | — | Test catalogue; `?search=`, paged |
| `POST` | `/tests` | ✓ | Add a test to the catalogue |
| `POST` | `/bookings` | ✓ | Book a test (starts `PENDING`) |
| `GET` | `/bookings` | ✓ | Your bookings; `?status=`, paged |
| `GET` | `/bookings/{id}` | ✓ | One of your bookings |
| `POST` | `/bookings/{id}/cancel` | ✓ | Cancel a booking |
| `POST` | `/payments` | ✓ | Pay for a booking (simulated) |
| `POST` | `/payments/webhook` | — | Provider callback (**idempotent**) |
| `GET` | `/healthz` | — | Liveness probe |

### Error format

Every failure — validation, authorisation, conflict, 500 — uses one envelope:

```json
{
  "error": {
    "code": "booking_not_payable",
    "message": "A booking in state CONFIRMED cannot be paid for.",
    "details": { "current_status": "CONFIRMED" }
  }
}
```

`code` is a stable, machine-readable string; `message` is for humans; `details`
is present only when there is something useful to add.

### Pagination

List endpoints take `?limit=` (1–100, default 20) and `?offset=`, and return:

```json
{
  "items": [ ... ],
  "meta": { "total": 42, "limit": 20, "offset": 0, "has_more": true }
}
```

---

## A complete walkthrough with curl

```bash
API=http://localhost:8000/api/v1

# 1. Log in as the seeded demo patient
TOKEN=$(curl -s -X POST $API/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"asha@example.com","password":"password123"}' | jq -r .access_token)

# 2. Find a centre and the tests it offers
curl -s "$API/centres?city=Hyderabad" | jq '.items[] | {id, name}'
curl -s "$API/centres/1/tests" | jq '.[] | {offering: .id, test: .test.code, price}'
```
```json
[
  { "offering": 1, "test": "CBC",   "price": "450.00" },
  { "offering": 2, "test": "LFT",   "price": "999.13" },
  { "offering": 3, "test": "TSH",   "price": "550.00" },
  { "offering": 4, "test": "LIPID", "price": "899.00" }
]
```
```bash
# 3. Book offering 1 (CBC at Banjara Hills, ₹450)
curl -s -X POST $API/bookings \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"centre_test_id": 1, "appointment_at": "2026-10-05T09:30:00+05:30"}' | jq
```
```json
{
  "id": 1,
  "status": "PENDING",
  "appointment_at": "2026-10-05T04:00:00Z",
  "amount": "450.00",
  "centre": { "id": 1, "name": "EVE Diagnostics - Banjara Hills", "city": "Hyderabad" },
  "test":   { "id": 1, "code": "CBC", "name": "Complete Blood Count" }
}
```

### Paying — two modes

**`sync`** (default) settles immediately:

```bash
curl -s -X POST $API/payments \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"booking_id": 1}' | jq '{status, provider_reference, booking: .booking.status}'
```
```json
{ "status": "SUCCESS", "provider_reference": "pay_84082dc9…", "booking": "CONFIRMED" }
```

**`async`** leaves the payment `PENDING` for the provider to settle by webhook —
this is what the webhook endpoint is for:

```bash
REF=$(curl -s -X POST $API/payments \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"booking_id": 2, "mode": "async"}' | jq -r .provider_reference)
```

### The webhook, delivered three times

```bash
for i in 1 2 3; do
  curl -s -X POST $API/payments/webhook -H 'Content-Type: application/json' \
    -d "{\"event_id\":\"evt_001\",\"provider_reference\":\"$REF\",
         \"status\":\"SUCCESS\",\"amount\":\"450.00\"}"
  echo
done
```
```json
{"event_id":"evt_001","outcome":"applied","payment_status":"SUCCESS","booking_status":"CONFIRMED"}
{"event_id":"evt_001","outcome":"duplicate","detail":"This event_id has already been processed."}
{"event_id":"evt_001","outcome":"duplicate","detail":"This event_id has already been processed."}
```

One payment row, one booking transition, and **HTTP 200 every time** — a
duplicate is not an error, because a provider retries anything that is not 2xx.

### Forcing a decline

The simulated gateway is deterministic: an amount whose minor units are `13`
(configurable via `PAYMENT_FAILURE_CENTS`) is declined. The seeded LFT offering
is priced `999.13` for exactly this reason. You can also force either branch:

```bash
curl -s -X POST $API/payments \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"booking_id": 3, "force_status": "FAILED"}' | jq '.booking.status'   # "FAILED"
```

A `FAILED` booking can be paid again; the retry moves it back to `PENDING` and
then to `CONFIRMED`, and both attempts are kept as separate payment rows.

---

## Database design

```mermaid
erDiagram
    users            ||--o{ bookings       : places
    centres          ||--o{ centre_tests   : offers
    diagnostic_tests ||--o{ centre_tests   : "is offered as"
    centre_tests     ||--o{ bookings       : "is booked as"
    bookings         ||--o{ payments       : "is paid by"
    payments         ||--o{ webhook_events : "is updated by"

    users {
        int      id PK
        string   email UK "lower-cased"
        string   password_hash
        string   full_name
        string   phone
    }
    centres {
        int      id PK
        string   name
        string   city "indexed"
        string   address
        bool     is_active
    }
    diagnostic_tests {
        int      id PK
        string   code UK "e.g. CBC"
        string   name
        text     description
        text     preparation
    }
    centre_tests {
        int      id PK
        int      centre_id FK
        int      test_id FK
        numeric  price "UNIQUE(centre_id, test_id)"
        bool     is_active
    }
    bookings {
        int      id PK
        int      user_id FK
        int      centre_test_id FK
        datetime appointment_at "UTC"
        numeric  amount "snapshot"
        enum     status "PENDING|CONFIRMED|FAILED|CANCELLED"
        string   cancellation_reason
    }
    payments {
        int      id PK
        int      booking_id FK
        numeric  amount
        enum     status "PENDING|SUCCESS|FAILED"
        string   provider_reference UK
        string   failure_reason
    }
    webhook_events {
        int      id PK
        string   event_id UK "idempotency key"
        int      payment_id FK "nullable"
        json     payload
        datetime processed_at
        string   outcome
    }
```

### The decisions worth explaining

**1. `centre_tests` carries the price.** A CBC costs ₹450 at Banjara Hills and
₹399 at Gachibowli. Price is a property of *the offering*, not of the test and
not of the centre. This also makes a booking point at a single foreign key:
`centre_test_id` pins centre, test and price together, so it is impossible to
express a booking for a test the chosen centre does not perform.

**2. `bookings.amount` is a snapshot.** If a centre re-prices the test tomorrow,
what an existing patient owes must not change. There is a test for this
(`test_booking_price_is_snapshotted`).

**3. Money is `NUMERIC(12,2)`, never `FLOAT`.** On SQLite — which has no exact
decimal type — a custom `Money` type stores a zero-padded fixed-point string so
values are exact and still sort correctly. The application only ever sees
`Decimal`.

**4. Timestamps are timezone-aware UTC.** A custom `UTCDateTime` type normalises
on the way in and out. Naive datetimes are rejected at the API boundary: `09:00`
without an offset is ambiguous, and an appointment is a real instant.

**5. Three constraints do work the application layer cannot do safely:**

| Constraint | What it prevents |
|---|---|
| `uq_bookings_active_slot` — partial unique on `(user_id, centre_test_id, appointment_at) WHERE status IN ('PENDING','CONFIRMED')` | The same patient double-booking a slot. Partial, so cancelling genuinely frees it. |
| `uq_payments_one_pending_per_booking` — partial unique on `booking_id WHERE status = 'PENDING'` | Two concurrent payment attempts both charging one booking. |
| `webhook_events.event_id` — `UNIQUE` | Processing the same provider event twice. |

Each is enforced by the database rather than by an `if already_exists:` check,
because a check-then-act pair can always be interleaved by a concurrent request.
`test_slot_uniqueness_is_enforced_by_the_database` asserts this at the DB level,
not through the API.

---

## Booking state machine

```
                    payment SUCCESS
      ┌───────────────────────────────────────────► CONFIRMED
      │                                                  │
   PENDING ◄──────────── retry payment ─┐                │
      │                                 │                │
      │  payment FAILED                 │                │  cancel
      ▼                                 │                │
   FAILED ────────────────────────────►─┘                │
      │                                                  │
      │  cancel                                          ▼
      └──────────────────────────────────────────►  CANCELLED  (terminal)
                                                         ▲
                        PENDING ─── cancel ───────────────┘
```

The table lives in
[`booking_service.ALLOWED_TRANSITIONS`](app/services/booking_service.py) and is
the single authority on booking state. Nothing in the codebase assigns
`booking.status` directly — callers ask `apply_transition()` for a move, which
raises `409` if the table forbids it. That is why a late webhook cannot revive a
`CANCELLED` booking: there is no code path that could express it.

`CANCELLED` is terminal by design. A patient who cancelled and walked away must
not find themselves booked again because a delayed callback arrived.

---

## How the webhook stays idempotent

The requirement: *"If the same webhook/event is received multiple times, it must
not create duplicate payments, duplicate bookings, or otherwise corrupt the
booking state."*

The naive approach is to check first:

```python
if await already_processed(event_id):   # ← two concurrent deliveries
    return                              #   both read "no" here
await apply(event)                      #   and both apply
```

That race is not theoretical; providers fan out retries in parallel. So the
claim and the check are the *same operation*, and the database arbitrates:

```sql
INSERT INTO webhook_events (event_id, payload, received_at)
VALUES (...)
ON CONFLICT (event_id) DO NOTHING
RETURNING id;
```

Exactly one caller gets an id back. Everyone else gets nothing and stops.

The full handler, all inside **one transaction**:

1. **Claim** `event_id` with the insert above. No row returned → `duplicate`, return 200.
2. **Lock** the payment: `SELECT … WHERE provider_reference = ? FOR UPDATE`.
   Unknown reference → record the event for audit, then 404 (a retry cannot make
   it exist).
3. **Verify** the amount if one was supplied; a mismatch is recorded and rejected 422.
4. **Short-circuit** if the payment has already settled — an out-of-order or
   contradictory redelivery is accepted (200) and changes nothing.
5. **Lock** the booking `FOR UPDATE` and settle, moving it only if the state
   machine permits.
6. **Stamp** the ledger row with its outcome and commit.

Because the claim and the state change share a transaction, a crash halfway
through rolls back the claim too — so the provider's retry is genuinely safe
rather than permanently swallowed.

### Outcomes

| `outcome` | HTTP | Meaning |
|---|:--:|---|
| `applied` | 200 | Payment settled and the booking moved |
| `duplicate` | 200 | This `event_id` was already processed; nothing changed |
| `ignored_terminal_payment` | 200 | The payment had already settled |
| `booking_not_updatable` | 200 | Payment recorded, but the booking is in a final state (e.g. cancelled) |
| — | 404 | `provider_reference` matches no payment |
| — | 422 | Amount does not match the payment |

`webhook_events` doubles as an audit log: every delivery is stored with its raw
payload and what the handler decided to do with it, including deliveries that
were rejected.

### Authentication

The webhook is unauthenticated by default — the caller is a payment provider,
not a logged-in user, and this keeps it callable straight from `/docs`. Setting
`WEBHOOK_SECRET` makes it require a matching `X-Webhook-Secret` header. A real
integration would verify an HMAC signature over the raw body instead.

---

## Edge cases

Every row here has a test.

| Situation | Response |
|---|---|
| Same `event_id` delivered N times | 200, `duplicate`, one payment, one transition |
| 8 simultaneous deliveries of one event | Exactly one `applied`, seven `duplicate` |
| `FAILED` webhook after the payment settled `SUCCESS` | 200, `ignored_terminal_payment`, booking unchanged |
| Webhook for a cancelled booking | 200, payment recorded, booking stays `CANCELLED` |
| Webhook for an unknown `provider_reference` | 404, event still recorded for audit |
| Webhook amount ≠ payment amount | 422, nothing changes |
| Same `event_id` reused across two different payments | 200, `duplicate`; the second payment is untouched |
| Reading/paying/cancelling another user's booking | **404, not 403** — a 403 confirms the id exists |
| Paying a `CONFIRMED` booking | 409 `booking_not_payable` |
| Paying a `CANCELLED` booking | 409 `booking_not_payable` |
| Second in-flight payment for one booking | 409 `payment_in_flight` |
| Retrying a `FAILED` booking | 201; booking returns to `PENDING`, then `CONFIRMED`; both attempts kept |
| Cancelling an already-cancelled booking | 409 `already_cancelled` |
| Appointment in the past | 422 `appointment_in_past` |
| Appointment >180 days ahead | 422 `appointment_too_far_ahead` |
| Appointment without a timezone offset | 422 |
| Double-booking the same slot | 409 `duplicate_booking` |
| Booking a withdrawn offering | 409 `offering_inactive` |
| Duplicate signup email (any case) | 409 `email_taken` |
| Login with an unknown email | 401, constant-time, never 404 |
| Password over bcrypt's 72-byte limit | 422, not a 500 |
| Expired / tampered / foreign-signed / non-access JWT | 401 |
| Missing `Authorization` header | 401 |
| `?limit=5000` | 422 — a client cannot request the whole table |

---

## Tests

```
tests/
  conftest.py                   fixtures: isolated DB, HTTP client, accounts, catalogue
  test_state_machine.py    (28) transition table + simulated gateway — pure units
  test_security.py         (10) password hashing, JWT issue/verify/expiry/tampering
  test_auth_api.py         (18) signup, login, /me, validation
  test_catalog_api.py      (17) centres, tests, offerings, filtering, pagination
  test_booking_api.py      (23) lifecycle, ownership, slot uniqueness, time rules
  test_payment_api.py      (13) sync/async payment, retries, double-charge
  test_webhook_idempotency.py (23) the idempotency contract in full
```

Integration tests run against the real ASGI app through `httpx`, so routing,
dependencies, serialisation and exception handlers are all exercised — not just
the service functions.

```bash
$ pytest -q
132 passed in 17s

$ pytest --cov --cov-report=term
TOTAL  951  36  96%
# app/services/*  100% across the board
```

> Coverage is configured with `concurrency = ["greenlet", "thread"]`. Without
> it, SQLAlchemy's async layer runs ORM work inside greenlets that the tracer
> cannot follow, and the service modules falsely report ~60%.

**One honest caveat.** The tests run on SQLite, which serialises writers. The
concurrency test therefore proves the *contract* (one `applied`, N−1
`duplicate`) but cannot demonstrate true parallel contention. The mechanisms
that make it correct under real concurrency — the unique index and
`SELECT … FOR UPDATE` — are PostgreSQL features; on SQLite `FOR UPDATE` compiles
to a no-op. Running the same suite against PostgreSQL is the first thing I would
add.

---

## Assumptions

1. **No roles.** The assignment defines only "users". Catalogue writes
   (`POST /centres`, `POST /tests`, `POST /centres/{id}/tests`) therefore require
   authentication but no particular role, so a reviewer can exercise the whole
   API with one account. A real system needs an operations role; the dependency
   to gate on would slot into `app/api/v1/deps.py`.
2. **Slot capacity is not modelled.** A centre is assumed able to serve any
   number of patients at a given time, so the uniqueness rule is per-patient. Real
   capacity would need a slots table with a per-slot count.
3. **`mode: "async"` on `POST /payments` is my addition.** Without it the
   simulated gateway always settles synchronously, which would leave the webhook
   with no non-trivial work to do. Real gateways support both, and this makes the
   webhook path exercisable.
4. **The gateway is deterministic**, not random — otherwise tests turn flaky and
   a reviewer cannot reproduce a run.
5. **A payment captured against a cancelled booking is recorded, not reversed.**
   The money moved; the booking stays cancelled. Refunds are out of scope, but
   this is the one place the system knowingly leaves a reconciliation task
   pending — see below.
6. **Access tokens only**, 60 minutes, no refresh tokens or revocation list.
7. **Soft-delete via `is_active`** on centres and offerings rather than hard
   deletes, so historical bookings keep pointing at something real.
8. **Single currency** (INR implied); no currency column.

---

## What I would improve with more time

**Correctness**

- **Run the suite against PostgreSQL in CI**, via `testcontainers` or a compose
  service. This is the top of the list: `FOR UPDATE` is a no-op on SQLite, so the
  locking is currently argued rather than demonstrated.
- **Refund / reconciliation path** for the case in assumption 5 — a payment that
  succeeds against a cancelled booking should queue a refund rather than sit as a
  silent liability.
- **HMAC signature verification** on the webhook instead of a shared secret, with
  a timestamp window to reject replays.

**Operability**

- **Structured JSON logging** with a request id propagated into every log line,
  and the `event_id` attached throughout webhook handling — that correlation is
  what you actually want at 3am.
- **Metrics**: payment success rate, webhook duplicate rate, booking funnel.
- **Rate limiting** on `/auth/login` and `/payments`.
- **Redis caching** for the centre catalogue, which is read-heavy and changes
  rarely.

**Product**

- **Slot capacity and availability**, so the system can answer "what times are
  free at this centre tomorrow?" — the question a real booking UI asks first.
- **Notifications** (email/SMS on confirmation) via a background worker; the
  transactional outbox pattern would fit the existing `webhook_events` design.
- **Cursor pagination** for the booking list, since offset pagination drifts as
  rows are inserted.
- **A `GET /payments/{id}`** and a payment history endpoint; today payments are
  only visible through the response that created them.

**Housekeeping**

- Pin dependencies with a lock file (`uv.lock` or `pip-compile`).
- `ruff` and `mypy --strict` in pre-commit and CI.
- An archival/retention policy for `webhook_events`, which grows without bound.

---

## Project layout

```
app/
  main.py                  app factory, exception handlers, router mounting
  core/
    config.py              pydantic-settings; refuses to boot in prod with the dev secret
    database.py            async engine, session factory, INSERT…ON CONFLICT helper
    security.py            bcrypt hashing, JWT issue/verify
    errors.py              AppError hierarchy → one JSON error envelope
  models/                  SQLAlchemy ORM + portable Money / UTCDateTime types
  schemas/                 Pydantic request/response DTOs
  api/v1/                  routers; deps.py holds session, current-user, pagination
  services/                all business logic — routers never touch the ORM
alembic/                   migrations (alembic check reports no drift)
scripts/seed.py            idempotent demo data
tests/                     132 tests
```

The dependency direction is one-way: `api → services → models`. Routers do no
data access and services raise no HTTP exceptions; they raise `AppError`
subclasses that `main.py` renders. That is what makes the state machine testable
without a web server and the webhook testable without HTTP.
