"""Initialize an empty ChangeWatch database.

Use only for a new database. This is not a schema-migration tool and should not
be run on every Vercel function startup or as a destructive reset operation.
"""
import app.models  # noqa: F401 - registers ORM model metadata
from app.db import Base, engine


def main() -> None:
    Base.metadata.create_all(bind=engine)
    print("ChangeWatch tables are present. Existing tables were left intact.")


if __name__ == "__main__":
    main()
