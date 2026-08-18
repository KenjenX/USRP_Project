import getpass
import sys

from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from backend.database import SessionLocal, engine
from backend.models import User


def main() -> int:
    if not inspect(engine).has_table(User.__tablename__):
        print(
            "The users table is not available. Run the users migration first.",
            file=sys.stderr,
        )
        return 1

    username = input("Username [admin]: ").strip() or "admin"
    if len(username) > 100:
        print("Username must not exceed 100 characters.", file=sys.stderr)
        return 1

    password = getpass.getpass("Password: ")
    password_confirmation = getpass.getpass("Confirm password: ")

    if not password:
        print("Password must not be empty.", file=sys.stderr)
        return 1

    if password != password_confirmation:
        print("Password confirmation does not match.", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        existing_user = (
            db.query(User)
            .filter(User.username == username)
            .first()
        )
        if existing_user is not None:
            print("That username already exists.", file=sys.stderr)
            return 1

        user = User(
            username=username,
            password=password,
        )
        db.add(user)
        db.commit()
    except IntegrityError:
        db.rollback()
        print("That username already exists.", file=sys.stderr)
        return 1
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print(f'Admin user "{username}" was created successfully.')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
