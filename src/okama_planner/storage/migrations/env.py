"""Run migrations on the connection owned by the storage API."""

from alembic import context

config = context.config
context.configure(connection=config.attributes["connection"])
with context.begin_transaction():
    context.run_migrations()
