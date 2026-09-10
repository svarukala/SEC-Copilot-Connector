"""CLI outcome and destination consistency regressions."""

from unittest.mock import AsyncMock, MagicMock

from click.testing import CliRunner
import pytest

from sec_connector.cli import main
from sec_connector.config import AppConfig


@pytest.fixture
def cli_pipeline(tmp_path, monkeypatch):
    config = AppConfig(
        azure={"tenant_id": "tenant", "client_id": "app", "client_secret": "test-only",
               "connection_id": "configured"},
        paths={"downloads": str(tmp_path / "downloads"), "payloads": str(tmp_path / "payloads"),
               "database": str(tmp_path / "state.db"), "logs": str(tmp_path / "logs")},
    )
    pipeline = MagicMock()
    pipeline.setup = AsyncMock()
    pipeline.ingest = AsyncMock(return_value={"errors": 1})
    pipeline.resume = AsyncMock(return_value={"filings_resumed": 1, "chunks_uploaded": 0, "errors": 1})
    factory = MagicMock(return_value=pipeline)
    monkeypatch.setattr("sec_connector.cli.load_config", lambda _: config)
    monkeypatch.setattr("sec_connector.cli.IngestionPipeline", factory)
    return config, pipeline, factory


@pytest.mark.parametrize("args", [["ingest", "-t", "AAPL"], ["resume"]])
def test_partial_failures_exit_nonzero(cli_pipeline, args):
    result = CliRunner().invoke(main, args)
    assert result.exit_code == 1
    assert "Errors" in result.output


def test_setup_reuses_configured_destination_without_prompt(cli_pipeline):
    config, pipeline, factory = cli_pipeline
    result = CliRunner().invoke(main, ["setup"])
    assert result.exit_code == 0, result.output
    pipeline.setup.assert_awaited_once()
    assert config.azure.connection_id == "configured"
    assert "Enter a name" not in result.output


@pytest.mark.parametrize("args", [
    ["ingest", "-t", ","], ["ingest", "-t", "AAPL", "--max-pages", "0"],
    ["ingest", "-t", "AAPL", "--max-filings", "-1"],
])
def test_invalid_ingest_input_does_not_run_pipeline(cli_pipeline, args):
    _, pipeline, _ = cli_pipeline
    assert CliRunner().invoke(main, args).exit_code != 0
    pipeline.ingest.assert_not_awaited()


def test_missing_secret_is_reported_before_pipeline(cli_pipeline):
    config, pipeline, _ = cli_pipeline
    config.azure.client_secret = ""
    result = CliRunner().invoke(main, ["setup"])
    assert result.exit_code == 1
    assert "AZURE_CLIENT_SECRET" in result.output
    pipeline.setup.assert_not_awaited()
