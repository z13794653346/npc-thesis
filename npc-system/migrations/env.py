"""Alembic environment. Pass sqlalchemy.url explicitly to migrate a database copy."""

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.db_models import Base
from app.storage import normalize_database_url

config = context.config
arguments = context.get_x_argument(as_dictionary=True)
database_url = normalize_database_url(
    arguments.get("database_url", config.get_main_option("sqlalchemy.url"))
)

if context.is_offline_mode():
    context.configure(
        url=database_url,
        target_metadata=Base.metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    section = config.get_section(config.config_ini_section)
    section["sqlalchemy.url"] = database_url
    engine = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
