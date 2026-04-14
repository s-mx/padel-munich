# Test suite

Automated tests for the padel-munich bot platform.  Runs without a Telegram
connection, a bot token, or any live group.

## Overview

| File | Type | What it tests |
|------|------|---------------|
| `test_shared_repository.py` | Integration (real Postgres) | All DB operations: upsert, bulk insert, stats, inactive list, top leaderboard |
| `test_activity_tracker_admin.py` | Unit (mocked session) | `/stats`, `/inactive`, `/top` — auth gate, argument parsing, reply formatting |
| `test_activity_tracker_activity.py` | Unit (mocked session) | Message and reaction handlers — human vs bot filtering, correct data forwarded |
| `test_activity_tracker_members.py` | Unit (mocked session) | Join event handler — valid join transitions, departure events, bot filtering |
| `conftest.py` | Fixtures | Shared DB session, mock session, message/reaction/event factories |

**56 tests total.**  Handler unit tests (34) run without Postgres in ~0.1 s.
Repository integration tests (22) need a running Postgres and take ~2 s.

## How it works

### Two testing layers

**Repository tests** hit a real PostgreSQL database (`padel_test`) because the
upsert logic uses `sqlalchemy.dialects.postgresql.insert`, which is
PostgreSQL-specific.  Each test gets a clean table — the fixture truncates
before and after every test.

**Handler tests** call handler functions directly, bypassing aiogram's router:

```python
await cmd_stats(msg, mock_session)
```

Repository functions are patched so the handler receives controlled data
without touching the database.  The only thing under test is the handler's
own logic: auth checks, argument parsing, and what text it sends back.

### Date-controlled setup

`upsert_member` always stamps `last_seen_at = now()`.  Tests that need to
simulate past activity (e.g. "member not seen in 35 days") insert `Member`
objects directly via `session.add()` with an explicit timestamp, bypassing
the upsert function entirely.

## Prerequisites

- Python 3.10+ (the codebase uses `str | None` union syntax)
- Docker (for the Postgres container)

## One-time setup

```bash
# 1. Start Postgres
docker compose up -d db

# 2. Create the test database (only needed once)
docker compose exec db psql -U padel -c "CREATE DATABASE padel_test;"

# 3. Create a virtualenv with Python 3.12
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 4. Install dependencies
pip install -r bots/activity_tracker/requirements.txt -r requirements-test.txt
```

`BOT_TOKEN` is required by pydantic-settings at import time.  Pass a dummy
value for tests — no real token is used:

```bash
export BOT_TOKEN=test
```

Or prefix every pytest command with `BOT_TOKEN=test` as shown below.

## Running tests

```bash
# All 56 tests
BOT_TOKEN=test pytest

# Verbose output (shows each test name)
BOT_TOKEN=test pytest -v

# Repository integration tests only (requires Postgres)
BOT_TOKEN=test pytest tests/test_repository.py -v

# Handler unit tests only (no Postgres needed)
BOT_TOKEN=test pytest tests/test_handlers_admin.py \
                       tests/test_handlers_activity.py \
                       tests/test_handlers_members.py -v

# Stop on first failure
BOT_TOKEN=test pytest -x

# Show local variables on failure (useful for debugging)
BOT_TOKEN=test pytest -l
```

## Configuration

`pytest.ini` (project root):

```ini
[pytest]
asyncio_mode = auto                      # all async test functions run automatically
asyncio_default_fixture_loop_scope = function   # each test gets its own event loop
pythonpath = .                           # mirrors PYTHONPATH=/app from Dockerfile
testpaths = tests
```

`asyncio_mode = auto` removes the need for `@pytest.mark.asyncio` on every
test.  `asyncio_default_fixture_loop_scope = function` combined with
`NullPool` (in the `db_session` fixture) prevents asyncpg's "operation in
progress" errors that occur when a pooled connection is reused across event
loops.
