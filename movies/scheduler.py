import threading
import time
import logging
# pyrefly: ignore [missing-import]
from django.db import close_old_connections

logger = logging.getLogger('movies')

def run_scheduler(interval_seconds=5):
    """
    Loop that periodically executes the expired seat reservation cleanup.
    Cleans up stale database connections before and after executing queries
    to avoid database connection leaks or stale thread connection errors.
    """
    from movies.views import cleanup_expired_bookings
    
    logger.info("Background seat reservation scheduler thread starting...")
    while True:
        try:
            close_old_connections()
            cleanup_expired_bookings()
        except Exception as e:
            logger.error(f"Error in background seat reservation scheduler: {str(e)}", exc_info=True)
        finally:
            close_old_connections()
        time.sleep(interval_seconds)

def start_background_scheduler():
    """
    Spawns the scheduler loop in a background daemon thread.
    """
    thread = threading.Thread(target=run_scheduler, daemon=True, name="SeatReservationScheduler")
    thread.start()
    logger.info("Seat reservation scheduler thread spawned successfully.")
