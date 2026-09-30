#!/bin/sh
set -e

DB_FILE="${DATABASE_URL#sqlite:///}"

if [ ! -f "$DB_FILE" ]; then
    # Fresh database: importing main runs create_all and seeds the admin user,
    # then mark the schema as current so later upgrades don't recreate tables.
    echo "Initializing new database at $DB_FILE"
    python -c "import main"
    alembic stamp head
else
    alembic upgrade head
fi

exec "$@"
