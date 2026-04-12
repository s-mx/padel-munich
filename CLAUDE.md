# Padel Munich — Bot Platform

A multi-bot Python monorepo for a 200+ member Padel Munich Telegram community.

## Repository Layout

```
padel-munich/
├── bots/
│   └── activity_tracker/        ← tracks last-seen date per member
│       ├── handlers/
│       │   ├── activity.py      ← catch-all: every message + reaction → upsert
│       │   ├── admin.py         ← /stats  /inactive [days]  /top [n]
│       │   └── members.py       ← new-member join events → upsert
│       ├── middlewares/
│       │   └── db.py            ← injects AsyncSession into every handler
│       ├── config.py            ← pydantic-settings; reads BOT_TOKEN, DB_URL, ADMIN_IDS from .env
│       ├── main.py              ← entry: init_db → create_tables → start_polling
│       ├── Dockerfile           ← build context = project root
│       └── requirements.txt
├── shared/
│   └── db/
│       ├── models.py            ← Member SQLAlchemy model
│       ├── session.py           ← init_db(), get_session_factory(), create_tables()
│       └── repository.py       ← upsert_member(), bulk_upsert_members(), get_stats(), get_inactive(), get_top()
├── scripts/
│   ├── seed_members.py          ← one-time initial scan via Pyrogram user client
│   └── requirements.txt        ← pyrogram + tgcrypto + sqlalchemy + asyncpg
├── docker-compose.yml           ← postgres:16-alpine + activity_tracker service
├── .env.example
└── .gitignore
```

**Adding a new bot:** create `bots/<bot_name>/` mirroring `activity_tracker/`. Add a new service in `docker-compose.yml` with `build.context: .` and its own `BOT_TOKEN`. It shares the same Postgres instance via `shared/db/`.

## Tech Stack

| Layer | Choice |
|---|---|
| Bot framework | aiogram v3 (async) |
| ORM | SQLAlchemy 2.0 async |
| DB driver | asyncpg (PostgreSQL) |
| Config | pydantic-settings v2 (.env) |
| DB | PostgreSQL 16 |
| Runtime | Python 3.12, Docker + Compose |

## Key Design Decisions

- **Build context = project root** so each bot's Dockerfile can `COPY shared/` into the image.
- **`PYTHONPATH=/app`** set in Dockerfile — enables `import shared` and `import bots.*` without package installs.
- **Admin router registered before activity router** so `/stats` etc. are matched before the catch-all `@router.message()`.
- **PostgreSQL-dialect upsert** (`sqlalchemy.dialects.postgresql.insert` + `on_conflict_do_update`) — works in both local Docker and Railway prod.
- **`bulk_upsert_members` uses `on_conflict_do_nothing`** — the seed script inserts missing members but never overwrites existing records (preserves message counts).
- **`chat_member` updates require the bot to be admin** — Telegram only delivers membership change events to admin bots.
- **Initial scan uses a Pyrogram user client** — the Bot API has no "list all members" endpoint; a user account is required for the one-time seed. The session file (`seed_session.session`) is gitignored.
- **No Alembic yet** — tables created with `Base.metadata.create_all` on startup. Add Alembic when schema migrations are needed.

## Database Schema

```sql
CREATE TABLE members (
    id              SERIAL PRIMARY KEY,
    tg_user_id      BIGINT UNIQUE NOT NULL,
    username        TEXT,
    first_name      TEXT,
    last_seen_at    TIMESTAMP WITH TIME ZONE NOT NULL,
    total_messages  INTEGER DEFAULT 0,
    joined_at       TIMESTAMP WITH TIME ZONE DEFAULT now()
);
```

## Environment Variables

```
BOT_TOKEN=         # from @BotFather
ADMIN_IDS=         # comma-separated Telegram user IDs (get yours from @userinfobot)
DB_URL=            # overridden per-service in docker-compose for local dev
LOG_LEVEL=         # DEBUG (local) | INFO (default) | WARNING (prod, quieter)

# seed script only
API_ID=            # from https://my.telegram.org
API_HASH=          # from https://my.telegram.org
CHAT_ID=           # group @username or numeric ID
```

Copy `.env.example` to `.env` and fill in values. Never commit `.env` or `*.session`.

## Local Dev

```bash
cp .env.example .env        # fill BOT_TOKEN and ADMIN_IDS
docker compose up           # starts postgres + bot; tables auto-created on first run
```

The bot must be added to the Telegram group as **admin** to receive all message updates,
including `chat_member` events (new member joins).

Inspect the DB directly:
```bash
docker compose exec db psql -U padel -c "SELECT * FROM members ORDER BY last_seen_at DESC;"
```

## Initial Member Scan (one-time)

Run this **once** after adding the bot to the group to seed all existing members:

```bash
# 1. Get API_ID + API_HASH from https://my.telegram.org (takes 2 min)
# 2. Fill API_ID, API_HASH, CHAT_ID in .env
# 3. Make sure DB is running:
docker compose up -d db

# 4. Install script deps (separate venv recommended):
pip install -r scripts/requirements.txt

# 5. Run the scan (will prompt for phone + OTP on first run):
python -m scripts.seed_members
```

Existing members are inserted with the current timestamp as `last_seen_at`.
If a member is already in the DB their record is left untouched.
The Pyrogram session file (`seed_session.session`) is gitignored — keep it safe.

## Production Hosting (Railway)

1. Push repo to GitHub
2. Railway → New Project → Deploy from GitHub repo
3. Add PostgreSQL plugin (auto-injects the DB connection string)
4. Set `BOT_TOKEN` and `ADMIN_IDS` env vars in Railway dashboard
5. Set `DB_URL` to the Railway Postgres URL

Each new bot = new Railway service in the same project, pointing at the same Postgres plugin.

## Admin Commands

| Command | Description |
|---|---|
| `/stats` | Total tracked members, active today, active this week |
| `/inactive [days]` | Members not seen in last N days (default 30) |
| `/top [n]` | Most active members by message count (default 10, max 25) |

Commands are silently ignored for non-admin users.

## Planned / Future

- Alembic migrations
- FastAPI read-only admin REST API
- Inactive member DM nudge
- Weekly activity digest posted to the group
- Match scheduler bot
- Poll/voting bot
