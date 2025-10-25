from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
import os
from dotenv import load_dotenv
from .models import Base

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql://username:password@158.69.0.165:5432/everifier"
)

# Configure engine with connection pooling for remote database
engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,  # Verify connections before using
    pool_recycle=3600,   # Recycle connections after 1 hour
    echo=False,
    connect_args={
        "options": "-c timezone=utc",
        "connect_timeout": 10
    }
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def test_connection():
    """Test database connection"""
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT 1"))
            print(" Database connection successful!")
            return True
    except Exception as e:
        print(f" Database connection failed: {e}")
        return False

def init_db():
    """Initialize database - create tables if they don't exist"""
    try:
        # Set schema to public
        with engine.connect() as connection:
            connection.execute(text("SET search_path TO public"))
            connection.commit()
        
        Base.metadata.create_all(bind=engine)
        print(" Database tables checked/created in 'public' schema!")
    except Exception as e:
        print(f" Error initializing database: {e}")
        raise
