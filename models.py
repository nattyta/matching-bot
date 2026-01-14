from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, BigInteger, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import logging
import re

logger = logging.getLogger(__name__)

Base = declarative_base()

# Define the complete schema we want - using BigInteger for chat IDs
class User(Base):
    __tablename__ = 'users'
    
    chat_id = Column(BigInteger, primary_key=True)  # Changed from Integer to BigInteger
    username = Column(String(100), nullable=True)
    name = Column(String(100), nullable=True)
    age = Column(Integer, nullable=True)
    gender = Column(String(1), nullable=True)
    location = Column(String(200), nullable=True)
    photo = Column(String(500), nullable=True)
    interests = Column(Text, nullable=True)
    looking_for = Column(String(10), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Like(Base):
    __tablename__ = 'likes'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    liker_chat_id = Column(BigInteger)  # Changed from Integer to BigInteger
    liked_chat_id = Column(BigInteger)  # Changed from Integer to BigInteger
    note = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

class BannedUser(Base):
    __tablename__ = 'banned_users'
    
    user_id = Column(BigInteger, primary_key=True)  # Changed from Integer to BigInteger

class Report(Base):
    __tablename__ = 'reports'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    reporter_chat_id = Column(BigInteger)  # Changed from Integer to BigInteger
    reported_chat_id = Column(BigInteger)  # Changed from Integer to BigInteger
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
    created_by = Column(BigInteger, nullable=True)  # Changed from Integer to BigInteger

# Database setup
engine = None
SessionLocal = None

def fix_database_url(database_url):
    """Fix Render database URLs that have incomplete hostnames"""
    if not database_url:
        return database_url
    
    # Log original (with password hidden)
    safe_original = re.sub(r':([^@]+)@', ':*****@', database_url)
    logger.info(f"Original DATABASE_URL: {safe_original}")
    
    # Check if hostname is missing the .render.com domain
    # Pattern: @dpg-xxxxx-xxxxxx (without .render.com)
    pattern = r'(@dpg-[a-zA-Z0-9]+)-([a-zA-Z0-9]+)/'
    match = re.search(pattern, database_url)
    
    if match and '.render.com' not in database_url:
        # Extract the parts
        full_match = match.group(0)
        first_part = match.group(1)  # @dpg-xxxxx
        second_part = match.group(2)  # xxxxxx
        
        # Construct the full hostname
        fixed_hostname = f"{first_part}-{second_part}.oregon-postgres.render.com"
        
        # Replace in the URL
        fixed_url = database_url.replace(f"{first_part}-{second_part}/", f"{fixed_hostname}/")
        
        # Add port if not present
        if ':5432' not in fixed_url and '.render.com/' in fixed_url:
            fixed_url = fixed_url.replace('.render.com/', '.render.com:5432/')
        
        safe_fixed = re.sub(r':([^@]+)@', ':*****@', fixed_url)
        logger.info(f"Fixed hostname from '{match.group(0)[1:-1]}' to '{fixed_hostname}'")
        logger.info(f"Final DATABASE_URL: {safe_fixed}")
        return fixed_url
    
    return database_url

def check_and_fix_column_type(engine, table_name, column_name, expected_type):
    """Check and fix column type if needed"""
    try:
        with engine.connect() as conn:
            # Check current column type
            result = conn.execute(text(f"""
                SELECT data_type, character_maximum_length 
                FROM information_schema.columns 
                WHERE table_name = '{table_name}' AND column_name = '{column_name}'
            """))
            
            column_info = result.fetchone()
            
            if column_info:
                current_type = column_info[0]
                max_length = column_info[1]
                
                # Normalize type names for comparison
                type_mapping = {
                    'integer': 'INTEGER',
                    'bigint': 'BIGINT',
                    'character varying': 'VARCHAR',
                    'text': 'TEXT',
                    'timestamp without time zone': 'TIMESTAMP'
                }
                
                current_type_normalized = type_mapping.get(current_type, current_type)
                
                # Check if type needs to be changed
                if current_type_normalized.upper() != expected_type.upper():
                    logger.warning(f"⚠️ Changing column '{column_name}' in table '{table_name}' from {current_type} to {expected_type}")
                    
                    # Build ALTER TABLE statement
                    if expected_type == 'BIGINT':
                        sql = f"ALTER TABLE {table_name} ALTER COLUMN {column_name} TYPE BIGINT"
                    elif expected_type == 'INTEGER':
                        sql = f"ALTER TABLE {table_name} ALTER COLUMN {column_name} TYPE INTEGER"
                    elif expected_type.startswith('VARCHAR'):
                        sql = f"ALTER TABLE {table_name} ALTER COLUMN {column_name} TYPE {expected_type}"
                    elif expected_type == 'TEXT':
                        sql = f"ALTER TABLE {table_name} ALTER COLUMN {column_name} TYPE TEXT"
                    elif expected_type == 'TIMESTAMP':
                        sql = f"ALTER TABLE {table_name} ALTER COLUMN {column_name} TYPE TIMESTAMP"
                    else:
                        sql = f"ALTER TABLE {table_name} ALTER COLUMN {column_name} TYPE {expected_type}"
                    
                    conn.execute(text(sql))
                    conn.commit()
                    logger.info(f"✅ Changed column '{column_name}' in '{table_name}' to {expected_type}")
                else:
                    logger.debug(f"Column '{column_name}' in '{table_name}' already has correct type: {expected_type}")
            else:
                logger.warning(f"Column '{column_name}' not found in table '{table_name}'")
                
    except Exception as e:
        logger.error(f"❌ Failed to check/fix column '{column_name}' in '{table_name}': {e}")

def add_missing_column(engine, table_name, column_name, column_type):
    """Add a missing column to a table"""
    try:
        with engine.connect() as conn:
            # Check if column exists
            result = conn.execute(text(f"""
                SELECT COUNT(*) 
                FROM information_schema.columns 
                WHERE table_name = '{table_name}' AND column_name = '{column_name}'
            """))
            
            if result.scalar() == 0:
                logger.warning(f"⚠️ Adding missing column '{column_name}' to table '{table_name}'")
                
                # Build ADD COLUMN statement
                if column_type == 'BIGINT':
                    sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} BIGINT"
                elif column_type == 'INTEGER':
                    sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} INTEGER"
                elif column_type.startswith('VARCHAR'):
                    sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
                elif column_type == 'TEXT':
                    sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} TEXT"
                elif column_type == 'TIMESTAMP':
                    sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                else:
                    sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
                
                conn.execute(text(sql))
                conn.commit()
                logger.info(f"✅ Added column '{column_name}' to table '{table_name}'")
            else:
                logger.debug(f"Column '{column_name}' already exists in table '{table_name}'")
                
    except Exception as e:
        logger.error(f"❌ Failed to add column '{column_name}' to '{table_name}': {e}")

def init_database(database_url):
    """Initialize database - checks and creates missing tables/columns, fixes column types"""
    global engine, SessionLocal
    
    try:
        logger.info("🔧 Initializing database...")
        
        if not database_url:
            logger.error("❌ DATABASE_URL is empty")
            return False
        
        # Fix the database URL first
        database_url = fix_database_url(database_url)
        
        # Create engine
        engine = create_engine(database_url)
        
        # Test connection
        logger.info("Testing connection...")
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            logger.info(f"✅ Connection test successful")
        
        # Create all tables (SQLAlchemy will skip existing ones)
        logger.info("Creating tables if they don't exist...")
        Base.metadata.create_all(bind=engine)
        logger.info("✅ Tables created/checked")
        
        # First, check and fix column types for existing columns
        logger.info("Checking and fixing column types...")
        
        # Define the correct schema for all columns
        table_schemas = {
            'users': [
                {'name': 'chat_id', 'type': 'BIGINT'},
                {'name': 'username', 'type': 'VARCHAR(100)'},
                {'name': 'name', 'type': 'VARCHAR(100)'},
                {'name': 'age', 'type': 'INTEGER'},
                {'name': 'gender', 'type': 'VARCHAR(1)'},
                {'name': 'location', 'type': 'VARCHAR(200)'},
                {'name': 'photo', 'type': 'VARCHAR(500)'},
                {'name': 'interests', 'type': 'TEXT'},
                {'name': 'looking_for', 'type': 'VARCHAR(10)'},
                {'name': 'created_at', 'type': 'TIMESTAMP'}
            ],
            'likes': [
                {'name': 'id', 'type': 'INTEGER'},
                {'name': 'liker_chat_id', 'type': 'BIGINT'},
                {'name': 'liked_chat_id', 'type': 'BIGINT'},
                {'name': 'note', 'type': 'TEXT'},
                {'name': 'timestamp', 'type': 'TIMESTAMP'}
            ],
            'banned_users': [
                {'name': 'user_id', 'type': 'BIGINT'}
            ],
            'reports': [
                {'name': 'id', 'type': 'INTEGER'},
                {'name': 'reporter_chat_id', 'type': 'BIGINT'},
                {'name': 'reported_chat_id', 'type': 'BIGINT'},
                {'name': 'violation', 'type': 'VARCHAR(50)'},
                {'name': 'created_at', 'type': 'TIMESTAMP'}
            ],
            'groups': [
                {'name': 'id', 'type': 'INTEGER'},
                {'name': 'name', 'type': 'VARCHAR(200)'},
                {'name': 'description', 'type': 'TEXT'},
                {'name': 'photo', 'type': 'VARCHAR(500)'},
                {'name': 'invite_link', 'type': 'VARCHAR(500)'},
                {'name': 'created_at', 'type': 'TIMESTAMP'},
                {'name': 'created_by', 'type': 'BIGINT'}
            ]
        }
        
        # Check each table
        inspector = inspect(engine)
        for table_name, columns in table_schemas.items():
            if table_name in inspector.get_table_names():
                logger.info(f"Checking table '{table_name}'...")
                
                # First, ensure all columns exist
                for column_spec in columns:
                    add_missing_column(engine, table_name, column_spec['name'], column_spec['type'])
                
                # Then, fix column types if needed
                for column_spec in columns:
                    check_and_fix_column_type(engine, table_name, column_spec['name'], column_spec['type'])
        
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        logger.info("✅ Database initialized and fixed successfully")
        return True
        
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

def get_db():
    """Get database session"""
    if SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_database first.")
    
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
