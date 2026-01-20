"""
SwiftLabel Command-Line Interface

Click-based CLI for launching SwiftLabel.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import webbrowser
from pathlib import Path

import click
import uvicorn

from swiftlabel.filesystem import validate_working_directory


def setup_logging(debug: bool) -> None:
    """Configure logging."""
    level = logging.DEBUG if debug else logging.ERROR
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )


@click.command()
@click.argument(
    "directory",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
)
@click.option(
    "--classes",
    "-c",
    required=True,
    help="Comma-separated list of class names (e.g., 'cat,dog,bird')",
)
@click.option(
    "--host",
    "-h",
    default="127.0.0.1",
    show_default=True,
    help="Server host address",
)
@click.option(
    "--port",
    "-p",
    default=8765,
    show_default=True,
    type=int,
    help="Server port",
)
@click.option(
    "--no-browser",
    is_flag=True,
    help="Don't open browser automatically",
)
@click.option(
    "--debug",
    is_flag=True,
    help="Enable debug logging",
)
@click.version_option()
def main(
    directory: Path,
    classes: str,
    host: str,
    port: int,
    no_browser: bool,
    debug: bool,
) -> None:
    """
    SwiftLabel - Keyboard-first image classification tool.

    DIRECTORY is the path to the folder containing images to classify.

    Example:

        swiftlabel ./images --classes cat,dog,bird
    """
    setup_logging(debug)

    # Parse classes
    class_list = [c.strip() for c in classes.split(",") if c.strip()]

    if not class_list:
        click.echo("Error: No classes specified", err=True)
        sys.exit(1)

    if len(class_list) > 10:
        click.echo("Error: Maximum 10 classes allowed", err=True)
        sys.exit(1)

    # Validate directory
    is_valid, issues = asyncio.run(validate_working_directory(directory))

    if not is_valid:
        click.echo("Error: Directory validation failed:", err=True)
        for issue in issues:
            click.echo(f"  - {issue}", err=True)
        sys.exit(1)

    # Print startup info
    click.echo("SwiftLabel starting...")
    click.echo(f"  Directory: {directory.resolve()}")
    click.echo(f"  Classes: {', '.join(class_list)}")
    click.echo(f"  Server: http://{host}:{port}")
    click.echo()
    click.echo("Press Ctrl+C to stop")
    click.echo()

    # Open browser with a slight delay to ensure server is ready
    if not no_browser:
        url = f"http://{host}:{port}"
        from threading import Timer
        Timer(1.5, webbrowser.open, args=[url]).start()

    # Create and run app
    from swiftlabel.server import create_app

    app = create_app(
        working_directory=directory.resolve(),
        classes=class_list,
        host=host,
        port=port,
    )

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="debug" if debug else "warning",
        access_log=debug,
    )


if __name__ == "__main__":
    main()
