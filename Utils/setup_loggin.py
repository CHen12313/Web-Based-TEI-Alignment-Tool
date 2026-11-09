import logging, sys

def setup_logging(level=logging.INFO):
    root = logging.getLogger()
    root.setLevel(level)  # always set level even if a handler was added first
    if root.handlers:  # idempotent — gunicorn workers re-import
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    ))
    root.addHandler(handler)
    root.setLevel(level)