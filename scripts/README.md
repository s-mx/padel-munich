# Initial Member Scan (one-time)

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
