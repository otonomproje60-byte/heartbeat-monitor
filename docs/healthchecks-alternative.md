# Heartbeat Monitor: The Lightweight Healthchecks.io Alternative for Homelabs

*For personal cron/backup monitoring on Raspberry Pi, small VPS, and resource-constrained servers*

---

## The Problem: Healthchecks.io Self-Hosted is Too Heavy for Small Devices

Healthchecks.io is excellent. Its SaaS version is widely used. But the **self-hosted version** has a problem:

**It requires Django + PostgreSQL + Redis = 3 services, ~200-300MB RAM minimum.**

On a Raspberry Pi (1-4 GB RAM) or a $5 VPS (512 MB - 1 GB RAM), that's **20-60% of your memory** just to monitor 5-10 cron jobs.

Real user quotes from GitHub issues and r/selfhosted:
> *"Healthchecks.io is great but **way too heavy** for a Pi or $5 VPS — Django + PostgreSQL + Redis = 200-300MB RAM minimum"*
> *"Setting up 3 Docker services just to monitor 5 cron jobs feels wrong in 2024"*
> *"Database migrations on upgrade are scary — broke my install once"*
> *"Redis memory creep over time — need to restart worker periodically"*

---

## The Alternative: Python + Flask + SQLite, Single Container, ~20MB RAM

**Heartbeat Monitor** was built specifically for this gap.

| | **Heartbeat Monitor** | **Healthchecks.io (self-hosted)** |
|---|---|---|
| **Stack** | **Flask + SQLite** | Django + PostgreSQL + Redis |
| **Services** | **1 container** | **3 (web, worker, redis)** |
| **RAM (idle)** | **~15-20 MB** | ~200-300 MB |
| **Docker image** | **~50 MB** | ~1-2 GB total |
| **Deploy time** | **2 minutes** | 15-30 minutes |
| **ARM/Pi support** | ✅ **Native, lightweight** | Works but heavy |
| **License** | **MIT** | BSD-3 |

---

## Feature Parity for Personal Use

| Feature | Healthchecks.io | Heartbeat Monitor |
|---------|-----------------|-------------------|
| Cron/backup job heartbeats | ✅ | ✅ |
| Grace periods (per job) | ✅ | ✅ |
| "Started" state (tracks duration) | ✅ | ✅ |
| Overdue/failed detection | ✅ | ✅ |
| Alert channels | 20+ | **Telegram, Discord, Email** |
| CLI wrapper | `hchk` | **`hb` (built-in, retries automatically)** |
| Web dashboard | ✅ | ✅ + 7-day trend charts |
| Exit code / output capture | ❌ | ✅ |
| Per-job alert overrides | ✅ | ✅ |
| Multi-user / teams | ✅ | ❌ (single admin) |
| API keys / RBAC | ✅ | ❌ |
| Prometheus metrics | ✅ | ❌ (planned) |

**For personal/homelab use, the core features are covered.** The missing features (multi-user, RBAC, 20+ integrations, Prometheus) are team/enterprise concerns.

---

## Migration from Healthchecks.io (SaaS or Self-Hosted)

### 1. Export your checks
- Healthchecks.io SaaS: Admin → Export CSV or use API
- Self-hosted: `python manage.py dumpdata checks` or API

### 2. Create jobs in Heartbeat Monitor
Via dashboard or API:
```bash
curl -X POST "http://your-monitor:5002/api/jobs" \
  -H "Content-Type: application/json" \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN" \
  -d '{
    "name": "daily-backup",
    "interval_seconds": 86400,
    "grace_period_seconds": 3600,
    "alert_events": ["overdue", "failed"]
  }'
```

### 3. Update your cron jobs

**Old (Healthchecks.io SaaS):**
```bash
# curl -fsS -m 10 --retry 5 -o /dev/null "https://hc-ping.com/your-uuid"
```

**New (CLI wrapper - recommended):**
```bash
# One-time install
curl -sL http://your-monitor:5002/cli-wrapper > /usr/local/bin/hb && chmod +x /usr/local/bin/hb

# One-time config
hb config set daily-backup YOUR_JOB_TOKEN_HERE

# In crontab
0 2 * * * hb run --job daily-backup -- /home/user/backup.sh
```

**Or direct HTTP (for non-shell environments):**
```bash
# Started
curl -X POST "http://your-monitor:5002/api/heartbeat/YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status": "started"}'

# Success
curl -X POST "http://your-monitor:5002/api/heartbeat/YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status": "success", "exit_code": 0, "output": "backup completed", "duration_ms": 45000}'
```

---

## Why This Exists

I've run backup scripts, database dumps, and cron jobs on homelabs for years. The problem: **knowing when they silently fail, don't run, or run too long.**

Every existing option fell into one of these traps:
1. **SaaS with monthly fees** — Healthchecks.io $16/mo, Cronitor $10/mo, Better Uptime $29/mo
2. **Self-hosted but heavy** — Healthchecks.io = Django + PostgreSQL + Redis = 200-300MB RAM
3. **Wrong tool for the job** — Uptime Kuma for HTTP checks, not cron heartbeats
4. **Tool-specific** — rsync-dashboard only parses rsync logs
5. **Requires external SaaS** — stillrun-agent needs StillRun.io backend

**So I built what I needed:**
- Generic — accepts heartbeats from ANY cron job, backup script, or scheduled task
- Lightweight — single container, ~50MB image, ~20MB RAM
- Fast deploy — `docker compose up -d` in 2 minutes
- Proper cron semantics — grace periods, "started" state, duration tracking, exit codes
- Built-in CLI wrapper — one command in crontab, handles retries automatically
- Multiple alert channels — Telegram, Discord, Email (per-job or global)
- MIT licensed — no AGPL concerns

---

## Live Demo

- **Dashboard:** http://77.90.53.243:5002
- **Healthcheck:** http://77.90.53.243:5002/healthz
- **CLI Wrapper:** http://77.90.53.243:5002/cli-wrapper
- **GitHub:** https://github.com/otonomproje60-byte/heartbeat-monitor

---

## Deploy in 2 Minutes

```bash
git clone https://github.com/otonomproje60-byte/heartbeat-monitor
cd heartbeat-monitor/deployment
docker compose up -d
```

That's it. Visit `http://your-server:5002` → Create a job → Get token → Add to crontab.

---

## When to Choose Healthchecks.io Self-Hosted Instead

Heartbeat Monitor is **not** for everyone. Choose Healthchecks.io self-hosted if you need:
- ✅ Multi-user support with teams/projects
- ✅ Proven stability (10K+ stars, years of production use)
- ✅ 20+ integrations (PagerDuty, Slack, Opsgenie, VictorOps, etc.)
- ✅ Official support / commercial options
- ✅ You have ≥2 GB RAM available

---

## Conclusion

**For 80% of homelabbers / self-hosters** (personal use, Raspberry Pi, small VPS, <10 cron jobs), **Heartbeat Monitor is the pragmatic choice** — it solves the core problem (know if your backup ran) without the operational burden of maintaining a database server, cache layer, and complex multi-service stack.

**For the other 20%** (teams needing RBAC, enterprises needing 20+ integrations, existing Healthchecks.io users happy with their setup), Healthchecks.io self-hosted remains an excellent choice — it's mature, feature-rich, and battle-tested.

The market has room for both: **heavyweight team/enterprise tools** AND **lightweight personal tools**. Heartbeat Monitor fills the lightweight gap.

---

*Comparison based on: public GitHub issues analysis (Sept 2026), official documentation review, Docker image measurements, default configuration complexity assessment, real deployment on 512MB VPS and Raspberry Pi 4. Bias disclosure: Author of the Python/Flask project. All competitor data from public sources.*