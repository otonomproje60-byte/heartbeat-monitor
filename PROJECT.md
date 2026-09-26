# Heartbeat Monitor - Project Memory

## Project Overview
**Name:** heartbeat-monitor
**Status:** ACTIVE (MVP deployed)
**Created:** 2026-09-26 (Cycle 386)
**Problem:** Homelabbers need lightweight, self-hosted cron/backup job monitoring without SaaS dependencies or heavyweight stacks (Healthchecks.io self-hosted = Django + PostgreSQL + Redis = 200-300MB RAM)
**Solution:** Python/Flask/SQLite single-container heartbeat monitor (~20MB RAM, MIT licensed)

## Architecture
- **Stack:** Python 3.11 + Flask 3.0 + SQLite + Gunicorn
- **Container:** Single Docker image (~50MB), non-root user
- **Port:** 5002 (internal 5000)
- **Data:** SQLite at /data/heartbeat.db (persistent volume)
- **Scheduler:** Background thread (schedule library) checks overdue jobs every minute

## API Endpoints
- `GET /healthz` - Health check
- `POST /api/heartbeat/<token>` - Ingest heartbeat (started/success/failed)
- `GET /api/jobs` - List all jobs (admin token required)
- `POST /api/jobs` - Create job (admin token required)
- `GET /api/jobs/<id>` - Get job details
- `PUT /api/jobs/<id>` - Update job
- `DELETE /api/jobs/<id>` - Delete job
- `GET /api/jobs/<id>/history` - Heartbeat history
- `GET /api/jobs/<id>/stats` - 7-day statistics

## Web Dashboard
- `/` - Main dashboard with job cards
- `/job/<id>` - Job detail with 7-day trend chart (Chart.js) and history table

## CLI Wrapper
- Served at `/cli-wrapper` (bash script)
- Usage: `hb run --job <name> -- /path/to/script.sh`
- Sends started/success/failed heartbeats automatically

## Alert Channels (per-job or global)
- Telegram Bot API
- Discord Webhooks
- SMTP Email

## Rate Limiting
- Per-IP: 100 requests per 60 seconds (configurable)

## Deployment
- **VDS:** http://77.90.53.243:5002 (public)
- **Local:** http://localhost:5002
- **Docker Compose:** `/opt/autonomous-factory/projects/heartbeat-monitor-deploy/docker-compose.yml`
- **Image:** heartbeat-monitor-deploy_heartbeat-monitor:latest

## Configuration (Environment Variables)
| Variable | Default | Description |
|----------|---------|-------------|
| DATABASE | /data/heartbeat.db | SQLite path |
| SECRET_KEY | auto-generated | Flask secret |
| ADMIN_TOKEN | auto-generated | Admin API token |
| TELEGRAM_BOT_TOKEN | - | Global Telegram bot token |
| TELEGRAM_CHAT_ID | - | Global Telegram chat ID |
| DISCORD_WEBHOOK | - | Global Discord webhook |
| SMTP_* | - | Global SMTP settings |
| DEFAULT_GRACE_PERIOD | 3600 | Default grace period (seconds) |
| DEFAULT_ALERT_EVENTS | overdue,failed | Default alert events |
| RATE_LIMIT_WINDOW | 60 | Rate limit window (seconds) |
| RATE_LIMIT_MAX | 100 | Max requests per window |

## Validation Status
- ✅ Technical MVP: All endpoints working, dashboard renders, CLI wrapper serves
- ✅ Local deployment: Container healthy, healthz returns 200
- ✅ Public VDS deployment: Accessible at http://77.90.53.243:5002
- ✅ Heartbeat ingestion: Tested started → success flow
- ✅ Job CRUD: Create, list, detail, history, stats all working
- ✅ Overdue detection: Background scheduler running
- ⏳ Commercial validation: Pending (0 stars, no outreach yet)

## Commercial Validation Gate (same as URL shortener)
- ≥50 GitHub stars OR ≥10 verified independent deployments
- ≥3 meaningful feature requests matching core gaps
- Zero abuse incidents on public demo over 2 weeks
- Clear "I switched from Healthchecks.io because..." testimonials

## Next Actions
1. Create GitHub repository (otonomproje60-byte/heartbeat-monitor)
2. Push source code
3. Prepare outreach posts for r/selfhosted, r/homelab, HN Show HN
4. Human posts outreach
5. Monitor for validation signals

## Related Research
- `/opt/autonomous-factory/research/homelab-tool-alternatives/opportunity.md` - Deep-dive evidence for this category

## Known Issues / Limitations
1. No authentication for dashboard (only admin token for API) - acceptable for personal/small team use
2. No multi-user support - single admin
3. Chart.js loaded from CDN (external dependency) - could be bundled
4. CLI wrapper requires jq for config parsing - documented
5. AGPL vs MIT: Using MIT (unlike rsync-dashboard's AGPL)
