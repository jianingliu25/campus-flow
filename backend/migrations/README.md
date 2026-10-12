# Database migrations

Migration 0001 defines 12 application tables with source/workspace ownership constraints.
Run `python scripts/manage.py migrate` from the root, or `alembic upgrade head`
using the project's virtual environment from backend/. Server startup also upgrades
the private database idempotently. Destructive downgrade is only tested against
empty temporary databases; do not use it to remove actual user data.
