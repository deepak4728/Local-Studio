# Local Studio

Local-first Django platform for small businesses, with private Ollama AI, optional cloud models, prompt-assisted business setup, customer order workflows, and operational dashboards.

Local Studio is a Django application for local Ollama chat and restaurant ordering. It includes customer ordering, staff order management, menu and business settings, and optional saved chat memory.

## Requirements

- Python 3.10 or newer
- Ollama running on the Django host or reachable at `OLLAMA_BASE_URL`
- An Ollama model pulled locally, for example `ollama pull llama3.2`

Menu ordering and staff management work without an LLM. Ollama supports local chat and AI drafting. Menu items can also be tagged with a barcode or QR payload so the customer ordering page can scan a code with the device camera to add the matching item to the basket. An OpenAI-compatible cloud provider can also be selected when its server-side credentials are configured.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set unique random values for `DJANGO_SECRET_KEY`, `OLLAMA_API_KEY`, and `STAFF_API_KEY`. Set `OLLAMA_DEFAULT_MODEL` to a model available in Ollama. For cloud use, set `CLOUD_API_KEY` and, if needed, `CLOUD_API_BASE_URL`; these credentials remain server-side. Django loads `.env` automatically, and existing shell variables take precedence.

```bash
set -a
source .env
set +a
python manage.py migrate
DJANGO_DEBUG=true python manage.py runserver 127.0.0.1:8000
```

Open these pages:

- `http://127.0.0.1:8000/` for chat
- `http://127.0.0.1:8000/order/` for customer ordering
- `http://127.0.0.1:8000/staff/` for the staff dashboard
- `http://127.0.0.1:8000/staff/menu/` for menu management
- `http://127.0.0.1:8000/staff/settings/` for business settings

The chat and customer ordering pages request the `OLLAMA_API_KEY`; staff pages request the `STAFF_API_KEY`. Keys are sent in request headers and are not embedded in rendered pages. The browser pages keep entered keys only for the current tab where applicable.

### Local model profiles

Staff settings can save a profile for any Ollama model name, including a model that
will be pulled later. Profiles define the context window, whether the model supports
thinking, and whether it accepts images. The chat model menu includes installed
models plus saved profiles, and the gear button lets a user override the context
window, thinking, and input mode for the next request. Image attachments are sent
to Ollama as base64 `images` fields and are rejected for text-only profiles.

## API

API requests use `X-API-Key` unless noted. Staff endpoints accept `X-Staff-Key`; some staff operations also accept `X-API-Key` for integrations.

- `GET /api/health/` and `GET /api/models/` check Ollama and list installed models.
- `GET/POST /api/local-model-profiles/` and `PATCH/DELETE /api/local-model-profiles/<id>/`
  manage local model capability profiles (staff authentication).
- `GET/POST /api/business/profile/` reads or updates business settings.
- `POST /api/business/draft/` creates an unsaved business/catalog draft; `POST /api/business/setup/` saves the owner-reviewed draft.
- `GET/POST /api/menu/` lists available menu items or creates a menu item.
- `POST /api/orders/preview/` calculates an order without saving it.
- `POST /api/orders/` submits a customer order.
- `GET /api/staff/dashboard/`, `GET /api/orders/queue/`, and `GET /api/orders/<id>/` provide staff order information.
- `PATCH /api/orders/<id>/status/` updates an order status.
- `POST /api/orders/parse/` parses a text order against available menu items for customer review.
- `POST /api/orders/ai-draft/` is the equivalent provider-neutral AI drafting endpoint.
  It returns a review-only draft with explicit `warnings` and `questions`; it never
  creates an order, chooses availability, sets modifiers/prices, charges payment,
  or sends anything to the kitchen. Provider JSON is treated as an untrusted
  proposal: menu IDs, quantities, availability, and all totals are validated and
  calculated from the current database catalog.
- `POST /api/chat/` streams a local response or a normalized cloud response as NDJSON and stores conversation history in SQLite.
- `/api/conversations/`, `/api/memory/`, and `/api/memories/` manage chat history and optional saved memory.

### Connected restaurant foundation

The first connected phase keeps legacy order clients working while adding
independent `fulfillment_status` and `payment_status` fields (existing
`status` values are copied to fulfillment during migration; payment starts as
`pending`). Signed table QR values and expiring dining-session tokens are
provided by `RestaurantTable.sign()`/`verify()` and `DiningSession.sign()`/
`verify()`; they are signed with Django's secret and never contain customer
data. `RestaurantNetworkPolicy` evaluates IPv4/IPv6 CIDRs and can optionally
honor a trusted proxy header. Order creation and lifecycle changes are written
to `SecurityAuditLog`.

Foundation endpoints are under `/api/restaurant/`: `GET/POST tables/`,
`POST tables/<id>/sessions/`, and `GET/PATCH network-policy/`. Feature flags
and fee plans are data models; `calculate_fee()` and `FeePlan.calculate()`
round deterministically to cents. No payment provider is selected or called.

### Payment phase 2

Payments use the provider-neutral `PaymentAdapter` protocol in
`restaurant.payments`. The deterministic `local` adapter never makes network
calls and is suitable for development and tests. Create an intent with
`POST /api/restaurant/payments/intents/` (staff key, including an
`idempotency_key` and `order_id`), confirm/refund/cancel it with
`POST /api/restaurant/payments/intents/<id>/`, and deliver provider events to
`POST /api/restaurant/payments/webhook/`. Webhook event IDs are unique and
replays are safe; invalid state transitions are rejected. Orders progressing
beyond pending from an outside network require a successful payment, while
signed live dining sessions and allowed networks remain trusted. The local
adapter can be replaced by registering another adapter without changing API
models or endpoints.

## Configuration and deployment

`DJANGO_DEBUG=true` is intended only for local development. For production, use `DJANGO_DEBUG=false`, set `DJANGO_ALLOWED_HOSTS` to the exact hostnames, run `python manage.py collectstatic`, and serve `STATIC_ROOT` through a production web server or static-file service. Do not expose Django's development server or Ollama's unauthenticated port to untrusted networks. Use HTTPS when sending credentials over a network.

Choose `local` in business settings for Ollama. Choose `cloud` and enter `openai` or `openai-compatible` to route model requests to the configured cloud endpoint. Set the cloud API key and endpoint in the server environment, then set the business default model to one supported by that endpoint. Cloud prompts, including optional memory extraction, leave the local network; disclose this to users and select cloud only with appropriate consent.

## Tests

```bash
python manage.py check
python manage.py test
```

## Kitchen workflow (phase 3)

Orders now have an explicit staff review gate before they can be sent to the kitchen. Staff can approve or reject an order with `PATCH /api/restaurant/orders/<id>/review/`, then create an idempotent KOT with `POST /api/restaurant/kitchen/tickets/` using `order_id` (and optional `station`/`notes`). The kitchen display is available at `/staff/kitchen/` and uses the staff key to read and transition tickets.

Kitchen tickets and their items support `queued`, `preparing`, `ready`, `completed`, and `cancelled` transitions. Invalid transitions return `409`; every review and kitchen transition is recorded in `SecurityAuditLog`. By default, a ticket requires a paid order and a trusted staff/session/network request. The restaurant network policy can explicitly enable `allow_unpaid_kitchen` or `allow_untrusted_kitchen` when a business policy requires it. Existing order endpoints and status fields remain available for backwards compatibility.

## Restaurant operations

The restaurant app now includes local-first operational foundations for outlets and staff roles, ingredients and recipes, auditable stock movements, low-stock alerts, suppliers and purchases, wastage, customers and loyalty transactions, offers, fee settlements, and daily operational reports. Staff endpoints are under `/api/restaurant/operations/<resource>/` and require the existing staff key authentication. Completing a kitchen ticket deducts recipe ingredients once per order using an idempotent stock movement key and records a security audit event. No external inventory, loyalty, or payment provider is assumed.
