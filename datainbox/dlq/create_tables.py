"""Create the `message_attempts` table in the datainbox database.

    python create_tables.py            # dry run: connect, list tables, print the DDL
    python create_tables.py --apply    # create any missing table from models.Base

`create_all` only adds tables that don't exist; it never alters or drops existing ones.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google.cloud.sql.connector import Connector, IPTypes
from google.oauth2 import service_account
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from models import Base

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


INSTANCE = os.getenv("DATAINBOX_DB_CONNECTION_NAME")
DB_NAME = os.getenv("DATAINBOX_DB_NAME")
USER = os.getenv("DATAINBOX_USER")
PASSWORD = os.getenv("DATAINBOX_PASSWORD")
IP_TYPE = os.getenv("DATAINBOX_DB_IP_TYPE", "public")


def credentials():
    path = os.getenv("GCLOUD_CREDS_PATH")
    if path:
        return service_account.Credentials.from_service_account_file(path)

    return None


def build_engine(connector: Connector):
    def getconn():
        return connector.connect(
            INSTANCE,
            "pg8000",
            user=USER,
            password=PASSWORD,
            db=DB_NAME,
        )

    return create_engine("postgresql+pg8000://", creator=getconn)


def print_ddl():
    dialect = postgresql.dialect()
    for table in Base.metadata.sorted_tables:
        print(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
        for index in table.indexes:
            print(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";")


def main(apply: bool):
    missing = [
        name
        for name, value in {
            "DATAINBOX_DB_CONNECTION_NAME": INSTANCE,
            "DATAINBOX_DB_NAME": DB_NAME,
            "DATAINBOX_USER": USER,
            "DATAINBOX_PASSWORD": PASSWORD,
        }.items()
        if not value
    ]
    if missing:
        raise SystemExit(f"missing env vars: {', '.join(missing)}")

    print(f"target: {INSTANCE} / {DB_NAME} as {USER} ({IP_TYPE} ip)")
    print(f"tables to ensure: {list(Base.metadata.tables)}\n")
    print_ddl()

    ip_type = IPTypes.PRIVATE if IP_TYPE.lower() == "private" else IPTypes.PUBLIC
    connector = Connector(credentials=credentials(), ip_type=ip_type)

    try:
        engine = build_engine(connector)

        before = inspect(engine).get_table_names(schema="public")
        print(f"\nexisting tables: {before}")

        if not apply:
            print("\ndry run only. re-run with --apply to create.")
            return

        Base.metadata.create_all(engine)

        inspector = inspect(engine)
        after = inspector.get_table_names(schema="public")
        print(f"tables after create_all: {after}")

        for name in Base.metadata.tables:
            columns = [f"{c['name']}:{c['type']}" for c in inspector.get_columns(name)]
            indexes = [i["name"] for i in inspector.get_indexes(name)]
            print(f"\n{name} columns: {columns}\n{name} indexes: {indexes}")

        engine.dispose()

    finally:
        connector.close()


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
