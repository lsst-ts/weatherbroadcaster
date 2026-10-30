"""Safe diagnostics for InfluxDB HTTP responses."""

from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import ClientResponse
from structlog.testing import capture_logs
from yarl import URL

from weatherbroadcaster.weather import _check_influx_response


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (502, b"upstream error secret", "HTTP request failed"),
        (200, b"<html>login secret</html>", "invalid JSON"),
        (200, b"", "invalid JSON"),
        (200, b'{"results": []}', None),
    ],
)
async def test_influx_response_diagnostics(
    status: int, body: bytes, error: str | None
) -> None:
    """Expose response metadata while excluding credentials and body text."""
    response = Mock(spec=ClientResponse)
    response.status = status
    response.url = URL(
        "https://user:secret@example.com/query?token=secret#secret"
    )
    response.headers = {"Content-Type": "text/html"}
    response.read = AsyncMock(return_value=body)

    with capture_logs() as logs:
        if error:
            with pytest.raises(RuntimeError, match=error) as caught:
                await _check_influx_response(response)
            assert "secret" not in str(caught.value)
        else:
            await _check_influx_response(response)

    assert logs[0]["status"] == status
    assert logs[0]["endpoint"] == "https://example.com/query"
    assert logs[0]["content_type"] == "text/html"
    assert "secret" not in str(logs)
    if error:
        assert logs[-1]["log_level"] == "error"
