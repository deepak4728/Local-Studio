# OrgForms

OrgForms is a Django application for organization workspaces, dynamic forms, public submissions, and AI-assisted work. SQLite stores application data. Ollama and optional cloud APIs provide inference.

## Project structure

`orgforms/` contains settings and top-level routing. The five Django apps are:

| App | Owns |
| --- | --- |
| `accounts` | Authentication, personal profiles, portfolios, personal documents |
| `organizations` | Workspaces, dashboard, categories, memberships, groups, organization documents |
| `forms` | Builder, field library, sharing, public forms, submissions, attachments, catalogs, item selections |
| `chat` | AI Hub, conversations, messages, memory, permission-scoped insights |
| `ai_gateway` | AI settings, model profiles, Ollama/cloud adapters, classification |

Shared layouts and browser assets live in `templates/` and `static/`. Feature-specific templates and assets live in their app. There are no `org`, `api`, or `restaurant` apps. Restaurant and cafe are organization categories; item cards and ratings are reusable fields for every category.

## Run locally

Requires Python 3.12+.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
DJANGO_DEBUG=true python manage.py runserver 127.0.0.1:8000
```

For a database created before the five-app reorganization, **use the import procedure below instead of running these new migrations on the old database**.

| Page | URL |
| --- | --- |
| Home | `/` |
| Signup / login | `/accounts/signup/`, `/accounts/login/` |
| Personal profile | `/accounts/profile/` |
| Dashboard | `/dashboard/` |
| Organization | `/org/<organization-slug>/` |
| People / settings | `/org/<organization-slug>/people/`, `/org/<organization-slug>/settings/` |
| Submissions | `/org/<organization-slug>/submissions/` |
| Form builder | `/org/<organization-slug>/forms/new/` |
| Public form | `/org/<organization-slug>/<form-slug>/` |
| Item catalog | `/org/<organization-slug>/menu/` |
| AI Hub | `/_chat/?org=<organization-slug>` |

Existing URLs and public links are retained. The legacy menu URL now manages a reusable item catalog.

## Forms and catalogs

Each `item_cards` field has an organization-owned `catalog_id`. If omitted, the organization's default catalog is assigned. Multiple fields can use separate catalogs through the advanced form schema. The existing catalog-management page edits the default catalog.

Responses accept `catalog_item_id` or the historical `menu_item_id`, plus a whole quantity from 1 to 50. Prices come from the server. Submissions retain item names and price snapshots, with quantities and totals recorded in `forms.ItemSelection` and `forms.SelectionLine`. Historical discounts, tax rules, IDs, and processing/payment states are preserved. The existing tax calculation applies tax to subtotal before discount.

Historical `restaurant_order`, `items_field_id`, and `order_id` values remain readable. An `order_id` stored in a submission refers to a migrated item selection. Respondents cannot attach arbitrary historical selections. Existing selections that have started processing or payment cannot be edited.

Moving a catalog form without responses requires an explicit `catalog_map` in the form-transfer API, mapping source catalog IDs to catalogs in the destination organization. Forms with item selections and saved responses must be duplicated or archived rather than moved, preserving their historical organization ownership. Ordinary forms retain the existing transfer behavior.

## Access and files

Workspaces require organization membership. Admins and managers manage organization forms; members only see forms they may access. Form audiences are public links, organization members, or selected accounts/groups. Public form access never grants workspace, file, chat, or response-list access. Installation API keys do not bypass organization membership.

Authenticated application APIs use Django sessions; no installation API key is required.

Signup uses Django's existing user model and email-as-login convention. An installation administrator can claim an unowned legacy organization with:

```bash
python manage.py claim_legacy_organization <organization-slug> <existing-account-email>
```

Uploaded files remain private under `MEDIA_ROOT`. Organization and personal documents and submission attachments are served by permission-checked endpoints. Do not expose a public `/media/` mapping. Back up both SQLite and the media directory.

## AI

All model calls use `ai_gateway`. Configure `OLLAMA_BASE_URL` and `OLLAMA_DEFAULT_MODEL` for local inference. Cloud adapters support OpenAI-compatible APIs using server-side `CLOUD_API_KEY` and `CLOUD_API_BASE_URL`. AI settings are independent of catalogs and are available at `/api/ai/configuration/`, scoped with `X-Organization` or `?org=`; only managers/admins may change their organization's settings. Shared model profiles require an installation superuser to modify.

### M1 Air local model reference

These are local measurements supplied by the project owner. They are useful for choosing a model on this MacBook Air; performance and memory usage can vary with context length, Ollama version, other running apps, and model quantization. “Think used” records the setting during the speed run. “Think available” records whether the published Ollama model family exposes thinking support; the AI Hub’s live toggle uses the capability reported by the installed Ollama model (or its configured model profile).

| Model | Think used | Think available | Active memory (Activity Monitor) | Speed (eval rate) | Process size (`ollama ps`) | File size |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| `gemma3:1b` | Off | No | 158 MB | 52.87 tok/s | ~870 MB | 815 MB |
| `llama3.2:1b` | Off | No | 230 MB | 42.58 tok/s | ~1.5 GB | 1.3 GB |
| `qwen3.5:0.8b` | Not recorded | Yes | 600 MB | 41.92 tok/s | Not recorded | Not recorded |
| `qwen3.5:2b` | Off | Yes | 860 MB | 25.88 tok/s | ~2.7 GB | 2.7 GB |
| `gemma4:e2b` | Off | Yes | 3.20 GB | 31.43 tok/s | ~7.2 GB | 7.2 GB |
| `qwen3.5:4b` | Off | Yes | 4.17 GB | 17.61 tok/s | ~3.4 GB | 3.4 GB |

Ollama publishes thinking capability for the Qwen 3.5 and Gemma 4 families; Gemma 3 and Llama 3.2 do not list that capability on their model pages ([Qwen 3.5](https://ollama.com/library/qwen3.5), [Gemma 4](https://ollama.com/library/gemma4), [Gemma 3](https://ollama.com/library/gemma3), [Llama 3.2](https://ollama.com/library/llama3.2)). The installed local model metadata is authoritative for the app toggle.

Quick selection guide from these measurements:

| Need | Suggested model | Why |
| --- | --- | --- |
| Fast replies and lowest observed memory | `gemma3:1b` | Fastest measured at 52.87 tok/s and 158 MB active memory. |
| Lightweight general chat | `llama3.2:1b` | 42.58 tok/s at 230 MB active memory. |
| Think-capable Qwen with a smaller footprint | `qwen3.5:0.8b` | 41.92 tok/s at 600 MB active memory; Think usage was not recorded. |
| Try Think mode without the largest measured footprint | `qwen3.5:2b` | Think capable, 25.88 tok/s, and 860 MB active memory. |
| More capable local reasoning | `gemma4:e2b` | Think capable and measured at 31.43 tok/s; it used 3.20 GB active memory. |
| Larger Qwen option | `qwen3.5:4b` | Think capable, with the slowest measured speed and highest active memory in this set. |

To install these Ollama models, run `ollama pull <model-name>` for each desired tag. Start Ollama, set `OLLAMA_DEFAULT_MODEL=<model-name>` in `.env` if you want a default, then run OrgForms. The AI Hub discovers installed models from `/api/models/`, lets you select one for a message, and shows this M1 Air reference under **Model guide**.

Organization APIs remain at `/api/orgs/`, form APIs at `/api/forms/`, and chat APIs at `/api/chat/`. Model discovery remains at `/api/models/`. Chat retrieval uses permission-scoped form/submission summaries and uploaded UTF-8 text, Markdown, and CSV documents; it never runs model-generated SQL. Unlinked historical item selections are excluded from chat summaries.

The local System 1 classifier handles public quick-fill without sending respondent text to a third party. Authenticated classification integrations can optionally use `JEV_API_URL` / `JEV_API_KEY` or `SCALEDOWN_API_URL` / `SCALEDOWN_API_KEY`.

## Import an older database

Stop the development server and other writers. Make a SQLite backup, preserve the existing code version, and copy `media/` before beginning. Run the following with an absolute path to a **new, nonexistent** destination database:

```bash
DJANGO_DB_NAME=/absolute/path/orgforms-next.sqlite3 python manage.py migrate --noinput
DJANGO_DB_NAME=/absolute/path/orgforms-next.sqlite3 python manage.py import_legacy_orgforms --source /absolute/path/legacy-backup.sqlite3
```

The importer reads the source in a consistent, read-only transaction and refuses a nonempty destination. It preserves retained records and timestamps, binds historical item selections to submissions, separates catalogs from AI settings, remaps model permissions, and verifies copied values, counts, and SQLite integrity before committing. Failed imports roll back. The source must include the latest historical migrations through submission attachments and chat message references.

After successful import and checks, replace `db.sqlite3` with the new file while all writers remain stopped, then restart the server. Keep the original database and original code together for rollback. Do not run the old code against the new schema. Removed payment, kitchen, inventory, and operations data remains in the archived original database.

The local pre-restructure recovery files are under the ignored `backups/` directory. The source archive includes the original `.env` and any uploaded files; keep it private and outside version control.

## Checks and deployment

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test --noinput
```

For deployment, configure a unique `DJANGO_SECRET_KEY`, exact `DJANGO_ALLOWED_HOSTS`, `DJANGO_DEBUG=false`, HTTPS, and collected static files. Do not expose the development server or an unauthenticated Ollama port to the internet.
