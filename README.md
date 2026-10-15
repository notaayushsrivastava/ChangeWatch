# ChangeWatch

ChangeWatch is a web service that monitors **public web pages** and alerts users to meaningful content changes while suppressing ordinary page churn (timestamps, counters, dynamic tokens, and ads).

---

## Features

- **Public-Only Monitoring with SSRF Defenses**: Strict IPv4/IPv6 private subnet, loopback, link-local, and cloud metadata filtering before navigation and during subresource requests.
- **Headless Browser Capture**: Uses Playwright Chromium to render dynamic, client-side JavaScript pages.
- **Noise Normalization**: Deterministic filtering of volatile timestamps, view/like counters, and dynamic session tokens before hashing.
- **Store-on-Change Policy**: Only the initial baseline and qualifying changed snapshots create permanent storage records; unchanged checks store lightweight run metadata.
- **Visual Region Picker**: Sandboxed interactive DOM preview allowing users to click page elements to configure Watch and Ignore CSS selectors.
- **Multi-Mode Version Comparison**:
  - Accessible Line-by-Line **Text Diff** (`+` and `-`).
  - **Side-by-Side Screenshots** with synchronized scrolling.
  - Interactive **Swipe Slider** (drag before/after divider).
  - Computer Vision **Pixel Diff Overlay** (Pillow-generated red highlight mask).
- **Alert Channels**: Email alerts (Console logger for dev, SMTP, or Resend) and Discord Webhook alerts with encrypted secrets and deduplication keys.
- **Background Worker & Scheduler**: Database-backed queue with jitter scheduling, bounded retries, and recovery across restarts.
- **Konami Code Easter Egg**: Enter `↑ ↑ ↓ ↓ ← → ← → B A` anywhere in the console to trigger retro radar HUD mode.

---

## Quickstart & Installation

### 1. Prerequisites
- **Python**: 3.12+ (tested with 3.14)
- **Node.js**: v20+ (for Tailwind CSS compiler)

### 2. Install Dependencies
```powershell
# Install Python packages
python -m pip install -r requirements.txt

# Install Playwright Chromium browser
python -m playwright install chromium

# Install frontend Tailwind tools
npm install
```

### 3. Build CSS Assets
```powershell
npm run build:css
```

### 4. Configure Environment
Copy `.env.example` to `.env`:
```powershell
cp .env.example .env
```
Default configuration is preset for instant local development with SQLite (`changewatch.db`), local artifact storage, and console email alerts.

---

## Running the Application

### Single-Process Development Server
In development mode, FastAPI runs the web server and background scheduler cooperatively:
```powershell
python -m uvicorn app.main:app --reload --port 8000
```
Open [http://localhost:8000](http://localhost:8000) in your browser.

### Multi-Process Production Deployment
In production, run the components as independent processes:

1. **Web Server**:
   ```powershell
   python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
   ```
2. **Scheduler Singleton**:
   ```powershell
   python workers/scheduler_process.py
   ```
3. **Queue Worker(s)**:
   ```powershell
   python workers/check_worker.py
   ```

---
## Vercel deployment (web runtime)

The FastAPI/Jinja web application can run as a Vercel Python function. Vercel is **not** the scheduler or browser worker host: functions can be archived, their writable filesystem is temporary, and the app must not start perpetual worker loops in a request runtime.

1. Import this repository at https://vercel.com/new.
2. Use the repository root as the project root; `pyproject.toml` points Vercel to `app.main:app` and builds the Tailwind CSS.
3. Configure these production environment variables in Vercel before using authenticated features:
   - `APP_ENV=production`
   - `APP_BASE_URL=https://your-deployment-domain`
   - `APP_SECRET_KEY` (unique random value, at least 32 characters)
   - `DATABASE_URL` (managed PostgreSQL using the `postgresql+psycopg://` dialect)
   - `ARTIFACT_STORAGE_BACKEND=s3`, `S3_BUCKET`, `S3_REGION`, and `S3_PREFIX`; configure `S3_ENDPOINT_URL` for S3-compatible providers and credentials/identity as required
   - `ENCRYPTION_KEY` (a freshly generated Fernet key)
   - production email provider settings if outbound mail alerts are required
4. Initialize a new database once from a trusted environment with `python -m scripts.init_db` after setting `DATABASE_URL`. This bootstrap creates missing tables but is not a migration system; use reviewed versioned migrations for subsequent schema changes.
5. Deploy a preview and verify login, DB connectivity, CSS and routes before promoting it to production.

The region-picker endpoint that directly invokes Chromium returns an explicit 503 on Vercel until a remote browser-worker endpoint is wired in. The normal monitor create/check-now actions enqueue jobs; a persistent worker must be running to process them.

## Docker Compose: PostgreSQL + web + scheduler + Chromium worker

For a local full-stack environment, copy `.env.example` to `.env` and then run:

```bash
docker compose up --build
```

The Compose stack starts PostgreSQL, an API web process, a separate scheduler, and a Playwright Chromium worker. PostgreSQL and local artifact files use named volumes. Visit http://localhost:8000. The web process does not run the inline scheduler or Chromium checks.

The `init-db` one-shot service runs automatically after Postgres is healthy and before the other services start. To rerun it against a deliberately blank local database, use:

```bash
docker compose run --rm init-db
```

This bootstrap creates tables that do not yet exist and is intended for initial setup, not schema evolution. It is not a versioned migration system; create and apply reviewed migrations for subsequent schema changes rather than treating `create_all` as a migration mechanism.

The Docker image uses the Playwright Python base image, so browser binaries and OS dependencies are supplied by the worker image. In a split deployment, run the scheduler/worker containers with the same `DATABASE_URL` and object-store settings as Vercel. Do not point them at the Docker Compose database unless that database is deliberately exposed through a secure private network.

## Required production limitations

- PostgreSQL and object storage are external production dependencies; they are intentionally not provisioned by Vercel project creation.
- Vercel production startup rejects development secrets, SQLite, localhost base URLs, or non-durable artifact storage.
- A permanent scheduler and browser worker must run in a persistent container environment. Do not run `workers/scheduler_process.py` or `workers/check_worker.py` as Vercel request functions.
- Region picker/browser preview requires the local/Docker runtime today; expose a restricted remote browser-worker endpoint before enabling that feature on Vercel.
- Playwright navigation must continue to use the existing public-URL/SSRF defenses. Do not expose the worker as an unrestricted URL-fetching public API.

---

## Running Tests

Run the full automated test suite with pytest:
```powershell
python -m pytest tests/ -v
```

Test coverage includes:
- `tests/test_url_safety.py`: SSRF defenses, private IP ranges, cloud metadata, invalid schemes.
- `tests/test_normalizer.py`: Volatile timestamp/counter noise suppression, sensitivity thresholds, SHA-256 stability.
- `tests/test_diff_engine.py`: Text diff generation and Pillow visual diff mask calculation.
- `tests/test_monitors_api.py`: User isolation, CSRF protection, and monitor state transitions.
- `tests/test_e2e_flow.py`: Full check lifecycle (baseline creation, unchanged check filtering, and change detection with alert dispatch).

---

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `development` | `development`, `test`, or `production` |
| `APP_SECRET_KEY` | *(32+ chars)* | Secret used for cookie signing and CSRF tokens |
| `DATABASE_URL` | `sqlite:///./changewatch.db` | Database connection string (SQLite or PostgreSQL) |
| `ARTIFACT_STORAGE_DIR` | `./data/artifacts` | Directory for storing screenshots and diff images |
| `BROWSER_NAV_TIMEOUT_SECONDS` | `30` | Playwright navigation timeout |
| `BROWSER_CHECK_TIMEOUT_SECONDS` | `60` | Maximum check duration |
| `EMAIL_PROVIDER` | `console` | `console`, `smtp`, or `resend` |
| `ENCRYPTION_KEY` | *(Fernet Key)* | 32 url-safe base64 characters for encrypting webhook URLs |

---
