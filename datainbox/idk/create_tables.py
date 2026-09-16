import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google.cloud.sql.connector import Connector, IPTypes
from google.oauth2 import service_account
from sqlalchemy import create_engine, inspect

sys.path.insert(0, str(Path(__file__).resolve().parent))
from models import Base

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


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

    return create_engine("postgresql+pg8000://", creator=getconn, echo=True)


def main():
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

    ip_type = IPTypes.PRIVATE if IP_TYPE.lower() == "private" else IPTypes.PUBLIC
    connector = Connector(credentials=credentials(), ip_type=ip_type)

    try:
        engine = build_engine(connector)

        # creates any table in Base.metadata that doesn't already exist.
        # existing tables are left untouched -- it does NOT alter columns.
        Base.metadata.create_all(engine)

        tables = inspect(engine).get_table_names(schema="public")
        print(f"\ntables in {DB_NAME}.public: {tables}")

        engine.dispose()

    finally:
        connector.close()


if __name__ == "__main__":
    main()
