# Local Studio

Local-first Django platform for small businesses, with private Ollama AI, optional cloud models, prompt-assisted business setup, customer order workflows, and operational dashboards.

Local Studio is a Django application for local Ollama chat and restaurant ordering. It includes customer ordering, staff order management, menu and business settings, and optional saved chat memory.

## Requirements

- Python 3.10 or newer
- Ollama running on the Django host or reachable at `OLLAMA_BASE_URL`
- An Ollama model pulled locally, for example `ollama pull llama3.2`

Menu ordering and staff management work without an LLM. Ollama supports local chat and AI drafting. An OpenAI-compatible cloud provider can also be selected when its server-side credentials are configured.

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

## API

API requests use `X-API-Key` unless noted. Staff endpoints accept `X-Staff-Key`; some staff operations also accept `X-API-Key` for integrations.

- `GET /api/health/` and `GET /api/models/` check Ollama and list installed models.
- `GET/POST /api/business/profile/` reads or updates business settings.
- `POST /api/business/draft/` creates an unsaved business/catalog draft; `POST /api/business/setup/` saves the owner-reviewed draft.
- `GET/POST /api/menu/` lists available menu items or creates a menu item.
- `POST /api/orders/preview/` calculates an order without saving it.
- `POST /api/orders/` submits a customer order.
- `GET /api/staff/dashboard/`, `GET /api/orders/queue/`, and `GET /api/orders/<id>/` provide staff order information.
- `PATCH /api/orders/<id>/status/` updates an order status.
- `POST /api/orders/parse/` parses a text order against available menu items for customer review.
- `POST /api/chat/` streams a local response or a normalized cloud response as NDJSON and stores conversation history in SQLite.
- `/api/conversations/`, `/api/memory/`, and `/api/memories/` manage chat history and optional saved memory.

## Configuration and deployment

`DJANGO_DEBUG=true` is intended only for local development. For production, use `DJANGO_DEBUG=false`, set `DJANGO_ALLOWED_HOSTS` to the exact hostnames, run `python manage.py collectstatic`, and serve `STATIC_ROOT` through a production web server or static-file service. Do not expose Django's development server or Ollama's unauthenticated port to untrusted networks. Use HTTPS when sending credentials over a network.

Choose `local` in business settings for Ollama. Choose `cloud` and enter `openai` or `openai-compatible` to route model requests to the configured cloud endpoint. Set the cloud API key and endpoint in the server environment, then set the business default model to one supported by that endpoint. Cloud prompts, including optional memory extraction, leave the local network; disclose this to users and select cloud only with appropriate consent.

## Tests

```bash
python manage.py check
python manage.py test
```
