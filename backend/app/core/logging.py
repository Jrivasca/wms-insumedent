import logging
import re
import sys

# Patterns that must never appear in logs in clear text.
_SENSITIVE_KEYS = re.compile(
    r"(?i)(password|password_encrypted|email_password|access_token|token|secret|authorization)"
    r"\"?\s*[:=]\s*\"?([^\",}\s]+)"
)


class RedactingFilter(logging.Filter):
    """Redacts obvious secrets (passwords/tokens) from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _SENSITIVE_KEYS.sub(lambda m: f"{m.group(1)}=***", record.msg)
        return True


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    handler.addFilter(RedactingFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def sanitize_payload(payload):
    """Return a copy of a dict/list payload with sensitive values masked.

    Used before persisting external request/response payloads for auditing.
    """
    sensitive = {
        "password",
        "password_encrypted",
        "email_password",
        "email_password_encrypted",
        "access_token",
        "access_token_encrypted",
        "token",
        "authorization",
        "secret",
        "jwt_secret",
    }
    if isinstance(payload, dict):
        return {
            k: ("***" if k.lower() in sensitive else sanitize_payload(v))
            for k, v in payload.items()
        }
    if isinstance(payload, list):
        return [sanitize_payload(v) for v in payload]
    return payload
