# Contributing

## Linting

Ruff is the linter (version pinned in `requirements-test.txt`). It runs automatically in CI on every push.

```bash
# Check for errors
.venv/bin/ruff check .

# Auto-fix all fixable errors (e.g. unused imports)
.venv/bin/ruff check . --fix
```

Run this before committing to catch issues locally before CI does.

## Testing

See `tests/README.md` for full details. Quick reference:

```bash
# One-time setup (creates padel_test DB and venv)
docker compose up -d db
docker compose exec db psql -U padel -c "CREATE DATABASE padel_test;"
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r bots/activity_tracker/requirements.txt -r requirements-test.txt

# Run all 56 tests
BOT_TOKEN=test pytest

# Run only handler unit tests (no Postgres needed)
BOT_TOKEN=test pytest tests/test_activity_tracker_*.py -v
```

Test files follow the `test_<bot_name>_<module>.py` convention so tests for
different bots stay unambiguous in a flat layout. Shared DB logic lives in
`test_shared_repository.py`.
