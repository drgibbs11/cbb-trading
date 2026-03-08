import time
import logging

# Set up standard logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def log(event: str, data: dict = None):
    """Emit simple log message."""
    if data:
        logger.info(f"{event}: {data}")
    else:
        logger.info(event)


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
            logger.warning(f"RETRY_{label}: attempt {attempt + 1}, delay {delay}s, error: {e}")
            time.sleep(delay)
    logger.error(f"RETRY_EXHAUSTED_{label}: {last_err}")
    return None


def sleep_ms(ms: int):
    time.sleep(ms / 1000)
