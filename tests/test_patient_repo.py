"""
Unit tests for patient repository pagination and exact count calculation (MED-01).
"""
import pytest
from unittest.mock import MagicMock
from backend.app.repositories.patient_repo import list_patients
from backend.app.models.patient import Patient


def test_list_patients_count_calculation_unbounded():
    """Verify list_patients executes direct scalar count without artificial bound_limit."""
    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_count_query = MagicMock()

    # db.query returns mock_query on first call (for patients) and mock_count_query on second call (for count)
    mock_db.query.side_effect = [mock_query, mock_count_query]

    # mock_count_query.scalar returns the exact count
    mock_count_query.filter.return_value = mock_count_query
    mock_count_query.scalar.return_value = 150000  # More than 10,001 rows

    # mock_query chaining
    mock_query.options.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.offset.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.all.return_value = []

    items, total = list_patients(mock_db, page=1, page_size=20)

    # Verify scalar count returned the exact count (150,000) rather than being bounded to 10,001
    assert total == 150000
    assert items == []
    # Verify scalar() was called directly on count query
    mock_count_query.scalar.assert_called_once()
