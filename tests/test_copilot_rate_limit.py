"""
Unit tests for Copilot distributed and resilient rate limiting (MED-02).
"""
import pytest
from unittest.mock import MagicMock, patch
from backend.app.routers.copilot_router import check_copilot_rate_limit, user_chat_timestamps


@pytest.fixture(autouse=True)
def reset_in_memory_timestamps():
    user_chat_timestamps.clear()
    yield
    user_chat_timestamps.clear()


def test_copilot_rate_limit_with_redis():
    """Verify that when Redis is available, check_copilot_rate_limit uses Redis pipeline atomic increment."""
    mock_redis = MagicMock()
    mock_pipeline = MagicMock()
    mock_redis.pipeline.return_value = mock_pipeline

    with patch("backend.app.core.redis_client.get_redis", return_value=mock_redis):
        # 1st request -> returns count 1 (allowed for limit=2)
        mock_pipeline.execute.return_value = [1, True]
        assert check_copilot_rate_limit("user-123", limit=2, window_seconds=60) is True

        # 2nd request -> returns count 2 (allowed for limit=2)
        mock_pipeline.execute.return_value = [2, True]
        assert check_copilot_rate_limit("user-123", limit=2, window_seconds=60) is True

        # 3rd request -> returns count 3 (exceeds limit=2 -> rejected)
        mock_pipeline.execute.return_value = [3, True]
        assert check_copilot_rate_limit("user-123", limit=2, window_seconds=60) is False

    mock_pipeline.incr.assert_called_with("copilot:ratelimit:user-123")
    mock_pipeline.expire.assert_called_with("copilot:ratelimit:user-123", 60, nx=True)


def test_copilot_rate_limit_fallback_in_memory():
    """Verify that when Redis is unavailable, check_copilot_rate_limit falls back to local in-memory sliding window."""
    with patch("backend.app.core.redis_client.get_redis", return_value=None):
        # 1st request -> allowed
        assert check_copilot_rate_limit("user-456", limit=2, window_seconds=60) is True
        # 2nd request -> allowed
        assert check_copilot_rate_limit("user-456", limit=2, window_seconds=60) is True
        # 3rd request -> rejected
        assert check_copilot_rate_limit("user-456", limit=2, window_seconds=60) is False

        # Different user -> allowed
        assert check_copilot_rate_limit("user-789", limit=2, window_seconds=60) is True
