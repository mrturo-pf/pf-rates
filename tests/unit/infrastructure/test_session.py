"""Tests for the database connection-budget configuration."""

from rates.infrastructure.db.session import engine


def test_engine_uses_approved_connection_pool_limits() -> None:
    """The engine must cap each instance at five database connections."""
    assert engine.pool.size() == 5
    assert engine.pool._max_overflow == 0


def test_engine_preserves_stale_connection_protection() -> None:
    """The engine must validate and recycle stale connections."""
    assert engine.pool._pre_ping is True
    assert engine.pool._recycle == 300
