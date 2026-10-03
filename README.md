# Heartbeat Monitor

Lightweight self-hosted cron/backup job heartbeat monitor. Python + Flask + SQLite, single container, ~2 minute deploy, ~20MB RAM.

**Live Demo:** http://77.90.53.243:5002 | **CLI Wrapper:** http://77.90.53.243:5002/cli-wrapper

---

## The Problem

You run backup scripts, database dumps, cron jobs, and scheduled tasks on your homelab or VPS. How do you know when they silently fail, don't run, or run too long?

**Existing options fall into these traps:**
- **SaaS with monthly fees** — Healthchecks.io $16/mo, Cronitor $10/mo, Better Uptime $29/mo
- **Self-hosted but heavy** — Healthchecks.io self-hosted = Django + PostgreSQL + Redis = 200-300MB RAM, 3 services
- **Wrong tool for the job** — Uptime Kuma for HTTP checks, not cron heartbeats (no grace periods, no "started" state)
- **Tool-specific** — rsync-dashboard only parses rsync logs, AGPL license
- **Requires external SaaS** — stillrun-agent needs StillRun.io backend

---

## The Solution

A generic, tool-agnostic heartbeat monitor that's actually lightweight.

| | This Project | Healthchecks.io (self-hosted) | Uptime Kuma |
|---|---|---|---|
| **Primary purpose** | **Cron/backup job heartbeats** | Cron/backup job heartbeats | HTTP/TCP/Ping uptime |
| **Stack** | **Python + Flask + SQLite** | Django + PostgreSQL + Redis | Node.js + SQLite |
| **RAM (idle)** | **~15-20 MB** | ~200-300 MB | ~50-80 MB |
| **Docker image** | **~50 MB** | ~1-2 GB (3 services) | ~100 MB |
| **Services** | **1 container** | **3 (web, worker, redis)** | 1 container |
| **Deploy time** | **2 minutes** | 15-30 min | 2 minutes |
| **ARM/Pi** | ✅ Native, lightweight | Works but heavy | ✅ Native |
| **License** | **MIT** | BSD-3 | MIT |

---

## Features

- **Generic** — accepts heartbeats from ANY cron job, backup script, or scheduled task
- **Web dashboard** — job cards with status (OK/Late/Overdue/Failed), last run, 7-day trend charts (Chart.js)
- **Overdue detection** — configurable grace periods per job, background scheduler checks every minute
- **Alert channels** — Telegram Bot, Discord webhooks, SMTP email (per-job or global defaults via env)
- **CLI wrapper (`hb`)** — one command in crontab: `hb run --job daily-backup -- /backup.sh`
  - Sends "started" heartbeat before command runs
  - Captures exit code, stdout/stderr, duration
  - Sends "success" or "failed" heartbeat after completion
  - Automatic retries with exponential backoff
- **Recovery alerts** — notifies when overdue/failed jobs start working again
- **Rate limiting** — 100 req/min per IP on ingest endpoint
- **Single container** — `docker compose up -d` and done
- **MIT licensed** — no AGPL concerns

---

## Quick Start (2 Minutes)

```bash
git clone https://github.com/otonomproje60-byte/heartbeat-monitor
cd heartbeat-monitor/deployment
docker compose up -d
```

Visit `http://your-server:5002` → Create a job → Get token → Add to crontab.

---

## CLI Wrapper (`hb`)

The built-in CLI wrapper handles the full heartbeat lifecycle:

```bash
# Install (one-time)
curl -sL http://your-server:5002/cli-wrapper > /usr/local/bin/hb && chmod +x /usr/local/bin/hb

# Configure job token (one-time)
hb config set daily-backup YOUR_JOB_TOKEN_HERE

# Use in crontab
0 2 * * * hb run --job daily-backup -- /home/user/backup.sh
```

**What it does automatically:**
1. Sends `"started"` heartbeat **before** your command runs
2. Executes your command, captures **exit code, stdout/stderr, duration**
3. Sends `"success"` or `"failed"` heartbeat **after** completion
4. **Retries with exponential backoff** (1s, 2s, 4s, 8s, 16s, max 30s) if monitor unreachable
5. **Limits output** to last 100KB
6. **Respects `HB_NO_LOG=true`** for sensitive commands

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/healthz` | Health check |
| `POST` | `/api/heartbeat/<token>` | Ingest heartbeat (started/success/failed) |
| `GET` | `/api/jobs` | List all jobs (admin token) |
| `POST` | `/api/jobs` | Create job (admin token) |
| `GET` | `/api/jobs/<id>` | Get job details |
| `PUT` | `/api/jobs/<id>` | Update job |
| `DELETE` | `/api/jobs/<id>` | Delete job |
| `GET` | `/api/jobs/<id>/history` | Heartbeat history |
| `GET` | `/api/jobs/<id>/stats` | 7-day statistics |

**Heartbeat payload:**
```json
{
  "status": "started" | "success" | "failed",
  "exit_code": 0,
  "output": "backup completed successfully",
  "duration_ms": 45000
}
```

---

## Alert Configuration

### Global (via environment variables)
```yaml
environment:
  - TELEGRAM_BOT_TOKEN=your_bot_token
  - TELEGRAM_CHAT_ID=your_chat_id
  - DISCORD_WEBHOOK=https://discord.com/api/webhooks/...
  - SMTP_HOST=smtp.gmail.com
  - SMTP_PORT=587
  - SMTP_USER=your@email.com
  - SMTP_PASSWORD=app_password
  - SMTP_FROM=Heartbeat Monitor <your@email.com>
  - SMTP_TO=alerts@yourdomain.com
  - DEFAULT_GRACE_PERIOD=3600
  - DEFAULT_ALERT_EVENTS=overdue,failed
```

### Per-Job (via API or Dashboard)
Each job can override globals with its own alert channels.

---

## Reverse Proxy (Custom Domain)

**Caddy (auto HTTPS) — recommended:**
```caddyfile
monitor.yourdomain.com {
    reverse_proxy heartbeat-monitor:5000
    header {
        X-Content-Type-Options "nosniff"
        X-Frame-Options "SAMEORIGIN"
    }
}
```

**Nginx:**
```nginx
server {
    listen 443 ssl;
    server_name monitor.yourdomain.com;
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    location / {
        proxy_pass http://heartbeat-monitor:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE` | `/data/heartbeat.db` | SQLite path |
| `SECRET_KEY` | auto-generated | Flask secret |
| `ADMIN_TOKEN` | auto-generated | Admin API token |
| `TELEGRAM_BOT_TOKEN` | — | Global Telegram bot token |
| `TELEGRAM_CHAT_ID` | — | Global Telegram chat ID |
| `DISCORD_WEBHOOK` | — | Global Discord webhook |
| `SMTP_*` | — | Global SMTP settings |
| `DEFAULT_GRACE_PERIOD` | `3600` | Default grace period (seconds) |
| `DEFAULT_ALERT_EVENTS` | `overdue,failed` | Default alert events |
| `RATE_LIMIT_WINDOW` | `60` | Rate limit window (seconds) |
| `RATE_LIMIT_MAX` | `100` | Max requests per window |

---

## Architecture

```
┌─────────────────────────────────────────────┐
│           Docker Container                  │
├─────────────────────────────────────────────┤
│  Gunicorn (4 workers)                       │
│  ├── Flask App (REST API + Dashboard)       │
│  └── Background Scheduler Thread            │
│       └── checks overdue jobs every minute  │
├─────────────────────────────────────────────┤
│  SQLite Database (/data/heartbeat.db)       │
└─────────────────────────────────────────────┘
```

- **Single process** — Gunicorn workers + scheduler thread in same container
- **No external dependencies** — no Redis, no PostgreSQL, no message queue
- **Persistent data** — SQLite file on Docker volume (`deployment_data`)
- **Easy backup** — `cp /data/heartbeat.db backup.db`

---

## MVP Limitations (Honest Disclosure)

- **Single-user** — admin token for management, job tokens for ingestion
- **No multi-user, no API keys, no RBAC** — not for shared teams
- **No Prometheus metrics endpoint** — planned
- **No webhook retry with backoff** — alerts fire once, planned
- **Chart.js from CDN** — external dependency, could be bundled
- **CLI wrapper requires `jq`** — standard on most systems

---

## Comparison with Alternatives

See [COMPARISON.md](source/COMPARISON.md) for detailed analysis including:
- Real user pain points from GitHub issues, Reddit, self-hosted communities
- Resource usage deep dive (this project vs Healthchecks.io vs Uptime Kuma vs Checkmk vs rsync-dashboard)
- Migration paths from Healthchecks.io, Uptime Kuma, Pushgateway
- When to choose each tool

---

## Why Flask + SQLite?

Most lightweight self-hosted tools are Go (Gitea, Miniflux, Uptime Kuma, Homepage). Python advantages:
- Easier customization for non-Go developers
- Huge standard library
- Proven stack on this VDS (forms-builder, URL shortener, notes-static-publish all use this pattern successfully)

---

## Contributing

Issues and PRs welcome. This is a personal/homelab tool — scope is intentionally narrow.

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## Related Projects

- **forms-builder** — Lightweight Python form endpoint/builder (OhMyForm alternative): https://github.com/otonomproje60-byte/forms-builder
- **NanoAnalytics** — Lightweight analytics (contributing upstream): https://github.com/callmefredcom/NanoAnalytics