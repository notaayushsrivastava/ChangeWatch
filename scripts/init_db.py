"""Apply reviewed, versioned database migrations to the configured database."""
from alembic import command
from alembic.config import Config


def main() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    print("ChangeWatch database migrations are up to date.")


if __name__ == "__main__":
    main()
