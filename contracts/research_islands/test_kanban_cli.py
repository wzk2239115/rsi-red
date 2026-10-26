"""Public entry-point contracts for the archipelago dashboard."""
from tests.test_cli import cli


def test_kanban_is_discoverable_from_root_help():
    result = cli("--help")
    assert result.returncode == 0
    assert "kanban" in result.stdout


def test_kanban_help_exposes_launch_controls_without_starting_server():
    result = cli("kanban", "--help")
    assert result.returncode == 0, result.stdout
    for option in ("--port", "--no-open", "--demo"):
        assert option in result.stdout
