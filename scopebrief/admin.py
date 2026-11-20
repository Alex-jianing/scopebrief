import argparse
from getpass import getpass
from pathlib import Path

from .identity import Conflict
from .settings import Settings
from .store import Store
from .team import Team


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage one ScopeBrief deployment.")
    parser.add_argument("--db", type=Path, help="Override SCOPEBRIEF_DB")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "bootstrap", help="Issue a single-use administrator code valid for 24 hours"
    )
    reset = commands.add_parser(
        "reset-password", help="Reset an account password and revoke its sessions"
    )
    reset.add_argument("username")
    backup = commands.add_parser("backup", help="Create a consistent SQLite snapshot in a new file")
    backup.add_argument("destination", type=Path)
    args = parser.parse_args()
    settings = Settings.from_env()
    path = args.db or settings.db
    store = Store(path)
    try:
        if args.command == "backup":
            if not path.is_file():
                parser.error("The source database does not exist")
            store.backup(args.destination)
            print(args.destination.resolve())
            return
        store.initialize(seed=False)
        team = Team(store)
        if args.command == "bootstrap":
            print(team.issue(None, "管理员初始化", {}, bootstrap=True)["code"])
        else:
            first = getpass("New password: ")
            if first != getpass("Confirm password: "):
                parser.error("Passwords differ")
            team.reset_password(args.username, first)
    except (ValueError, Conflict, LookupError, RuntimeError, FileExistsError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
