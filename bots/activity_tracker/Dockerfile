FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (cached layer)
COPY bots/activity_tracker/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Copy source — build context is the project root
COPY shared/ ./shared/
COPY bots/ ./bots/

ENV PYTHONPATH=/app

CMD ["python", "-m", "bots.activity_tracker.main"]
