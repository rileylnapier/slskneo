"""Redact configured credentials even inside dependency exception messages."""

import json
import logging


class CredentialFormatter(logging.Formatter):
    def __init__(self, password: str):
        super().__init__("%(levelname)s %(name)s: %(message)s")
        self._secrets = sorted(
            {password, repr(password)[1:-1], json.dumps(password)[1:-1]} - {""},
            key=len, reverse=True,
        )

    def format(self, record: logging.LogRecord) -> str:
        output = super().format(record)
        for secret in self._secrets:
            output = output.replace(secret, "[REDACTED]")
        return output


def configure_logging(password: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(CredentialFormatter(password))
    logging.basicConfig(level=logging.WARNING, handlers=[handler], force=True)
    # This upstream logger includes complete protocol objects in some warnings.
    logging.getLogger("aioslsk.network.connection").disabled = True

