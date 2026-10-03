# Heartbeat Monitor - Technical Architecture

## Overview
Heartbeat Monitor is a lightweight, self-hosted cron/backup job monitoring service. It provides a simpler, lighter alternative to Healthchecks.io (Django + PostgreSQL + Redis, 200-300MB RAM) by using Flask + SQLite in a single container (~20MB RAM). Designed for homelabbers and small teams who need to monitor scheduled jobs without heavy infrastructure.

## Technology Stack
- **Language**: Python 3.11
- **Framework**: Flask (synchronous)
- **Database**: SQLite (embedded, file-based)
- **Scheduler**: `schedule` library (in-process)
- **Container**: Docker (single container, ~50MB image, ~20MB RAM)
- **Deployment**: Docker Compose on port 5002

## Architecture Diagram
```
┌─────────────────────────────────────────────────────────────┐
│                     External Monitors                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  cron jobs  │  │  systemd    │  │  Custom scripts     │  │
│  │  (curl)     │  │  timers     │  │  (Python/Go/Shell)  │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
│         │                │                    │              │
│         └────────────────┼────────────────────┘              │
│                          │ HTTP POST /api/heartbeat/<token>  │
│                          ▼                                    │
┌─────────────────────────────────────────────────────────────┐
│                    Heartbeat Monitor (5002)                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │   Flask      │  │  Jinja2      │  │   SQLite DB      │  │
│  │  Application │──│  Templates   │  │  (heartbeat.db)  │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
│        │                                    │               │
│  ┌─────▼─────┐                        ┌─────▼─────┐         │
│  │ Background│                        │  Alert    │         │
│  │ Scheduler │                        │  Manager  │         │
│  │(checks    │                        │(Telegram, │         │
│  │ overdue)  │                        │ Discord,  │         │
│  └───────────┘                        │ Email)    │         │
│                                       └───────────┘         │
└─────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. Flask Application (`app.py`)
- Single-file application (~450 lines)
- Rate limiting on heartbeat endpoint (100 req/60s per IP)
- Token-based authentication (SHA-256 hashed tokens)
- Admin token for management API
- Background scheduler thread (checks overdue jobs every minute)

### 2. Database Schema (`init_db()`)
```sql
-- Jobs table
jobs: id, name, token_hash, interval_seconds, grace_period_seconds,
      description, alert_events, notification_config (Telegram, Discord, Email),
      created_at, updated_at

-- Heartbeats table
heartbeats: id, job_id, status (started/success/failed), exit_code,
            output, duration_ms, timestamp

-- Alert state table (prevents duplicate alerts)
alert_state: job_id, last_overdue_alert, last_failed_alert, last_recovery_alert
```

### 3. Job Monitoring Logic
- **Heartbeat received**: Job posts to `/api/heartbeat/<token>` with status
- **Overdue detection**: Background scheduler checks every minute:
  - `time_since_last_run > interval + grace_period` → overdue
  - `last_status == failed` → failed
- **Alert deduplication**: `alert_state` table tracks what's been alerted
- **Recovery alerts**: Automatically sent when job recovers from overdue/failed

### 4. Notification Channels
- **Telegram**: Bot API (`sendMessage` with HTML parse mode)
- **Discord**: Webhook (content field)
- **Email**: SMTP with TLS (configurable per-job or global defaults)

### 5. CLI Wrapper (`cli_wrapper.sh`)
```bash
# Usage from cron/systemd:
/usr/local/bin/hb-wrapper --token <token> --interval 3600 -- my-backup-script.sh

# Wrapper handles:
# - Start heartbeat (status=started)
# - Run command, capture exit code, output, duration
# - Success heartbeat (status=success) or failed (status=failed, exit_code)
```

## API Endpoints

### Public (Token Auth)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/heartbeat/<token>` | Receive heartbeat |
| GET | `/health` `/healthz` | Health checks |

### Admin API (Admin Token: `X-Admin-Token` header)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/jobs` | List all jobs with status |
| POST | `/api/jobs` | Create job (returns token) |
| GET | `/api/jobs/<id>` | Get job details |
| PUT | `/api/jobs/<id>` | Update job |
| DELETE | `/api/jobs/<id>` | Delete job |
| GET | `/api/jobs/<id>/history` | Heartbeat history (paginated) |
| GET | `/api/jobs/<id>/stats` | 7-day statistics |

### Web Dashboard
| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Main dashboard (all jobs status) |
| GET | `/job/<id>` | Job detail with history |
| GET | `/compare` | Comparison page (Healthchecks.io vs Uptime Kuma vs Lightweight) |
| GET | `/cli-wrapper` | Download CLI wrapper script |
| GET | `/sitemap.xml` | SEO sitemap |

## Security Considerations
- **Token hashing**: Tokens stored as SHA-256 hashes, never plaintext
- **Rate limiting**: In-memory sliding window per IP (100 req/60s)
- **Admin token**: Separate from job tokens, configurable via env
- **Input validation**: All inputs validated before DB operations
- **SQL injection**: Parameterized queries only
- **Output limiting**: Heartbeat output truncated to 10KB
- **No authentication on dashboard**: Designed for internal/VPN use; add reverse proxy auth for public exposure

## Deployment
```yaml
# docker-compose.yml
services:
  heartbeat-monitor:
    build: ./source
    ports: ["5002:5002"]
    volumes: ["./data:/data"]
    environment:
      - DATABASE=/data/heartbeat.db
      - SECRET_KEY=your-secret-key
      - ADMIN_TOKEN=your-admin-token
      # Optional global alert defaults:
      - TELEGRAM_BOT_TOKEN=
      - TELEGRAM_CHAT_ID=
      - DISCORD_WEBHOOK=
      - SMTP_HOST=
      - SMTP_PORT=587
      - SMTP_USER=
      - SMTP_PASSWORD=
      - SMTP_FROM=
      - SMTP_TO=
      - SMTP_TLS=true
```

## Data Persistence
- SQLite database at `/data/heartbeat.db` (Docker volume)
- Backup: `sqlite3 heartbeat.db .dump > backup.sql`
- Heartbeat history retained indefinitely (configurable retention could be added)

## Job Status States
| State | Condition |
|-------|-----------|
| `ok` | Last run within interval |
| `late` | Last run > interval but ≤ interval + grace |
| `overdue` | Last run > interval + grace |
| `failed` | Last heartbeat status = failed |
| `pending` | Job created, never received heartbeat |

## Key Differentiators
1. **Flask + SQLite** — Single container, ~20MB RAM vs Healthchecks.io ~200-300MB
2. **No external dependencies** — No Redis, PostgreSQL, Celery, message queue
3. **Per-job alert config** — Each job can have its own Telegram/Discord/Email settings
4. **CLI wrapper included** — Drop-in for cron/systemd with zero code changes
5. **Recovery alerts** — Automatic notification when job recovers
6. **MIT license** — No AGPL restrictions
7. **Admin API** — Full CRUD for automation/integration
8. **Sitemap + robots.txt** — SEO-ready for public deployment

## File Structure
```
source/
├── app.py               # Main Flask application
├── COMPARISON.md        # Comparison page content
├── Dockerfile
├── requirements.txt
├── robots.txt
└── templates/
    ├── base.html
    ├── dashboard.html
    ├── job_detail.html
    ├── compare.html
    └── cli_wrapper.sh
```

## Testing
```bash
# Manual API test
TOKEN="your-job-token"
curl -X POST http://localhost:5002/api/heartbeat/$TOKEN \
  -H "Content-Type: application/json" \
  -d '{"status": "success", "exit_code": 0, "duration_ms": 1500}'

# Admin API test
curl -H "X-Admin-Token: your-admin-token" http://localhost:5002/api/jobs

# Health check
curl http://localhost:5002/health
```

## Monitoring
- Health endpoints: `/health`, `/healthz` (both return `{"status": "healthy", "database": "connected"}`)
- Logs: `docker logs heartbeat-monitor`
- Metrics: Job status via `/api/jobs` admin endpoint

## Future Enhancements (Post-Validation)
- Web UI for job creation (currently API-only)
- Retention policy for old heartbeats
- Prometheus metrics endpoint
- Multi-user support with auth
- Job dependencies (job B runs after job A succeeds)
- Webhook callbacks for integration
- Dark mode for dashboard