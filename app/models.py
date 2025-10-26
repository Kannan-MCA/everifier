from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.orm import declarative_base
from datetime import datetime, UTC

Base = declarative_base()

class EmailValidation(Base):
    __tablename__ = "email_validations"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), index=True, nullable=False)
    status = Column(String(50), nullable=False)
    reason = Column(Text)
    mx_records = Column(Text)
    smtp_response = Column(Text)
    validated_at = Column(DateTime, default=lambda: datetime.now(UTC))
    catchall_checked = Column(Boolean, default=False, nullable=False)  # New field to track catch-all detection status

    def __repr__(self):
        return f"<EmailValidation(email={self.email}, status={self.status})>"
