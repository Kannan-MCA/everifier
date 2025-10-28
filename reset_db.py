from sqlalchemy import create_engine
from dotenv import load_dotenv
import os
from app.models import Base

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/email_validator")

def reset_database():
    engine = create_engine(DATABASE_URL, echo=True)

    try:
        print("Dropping all tables...")
        Base.metadata.drop_all(bind=engine)
        print("All tables dropped successfully.")
    except Exception as e:
        print(f"Warning during drop: {e}")

    try:
        print("Creating tables with correct schema...")
        Base.metadata.create_all(bind=engine)
        print("Tables created successfully.")
    except Exception as e:
        print(f"Error during table creation: {e}")
        return

    print("\nDatabase reset complete!")
    print("Table 'email_validations' created with columns:")
    print("  - id (SERIAL PRIMARY KEY)")
    print("  - email (VARCHAR(255))")
    print("  - status (VARCHAR(50))")
    print("  - reason (TEXT)")
    print("  - mx_records (TEXT)")
    print("  - smtp_response (TEXT)")
    print("  - validated_at (TIMESTAMP)")
    print("  - catchall_checked (BOOLEAN)")
    print("  - catch_all (BOOLEAN, nullable)")
    print("  - catchall_reason (TEXT, nullable)")

if __name__ == "__main__":
    reset_database()
