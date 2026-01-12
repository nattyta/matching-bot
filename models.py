from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, ForeignKey, inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    chat_id = Column(Integer, primary_key=True)
    username = Column(String(100))
    name = Column(String(100))
    age = Column(Integer)
    gender = Column(String(1))  # 'M' or 'F'
    location = Column(String(200))  # THIS WAS MISSING!
    photo = Column(String(500))
    interests = Column(Text)
    looking_for = Column(String(10))  # '1' for Dating, '2' for Friends
    created_at = Column(DateTime, default=datetime.utcnow)

class Like(Base):
    __tablename__ = 'likes'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    liker_chat_id = Column(Integer)
    liked_chat_id = Column(Integer)
    note = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)

class BannedUser(Base):
    __tablename__ = 'banned_users'
    
    user_id = Column(Integer, primary_key=True)

class Report(Base):
    __tablename__ = 'reports'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    reporter_chat_id = Column(Integer)
    reported_chat_id = Column(Integer)
    violation = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)

class Group(Base):
    __tablename__ = 'groups'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200))
    description = Column(Text)
    photo = Column(String(500))
    invite_link = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(Integer)

# Database setup
engine = None
SessionLocal = None

def init_database(database_url):
    """Initialize database - will add missing columns"""
    global engine, SessionLocal
    
    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        
        print("🔄 Checking database schema...")
        
        # Create inspector to check existing columns
        inspector = inspect(engine)
        
        # Check if users table exists
        if inspector.has_table('users'):
            print("✅ Users table exists")
            
            # Get existing columns
            existing_columns = [col['name'] for col in inspector.get_columns('users')]
            print(f"📊 Existing columns: {existing_columns}")
            
            # Check for missing columns
            required_columns = ['chat_id', 'username', 'name', 'age', 'gender', 'location', 
                              'photo', 'interests', 'looking_for', 'created_at']
            
            missing_columns = [col for col in required_columns if col not in existing_columns]
            
            if missing_columns:
                print(f"⚠️ Missing columns: {missing_columns}")
                print("🔄 Adding missing columns...")
                
                # Create all tables from scratch (will add missing columns)
                Base.metadata.create_all(bind=engine)
                print("✅ Added missing columns")
            else:
                print("✅ All columns exist")
        else:
            print("🔄 Creating all tables...")
            Base.metadata.create_all(bind=engine)
            print("✅ Created all tables")
        
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        print("✅ Database initialized successfully")
        return True
        
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
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
