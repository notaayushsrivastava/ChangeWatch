"""Apply reviewed, versioned database migrations to the configured database."""
from app.database_migrations import apply_database_migrations


def main() -> None:
    apply_database_migrations()
    print("ChangeWatch database migrations are up to date.")


if __name__ == "__main__":
    main()
