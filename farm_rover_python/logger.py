"""Simple shared logger writing to console + logs/rover.log."""
import logging
import os
import config

def get_logger():
    os.makedirs(config.LOG_DIR, exist_ok=True)
    log = logging.getLogger("rover")
    if log.handlers:
        return log  # already configured
    log.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    fh = logging.FileHandler(os.path.join(config.LOG_DIR, "rover.log"))
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    ch.setLevel(logging.INFO)

    log.addHandler(fh)
    log.addHandler(ch)
    return log
