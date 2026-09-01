import time

from sqlalchemy import select

from app.db import SessionLocal
from app.models import PlanningJob
from app.services import process_job


def run() -> None:
    while True:
        db = SessionLocal()
        try:
            job = db.scalar(select(PlanningJob).where(PlanningJob.status == "queued").order_by(PlanningJob.id))
            if job:
                process_job(job.id)
        finally:
            db.close()
        time.sleep(1)


if __name__ == "__main__":
    run()
