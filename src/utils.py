"""
Common utilities for AShare data processing
"""
import logging
import time
from functools import wraps
from typing import Any, Callable


def setup_logging(level: str = "INFO", log_file: str = None, log_format: str = None):
    """Setup logging configuration"""
    if log_format is None:
        log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    handlers = [logging.StreamHandler()]
    if log_file:
        # Add timestamp to log file name
        from datetime import datetime
        from pathlib import Path
        
        log_path = Path(log_file)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file_with_timestamp = log_path.parent / f"{log_path.stem}_{timestamp}{log_path.suffix}"
        
        # Create log directory if it doesn't exist
        log_file_with_timestamp.parent.mkdir(parents=True, exist_ok=True)
        
        handlers.append(logging.FileHandler(log_file_with_timestamp, encoding='utf-8'))
        print(f"Log file: {log_file_with_timestamp}")
    
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format=log_format,
        handlers=handlers
    )


def retry_on_exception(max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """
    Retry decorator with exponential backoff
    
    Args:
        max_retries: Maximum number of retry attempts
        delay: Initial delay between retries in seconds
        backoff: Multiplier for delay after each retry
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries:
                        logging.warning(
                            f"Attempt {attempt + 1}/{max_retries} failed for {func.__name__}: {str(e)}. "
                            f"Retrying in {current_delay}s..."
                        )
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logging.error(
                            f"All {max_retries} retry attempts failed for {func.__name__}"
                        )
            
            raise last_exception
        
        return wrapper
    return decorator


class RateLimiter:
    """Simple rate limiter using token bucket algorithm"""
    
    def __init__(self, rate: float):
        """
        Args:
            rate: Maximum number of calls per second (0 = no limit)
        """
        self.rate = rate
        self.last_call = 0.0
        
    def wait(self):
        """Wait if necessary to respect rate limit"""
        if self.rate <= 0:
            return
        
        now = time.time()
        time_since_last = now - self.last_call
        min_interval = 1.0 / self.rate
        
        if time_since_last < min_interval:
            sleep_time = min_interval - time_since_last
            time.sleep(sleep_time)
        
        self.last_call = time.time()
