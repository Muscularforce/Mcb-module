import datetime
from database import SessionLocal, engine
import models

# Ensure tables exist
models.Base.metadata.create_all(bind=engine)

db = SessionLocal()

# Check if data already exists to avoid duplicate seeding
if db.query(models.Entry).count() == 0:
    yesterday = datetime.date.today() - datetime.timedelta(days=1)

    entries = [
        models.Entry(
            entry_type="DiaryEntry",
            subject="Mathematics",
            teacher="John Doe",
            date=yesterday,
            summary="Homework: Complete exercises 1-10 on page 42.",
            attachment_url="https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
        ),
        models.Entry(
            entry_type="Worksheet",
            subject="Physics",
            teacher="Jane Smith",
            date=yesterday,
            summary="Newton's Laws of Motion Practice Problems.",
            attachment_url="https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
        ),
        models.Entry(
            entry_type="Worksheet",
            subject="Chemistry",
            teacher="Alan Turing",
            date=yesterday,
            summary="Balancing Chemical Equations Worksheet.",
            attachment_url="https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
        ),
        models.Entry(
            entry_type="Worksheet",
            subject="Biology",
            teacher="Rosalind Franklin",
            date=yesterday,
            summary="Cell Structure and Function Diagram Labeling.",
            attachment_url="https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
        )
    ]

    for e in entries:
        db.add(e)
        
    db.commit()
    print("Database seeded successfully with yesterday's diary and 3 worksheets!")
else:
    print("Database already seeded.")

db.close()
