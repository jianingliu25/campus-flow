from alembic import context

from app.config import get_settings
from app.db import Database
from app.models import Base, UTCDateTime

config = context.config


def migrate(connection):
    def render_item(type_, item, autogen_context):
        if type_ == "type" and isinstance(item, UTCDateTime):
            return "sa.DateTime()"
        return False
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True, render_as_batch=True, render_item=render_item)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("Use online migrations against a private database")
elif config.attributes.get("connection") is not None:
    migrate(config.attributes["connection"])
else:
    db = Database(get_settings().data_dir)
    try:
        with db.engine.begin() as connection:
            migrate(connection)
    finally:
        db.close()
