"""CLI: seed the demonstration pipeline.

Usage:  python -m app.seed_demo
Requires an existing user account (first registered user) to attribute actions.
"""
from app.core.logging import configure_logging
from app.db.base import SessionLocal
from app.main import app  # noqa: F401  (ensures models are registered)
from app.models.user import User
from app.services.demo import load_demo


def main() -> None:
    configure_logging()
    db = SessionLocal()
    try:
        user = db.query(User).order_by(User.id).first()
        if user is None:
            print("No users found. Register an account in the app first, then re-run.")
            return
        result = load_demo(db, user)
        print("Demonstration data loaded (clearly labeled — not production data):")
        for key, value in result.items():
            print(f"  {key}: {value}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
