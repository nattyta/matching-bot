from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, ForeignKey, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import logging

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    chat_id = Column(Integer, primary_key=True)
    username = Column(String(100))
    name = Column(String(100))
    age = Column(Integer)
    gender = Column(String(1))  # 'M' or 'F'
    location = Column(String(200))
    photo = Column(String(500))
    interests = Column(Text)
    looking_for = Column(String(10))  # '1' for Dating, '2' for Friends
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)

class Like(Base):
    __tablename__ = 'likes'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    liker_chat_id = Column(Integer, index=True)
    liked_chat_id = Column(Integer, index=True)
    note = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

class BannedUser(Base):
    __tablename__ = 'banned_users'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, unique=True, index=True)
    reason = Column(Text)
    banned_at = Column(DateTime, default=datetime.utcnow)
    banned_by = Column(Integer)

class Report(Base):
    __tablename__ = 'reports'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    reporter_chat_id = Column(Integer, index=True)
    reported_chat_id = Column(Integer, index=True)
    violation = Column(String(50))
    description = Column(Text)
    status = Column(String(20), default='pending')  # pending, reviewed, resolved
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime)

class Group(Base):
    __tablename__ = 'groups'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200))
    description = Column(Text)
    photo = Column(String(500))
    invite_link = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(Integer)
    is_active = Column(Boolean, default=True)
    member_count = Column(Integer, default=0)

class ChatSession(Base):
    __tablename__ = 'chat_sessions'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user1_id = Column(Integer, index=True)
    user2_id = Column(Integer, index=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime)
    rating = Column(Integer)  # 1-5

# Database setup
engine = None
SessionLocal = None

def init_database(database_url):
    """Initialize database with proper schema"""
    global engine, SessionLocal
    
    try:
        # Create engine with connection pooling
        engine = create_engine(
            database_url,
            pool_size=20,
            max_overflow=30,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=False  # Set to True for debugging SQL queries
        )
        
        # Create all tables
        Base.metadata.create_all(bind=engine)
        
        # Create indexes if they don't exist
        with engine.begin() as conn:
            # Create composite index for faster mutual like queries
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_likes_mutual 
                ON likes (liker_chat_id, liked_chat_id, timestamp)
            """))
            
            # Create index for user activity
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_users_activity 
                ON users (is_active, looking_for, gender)
            """))
        
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        return True
        
    except Exception as e:
        logging.error(f"Database initialization failed: {e}")
        return False

def get_db():
    """Get database session"""
    if SessionLocal is None:
        raise RuntimeError("Database not initialized")
    
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
