import time
import json
from datetime import datetime, timezone


def log(event: str, data: dict = None):
    """Emit structured JSON log to stdout."""
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
    }
    if data:
        payload.update(data)
    print(json.dumps(payload), flush=True)


def retry(fn, delays: list[int], label: str = ""):
    """
    Call fn() with exponential backoff retries.
    Returns result on success. Returns None after all retries exhausted.
    Logs each failure.
    """
    last_err = None
    for attempt, delay in enumerate(delays):
        try:
            return fn()
        except Exception as e:
            last_err = e
            log(f"RETRY_{label}", {"attempt": attempt + 1, "delay": delay, "error": str(e)})
            time.sleep(delay)
    log(f"RETRY_EXHAUSTED_{label}", {"error": str(last_err)})
    return None


def sleep_ms(ms: int):
    time.sleep(ms / 1000)
