import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class EmailValidationTransaction(Base):
    __tablename__ = "email_validation_transactions"
    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    description = Column(String(255), nullable=True)

class ESPDomain(Base):
    __tablename__ = "esp_domains"
    id = Column(Integer, primary_key=True, index=True)
    domain = Column(String(255), unique=True, index=True, nullable=False)
    esp_name = Column(String(100), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    
class EmailSyntaxMXValidation(Base):
    __tablename__ = "email_syntax_mx_validations"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), index=True, nullable=False)
    transaction_id = Column(String, ForeignKey("email_validation_transactions.id"), nullable=False)
    syntax_valid = Column(Boolean, nullable=False)
    mx_records = Column(Text)  # comma separated "priority:host"
    is_smtp_checked = Column(Boolean, nullable=False, default=False)
    smtp_valid = Column(Boolean, nullable=True)
    smtp_response = Column(Text, nullable=True)
    smtp_status = Column(String(255), nullable=True)  # Detailed SMTP validation status
    is_syntax_mx_valid = Column(Boolean, nullable=False, default=False)  # Syntax and MX valid flag
    is_level1_checked = Column(Boolean, nullable=False, default=False)  # Level 1 SMTP check done flag
    is_level2_checked = Column(Boolean, nullable=False, default=False)  # Level 2 SMTP check done flag
    is_catchall_checked = Column(Boolean, nullable=False, default=False)  # Catch-all check done flag
    validated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=True)
    smtp_validated_at = Column(DateTime(timezone=True), nullable=True)  # Timestamp for SMTP validation
    esp_category = Column(String(100), nullable=False, default="Unknown")
    __table_args__ = (
        UniqueConstraint('email', 'transaction_id', name='uix_email_transaction'),
    )
