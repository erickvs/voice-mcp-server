import logging
import sys
import os

def setup_logger(name="VoiceMCP", level=logging.INFO):
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(level)
        # Use a professional telemetry format
        formatter = logging.Formatter(
            fmt='%(asctime)s.%(msecs)03d | %(levelname)-7s | %(module)-15s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Output to stderr to avoid breaking stdio (MCP communication)
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
        # File logger for persistent telemetry
        log_dir = os.path.expanduser("~/Library/Application Support/VoiceMCP/logs")
        os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.FileHandler(os.path.join(log_dir, "telemetry.log"))
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
    return logger

logger = setup_logger()