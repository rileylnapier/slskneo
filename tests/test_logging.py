import logging
import sys

from aioslsk.protocol.messages import Login
from soulseek_mcp.logging_utils import CredentialFormatter


def test_protocol_password_redacted_in_repr_and_exception_trace():
    secret = 'private\\password\n"quoted"'
    request = Login.Request(username="test", password=secret, client_version=157, md5hash="hash", minor_version=100)
    formatter = CredentialFormatter(secret)
    record = logging.LogRecord("aioslsk", logging.WARNING, __file__, 1, "message %r", (request,), None)
    output = formatter.format(record)
    assert secret not in output
    assert repr(secret)[1:-1] not in output
    assert "[REDACTED]" in output
    try:
        raise RuntimeError(secret)
    except RuntimeError:
        record = logging.LogRecord("aioslsk", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())
        output = formatter.format(record)
    assert secret not in output
    assert "[REDACTED]" in output
