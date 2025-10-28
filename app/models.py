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
    catchall_checked = Column(Boolean, default=False, nullable=False)  # Indicates if catch-all was checked
    catch_all = Column(Boolean, nullable=True, default=None)  # Catch-all status: True/False/None
    catchall_reason = Column(Text, nullable=True)  # Optional detailed reason/explanation

    def __repr__(self):
        return f"<EmailValidation(email={self.email}, status={self.status}, catch_all={self.catch_all})>"
