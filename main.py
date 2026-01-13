import sys
import random
import json
import math
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict
import hashlib
import time
from datetime import datetime, timedelta
from telebot import TeleBot, types
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
import logging
from logging.handlers import RotatingFileHandler
import threading
import os
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
import keepalive
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, not_, func, desc

# Import models and database functions
from models import get_db, User, Like, Report, BannedUser, Group, RandomChatQueue, UserState, SeenProfile, init_database, cleanup_old_queue_entries

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler('bot.log', maxBytes=10485760, backupCount=5),  # 10MB per file
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

keepalive.keep_alive()

# Load environment variables
load_dotenv()

# Get API Key & DB URL from .env
API_KEY = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
MAX_DISTANCE_KM = int(os.getenv("MAX_DISTANCE_KM", "100"))
MIN_INTEREST_MATCH = int(os.getenv("MIN_INTEREST_MATCH", "1"))
CACHE_TIMEOUT = int(os.getenv("CACHE_TIMEOUT", "300"))

if not DATABASE_URL:
    raise ValueError("DATABASE_URL not found in environment variables")

# Initialize database
init_database(DATABASE_URL)
logger.info("Database initialized successfully")

bot = TeleBot(API_KEY, parse_mode="HTML")

# Caching system
class Cache:
    def __init__(self):
        self.cache = {}
        self.timestamps = {}
        
    def get(self, key):
        if key in self.cache and time.time() - self.timestamps.get(key, 0) < CACHE_TIMEOUT:
            return self.cache[key]
        return None
    
    def set(self, key, value):
        self.cache[key] = value
        self.timestamps[key] = time.time()
    
    def delete(self, key):
        self.cache.pop(key, None)
        self.timestamps.pop(key, None)
    
    def clear_old(self):
        current_time = time.time()
        old_keys = [k for k, ts in self.timestamps.items() 
                   if current_time - ts > CACHE_TIMEOUT]
        for key in old_keys:
            self.delete(key)

cache = Cache()

# In-memory state (minimal, most state in database)
active_chats = {}  # chat_id -> partner_chat_id
user_sessions = {}  # chat_id -> session_data

# Tips system
tips = [
    "Do you know you can join or create a community about whatever you like? Just use the command /community!",
    "Do you know you can have a random chat with someone? Just go to the command /random!",
    "Update your interests regularly to get better matches!",
    "Be respectful and follow community guidelines when chatting with others."
]

class MatchingEngine:
    """Improved matching engine with better algorithms"""
    
    @staticmethod
    def parse_location(location_str: str) -> Tuple[Optional[float], Optional[float], str]:
        """Parse location string to coordinates"""
        try:
            # Try parsing as coordinates first
            if ',' in location_str:
                parts = location_str.split(',')
                if len(parts) == 2:
                    lat = float(parts[0].strip())
                    lon = float(parts[1].strip())
                    if -90 <= lat <= 90 and -180 <= lon <= 180:
                        return lat, lon, location_str
            
            # Try geocoding for text locations
            geolocator = Nominatim(user_agent="match_bot", timeout=10)
            location = geolocator.geocode(location_str, exactly_one=True)
            if location:
                return location.latitude, location.longitude, location.address
            
            return None, None, location_str
        except (ValueError, GeocoderTimedOut):
            return None, None, location_str
    
    @staticmethod
    def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance between two points in km"""
        try:
            return geodesic((lat1, lon1), (lat2, lon2)).kilometers
        except:
            return float('inf')
    
    @staticmethod
    def interest_similarity(interests1: str, interests2: str) -> float:
        """Calculate interest similarity with weights"""
        if not interests1 or not interests2:
            return 0.0
        
        # Normalize interests
        interests_list1 = [i.strip().lower() for i in interests1.split(',')]
        interests_list2 = [i.strip().lower() for i in interests2.split(',')]
        
        if not interests_list1 or not interests_list2:
            return 0.0
        
        # Exact matches
        exact_matches = len(set(interests_list1) & set(interests_list2))
        
        # Calculate Jaccard similarity
        union_size = len(set(interests_list1) | set(interests_list2))
        if union_size == 0:
            return 0.0
        
        similarity = exact_matches / union_size
        
        # Boost for having more interests in common
        interest_boost = min(0.2, exact_matches * 0.05)
        
        return min(1.0, similarity + interest_boost)
    
    @staticmethod
    def calculate_match_score(user1: dict, user2: dict) -> float:
        """Calculate comprehensive match score"""
        score = 0.0
        
        # Age compatibility (prefer similar age)
        age_diff = abs(user1['age'] - user2['age'])
        if age_diff <= 2:
            score += 0.3
        elif age_diff <= 5:
            score += 0.2
        elif age_diff <= 10:
            score += 0.1
        
        # Interest similarity
        interest_score = MatchingEngine.interest_similarity(
            user1['interests'], user2['interests']
        )
        score += interest_score * 0.4
        
        # Location proximity
        if user1.get('location_lat') and user1.get('location_lon') and \
           user2.get('location_lat') and user2.get('location_lon'):
            distance = MatchingEngine.calculate_distance(
                user1['location_lat'], user1['location_lon'],
                user2['location_lat'], user2['location_lon']
            )
            if distance <= 10:
                score += 0.2
            elif distance <= 50:
                score += 0.1
            elif distance <= 100:
                score += 0.05
        
        # Activity bonus (both recently active)
        now = datetime.utcnow()
        user1_active = (now - user1.get('last_active', now)).total_seconds() < 86400  # 1 day
        user2_active = (now - user2.get('last_active', now)).total_seconds() < 86400
        
        if user1_active and user2_active:
            score += 0.1
        
        return min(1.0, score)

class UserManager:
    """Manages user data and operations"""
    
    @staticmethod
    def get_user_info(chat_id: int) -> Optional[Dict]:
        """Get user info from database with caching"""
        cache_key = f"user_{chat_id}"
        cached = cache.get(cache_key)
        if cached:
            return cached
        
        try:
            db: Session = next(get_db())
            user = db.query(User).filter(User.chat_id == chat_id).first()
            
            if user:
                user_info = {
                    'chat_id': user.chat_id,
                    'username': user.username,
                    'name': user.name,
                    'age': user.age,
                    'gender': user.gender,
                    'location_lat': user.location_lat,
                    'location_lon': user.location_lon,
                    'location_text': user.location_text,
                    'photo': user.photo,
                    'interests': user.interests,
                    'looking_for': user.looking_for,
                    'last_active': user.last_active
                }
                cache.set(cache_key, user_info)
                return user_info
            return None
        except Exception as e:
            logger.error(f"Error getting user info for {chat_id}: {e}")
            return None
    
    @staticmethod
    def update_user_last_active(chat_id: int):
        """Update user's last active timestamp"""
        try:
            db: Session = next(get_db())
            user = db.query(User).filter(User.chat_id == chat_id).first()
            if user:
                user.last_active = datetime.utcnow()
                db.commit()
                # Clear cache
                cache.delete(f"user_{chat_id}")
        except Exception as e:
            logger.error(f"Error updating last active for {chat_id}: {e}")
    
    @staticmethod
    def get_matched_profiles(chat_id: int, limit: int = 20, offset: int = 0) -> List[Tuple[Dict, float]]:
        """Get matched profiles with pagination and filtering"""
        user_info = UserManager.get_user_info(chat_id)
        if not user_info:
            return []
        
        cache_key = f"matches_{chat_id}_{offset}_{limit}"
        cached = cache.get(cache_key)
        if cached:
            return cached
        
        try:
            db: Session = next(get_db())
            
            # Determine gender preference
            if user_info['looking_for'] == '2':  # Friends
                gender_preference = None  # Show both genders
            else:  # Dating
                gender_preference = 'F' if user_info['gender'] == 'M' else 'M'
            
            # Build query
            query = db.query(User).filter(User.chat_id != chat_id)
            
            # Apply gender filter if specified
            if gender_preference:
                query = query.filter(User.gender == gender_preference)
            
            # Filter by looking_for
            if user_info['looking_for'] == '1':  # Dating
                # Only show users also looking for dating with opposite gender
                query = query.filter(User.looking_for == '1')
            
            # Exclude already seen profiles
            seen_subquery = db.query(SeenProfile.profile_chat_id).filter(
                SeenProfile.viewer_chat_id == chat_id
            )
            query = query.filter(not_(User.chat_id.in_(seen_subquery)))
            
            # Exclude banned users
            banned_subquery = db.query(BannedUser.user_id)
            query = query.filter(not_(User.chat_id.in_(banned_subquery)))
            
            # Apply distance filter if coordinates available
            if user_info.get('location_lat') and user_info.get('location_lon'):
                # This is a simplified filter - in production you'd use PostGIS
                query = query.filter(
                    User.location_lat.isnot(None),
                    User.location_lon.isnot(None)
                )
            
            # Get total count for pagination
            total_count = query.count()
            
            # Apply pagination
            query = query.offset(offset).limit(limit)
            
            # Execute query
            users = query.all()
            
            # Calculate match scores
            matched_profiles = []
            for user in users:
                profile_data = {
                    'chat_id': user.chat_id,
                    'name': user.name,
                    'age': user.age,
                    'gender': user.gender,
                    'location_text': user.location_text,
                    'photo': user.photo,
                    'interests': user.interests,
                    'looking_for': user.looking_for
                }
                
                match_score = MatchingEngine.calculate_match_score(user_info, {
                    'age': user.age,
                    'interests': user.interests,
                    'location_lat': user.location_lat,
                    'location_lon': user.location_lon,
                    'last_active': user.last_active
                })
                
                # Filter by minimum match score
                if match_score >= 0.2:  # Minimum 20% match
                    matched_profiles.append((profile_data, match_score))
            
            # Sort by match score (highest first)
            matched_profiles.sort(key=lambda x: x[1], reverse=True)
            
            cache.set(cache_key, matched_profiles)
            return matched_profiles
            
        except Exception as e:
            logger.error(f"Error getting matched profiles for {chat_id}: {e}")
            return []
    
    @staticmethod
    def mark_profile_seen(viewer_id: int, profile_id: int, liked: bool = False):
        """Mark a profile as seen by a user"""
        try:
            db: Session = next(get_db())
            
            # Check if already seen
            seen = db.query(SeenProfile).filter(
                SeenProfile.viewer_chat_id == viewer_id,
                SeenProfile.profile_chat_id == profile_id
            ).first()
            
            if not seen:
                seen = SeenProfile(
                    viewer_chat_id=viewer_id,
                    profile_chat_id=profile_id,
                    liked=liked
                )
                db.add(seen)
            else:
                seen.liked = liked
                seen.timestamp = datetime.utcnow()
            
            db.commit()
            
            # Clear cache for this user's matches
            for key in list(cache.cache.keys()):
                if key.startswith(f"matches_{viewer_id}_"):
                    cache.delete(key)
                    
        except Exception as e:
            logger.error(f"Error marking profile seen: {e}")

class SessionManager:
    """Manages user sessions and state"""
    
    @staticmethod
    def get_session(chat_id: int) -> Dict:
        """Get or create user session"""
        if chat_id not in user_sessions:
            # Try to load from database
            try:
                db: Session = next(get_db())
                state = db.query(UserState).filter(UserState.chat_id == chat_id).first()
                if state and state.state_data:
                    user_sessions[chat_id] = json.loads(state.state_data)
                else:
                    user_sessions[chat_id] = {}
            except:
                user_sessions[chat_id] = {}
        return user_sessions[chat_id]
    
    @staticmethod
    def save_session(chat_id: int):
        """Save session to database"""
        if chat_id in user_sessions:
            try:
                db: Session = next(get_db())
                state_data = json.dumps(user_sessions[chat_id])
                
                state = db.query(UserState).filter(UserState.chat_id == chat_id).first()
                if state:
                    state.state_data = state_data
                    state.last_updated = datetime.utcnow()
                else:
                    state = UserState(
                        chat_id=chat_id,
                        state_data=state_data,
                        current_state=user_sessions[chat_id].get('state', '')
                    )
                    db.add(state)
                
                db.commit()
            except Exception as e:
                logger.error(f"Error saving session for {chat_id}: {e}")
    
    @staticmethod
    def clear_session(chat_id: int):
        """Clear user session"""
        if chat_id in user_sessions:
            del user_sessions[chat_id]
        
        try:
            db: Session = next(get_db())
            db.query(UserState).filter(UserState.chat_id == chat_id).delete()
            db.commit()
        except Exception as e:
            logger.error(f"Error clearing session for {chat_id}: {e}")

# Bot Handlers
@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        chat_id = message.chat.id
        username = message.from_user.username
        
        # Update last active
        UserManager.update_user_last_active(chat_id)
        
        # Check if banned
        db: Session = next(get_db())
        banned = db.query(BannedUser).filter(BannedUser.user_id == chat_id).first()
        if banned:
            bot.send_message(chat_id, "❌ You have been banned and cannot use this bot.")
            db.close()
            return
        
        # Check if user exists
        existing_user = db.query(User).filter(User.chat_id == chat_id).first()
        db.close()
        
        if existing_user:
            bot.send_message(chat_id, 
                "👋 Welcome back! Here are your options:\n\n"
                "/my_profile - View and edit your profile\n"
                "/view_profiles - Browse profiles\n"
                "/view_likes - See who liked you\n"
                "/random - Random chat\n"
                "/community - Communities\n"
                "/help - Help and support"
            )
            return
        
        # New user - start profile setup
        session = SessionManager.get_session(chat_id)
        session['setup_step'] = 'name'
        session['username'] = username
        SessionManager.save_session(chat_id)
        
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add('Start Profile Setup')
        bot.send_message(chat_id, 
            "👋 Welcome! I'm your matchmaking bot.\n\n"
            "To get started, I'll help you create a profile so you can "
            "connect with others who share your interests.",
            reply_markup=markup
        )
        
    except Exception as e:
        logger.error(f"Error in send_welcome: {e}")
        bot.send_message(message.chat.id, "⚠️ An error occurred. Please try again.")

@bot.message_handler(func=lambda msg: msg.text == 'Start Profile Setup')
def start_profile_setup(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "Great! Let's start with your name. What's your name?")
    
    session = SessionManager.get_session(chat_id)
    session['setup_step'] = 'name'
    SessionManager.save_session(chat_id)

@bot.message_handler(func=lambda msg: True, content_types=['text'])
def handle_text(message):
    chat_id = message.chat.id
    session = SessionManager.get_session(chat_id)
    
    # Update last active
    UserManager.update_user_last_active(chat_id)
    
    # Check setup flow
    if 'setup_step' in session:
        handle_profile_setup(message, session)
        return
    
    # Handle regular messages
    if chat_id in active_chats:
        handle_chat_message(message)
    else:
        bot.send_message(chat_id, 
            "I didn't understand that. Use /help to see available commands.")

def handle_profile_setup(message, session):
    chat_id = message.chat.id
    step = session['setup_step']
    
    try:
        if step == 'name':
            session['name'] = message.text.strip()
            session['setup_step'] = 'age'
            SessionManager.save_session(chat_id)
            
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            for i in range(18, 31, 3):
                markup.add(str(i))
            markup.add("30+")
            
            bot.send_message(chat_id, "How old are you?", reply_markup=markup)
            
        elif step == 'age':
            age_text = message.text.strip()
            if age_text == "30+":
                session['setup_step'] = 'age_manual'
                SessionManager.save_session(chat_id)
                bot.send_message(chat_id, "Please enter your age (13-120):")
            elif age_text.isdigit():
                age = int(age_text)
                if 13 <= age <= 120:
                    session['age'] = age
                    session['setup_step'] = 'gender'
                    SessionManager.save_session(chat_id)
                    
                    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
                    markup.add("Male 👨", "Female 👩")
                    bot.send_message(chat_id, "What's your gender?", reply_markup=markup)
                else:
                    bot.send_message(chat_id, "Please enter a valid age between 13 and 120:")
            else:
                bot.send_message(chat_id, "Please enter a valid number:")
                
        elif step == 'age_manual':
            if message.text.isdigit():
                age = int(message.text)
                if 13 <= age <= 120:
                    session['age'] = age
                    session['setup_step'] = 'gender'
                    SessionManager.save_session(chat_id)
                    
                    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
                    markup.add("Male 👨", "Female 👩")
                    bot.send_message(chat_id, "What's your gender?", reply_markup=markup)
                else:
                    bot.send_message(chat_id, "Age must be between 13 and 120. Please try again:")
            else:
                bot.send_message(chat_id, "Please enter a valid number:")
                
        elif step == 'gender':
            gender_text = message.text.strip()
            if "Male" in gender_text or "👨" in gender_text:
                session['gender'] = 'M'
            elif "Female" in gender_text or "👩" in gender_text:
                session['gender'] = 'F'
            else:
                bot.send_message(chat_id, "Please select Male or Female:")
                return
            
            session['setup_step'] = 'looking_for'
            SessionManager.save_session(chat_id)
            
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            markup.add("💑 Dating (opposite gender)", "👥 Friends (any gender)")
            bot.send_message(chat_id, 
                "What are you looking for?\n\n"
                "💑 <b>Dating</b>: Match with opposite gender\n"
                "👥 <b>Friends</b>: Match with any gender",
                reply_markup=markup, parse_mode="HTML")
                
        elif step == 'looking_for':
            looking_text = message.text.strip()
            if "Dating" in looking_text or "💑" in looking_text:
                session['looking_for'] = '1'
            elif "Friends" in looking_text or "👥" in looking_text:
                session['looking_for'] = '2'
            else:
                bot.send_message(chat_id, "Please select an option:")
                return
            
            session['setup_step'] = 'location'
            SessionManager.save_session(chat_id)
            
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            location_button = types.KeyboardButton("📍 Share Location", request_location=True)
            markup.add(location_button)
            markup.add("Skip location")
            
            bot.send_message(chat_id,
                "📍 <b>Location</b> (optional):\n\n"
                "Sharing your location helps find matches nearby. "
                "You can share your location or type it (e.g., 'New York').",
                reply_markup=markup, parse_mode="HTML")
                
        elif step == 'location':
            location_text = message.text
            if location_text == "Skip location":
                session['location_text'] = "Location not shared"
                session['location_lat'] = None
                session['location_lon'] = None
            else:
                session['location_text'] = location_text
                # Parse location later when needed
                session['location_lat'] = None
                session['location_lon'] = None
            
            session['setup_step'] = 'photo'
            SessionManager.save_session(chat_id)
            
            bot.send_message(chat_id,
                "📸 <b>Profile Photo</b>:\n\n"
                "Please send a photo for your profile. "
                "This helps others recognize you!",
                parse_mode="HTML")
                
        elif step == 'photo':
            bot.send_message(chat_id, 
                "Please send a photo using the paperclip 📎 button.")
                
        elif step == 'interests':
            interests = message.text.strip()
            if len(interests) < 2:
                bot.send_message(chat_id, 
                    "Please enter at least one interest (e.g., 'music, movies, hiking'):")
                return
            
            session['interests'] = interests
            session['setup_step'] = 'complete'
            SessionManager.save_session(chat_id)
            
            # Complete profile setup
            complete_profile_setup(chat_id, session)
            
    except Exception as e:
        logger.error(f"Error in profile setup: {e}")
        bot.send_message(chat_id, "⚠️ An error occurred. Please try again.")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    chat_id = message.chat.id
    session = SessionManager.get_session(chat_id)
    
    if 'setup_step' in session and session['setup_step'] == 'photo':
        # Save photo file_id
        session['photo'] = message.photo[-1].file_id
        session['setup_step'] = 'interests'
        SessionManager.save_session(chat_id)
        
        bot.send_message(chat_id,
            "🎯 <b>Interests</b>:\n\n"
            "What are your interests? (e.g., 'music, movies, hiking, photography')\n"
            "Separate them with commas.",
            parse_mode="HTML")
    else:
        # Regular photo message in chat
        if chat_id in active_chats:
            partner_id = active_chats[chat_id]
            bot.send_photo(partner_id, message.photo[-1].file_id)

@bot.message_handler(content_types=['location'])
def handle_location(message):
    chat_id = message.chat.id
    session = SessionManager.get_session(chat_id)
    
    if 'setup_step' in session and session['setup_step'] == 'location':
        lat = message.location.latitude
        lon = message.location.longitude
        
        # Get location name
        try:
            geolocator = Nominatim(user_agent="match_bot", timeout=5)
            location = geolocator.reverse((lat, lon), exactly_one=True)
            location_text = location.address if location else f"{lat}, {lon}"
        except:
            location_text = f"{lat:.4f}, {lon:.4f}"
        
        session['location_text'] = location_text
        session['location_lat'] = lat
        session['location_lon'] = lon
        session['setup_step'] = 'photo'
        SessionManager.save_session(chat_id)
        
        bot.send_message(chat_id,
            "📍 Location saved!\n\n"
            f"<i>{location_text}</i>\n\n"
            "Now, please send a photo for your profile.",
            parse_mode="HTML")

def complete_profile_setup(chat_id, session):
    """Complete profile setup and save to database"""
    try:
        db: Session = next(get_db())
        
        # Parse location if text
        lat, lon = session.get('location_lat'), session.get('location_lon')
        location_text = session.get('location_text', '')
        
        if not lat and not lon and location_text and location_text != "Location not shared":
            lat, lon, parsed_text = MatchingEngine.parse_location(location_text)
            if lat and lon:
                session['location_lat'] = lat
                session['location_lon'] = lon
                if parsed_text != location_text:
                    session['location_text'] = parsed_text
        
        # Create user
        user = User(
            chat_id=chat_id,
            username=session.get('username'),
            name=session['name'],
            age=session['age'],
            gender=session['gender'],
            location_lat=session.get('location_lat'),
            location_lon=session.get('location_lon'),
            location_text=session.get('location_text', ''),
            photo=session['photo'],
            interests=session['interests'],
            looking_for=session['looking_for'],
            last_active=datetime.utcnow()
        )
        
        db.add(user)
        db.commit()
        
        # Clear session
        SessionManager.clear_session(chat_id)
        
        # Send welcome message with profile
        profile_summary = (
            f"✅ <b>Profile Complete!</b>\n\n"
            f"👤 <b>Name:</b> {user.name}\n"
            f"🎂 <b>Age:</b> {user.age}\n"
            f"⚧️ <b>Gender:</b> {'Male' if user.gender == 'M' else 'Female'}\n"
            f"📍 <b>Location:</b> {user.location_text or 'Not specified'}\n"
            f"🎯 <b>Looking for:</b> {'Dating 💑' if user.looking_for == '1' else 'Friends 👥'}\n"
            f"❤️ <b>Interests:</b> {user.interests}\n\n"
            f"<i>Use /my_profile to edit your profile</i>"
        )
        
        bot.send_photo(chat_id, user.photo, 
                      caption=profile_summary,
                      parse_mode="HTML")
        
        # Send help message
        bot.send_message(chat_id,
            "🚀 <b>Ready to start?</b>\n\n"
            "Here are your options:\n\n"
            "👁️ <b>/view_profiles</b> - Browse and match with others\n"
            "💬 <b>/random</b> - Start a random chat\n"
            "❤️ <b>/view_likes</b> - See who liked you\n"
            "👥 <b>/community</b> - Join or create communities\n"
            "ℹ️ <b>/help</b> - Help and support\n\n"
            "<i>Tip: Update your interests regularly for better matches!</i>",
            parse_mode="HTML")
        
        db.close()
        
    except Exception as e:
        logger.error(f"Error completing profile setup: {e}")
        bot.send_message(chat_id, "⚠️ Error saving profile. Please try /start again.")

@bot.message_handler(commands=['my_profile'])
def my_profile(message):
    chat_id = message.chat.id
    UserManager.update_user_last_active(chat_id)
    
    user_info = UserManager.get_user_info(chat_id)
    if not user_info:
        bot.send_message(chat_id, "You don't have a profile yet. Use /start to create one.")
        return
    
    profile_summary = (
        f"👤 <b>Your Profile</b>\n\n"
        f"📛 <b>Name:</b> {user_info['name']}\n"
        f"🎂 <b>Age:</b> {user_info['age']}\n"
        f"⚧️ <b>Gender:</b> {'Male' if user_info['gender'] == 'M' else 'Female'}\n"
        f"📍 <b>Location:</b> {user_info['location_text'] or 'Not specified'}\n"
        f"🎯 <b>Looking for:</b> {'Dating 💑' if user_info['looking_for'] == '1' else 'Friends 👥'}\n"
        f"❤️ <b>Interests:</b> {user_info['interests']}\n\n"
        f"<i>Last active: {user_info['last_active'].strftime('%Y-%m-%d %H:%M') if user_info.get('last_active') else 'Recently'}</i>"
    )
    
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("✏️ Edit Profile", callback_data="edit_profile"),
        InlineKeyboardButton("📊 View Stats", callback_data="view_stats")
    )
    
    if user_info.get('photo'):
        bot.send_photo(chat_id, user_info['photo'], 
                      caption=profile_summary,
                      reply_markup=markup,
                      parse_mode="HTML")
    else:
        bot.send_message(chat_id, profile_summary, 
                        reply_markup=markup,
                        parse_mode="HTML")

@bot.message_handler(commands=['view_profiles'])
def view_profiles(message):
    chat_id = message.chat.id
    UserManager.update_user_last_active(chat_id)
    
    user_info = UserManager.get_user_info(chat_id)
    if not user_info:
        bot.send_message(chat_id, "You need to create a profile first. Use /start")
        return
    
    # Get matches
    matches = UserManager.get_matched_profiles(chat_id, limit=10)
    
    if not matches:
        bot.send_message(chat_id,
            "😔 <b>No matches found right now.</b>\n\n"
            "Try updating your interests or check back later. "
            "You can also try /random for instant chatting.",
            parse_mode="HTML")
        return
    
    # Store matches in session
    session = SessionManager.get_session(chat_id)
    session['current_matches'] = matches
    session['match_index'] = 0
    SessionManager.save_session(chat_id)
    
    # Show first profile
    show_next_match(chat_id)

def show_next_match(chat_id):
    """Show the next match from session"""
    session = SessionManager.get_session(chat_id)
    matches = session.get('current_matches', [])
    index = session.get('match_index', 0)
    
    if index >= len(matches):
        bot.send_message(chat_id,
            "🎉 <b>You've seen all available matches!</b>\n\n"
            "Check back later for new profiles, "
            "or try /random for instant chatting.",
            parse_mode="HTML")
        return
    
    profile, match_score = matches[index]
    
    # Mark as seen
    UserManager.mark_profile_seen(chat_id, profile['chat_id'])
    
    # Prepare profile info
    match_percentage = int(match_score * 100)
    profile_summary = (
        f"👤 <b>{profile['name']}, {profile['age']}</b>\n"
        f"⚧️ <b>Gender:</b> {'Male' if profile['gender'] == 'M' else 'Female'}\n"
        f"📍 <b>Location:</b> {profile.get('location_text', 'Not specified')}\n"
        f"❤️ <b>Interests:</b> {profile['interests'][:100]}{'...' if len(profile['interests']) > 100 else ''}\n\n"
        f"🎯 <b>Match score:</b> {match_percentage}%"
    )
    
    # Create buttons
    markup = InlineKeyboardMarkup(row_width=3)
    markup.add(
        InlineKeyboardButton("👍 Like", callback_data=f"like_{profile['chat_id']}"),
        InlineKeyboardButton("👎 Skip", callback_data=f"skip_{profile['chat_id']}"),
        InlineKeyboardButton("💬 Chat", callback_data=f"chat_{profile['chat_id']}")
    )
    
    # Navigation buttons
    nav_buttons = []
    if index > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Previous", callback_data="prev_match"))
    nav_buttons.append(InlineKeyboardButton(f"{index + 1}/{len(matches)}", callback_data="count"))
    if index < len(matches) - 1:
        nav_buttons.append(InlineKeyboardButton("Next ▶️", callback_data="next_match"))
    
    if nav_buttons:
        markup.row(*nav_buttons)
    
    # Send profile
    try:
        bot.send_photo(chat_id, profile['photo'],
                      caption=profile_summary,
                      reply_markup=markup,
                      parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error sending profile photo: {e}")
        bot.send_message(chat_id, profile_summary,
                        reply_markup=markup,
                        parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    data = call.data
    
    UserManager.update_user_last_active(chat_id)
    
    try:
        if data.startswith("like_"):
            target_id = int(data.split("_")[1])
            handle_like(chat_id, target_id)
            bot.answer_callback_query(call.id, "👍 Liked!")
            
        elif data.startswith("skip_"):
            target_id = int(data.split("_")[1])
            UserManager.mark_profile_seen(chat_id, target_id, liked=False)
            bot.answer_callback_query(call.id, "Skipped")
            
        elif data.startswith("chat_"):
            target_id = int(data.split("_")[1])
            # Start chat implementation would go here
            bot.answer_callback_query(call.id, "Chat feature coming soon!")
            
        elif data == "prev_match":
            session = SessionManager.get_session(chat_id)
            session['match_index'] = max(0, session.get('match_index', 1) - 1)
            SessionManager.save_session(chat_id)
            
            bot.delete_message(chat_id, call.message.message_id)
            show_next_match(chat_id)
            
        elif data == "next_match":
            session = SessionManager.get_session(chat_id)
            matches = session.get('current_matches', [])
            current_index = session.get('match_index', 0)
            
            if current_index < len(matches) - 1:
                session['match_index'] = current_index + 1
                SessionManager.save_session(chat_id)
                
                bot.delete_message(chat_id, call.message.message_id)
                show_next_match(chat_id)
            else:
                bot.answer_callback_query(call.id, "No more matches")
                
        elif data == "edit_profile":
            bot.answer_callback_query(call.id)
            show_edit_options(chat_id)
            
        elif data.startswith("violation_"):
            parts = data.split("_")
            if len(parts) == 3:
                violation_type = parts[1]
                reported_id = int(parts[2])
                handle_report(chat_id, reported_id, violation_type)
                bot.answer_callback_query(call.id, "Report submitted")
                
    except Exception as e:
        logger.error(f"Error in callback handler: {e}")
        bot.answer_callback_query(call.id, "⚠️ Error occurred")

def handle_like(liker_id, liked_id):
    """Handle user liking another profile"""
    try:
        db: Session = next(get_db())
        
        # Check if like already exists
        existing_like = db.query(Like).filter(
            Like.liker_chat_id == liker_id,
            Like.liked_chat_id == liked_id
        ).first()
        
        if not existing_like:
            # Create new like
            like = Like(
                liker_chat_id=liker_id,
                liked_chat_id=liked_id,
                timestamp=datetime.utcnow()
            )
            db.add(like)
            
            # Mark as seen and liked
            UserManager.mark_profile_seen(liker_id, liked_id, liked=True)
            
            # Check for mutual like
            mutual_like = db.query(Like).filter(
                Like.liker_chat_id == liked_id,
                Like.liked_chat_id == liker_id
            ).first()
            
            if mutual_like:
                # Notify both users
                liker_info = UserManager.get_user_info(liker_id)
                liked_info = UserManager.get_user_info(liked_id)
                
                if liker_info and liked_info:
                    bot.send_message(liker_id,
                        f"💞 <b>It's a match!</b>\n\n"
                        f"You and {liked_info['name']} liked each other!\n"
                        f"Say hello! 👋",
                        parse_mode="HTML")
                    
                    bot.send_message(liked_id,
                        f"💞 <b>It's a match!</b>\n\n"
                        f"You and {liker_info['name']} liked each other!\n"
                        f"Say hello! 👋",
                        parse_mode="HTML")
        
        db.commit()
        db.close()
        
        # Move to next match
        session = SessionManager.get_session(liker_id)
        if 'current_matches' in session:
            matches = session['current_matches']
            current_index = session.get('match_index', 0)
            
            if current_index < len(matches) - 1:
                session['match_index'] = current_index + 1
                SessionManager.save_session(liker_id)
                
                # Show next match
                show_next_match(liker_id)
        
    except Exception as e:
        logger.error(f"Error in handle_like: {e}")

@bot.message_handler(commands=['view_likes'])
def view_likes(message):
    chat_id = message.chat.id
    UserManager.update_user_last_active(chat_id)
    
    try:
        db: Session = next(get_db())
        
        # Get likes for this user
        likes = db.query(Like).filter(
            Like.liked_chat_id == chat_id
        ).order_by(Like.timestamp.desc()).limit(20).all()
        
        if not likes:
            bot.send_message(chat_id,
                "❤️ <b>No likes yet</b>\n\n"
                "Start browsing profiles with /view_profiles to get likes!",
                parse_mode="HTML")
            return
        
        for like in likes:
            user_info = UserManager.get_user_info(like.liker_chat_id)
            if user_info:
                like_summary = (
                    f"❤️ <b>New Like!</b>\n\n"
                    f"👤 <b>{user_info['name']}, {user_info['age']}</b>\n"
                    f"⚧️ <b>Gender:</b> {'Male' if user_info['gender'] == 'M' else 'Female'}\n"
                    f"❤️ <b>Interests:</b> {user_info['interests'][:100]}{'...' if len(user_info['interests']) > 100 else ''}\n\n"
                    f"<i>Liked on: {like.timestamp.strftime('%Y-%m-%d %H:%M')}</i>"
                )
                
                markup = InlineKeyboardMarkup()
                markup.add(
                    InlineKeyboardButton("👁️ View Profile", callback_data=f"view_{like.liker_chat_id}"),
                    InlineKeyboardButton("💬 Chat", callback_data=f"chat_{like.liker_chat_id}")
                )
                
                if user_info.get('photo'):
                    bot.send_photo(chat_id, user_info['photo'],
                                  caption=like_summary,
                                  reply_markup=markup,
                                  parse_mode="HTML")
                else:
                    bot.send_message(chat_id, like_summary,
                                    reply_markup=markup,
                                    parse_mode="HTML")
        
        db.close()
        
    except Exception as e:
        logger.error(f"Error in view_likes: {e}")
        bot.send_message(chat_id, "⚠️ Error loading likes")

def show_edit_options(chat_id):
    """Show profile edit options"""
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("✏️ Name", callback_data="edit_name"),
        InlineKeyboardButton("🎂 Age", callback_data="edit_age"),
        InlineKeyboardButton("📍 Location", callback_data="edit_location"),
        InlineKeyboardButton("📸 Photo", callback_data="edit_photo"),
        InlineKeyboardButton("❤️ Interests", callback_data="edit_interests"),
        InlineKeyboardButton("🎯 Looking For", callback_data="edit_looking_for")
    )
    
    bot.send_message(chat_id,
        "✏️ <b>Edit Profile</b>\n\n"
        "What would you like to edit?",
        reply_markup=markup,
        parse_mode="HTML")

@bot.message_handler(commands=['random'])
def random_chat(message):
    chat_id = message.chat.id
    UserManager.update_user_last_active(chat_id)
    
    # Check if already in chat
    if chat_id in active_chats:
        bot.send_message(chat_id, "You're already in a chat. Type 'End' to end it.")
        return
    
    markup = InlineKeyboardMarkup(row_width=3)
    markup.add(
        InlineKeyboardButton("👨 Male", callback_data="random_male"),
        InlineKeyboardButton("👩 Female", callback_data="random_female"),
        InlineKeyboardButton("👥 Any", callback_data="random_any")
    )
    
    bot.send_message(chat_id,
        "💬 <b>Random Chat</b>\n\n"
        "Who would you like to chat with?\n\n"
        "👨 <b>Male</b> - Chat with males\n"
        "👩 <b>Female</b> - Chat with females\n"
        "👥 <b>Any</b> - Chat with anyone\n\n"
        "<i>You'll be matched with someone looking for the same.</i>",
        reply_markup=markup,
        parse_mode="HTML")

@bot.message_handler(commands=['community'])
def community_command(message):
    chat_id = message.chat.id
    UserManager.update_user_last_active(chat_id)
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("➕ Create Community", callback_data="create_community"),
        InlineKeyboardButton("👥 Browse Communities", callback_data="browse_communities"),
        InlineKeyboardButton("⭐ My Communities", callback_data="my_communities")
    )
    
    bot.send_message(chat_id,
        "👥 <b>Communities</b>\n\n"
        "Join or create communities based on your interests!\n\n"
        "• <b>Create Community</b> - Start your own community\n"
        "• <b>Browse Communities</b> - Find communities to join\n"
        "• <b>My Communities</b> - Communities you've joined",
        reply_markup=markup,
        parse_mode="HTML")

@bot.message_handler(commands=['help'])
def help_command(message):
    chat_id = message.chat.id
    
    help_text = (
        "🤖 <b>Matchmaking Bot Help</b>\n\n"
        
        "📋 <b>Basic Commands:</b>\n"
        "/start - Create or access your profile\n"
        "/my_profile - View and edit your profile\n"
        "/view_profiles - Browse and match with others\n"
        "/view_likes - See who liked you\n"
        "/random - Start a random chat\n"
        "/community - Join or create communities\n\n"
        
        "💡 <b>Tips:</b>\n"
        "• Keep your profile updated for better matches\n"
        "• Be respectful when chatting with others\n"
        "• Report inappropriate behavior\n"
        "• Update interests regularly\n\n"
        
        "⚠️ <b>Community Guidelines:</b>\n"
        "• No harassment or hate speech\n"
        "• No spam or advertising\n"
        "• Respect others' privacy\n"
        "• Be honest in your profile\n\n"
        
        "📞 <b>Support:</b>\n"
        "For issues or feedback, contact @meh9061\n"
        "Email: natnaeltakele36@gmail.com\n"
        "Phone: +251935519061\n\n"
        
        "<i>We're here to help you connect safely!</i>"
    )
    
    bot.send_message(chat_id, help_text, parse_mode="HTML")

def handle_chat_message(message):
    """Handle messages in active chat"""
    chat_id = message.chat.id
    
    if chat_id in active_chats:
        partner_id = active_chats[chat_id]
        
        if message.text and message.text.lower() == 'end':
            # End chat
            end_random_chat(chat_id, partner_id)
        else:
            # Relay message
            try:
                if message.text:
                    bot.send_message(partner_id, message.text)
                elif message.photo:
                    bot.send_photo(partner_id, message.photo[-1].file_id)
                elif message.sticker:
                    bot.send_sticker(partner_id, message.sticker.file_id)
                elif message.voice:
                    bot.send_voice(partner_id, message.voice.file_id)
            except Exception as e:
                logger.error(f"Error relaying message: {e}")
                bot.send_message(chat_id, "⚠️ Could not send message. Partner may have left.")

def end_random_chat(user1_id, user2_id):
    """End a random chat between two users"""
    # Remove from active chats
    active_chats.pop(user1_id, None)
    active_chats.pop(user2_id, None)
    
    # Send end messages
    bot.send_message(user1_id,
        "💬 <b>Chat ended</b>\n\n"
        "The chat has ended. You can:\n"
        "• Start a new chat with /random\n"
        "• Browse profiles with /view_profiles\n"
        "• Check your likes with /view_likes",
        parse_mode="HTML")
    
    bot.send_message(user2_id,
        "💬 <b>Chat ended</b>\n\n"
        "The chat has ended. You can:\n"
        "• Start a new chat with /random\n"
        "• Browse profiles with /view_profiles\n"
        "• Check your likes with /view_likes",
        parse_mode="HTML")
    
    # Show like/dislike buttons
    markup1 = generate_like_dislike_buttons(user1_id, user2_id)
    markup2 = generate_like_dislike_buttons(user2_id, user1_id)
    
    bot.send_message(user1_id, "Did you enjoy chatting?", reply_markup=markup1)
    bot.send_message(user2_id, "Did you enjoy chatting?", reply_markup=markup2)

def generate_like_dislike_buttons(user_id, target_id):
    """Generate buttons for after-chat rating"""
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("👍 Like", callback_data=f"rate_like_{target_id}"),
        InlineKeyboardButton("👎 Dislike", callback_data=f"rate_dislike_{target_id}"),
        InlineKeyboardButton("🚩 Report", callback_data=f"report_{target_id}")
    )
    return markup

def handle_report(reporter_id, reported_id, violation_type):
    """Handle user reports"""
    try:
        db: Session = next(get_db())
        
        # Check if already reported recently
        recent_report = db.query(Report).filter(
            Report.reporter_chat_id == reporter_id,
            Report.reported_chat_id == reported_id,
            Report.created_at > datetime.utcnow() - timedelta(hours=24)
        ).first()
        
        if recent_report:
            bot.send_message(reporter_id, "You've already reported this user recently.")
            return
        
        # Create report
        report = Report(
            reporter_chat_id=reporter_id,
            reported_chat_id=reported_id,
            violation=violation_type,
            created_at=datetime.utcnow()
        )
        db.add(report)
        
        # Check report count
        report_count = db.query(Report).filter(
            Report.reported_chat_id == reported_id
        ).count()
        
        # Take action based on report count
        if report_count >= 3:
            # Send warning
            bot.send_message(reported_id,
                "⚠️ <b>Warning</b>\n\n"
                "You have received multiple reports. "
                "Please review community guidelines.",
                parse_mode="HTML")
        
        if report_count >= 5:
            # Ban user
            banned = BannedUser(
                user_id=reported_id,
                reason=f"Multiple reports ({report_count})",
                banned_at=datetime.utcnow()
            )
            db.add(banned)
            
            bot.send_message(reported_id,
                "❌ <b>Account Banned</b>\n\n"
                "Your account has been banned due to multiple violations.",
                parse_mode="HTML")
        
        db.commit()
        db.close()
        
        bot.send_message(reporter_id,
            "✅ <b>Report Submitted</b>\n\n"
            "Thank you for reporting. We'll review this user.",
            parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Error handling report: {e}")

# Background tasks
def cleanup_tasks():
    """Run periodic cleanup tasks"""
    while True:
        try:
            # Clean old cache entries
            cache.clear_old()
            
            # Clean old queue entries
            cleanup_old_queue_entries()
            
            # Remove inactive chats (30 minutes timeout)
            current_time = time.time()
            inactive_chats = []
            for chat_id in list(active_chats.keys()):
                # Check if user is still active (simplified)
                pass
            
            # Sleep for 5 minutes
            time.sleep(300)
            
        except Exception as e:
            logger.error(f"Error in cleanup tasks: {e}")
            time.sleep(60)

# Start background tasks
cleanup_thread = threading.Thread(target=cleanup_tasks, daemon=True)
cleanup_thread.start()

# Start the bot
if __name__ == '__main__':
    logger.info("Bot starting...")
    
    try:
        bot.polling(none_stop=True, interval=0, timeout=20)
    except Exception as e:
        logger.error(f"Bot polling error: {e}")
        time.sleep(5)
