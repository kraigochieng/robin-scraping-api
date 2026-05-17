import shutil
from pathlib import Path

import typer
from scrapling.fetchers import StealthySession

from robin_scraping_api.config import PROFILES_DIR

app = typer.Typer(no_args_is_help=True)


def _list_profiles() -> list[str]:
    """Helper to get all profiles"""
    profiles_path = Path(PROFILES_DIR)
    if not profiles_path.exists():
        return []
    return [p.name for p in profiles_path.iterdir() if p.is_dir()]


def _show_profiles():
    """Print available profiles to terminal"""
    profiles = _list_profiles()
    if not profiles:
        typer.echo("No profiles found.")
        return
    typer.echo("\nAvailable profiles:")
    for profile in profiles:
        typer.echo(f"  - {profile}")
    typer.echo("")


@app.command()
def create_profile():
    """
    Create profile
    """
    _show_profiles()

    profile_name = typer.prompt("Enter profile name (Do not use special characters)")

    profile_path = PROFILES_DIR / profile_name

    if profile_path.exists():
        typer.echo(f"Profile '{profile_name}' already exists.")
        raise typer.Exit()

    # proceed with creation
    profile_path.mkdir(parents=True)
    typer.echo(f"Profile '{profile_name}' created successfully.")


@app.command()
def list_profiles():
    """
    List all available profiles
    """

    if not PROFILES_DIR.exists():
        typer.echo("No profiles directory found.")
        raise typer.Exit()

    profiles = [p.name for p in PROFILES_DIR.iterdir() if p.is_dir()]

    if not profiles:
        typer.echo("No profiles found.")
        raise typer.Exit()

    typer.echo("Available profiles:")
    for profile in profiles:
        typer.echo(f"  - {profile}")


@app.command()
def open_session():
    """
    Open a Chrome browser session, log in manually, and save the session to a profile
    """
    _show_profiles()

    profile_name = typer.prompt("Enter profile name")
    profile_path = Path(PROFILES_DIR) / profile_name

    if not profile_path.exists():
        typer.echo(f"Profile '{profile_name}' not found. Run `create-profile` first.")
        raise typer.Exit()

    typer.echo(f"Opening browser for profile: {profile_name}")

    with StealthySession(
        headless=False,
        user_data_dir=str(profile_path),
    ) as browser:
        browser.fetch("https://www.google.com/", network_idle=True)
        typer.prompt(
            "Log in, then press ENTER to save and close", default="", show_default=False
        )

    typer.echo(f"Session saved to: {profile_path}")


@app.command()
def delete_profile():
    """
    Delete a profile and all its data
    """
    _show_profiles()

    profile_name = typer.prompt("Enter profile name to delete")
    profile_path = Path(PROFILES_DIR) / profile_name

    if not profile_path.exists():
        typer.echo(f"Profile '{profile_name}' not found.")
        raise typer.Exit()

    confirm = typer.confirm(
        f"Are you sure you want to delete '{profile_name}'? This cannot be undone"
    )
    if not confirm:
        typer.echo("Cancelled.")
        raise typer.Exit()

    shutil.rmtree(profile_path)
    typer.echo(f"Profile '{profile_name}' deleted.")


if __name__ == "__main__":
    # typer.run(main)
    app()
