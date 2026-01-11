from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, ForeignKey, ARRAY
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    # Based on your INSERT query in ask_interests function
    chat_id = Column(Integer, primary_key=True)
    username = Column(String(100))
    name = Column(String(100))
    age = Column(Integer)
    gender = Column(String(1))  # 'M' or 'F'
    location = Column(String(200))
    photo = Column(String(500))  # Telegram file_id or URL
    interests = Column(Text)  # Stored as comma-separated string
    looking_for = Column(String(10))  # '1' for Dating, '2' for Friends
    
    # Relationships
    sent_likes = relationship('Like', foreign_keys='Like.liker_chat_id', back_populates='liker')
    received_likes = relationship('Like', foreign_keys='Like.liked_chat_id', back_populates='liked_user')
    sent_reports = relationship('Report', foreign_keys='Report.reporter_chat_id', back_populates='reporter')
    received_reports = relationship('Report', foreign_keys='Report.reported_chat_id', back_populates='reported_user')

class Like(Base):
    __tablename__ = 'likes'
    
    # Based on your INSERT queries in handle_like_action and handle_send_note_action
    id = Column(Integer, primary_key=True, autoincrement=True)
    liker_chat_id = Column(Integer, ForeignKey('users.chat_id'))
    liked_chat_id = Column(Integer, ForeignKey('users.chat_id'))
    note = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    liker = relationship('User', foreign_keys=[liker_chat_id], back_populates='sent_likes')
    liked_user = relationship('User', foreign_keys=[liked_chat_id], back_populates='received_likes')

class BannedUser(Base):
    __tablename__ = 'banned_users'
    
    # Based on your query in send_welcome function
    user_id = Column(Integer, primary_key=True)  # chat_id of banned user

class Report(Base):
    __tablename__ = 'reports'
    
    # Based on your INSERT query in handle_violation function
    id = Column(Integer, primary_key=True, autoincrement=True)
    reporter_chat_id = Column(Integer, ForeignKey('users.chat_id'))
    reported_chat_id = Column(Integer, ForeignKey('users.chat_id'))
    violation = Column(String(50))  # 'spam', 'harassment', 'other'
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    reporter = relationship('User', foreign_keys=[reporter_chat_id], back_populates='sent_reports')
    reported_user = relationship('User', foreign_keys=[reported_chat_id], back_populates='received_reports')

class Group(Base):
    __tablename__ = 'groups'
    
    # Based on your INSERT query in register_group function
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200))
    description = Column(Text)
    photo = Column(String(500))  # Telegram file_id
    invite_link = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)

# Create engine and session
# DATABASE_URL = "postgresql://username:password@localhost/dbname"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def create_tables():
    """Create all tables in the database"""
    Base.metadata.create_all(bind=engine)
