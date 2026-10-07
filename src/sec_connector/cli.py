"""Click-based CLI for SEC Connector."""

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from .config import load_config, ensure_directories
from .pipeline import IngestionPipeline
from .utils import setup_logging
from .state_manager import check_state_access, scoped_database_path

console = Console()


def run_async(coro):
    """Run an async coroutine."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(coro)


def sanitize_connection_id(name: str) -> str:
    """Sanitize connection ID to meet Graph API requirements.

    Graph Connector IDs must be alphanumeric only (no hyphens, spaces, or special chars).

    Args:
        name: User-provided connection name

    Returns:
        Sanitized alphanumeric connection ID
    """
    # Remove all non-alphanumeric characters
    sanitized = re.sub(r'[^a-zA-Z0-9]', '', name)

    # Ensure it's not empty
    if not sanitized:
        sanitized = "secfilings"

    # Ensure it starts with a letter (Graph API requirement)
    if sanitized[0].isdigit():
        sanitized = "conn" + sanitized

    # Lowercase for consistency
    return sanitized.lower()


def require_graph_credentials(config) -> None:
    if not all((config.azure.client_id, config.azure.tenant_id, config.azure.client_secret)):
        raise click.ClickException(
            "Set AZURE_TENANT_ID, AZURE_CLIENT_ID, and AZURE_CLIENT_SECRET before Graph operations."
        )


@click.group()
@click.option("--config", "-c", type=click.Path(exists=True), help="Path to config file")
@click.option("--connection-id", "-n", help="Connection ID for Graph connector (alphanumeric only)")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
@click.pass_context
def main(ctx, config: Optional[str], connection_id: Optional[str], verbose: bool):
    """SEC Copilot Connector - Import SEC EDGAR filings into Microsoft 365."""
    ctx.ensure_object(dict)

    config_path = Path(config) if config else None
    try:
        ctx.obj["config"] = load_config(config_path)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    ctx.obj["verbose"] = verbose
    ctx.obj["connection_id_override"] = connection_id


def initialize_logging(config, verbose):
    check_state_access(
        scoped_database_path(Path(config.paths.database), config.azure.tenant_id, config.azure.connection_id),
        (config.azure.tenant_id.lower(), config.azure.connection_id),
    )
    ensure_directories(config)
    setup_logging(Path(config.paths.logs), verbose)


def apply_connection_config(config, connection_id: Optional[str] = None, connection_name: Optional[str] = None) -> None:
    """Apply connection ID and name to the config object.

    Args:
        config: AppConfig to update
        connection_id: Sanitized connection ID
        connection_name: Human-readable display name for the connection
    """
    if connection_id:
        config.azure.connection_id = connection_id
    if connection_name:
        config.azure.connection_name = connection_name


@main.command()
@click.option("--connection-id", "-n", help="Connection ID for Graph connector")
@click.option("--connection-name", help="Display name for the connector in Microsoft 365")
@click.pass_context
def setup(ctx, connection_id: Optional[str], connection_name: Optional[str]):
    """Set up the Graph connector and schema."""
    config = ctx.obj["config"]

    require_graph_credentials(config)

    # Use the same configured destination across setup and subsequent commands.
    if connection_id:
        conn_id = sanitize_connection_id(connection_id)
        conn_name = connection_name or connection_id
        if conn_id != connection_id:
            console.print(f"[yellow]Connection ID sanitized: {connection_id} -> {conn_id}[/]")
    elif ctx.obj.get("connection_id_override"):
        raw = ctx.obj["connection_id_override"]
        conn_id = sanitize_connection_id(raw)
        conn_name = connection_name or raw
    else:
        conn_id = config.azure.connection_id
        conn_name = connection_name or config.azure.connection_name

    apply_connection_config(config, conn_id, conn_name)
    console.print(f"[bold]Connection name: [yellow]{config.azure.connection_name}[/][/]")
    console.print(f"[bold]Connection ID:   [green]{config.azure.connection_id}[/][/]")

    pipeline = IngestionPipeline(config)

    try:
        initialize_logging(config, ctx.obj["verbose"])
        run_async(pipeline.setup())
    except Exception as e:
        console.print(f"[bold red]Setup failed: {e}[/]")
        raise SystemExit(1)


@main.command()
@click.option("--tickers", "-t", required=True, help="Comma-separated list of ticker symbols")
@click.option("--connection-id", "-n", help="Connection ID for Graph connector")
@click.option("--connection-name", help="Display name for the connector in Microsoft 365")
@click.option("--test", is_flag=True, help="Run in test mode (limited filings)")
@click.option("--max-filings", type=click.IntRange(min=1), help="Maximum filings per ticker")
@click.option("--max-pages", type=click.IntRange(min=1), help="Maximum chunks per filing (sampled coverage)")
@click.option("--prune/--no-prune", default=None, help="Delete missing filings only after a complete unlimited historical crawl")
@click.option("--reprocess", is_flag=True, help="Rebuild selected in-flight filings with current processing settings; preserve old IDs until replacement uploads succeed")
@click.option("--save-payloads", is_flag=True, default=False, help="Save upload payloads as JSON files to data/payloads/")
@click.option("--ocr", is_flag=True, default=False, help="OCR local rotated-text images (requires OCR extra and Tesseract)")
@click.pass_context
def ingest(ctx, tickers: str, connection_id: Optional[str], connection_name: Optional[str], test: bool, max_filings: Optional[int], max_pages: Optional[int], prune: Optional[bool], save_payloads: bool, ocr: bool, reprocess: bool):
    """Ingest SEC filings for specified tickers."""
    config = ctx.obj["config"]
    require_graph_credentials(config)

    # Apply connection overrides
    if connection_id:
        conn_id = sanitize_connection_id(connection_id)
        if conn_id != connection_id:
            console.print(f"[yellow]Connection ID sanitized: {connection_id} -> {conn_id}[/]")
        apply_connection_config(config, conn_id, connection_name or connection_id)
    elif ctx.obj.get("connection_id_override"):
        raw = ctx.obj["connection_id_override"]
        apply_connection_config(config, sanitize_connection_id(raw), connection_name or raw)
    elif connection_name:
        apply_connection_config(config, connection_name=connection_name)

    if ocr:
        config.processing.ocr_images = True
    if prune is not None:
        config.sync.prune_missing_filings = prune

    ticker_list = [t.strip().upper() for t in tickers.split(",")]

    if not ticker_list or any(not ticker for ticker in ticker_list):
        console.print("[bold red]Error: No tickers specified[/]")
        raise SystemExit(1)

    console.print(f"[bold]SEC Connector - Ingesting filings for: {', '.join(ticker_list)}[/]")
    console.print(f"[dim]Connection: {config.azure.connection_name} ({config.azure.connection_id})[/]")

    if ocr:
        console.print("[cyan]OCR enabled for rotated-text images[/]")
    if test:
        console.print("[yellow]Running in TEST MODE[/]")
    if reprocess:
        console.print("[yellow]Reprocessing only discovered filings in the requested ticker/date scope; "
                      "previous remote IDs remain tracked until replacement delivery succeeds.[/]")

    pipeline = IngestionPipeline(config, test_mode=test, save_payloads=save_payloads)

    try:
        initialize_logging(config, ctx.obj["verbose"])
        stats = run_async(pipeline.ingest(
            tickers=ticker_list,
            max_filings=max_filings,
            max_pages=max_pages,
            reprocess=reprocess,
        ))

        _print_stats(stats)
        if stats["errors"]:
            raise SystemExit(1)

    except Exception as e:
        console.print(f"[bold red]Ingestion failed: {e}[/]")
        raise SystemExit(1)


@main.command()
@click.option("--connection-id", "-n", help="Connection ID for Graph connector")
@click.option("--connection-name", help="Display name for the connector in Microsoft 365")
@click.option("--save-payloads", is_flag=True, default=False, help="Save upload payloads as JSON files to data/payloads/")
@click.option("--ocr", is_flag=True, default=False, help="Compatibility flag; resume uses each filing's captured OCR setting")
@click.pass_context
def resume(ctx, connection_id: Optional[str], connection_name: Optional[str], save_payloads: bool, ocr: bool):
    """Resume interrupted processing."""
    config = ctx.obj["config"]
    require_graph_credentials(config)

    # Apply connection overrides
    if connection_id:
        apply_connection_config(config, sanitize_connection_id(connection_id), connection_name or connection_id)
    elif ctx.obj.get("connection_id_override"):
        raw = ctx.obj["connection_id_override"]
        apply_connection_config(config, sanitize_connection_id(raw), connection_name or raw)
    elif connection_name:
        apply_connection_config(config, connection_name=connection_name)

    if ocr:
        config.processing.ocr_images = True

    console.print("[bold]Resuming interrupted processing...[/]")
    console.print(f"[dim]Connection: {config.azure.connection_name} ({config.azure.connection_id})[/]")

    pipeline = IngestionPipeline(config, save_payloads=save_payloads)

    try:
        initialize_logging(config, ctx.obj["verbose"])
        stats = run_async(pipeline.resume())

        console.print("\n[bold]Resume Results:[/]")
        console.print(f"  Filings resumed: {stats['filings_resumed']}")
        console.print(f"  Queued filings outside date window (untouched): {stats.get('filings_outside_window', 0)}")
        console.print(f"  Chunks uploaded: {stats['chunks_uploaded']}")
        console.print(f"  Errors: {stats['errors']}")
        if stats["errors"]:
            raise SystemExit(1)

    except Exception as e:
        console.print(f"[bold red]Resume failed: {e}[/]")
        raise SystemExit(1)


@main.command()
@click.option("--connection-id", "-n", help="Connection ID for Graph connector")
@click.pass_context
def status(ctx, connection_id: Optional[str]):
    """Show processing status."""
    config = ctx.obj["config"]

    # Apply connection overrides
    if connection_id:
        apply_connection_config(config, sanitize_connection_id(connection_id))
    elif ctx.obj.get("connection_id_override"):
        apply_connection_config(config, sanitize_connection_id(ctx.obj["connection_id_override"]))

    console.print(f"[dim]Connection: {config.azure.connection_name} ({config.azure.connection_id})[/]")

    pipeline = IngestionPipeline(config)

    try:
        initialize_logging(config, ctx.obj["verbose"])
        stats = run_async(pipeline.status())

        console.print("\n[bold]Processing Status:[/]")

        table = Table(title="Filings")
        table.add_column("State", style="cyan")
        table.add_column("Count", justify="right")

        for state, count in stats.get("filings", {}).items():
            table.add_row(state, str(count))

        table.add_row("[bold]Total[/]", f"[bold]{stats.get('total_filings', 0)}[/]")
        console.print(table)

        console.print(f"Acknowledged remote items: {stats.get('acknowledged_items', 0)}")
        if stats.get("last_run"):
            run = stats["last_run"]
            console.print(f"Last run: {run['status']} (started {run['started_at']}, finished {run['completed_at'] or 'not finished'})")

        table = Table(title="Chunks")
        table.add_column("State", style="cyan")
        table.add_column("Count", justify="right")

        for state, count in stats.get("chunks", {}).items():
            table.add_row(state, str(count))

        table.add_row("[bold]Total[/]", f"[bold]{stats.get('total_chunks', 0)}[/]")
        console.print(table)

    except Exception as e:
        console.print(f"[bold red]Status check failed: {e}[/]")
        raise SystemExit(1)


@main.command()
@click.option("--connection-id", "-n", help="Connection ID for Graph connector")
@click.confirmation_option(prompt="Are you sure you want to reset the connector?")
@click.pass_context
def reset(ctx, connection_id: Optional[str]):
    """Reset the connector (delete connection and state)."""
    config = ctx.obj["config"]
    require_graph_credentials(config)

    # Apply connection overrides
    if connection_id:
        apply_connection_config(config, sanitize_connection_id(connection_id))
    elif ctx.obj.get("connection_id_override"):
        apply_connection_config(config, sanitize_connection_id(ctx.obj["connection_id_override"]))

    console.print(f"[dim]Connection: {config.azure.connection_name} ({config.azure.connection_id})[/]")

    pipeline = IngestionPipeline(config)

    try:
        initialize_logging(config, ctx.obj["verbose"])
        run_async(pipeline.reset())
    except Exception as e:
        console.print(f"[bold red]Reset failed: {e}[/]")
        raise SystemExit(1)


def _print_stats(stats: dict) -> None:
    """Print ingestion statistics."""
    console.print("\n[bold]Ingestion Results[/]")

    table = Table(title="Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Tickers processed", str(stats.get("tickers_processed", 0)))
    table.add_row("Filings discovered", str(stats.get("filings_discovered", 0)))
    table.add_row("Filings downloaded", str(stats.get("filings_downloaded", 0)))
    table.add_row("Filings parsed", str(stats.get("filings_parsed", 0)))
    table.add_row("Chunks created", str(stats.get("chunks_created", 0)))
    table.add_row("Chunks uploaded", str(stats.get("chunks_uploaded", 0)))
    table.add_row("Unchanged chunks (PUT skipped)", str(stats.get("chunks_unchanged", 0)))
    table.add_row("Cached documents (parse skipped)", str(stats.get("documents_cached", 0)))
    table.add_row("Obsolete chunks deleted", str(stats.get("chunks_deleted", 0)))
    table.add_row("Missing filings retired", str(stats.get("filings_retired", 0)))
    table.add_row("Complete filings", str(stats.get("filings_completed", 0)))
    table.add_row("Sampled filings (not full coverage)", str(stats.get("filings_sampled", 0)))
    table.add_row("Previously completed/sample filings skipped", str(stats.get("filings_skipped", 0)))
    table.add_row("Errors", str(stats.get("errors", 0)))

    console.print(table)

    if stats.get("errors", 0) > 0:
        console.print("\n[yellow]Some errors occurred. Check logs for details.[/]")
    else:
        console.print("\n[green]Run finished without processing errors. Sampled filings are not full coverage.[/]")


@main.group()
def maintenance():
    """Provisional exact-document upgrades; quiesce ALL writers before applying.

    Prepare/inspect do not mutate Graph or source state. Apply promotes SQLite
    format 3 to 4 permanently (separate from processing version 8). Old clients
    cannot reopen it, even after rollback. Normal resume is not maintenance
    recovery. See docs/maintenance.md before authorizing any live writes.
    """


def maintenance_config(ctx):
    config = ctx.obj["config"]
    override = ctx.obj.get("connection_id_override")
    if override:
        config.azure.connection_id = override
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{2,31}", config.azure.connection_id):
        raise click.ClickException("Maintenance requires an exact alphanumeric connection ID")
    return config


@maintenance.command("prepare")
@click.option("--cik", required=True)
@click.option("--accession", required=True)
@click.option("--filename")
@click.option("--sequence", type=click.IntRange(min=1))
@click.option("--source", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--document", "documents", multiple=True,
              type=(str, click.IntRange(min=1), click.Path(exists=True, dir_okay=False, path_type=Path)),
              help="Repeat FILENAME SEQUENCE SOURCE for EVERY persisted document in a completed non-OCR filing.")
@click.option("--out", type=click.Path(dir_okay=False, path_type=Path), required=True)
@click.option("--recover-prepared", is_flag=True,
              help="Opt in to replacing a complete sole-document interrupted manifest; prefer finishing ordinary resume.")
@click.pass_context
def maintenance_prepare(ctx, cik, accession, filename, sequence, source, documents, out, recover_prepared):
    """Freeze exact cached scope: one document or an explicit full inventory; GET only."""
    from .maintenance import MaintenanceGraphClient, prepare, prepare_documents
    if documents:
        if any(value is not None for value in (filename, sequence, source)) or recover_prepared:
            raise click.UsageError("--document cannot be combined with single-document options or --recover-prepared")
        if len(documents) < 2:
            raise click.UsageError("--document requires at least two documents; use single-document options otherwise")
    elif any(value is None for value in (filename, sequence, source)):
        raise click.UsageError("Supply --filename, --sequence and --source, or repeat --document for the full inventory")
    config = maintenance_config(ctx)
    require_graph_credentials(config)

    async def run():
        async with MaintenanceGraphClient(config) as graph:
            if documents:
                return await prepare_documents(config, graph, cik=cik, accession=accession,
                                               selections=documents, output=out)
            return await prepare(config, graph, cik=cik, accession=accession, filename=filename,
                                 sequence=sequence, source=source, output=out,
                                 recover_prepared=recover_prepared)
    try:
        click.echo(f"Reviewed plan digest: {run_async(run())}")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@maintenance.command("inspect")
@click.option("--plan", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option("--plan-digest", required=True)
def maintenance_inspect(plan, plan_digest):
    """Read frozen scope/checkpoints without authentication, locks or migration."""
    from .maintenance import inspect, load_plan
    try:
        click.echo(json.dumps(inspect(load_plan(plan, plan_digest), plan_digest), indent=2))
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


def register_maintenance_action(action):
    @maintenance.command(action)
    @click.option("--plan", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
    @click.option("--plan-digest", required=True, help="Digest printed by prepare; review before authorizing.")
    @click.option("--maintenance-ack", is_flag=True, required=True,
                  help="All local/scheduled/other-machine writers are quiesced; authorize scoped Graph writes.")
    @click.option("--recovery-dir", type=click.Path(file_okay=False, path_type=Path),
                  help="Required new private directory for apply; retained for all recovery.")
    @click.pass_context
    def command(ctx, plan, plan_digest, maintenance_ack, recovery_dir):
        from .maintenance import MaintenanceGraphClient, execute, load_plan
        config = maintenance_config(ctx)
        require_graph_credentials(config)

        async def run():
            frozen = load_plan(plan, plan_digest)
            async with MaintenanceGraphClient(config) as graph:
                return await execute(config, graph, frozen, plan_digest, action,
                                     acknowledged=maintenance_ack, recovery=recovery_dir)
        try:
            click.echo(run_async(run()))
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc
    command.help = {
        "apply": "Authorize a reviewed plan, capture recovery, then overwrite/verify/retire exact IDs.",
        "resume": "Continue the same guarded forward operation; never reparse or use normal resume.",
        "rollback": "Restore and verify old Graph items FIRST, then remove owned new IDs and restore scoped rows. Repeat to resume rollback.",
    }[action]


for _action in ("apply", "resume", "rollback"):
    register_maintenance_action(_action)


if __name__ == "__main__":
    main()
