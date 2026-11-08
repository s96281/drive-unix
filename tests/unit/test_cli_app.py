from __future__ import annotations

from cli.app import create_app


EXPECTED_COMMANDS = {
    "ls", "tree", "find", "search", "mkdir", "rm", "stat",
    "cp", "mv", "upload", "download", "download-link",
    "sync", "bisync", "diff", "checksum", "init",
    "add-sp", "add-odb", "add-gdrive", "add-photos", "add-local", "add-ftp",
    "add-webdav", "add-onedrive", "add-pikpak", "list-nodes", "remove-node",
    "rename-node", "edit-node", "export-env", "import-env",
    "cron-add", "cron-ls", "cron-rm", "cron-toggle", "cron-start",
}


def test_root_cli_registers_all_commands() -> None:
    app = create_app()
    commands = {command.name for command in app.registered_commands}

    assert commands == EXPECTED_COMMANDS
    assert {group.name for group in app.registered_groups} == {"remote", "schedule", "env", "upstash"}


def test_legacy_admin_commands_are_hidden_from_root_help() -> None:
    app = create_app()
    hidden = {command.name for command in app.registered_commands if command.hidden}
    assert {
        "add-sp", "add-odb", "add-gdrive", "add-photos", "add-local", "add-ftp",
        "add-webdav", "add-onedrive", "add-pikpak", "list-nodes", "remove-node",
        "rename-node", "edit-node", "export-env", "import-env",
        "cron-add", "cron-ls", "cron-rm", "cron-toggle", "cron-start",
    } <= hidden


def test_sync_exposes_one_way_and_two_way_flags() -> None:
    import click
    import typer

    command = typer.main.get_command(create_app())
    sync_command = command.get_command(click.Context(command), "sync")
    assert sync_command is not None

    one_way = next(param for param in sync_command.params if param.name == "one_way")
    assert one_way.default is True
    assert one_way.is_flag is True
    assert one_way.opts == ["--one-way"]
    assert one_way.secondary_opts == ["--two-way"]


def test_bisync_is_a_dedicated_two_way_command() -> None:
    import click
    import typer

    command = typer.main.get_command(create_app())
    bisync_command = command.get_command(click.Context(command), "bisync")
    assert bisync_command is not None
    assert not any(param.name == "one_way" for param in bisync_command.params)


def test_schedule_exposes_background_service_lifecycle() -> None:
    import click
    import typer

    command = typer.main.get_command(create_app())
    root_ctx = click.Context(command)
    schedule = command.get_command(root_ctx, "schedule")
    assert schedule is not None

    service = schedule.get_command(click.Context(schedule, parent=root_ctx), "service")
    assert service is not None
    assert set(service.commands) == {"install", "start", "status", "stop", "uninstall"}


def test_root_exposes_plain_output_option() -> None:
    import typer

    command = typer.main.get_command(create_app())
    plain = next(param for param in command.params if param.name == "plain")
    assert plain.is_flag is True
    assert plain.opts == ["--plain"]
