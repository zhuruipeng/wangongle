from .database import SessionLocal
from .storage import get_storage
from .storage.cleanup import retry_storage_cleanup


def run() -> None:
    with SessionLocal() as db:
        result = retry_storage_cleanup(db, get_storage())
    print(f"storage cleanup: succeeded={result['succeeded']} failed={result['failed']}")


if __name__ == "__main__":
    run()
