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
