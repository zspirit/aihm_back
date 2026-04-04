"""Tests for copilot service — execute_tool routing and error handling."""
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.copilot import execute_tool


@pytest.mark.asyncio
class TestExecuteToolRouting:
    async def test_search_candidates_routes_correctly(self):
        db = AsyncMock()
        tid = uuid4()
        with patch("app.services.copilot.handle_search_candidates", new_callable=AsyncMock) as mock_handler:
            mock_handler.return_value = '{"candidates": []}'
            result = await execute_tool("search_candidates", {"search": "test"}, db, tid)
            mock_handler.assert_called_once_with(db, tid, {"search": "test"})
            assert result == '{"candidates": []}'

    async def test_list_positions_routes_correctly(self):
        db = AsyncMock()
        tid = uuid4()
        with patch("app.services.copilot.handle_list_positions", new_callable=AsyncMock) as mock_handler:
            mock_handler.return_value = '{"positions": []}'
            result = await execute_tool("list_positions", {}, db, tid)
            mock_handler.assert_called_once()

    async def test_get_position_details_routes(self):
        db = AsyncMock()
        tid = uuid4()
        with patch("app.services.copilot.handle_get_position_details", new_callable=AsyncMock) as mock_handler:
            mock_handler.return_value = '{"position": {}}'
            await execute_tool("get_position_details", {"position_id": "x"}, db, tid)
            mock_handler.assert_called_once()

    async def test_get_candidate_details_routes(self):
        db = AsyncMock()
        tid = uuid4()
        with patch("app.services.copilot.handle_get_candidate_details", new_callable=AsyncMock) as mock_handler:
            mock_handler.return_value = '{"candidate": {}}'
            await execute_tool("get_candidate_details", {"candidate_id": "x"}, db, tid)
            mock_handler.assert_called_once()

    async def test_get_analytics_overview_routes(self):
        db = AsyncMock()
        tid = uuid4()
        with patch("app.services.copilot.handle_get_analytics_overview", new_callable=AsyncMock) as mock_handler:
            mock_handler.return_value = '{"kpis": {}}'
            await execute_tool("get_analytics_overview", {}, db, tid)
            mock_handler.assert_called_once()

    async def test_aggregate_scores_routes(self):
        db = AsyncMock()
        tid = uuid4()
        with patch("app.services.copilot.handle_aggregate_scores", new_callable=AsyncMock) as mock_handler:
            mock_handler.return_value = '{"stats": {}}'
            await execute_tool("aggregate_scores", {"score_type": "cv_score"}, db, tid)
            mock_handler.assert_called_once()

    async def test_get_pipeline_breakdown_routes(self):
        db = AsyncMock()
        tid = uuid4()
        with patch("app.services.copilot.handle_get_pipeline_breakdown", new_callable=AsyncMock) as mock_handler:
            mock_handler.return_value = '{"breakdown": {}}'
            await execute_tool("get_pipeline_breakdown", {}, db, tid)
            mock_handler.assert_called_once()

    async def test_export_data_routes(self):
        db = AsyncMock()
        tid = uuid4()
        with patch("app.services.copilot.handle_export_data", new_callable=AsyncMock) as mock_handler:
            mock_handler.return_value = '{"url": "/export/file.xlsx"}'
            await execute_tool("export_data", {"data_type": "candidates"}, db, tid)
            mock_handler.assert_called_once()


@pytest.mark.asyncio
class TestExecuteToolEdgeCases:
    async def test_unknown_tool_returns_error(self):
        db = AsyncMock()
        tid = uuid4()
        result = await execute_tool("nonexistent_tool", {}, db, tid)
        parsed = json.loads(result)
        assert "error" in parsed
        assert "inconnu" in parsed["error"]

    async def test_handler_exception_returns_error(self):
        db = AsyncMock()
        tid = uuid4()
        with patch("app.services.copilot.handle_search_candidates", new_callable=AsyncMock) as mock_handler:
            mock_handler.side_effect = RuntimeError("DB connection failed")
            result = await execute_tool("search_candidates", {}, db, tid)
            parsed = json.loads(result)
            assert "error" in parsed
            assert "DB connection failed" in parsed["error"]

    async def test_empty_tool_input(self):
        db = AsyncMock()
        tid = uuid4()
        with patch("app.services.copilot.handle_get_analytics_overview", new_callable=AsyncMock) as mock_handler:
            mock_handler.return_value = '{"total": 0}'
            result = await execute_tool("get_analytics_overview", {}, db, tid)
            assert result == '{"total": 0}'
