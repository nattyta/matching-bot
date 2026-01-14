import random
import json
import math
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict, OrderedDict
import hashlib
import time
from datetime import datetime, timedelta
from telebot import TeleBot, types
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
import logging
import threading
import os
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
import keepalive
from sqlalchemy.orm import Session
from models import get_db, User, Like, Report, BannedUser, Group, init_database
import sqlalchemy
import re

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
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

if not DATABASE_URL:
    raise ValueError("DATABASE_URL not found in environment variables")

# Initialize database
if not init_database(DATABASE_URL):
    logger.error("Failed to initialize database. Exiting...")
    exit(1)
    
logger.info("Database initialized successfully")

bot = TeleBot(API_KEY, parse_mode="HTML")

# Thread-safe data structures
class ThreadSafeDict:
    def __init__(self):
        self._data = {}
        self._lock = threading.Lock()
    
    def get(self, key, default=None):
        with self._lock:
            return self._data.get(key, default)
    
    def set(self, key, value):
        with self._lock:
            self._data[key] = value
    
    def delete(self, key):
        with self._lock:
            if key in self._data:
                del self._data[key]
    
    def pop(self, key, default=None):
        with self._lock:
            return self._data.pop(key, default)
    
    def __contains__(self, key):
        with self._lock:
            return key in self._data

# Thread-safe data storage
user_data = ThreadSafeDict()
pending_users = []
pending_users_lock = threading.Lock()
users_interacted = set()
tip_index = {}
user_likes = {}
active_chats = {}
active_chats_lock = threading.Lock()

# Rate Limiter
class RateLimiter:
    def __init__(self, max_requests=10, period_seconds=60):
        self.requests = defaultdict(list)
        self.max_requests = max_requests
        self.period = timedelta(seconds=period_seconds)
    
    def is_allowed(self, chat_id):
        now = datetime.now()
        self.requests[chat_id] = [t for t in self.requests[chat_id] 
                                 if now - t < self.period]
        
        if len(self.requests[chat_id]) < self.max_requests:
            self.requests[chat_id].append(now)
            return True
        return False

rate_limiter = RateLimiter(max_requests=20, period_seconds=60)

# LRU Cache for user data
class UserDataCache:
    def __init__(self, max_size=1000, ttl_hours=6):
        self.cache = OrderedDict()
        self.max_size = max_size
        self.ttl = timedelta(hours=ttl_hours)
        self.lock = threading.Lock()
    
    def get(self, chat_id):
        with self.lock:
            if chat_id in self.cache:
                data, timestamp = self.cache[chat_id]
                if datetime.now() - timestamp < self.ttl:
                    # Move to end (most recently used)
                    self.cache.move_to_end(chat_id)
                    return data
                else:
                    # Expired
                    del self.cache[chat_id]
            return None
    
    def set(self, chat_id, data):
        with self.lock:
            self.cache[chat_id] = (data, datetime.now())
            if len(self.cache) > self.max_size:
                # Remove oldest item
                self.cache.popitem(last=False)
    
    def delete(self, chat_id):
        with self.lock:
            if chat_id in self.cache:
                del self.cache[chat_id]

user_cache = UserDataCache(max_size=500, ttl_hours=6)

# Global lists and dictionaries
tips = [
    "💡 Do you know you can join or create a community about whatever you like? Just use the command /community!",
    "💡 Do you know you can have a random chat with someone? Just go to the command /random!",
    "💡 Complete your profile to get better matches! Use /my_profile to check your profile quality.",
    "💡 Set your preferences with /preferences to find exactly what you're looking for!",
    "💡 Use /filter to narrow down your search to profiles that match your criteria!",
    "💡 Found someone interesting? Send them a note with the 'Send Note' button!",
    "💡 Having issues? Contact @meh9061 for help and support."
]

# Database helper functions with proper session management
def get_user_info(chat_id):
    """Get user info using SQLAlchemy with context manager"""
    try:
        with get_db() as db:
            user = db.query(User).filter(User.chat_id == chat_id).first()
            if user:
                return {
                    'chat_id': user.chat_id,
                    'name': user.name,
                    'age': user.age,
                    'gender': user.gender,
                    'location': user.location,
                    'photo': user.photo,
                    'interests': user.interests,
                    'looking_for': user.looking_for,
                    'username': user.username
                }
    except Exception as e:
        logger.error(f"Error getting user info: {e}")
    return None

def save_user_to_db(chat_id, user_data_dict):
    """Save user to database using SQLAlchemy"""
    try:
        with get_db() as db:
            # Check if user exists
            user = db.query(User).filter(User.chat_id == chat_id).first()
            
            if user:
                # Update existing user
                user.username = user_data_dict.get('username')
                user.name = user_data_dict.get('name')
                user.age = user_data_dict.get('age')
                user.gender = user_data_dict.get('gender')
                user.location = user_data_dict.get('location')
                user.photo = user_data_dict.get('photo')
                user.interests = user_data_dict.get('interests')
                user.looking_for = user_data_dict.get('looking_for')
                user.created_at = datetime.utcnow()
            else:
                # Create new user
                user = User(
                    chat_id=chat_id,
                    username=user_data_dict.get('username'),
                    name=user_data_dict.get('name'),
                    age=user_data_dict.get('age'),
                    gender=user_data_dict.get('gender'),
                    location=user_data_dict.get('location'),
                    photo=user_data_dict.get('photo'),
                    interests=user_data_dict.get('interests'),
                    looking_for=user_data_dict.get('looking_for'),
                    created_at=datetime.utcnow()
                )
                db.add(user)
            
            db.commit()
            return True
    except sqlalchemy.exc.IntegrityError as e:
        logger.error(f"Integrity error saving user {chat_id}: {e}")
        return False
    except sqlalchemy.exc.OperationalError as e:
        logger.error(f"Database connection error for user {chat_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error saving user {chat_id}: {e}")
        return False

def update_user_field(chat_id, field, value):
    """Update specific user field"""
    try:
        with get_db() as db:
            user = db.query(User).filter(User.chat_id == chat_id).first()
            if user:
                setattr(user, field, value)
                db.commit()
                return True
            return False
    except Exception as e:
        logger.error(f"Error updating user field: {e}")
        return False

def check_banned(chat_id):
    """Check if user is banned"""
    try:
        with get_db() as db:
            banned = db.query(BannedUser).filter(BannedUser.user_id == chat_id).first()
            return banned is not None
    except Exception as e:
        logger.error(f"Error checking banned: {e}")
        return False

def save_like(liker_chat_id, liked_chat_id, note=None):
    """Save like to database"""
    try:
        with get_db() as db:
            # Check if like already exists
            existing_like = db.query(Like).filter(
                Like.liker_chat_id == liker_chat_id,
                Like.liked_chat_id == liked_chat_id
            ).first()
            
            if existing_like:
                existing_like.timestamp = datetime.utcnow()
                if note:
                    existing_like.note = note
            else:
                like = Like(
                    liker_chat_id=liker_chat_id,
                    liked_chat_id=liked_chat_id,
                    timestamp=datetime.utcnow(),
                    note=note
                )
                db.add(like)
            
            db.commit()
            return True
    except Exception as e:
        logger.error(f"Error saving like: {e}")
        return False

def get_likes_for_user(chat_id, limit=5, offset=0):
    """Get likes for a user with pagination"""
    try:
        with get_db() as db:
            likes = db.query(Like).filter(
                Like.liked_chat_id == chat_id
            ).order_by(Like.timestamp.desc()).offset(offset).limit(limit).all()
            
            result = []
            for like in likes:
                user = db.query(User).filter(User.chat_id == like.liker_chat_id).first()
                if user:
                    result.append({
                        'liker_chat_id': like.liker_chat_id,
                        'note': like.note,
                        'timestamp': like.timestamp,
                        'name': user.name,
                        'age': user.age,
                        'location': user.location,
                        'interests': user.interests,
                        'photo': user.photo,
                        'username': user.username
                    })
            
            return result
    except Exception as e:
        logger.error(f"Error getting likes: {e}")
        return []

def save_report(reporter_id, reported_id, violation_type):
    """Save report to database"""
    try:
        with get_db() as db:
            report = Report(
                reporter_chat_id=reporter_id,
                reported_chat_id=reported_id,
                violation=violation_type,
                created_at=datetime.utcnow()
            )
            db.add(report)
            db.commit()
            return True
    except Exception as e:
        logger.error(f"Error saving report: {e}")
        return False

def calculate_distance(location1, location2):
    """Calculate distance between two locations"""
    try:
        if ',' in location1 and ',' in location2:
            coords_1 = tuple(map(float, location1.split(',')))
            coords_2 = tuple(map(float, location2.split(',')))
            return geodesic(coords_1, coords_2).kilometers
        return 50  # Default distance for text locations
    except ValueError:
        return float('inf')
    except Exception as e:
        logger.error(f"Error in calculate_distance: {e}")
        return float('inf')

def interest_similarity(interests1, interests2):
    """Calculate interest similarity"""
    try:
        if not interests1 or not interests2:
            return 0
        set1 = set(interests1.split(', '))
        set2 = set(interests2.split(', '))
        return len(set1 & set2)
    except Exception as e:
        logger.error(f"Error in interest_similarity: {e}")
        return 0

# Input validation and sanitization
def sanitize_text(text, max_length=500):
    """Sanitize user input text"""
    if not text:
        return ""
    # Remove excessive whitespace
    text = ' '.join(text.split())
    # Limit length
    if len(text) > max_length:
        text = text[:max_length]
    return text.strip()

def validate_location(location):
    """Validate location input"""
    if not location or len(location.strip()) < 2:
        return False, "Location is too short"
    
    # Check if it's coordinates
    if ',' in location:
        try:
            parts = location.split(',')
            if len(parts) == 2:
                lat = float(parts[0].strip())
                lon = float(parts[1].strip())
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    return True, "Valid coordinates"
        except:
            pass
    
    # Text location is also valid
    return True, "Valid text location"

def validate_interests(interests_text):
    """Validate and normalize interests"""
    if not interests_text:
        return False, "Please enter at least one interest"
    
    interests = [interest.strip() for interest in interests_text.split(',') if interest.strip()]
    
    if len(interests) < 1:
        return False, "Please enter at least one interest"
    
    # Limit to 10 interests
    if len(interests) > 10:
        interests = interests[:10]
    
    return True, interests

# Enhanced matching algorithm
def calculate_match_score(user1, user2, distance):
    """Calculate weighted match score between two users"""
    try:
        # Interest similarity (Jaccard)
        interests1 = set(user1['interests'].split(', ')) if user1.get('interests') else set()
        interests2 = set(user2['interests'].split(', ')) if user2.get('interests') else set()
        
        union = len(interests1 | interests2)
        if union == 0:
            similarity = 0
        else:
            similarity = len(interests1 & interests2) / union
        
        # Age compatibility (closer age = higher score)
        age_diff = abs(user1['age'] - user2['age'])
        age_score = 1 - (min(age_diff, 20) / 20)  # Normalize to 0-1
        
        # Distance score (closer = higher score)
        max_distance = 100  # km
        normalized_distance = min(distance / max_distance, 1.0)
        distance_score = 1 - normalized_distance
        
        # Weighted total score
        weights = {
            'similarity': 0.5,
            'age': 0.3,
            'distance': 0.2
        }
        
        total_score = (
            similarity * weights['similarity'] +
            age_score * weights['age'] +
            distance_score * weights['distance']
        )
        
        return total_score, similarity, age_score, distance_score
        
    except Exception as e:
        logger.error(f"Error calculating match score: {e}")
        return 0, 0, 0, 0

def get_matched_profiles(user_info, gender_preference, limit=20):
    """Get matched profiles with pagination and scoring"""
    try:
        with get_db() as db:
            # Base query
            query = db.query(User).filter(User.chat_id != user_info['chat_id'])
            
            # Gender filter
            if gender_preference != 'BOTH':
                query = query.filter(User.gender == gender_preference)
            
            # Age range filter (±10 years)
            age_min = user_info['age'] - 10
            age_max = user_info['age'] + 10
            query = query.filter(User.age.between(age_min, age_max))
            
            # Get limited results
            users = query.limit(limit).all()
            
            matched_profiles = []
            for user in users:
                partner_info = {
                    'chat_id': user.chat_id,
                    'name': user.name,
                    'age': user.age,
                    'gender': user.gender,
                    'location': user.location,
                    'photo': user.photo,
                    'interests': user.interests,
                    'looking_for': user.looking_for
                }
                
                # Calculate distance
                try:
                    if ',' in user_info['location'] and ',' in partner_info['location']:
                        coords_1 = tuple(map(float, user_info['location'].split(',')))
                        coords_2 = tuple(map(float, partner_info['location'].split(',')))
                        distance = geodesic(coords_1, coords_2).kilometers
                    else:
                        distance = 50  # Default for text locations
                except:
                    distance = 50
                
                # Calculate match score
                score, similarity, age_score, distance_score = calculate_match_score(
                    user_info, partner_info, distance
                )
                
                matched_profiles.append((
                    partner_info, 
                    score, 
                    distance, 
                    similarity,
                    age_score,
                    distance_score
                ))
            
            # Sort by match score (highest first)
            matched_profiles.sort(key=lambda x: x[1], reverse=True)
            return matched_profiles[:10]  # Return top 10
            
    except Exception as e:
        logger.error(f"Error in get_matched_profiles: {e}")
        return []

def get_gender_preference(user_info):
    """Get gender preference based on what user is looking for"""
    if user_info['looking_for'] == '2':
        return 'BOTH'
    else:
        return 'F' if user_info['gender'] == 'M' else 'M'

# Profile quality assessment
def get_profile_quality(profile):
    """Calculate profile completeness score"""
    score = 0
    total_possible = 100
    
    # Photo (30 points)
    if profile.get('photo'):
        score += 30
    
    # Interests (25 points)
    if profile.get('interests'):
        interests = profile['interests'].split(', ')
        interests_count = len(interests)
        score += min(interests_count * 5, 25)  # 5 points per interest, max 25
    
    # Location (20 points)
    if profile.get('location'):
        if ',' in profile['location']:  # Coordinates
            score += 20
        else:  # Text location
            score += 10
    
    # Basic info (25 points)
    if profile.get('name'): score += 10
    if profile.get('age'): score += 10
    if profile.get('gender'): score += 5
    
    # Calculate percentage
    percentage = (score / total_possible) * 100
    
    # Rating
    if percentage >= 90:
        rating = "🌟🌟🌟🌟🌟 Excellent"
    elif percentage >= 75:
        rating = "🌟🌟🌟🌟 Good"
    elif percentage >= 60:
        rating = "🌟🌟🌟 Average"
    elif percentage >= 40:
        rating = "🌟🌟 Basic"
    else:
        rating = "🌟 Incomplete"
    
    return {
        'score': score,
        'percentage': percentage,
        'rating': rating,
        'missing': []  # Could add what's missing
    }

# Display functions
def show_profile_with_consistent_ui(chat_id, profile, match_info=None):
    """Show profile with consistent UI and match reasons"""
    try:
        profile_summary = (
            f"👤 {profile['name']}, {profile['age']}\n"
            f"⚧️ {profile['gender']}\n"
            f"📍 {profile['location']}\n"
            f"🎯 Interests: {', '.join(profile['interests'].split(', '))}"
        )
        
        # Add match reasons if available
        if match_info:
            score, distance, similarity, age_score, distance_score = match_info
            match_reasons = []
            
            if similarity > 0.3:
                user_info = user_data.get(chat_id)
                if user_info and 'interests' in user_info:
                    common_interests = set(profile['interests'].split(', ')) & set(user_info['interests'])
                    if common_interests:
                        match_reasons.append(f"🎯 {len(common_interests)} shared interests")
            
            if distance < 50:
                match_reasons.append(f"📍 {distance:.1f} km away")
            
            if age_score > 0.7:
                match_reasons.append(f"🎂 Similar age")
            
            if match_reasons:
                profile_summary += f"\n\n✨ Match: " + " • ".join(match_reasons)
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        btn_like = InlineKeyboardButton("👍 Like", callback_data=f"like_{profile['chat_id']}")
        btn_dislike = InlineKeyboardButton("👎 Pass", callback_data=f"dislike_{profile['chat_id']}")
        btn_note = InlineKeyboardButton("💌 Send Note", callback_data=f"note_{profile['chat_id']}")
        btn_report = InlineKeyboardButton("🚩 Report", callback_data=f"report_{profile['chat_id']}")
        
        markup.add(btn_like, btn_dislike, btn_note, btn_report)
        
        # Add navigation button if there are more profiles
        user_data_obj = user_data.get(chat_id)
        if user_data_obj and 'matched_profiles' in user_data_obj:
            btn_next = InlineKeyboardButton("➡️ Next Profile", callback_data="next_profile")
            markup.add(btn_next)
        
        bot.send_photo(chat_id, profile['photo'], caption=profile_summary, reply_markup=markup)
        
    except Exception as e:
        logger.error(f"Error in show_profile_with_consistent_ui: {e}")
        bot.send_message(chat_id, "Error displaying profile. Please try again.")

def display_next_profile(chat_id):
    """Display the next profile in the queue"""
    try:
        user_data_obj = user_data.get(chat_id)
        if not user_data_obj or 'matched_profiles' not in user_data_obj:
            bot.send_message(chat_id, "No more profiles to show. Try /view_profiles again.")
            return
        
        matched_profiles = user_data_obj['matched_profiles']
        current_index = user_data_obj.get('current_profile_index', -1)
        
        # Move to next profile
        current_index += 1
        
        if current_index < len(matched_profiles):
            user_data_obj['current_profile_index'] = current_index
            user_data.set(chat_id, user_data_obj)
            
            profile_tuple = matched_profiles[current_index]
            profile = profile_tuple[0]
            match_info = profile_tuple[1:] if len(profile_tuple) > 1 else None
            
            show_profile_with_consistent_ui(chat_id, profile, match_info)
        else:
            bot.send_message(chat_id, 
                "🎉 You've seen all available profiles!\n\n"
                "Try again later or improve your profile for better matches."
            )
            
    except Exception as e:
        logger.error(f"Error in display_next_profile: {e}")
        bot.send_message(chat_id, "Error showing next profile. Please try again.")

# Queue information helper
def get_queue_info():
    """Get queue information for user feedback"""
    with pending_users_lock:
        queue_size = len(pending_users)
        estimated_wait = queue_size * 30  # 30 seconds per person in queue
        
        return (
            f"🔍 Searching for compatible matches...\n\n"
            f"📊 Queue position: {queue_size}\n"
            f"⏱️ Estimated wait: {estimated_wait} seconds\n\n"
            f"💡 Tip: Complete your profile for better matches!"
        )

# Profile setup functions
@bot.message_handler(commands=['start', 'setup'])
def send_welcome(message):
    try:
        chat_id = message.chat.id
        username = message.from_user.username

        # Rate limiting
        if not rate_limiter.is_allowed(chat_id):
            bot.send_message(chat_id, "⏳ Too many requests. Please wait a moment.")
            return

        # Check if the user is banned
        if check_banned(chat_id):
            bot.send_message(chat_id, "❌ You have been banned and cannot use this bot.")
            return

        # Check if user already has a profile
        user_info = get_user_info(chat_id)
        if user_info:
            # User already has profile, ask if they want to edit
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            markup.add('Edit Profile', 'View My Profile')
            msg = bot.reply_to(message, 
                f"Welcome back, {user_info['name']}!\n\n"
                "Would you like to edit your profile or view it?",
                reply_markup=markup
            )
            bot.register_next_step_handler(msg, handle_returning_user)
            return

        # New user - start profile setup
        user_data.set(chat_id, {'username': username})
        
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add('🚀 Quick Setup', '📋 Complete Setup')
        msg = bot.reply_to(message, 
            "Welcome! Let's set up your profile.\n\n"
            "Choose setup type:\n"
            "🚀 Quick Setup: Basic info (1-2 minutes)\n"
            "📋 Complete Setup: Full profile (3-5 minutes)",
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, ask_name)

    except Exception as e:
        logger.error(f"Error in send_welcome: {e}")
        bot.reply_to(message, "An unexpected error occurred. Please try again later.")

def handle_returning_user(message):
    chat_id = message.chat.id
    choice = message.text
    
    if 'Edit' in choice:
        edit_profile(message)
    elif 'View' in choice:
        my_profile(message)
    else:
        send_welcome(message)

def ask_name(message):
    try:
        chat_id = message.chat.id
        user_data.set(chat_id, {'name': message.text})
        msg = bot.reply_to(message, "Please enter your age:")
        bot.register_next_step_handler(msg, validate_age)
    except Exception as e:
        logger.error(f"Error in ask_name: {e}")
        bot.reply_to(message, "An unexpected error occurred. Please try again later.")

def validate_age(message):
    try:
        chat_id = message.chat.id
        if message.text.isdigit():
            age = int(message.text)
            if 13 <= age <= 120:  # Add validation
                user_data_obj = user_data.get(chat_id) or {}
                user_data_obj['age'] = age
                user_data.set(chat_id, user_data_obj)
                ask_gender(message)
            else:
                msg = bot.reply_to(message, "Age must be between 13 and 120. Please enter a valid age:")
                bot.register_next_step_handler(msg, validate_age)
        else:
            msg = bot.reply_to(message, "Invalid input. Please enter a valid number for your age:")
            bot.register_next_step_handler(msg, validate_age)
    except Exception as e:
        logger.error(f"Error in validate_age: {e}")
        bot.reply_to(message, "An unexpected error occurred. Please try again later.")

def ask_gender(message):
    try:
        chat_id = message.chat.id
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add(types.KeyboardButton("👨 Male"), types.KeyboardButton("👩 Female"))
        msg = bot.reply_to(message, "Please select your gender:", reply_markup=markup)
        bot.register_next_step_handler(msg, validate_gender)
    except Exception as e:
        logger.error(f"Error in ask_gender: {e}")
        bot.reply_to(message, "An unexpected error occurred. Please try again later.")

def validate_gender(message):
    try:
        chat_id = message.chat.id
        gender_text = message.text
        gender_map = {"👨 Male": "M", "👩 Female": "F", "M": "M", "F": "F"}
        gender = gender_map.get(gender_text, gender_text.upper())
        
        if gender in ['M', 'F']:
            user_data_obj = user_data.get(chat_id) or {}
            user_data_obj['gender'] = gender
            user_data.set(chat_id, user_data_obj)
            ask_looking_for(message)
        else:
            msg = bot.reply_to(message, "Invalid input. Please select 'Male' or 'Female'.")
            bot.register_next_step_handler(msg, ask_gender)
    except Exception as e:
        logger.error(f"Error in validate_gender: {e}")
        bot.reply_to(message, "An unexpected error occurred. Please try again later.")

def ask_looking_for(message):
    try:
        chat_id = message.chat.id
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add("💑 Dating", "👥 Friends")
        msg = bot.reply_to(message, 
            "What are you looking for?\n\n"
            "💑 Dating: Matches with opposite gender\n"
            "👥 Friends: Matches with both genders",
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, validate_looking_for)
    except Exception as e:
        logger.error(f"Error in ask_looking_for: {e}")
        bot.reply_to(message, "An unexpected error occurred. Please try again later.")

def validate_looking_for(message):
    try:
        chat_id = message.chat.id
        looking_for_text = message.text
        looking_for_map = {"💑 Dating": "1", "👥 Friends": "2", "Dating": "1", "Friends": "2"}
        looking_for = looking_for_map.get(looking_for_text, looking_for_text)
        
        if looking_for in ['1', '2']:
            user_data_obj = user_data.get(chat_id) or {}
            user_data_obj['looking_for'] = looking_for
            
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            location_button = types.KeyboardButton("📍 Share Location", request_location=True)
            markup.add(location_button)
            msg = bot.reply_to(message, 
                "Please share your location or type it (e.g., 'New York' or '51.5074, -0.1278'):",
                reply_markup=markup
            )
            bot.register_next_step_handler(msg, handle_location_or_prompt_for_location)
        else:
            msg = bot.reply_to(message, "Invalid input. Please select 'Dating' or 'Friends'.")
            bot.register_next_step_handler(msg, ask_looking_for)
    except Exception as e:
        logger.error(f"Error in validate_looking_for: {e}")
        bot.reply_to(message, "An unexpected error occurred. Please try again later.")

def handle_location_or_prompt_for_location(message):
    try:
        chat_id = message.chat.id
        if message.location:
            location = f"{message.location.latitude}, {message.location.longitude}"
        else:
            location = sanitize_text(message.text)
        
        if not location:
            msg = bot.reply_to(message, "Please provide a valid location.")
            bot.register_next_step_handler(msg, handle_location_or_prompt_for_location)
            return
        
        user_data_obj = user_data.get(chat_id) or {}
        user_data_obj['location'] = location
        user_data.set(chat_id, user_data_obj)
        
        msg = bot.reply_to(message, "Great! Please send a photo of yourself:")
        bot.register_next_step_handler(msg, ask_photo)
    except Exception as e:
        logger.error(f"Error in handle_location_or_prompt_for_location: {e}")
        bot.reply_to(message, "An unexpected error occurred. Please try again later.")

def ask_photo(message):
    try:
        chat_id = message.chat.id
        if message.content_type == 'photo':
            # Get the largest photo size
            photo = message.photo[-1].file_id
            
            user_data_obj = user_data.get(chat_id) or {}
            user_data_obj['photo'] = photo
            user_data.set(chat_id, user_data_obj)
            
            msg = bot.reply_to(message, 
                "Excellent! Please enter your interests (separate with commas):\n\n"
                "Example: coding, hiking, music, movies")
            bot.register_next_step_handler(msg, ask_interests)
        else:
            msg = bot.reply_to(message, "Please send a photo.")
            bot.register_next_step_handler(msg, ask_photo)
    except Exception as e:
        logger.error(f"Error in ask_photo: {e}")
        bot.reply_to(message, "An unexpected error occurred. Please try again later.")

def ask_interests(message):
    try:
        chat_id = message.chat.id
        interests_text = sanitize_text(message.text)
        
        valid, interests_result = validate_interests(interests_text)
        if not valid:
            msg = bot.reply_to(message, interests_result)
            bot.register_next_step_handler(msg, ask_interests)
            return
        
        user_data_obj = user_data.get(chat_id) or {}
        
        # Check if username is missing
        if 'username' not in user_data_obj:
            user_info = get_user_info(chat_id)
            if user_info and 'username' in user_info:
                user_data_obj['username'] = user_info['username']
            else:
                user_data_obj['username'] = message.from_user.username or "Unknown"
        
        user_data_obj['interests'] = ', '.join(interests_result)
        user_data.set(chat_id, user_data_obj)
        
        # Save to database
        save_success = save_user_to_db(chat_id, user_data_obj)
        
        if not save_success:
            bot.send_message(chat_id, "⚠️ There was an error saving your profile. Please try again.")
            return
        
        # Show profile summary
        profile_summary = (
            f"🎉 Profile Setup Complete!\n\n"
            f"👤 Name: {user_data_obj['name']}\n"
            f"🎂 Age: {user_data_obj['age']}\n"
            f"⚧️ Gender: {user_data_obj['gender']}\n"
            f"📍 Location: {user_data_obj['location']}\n"
            f"🎯 Looking for: {'💑 Dating' if user_data_obj['looking_for'] == '1' else '👥 Friends'}\n"
            f"🎨 Interests: {user_data_obj['interests']}\n\n"
            f"📊 Profile Quality: {get_profile_quality(user_data_obj)['rating']}"
        )
        
        bot.send_photo(chat_id, user_data_obj['photo'], caption=profile_summary)
        
        # Show available commands
        commands_text = (
            f"🚀 Get Started:\n\n"
            f"/my_profile - View and edit your profile\n"
            f"/view_profiles - Browse compatible profiles\n"
            f"/random - Chat with someone new\n"
            f"/preferences - Set your matching preferences\n"
            f"/quality - Check your profile quality\n"
            f"/help - Get help and support"
        )
        
        bot.send_message(chat_id, commands_text)
        
        # Add user to interacted set for tips
        users_interacted.add(chat_id)
        
        logger.info(f"User profile created for {chat_id}: {user_data_obj}")
        
    except Exception as e:
        logger.error(f"Error in ask_interests: {e}")
        bot.reply_to(message, "An unexpected error occurred. Please try again later.")

# Profile management commands
@bot.message_handler(commands=['my_profile'])
def my_profile(message):
    chat_id = message.chat.id
    
    # Rate limiting
    if not rate_limiter.is_allowed(chat_id):
        bot.send_message(chat_id, "⏳ Too many requests. Please wait a moment.")
        return
    
    user_info = get_user_info(chat_id)
    if user_info:
        # Calculate profile quality
        quality = get_profile_quality(user_info)
        
        profile_summary = (
            f"👤 Your Profile:\n\n"
            f"📛 Name: {user_info['name']}\n"
            f"🎂 Age: {user_info['age']}\n"
            f"⚧️ Gender: {user_info['gender']}\n"
            f"📍 Location: {user_info['location']}\n"
            f"🎯 Looking for: {'💑 Dating' if user_info['looking_for'] == '1' else '👥 Friends'}\n"
            f"🎨 Interests: {', '.join(user_info['interests'].split(', '))}\n\n"
            f"📊 Profile Quality: {quality['rating']}\n"
            f"📈 Score: {quality['score']}/100 ({quality['percentage']:.0f}%)\n"
        )
        
        if quality['percentage'] < 75:
            profile_summary += "\n💡 Tips to improve:\n"
            if not user_info.get('photo'):
                profile_summary += "• Add a profile photo\n"
            if len(user_info.get('interests', '').split(', ')) < 5:
                profile_summary += "• Add more interests\n"
            if ',' not in user_info.get('location', ''):
                profile_summary += "• Share your exact location\n"
        
        bot.send_photo(chat_id, user_info['photo'], caption=profile_summary)
        
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("/edit_profile", "/quality", "/preferences")
        bot.send_message(chat_id, "Manage your profile:", reply_markup=markup)
    else:
        bot.reply_to(message, "No profile found. Please set up your profile using /start.")

@bot.message_handler(commands=['edit_profile'])
def edit_profile(message):
    chat_id = message.chat.id
    
    # Rate limiting
    if not rate_limiter.is_allowed(chat_id):
        bot.send_message(chat_id, "⏳ Too many requests. Please wait a moment.")
        return
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("📛 Name", "🎂 Age", "⚧️ Gender", "📍 Location", "📸 Photo", "🎨 Interests", "🎯 Looking For")
    msg = bot.reply_to(message, "What would you like to edit?", reply_markup=markup)
    bot.register_next_step_handler(msg, handle_edit_choice)

def handle_edit_choice(message):
    chat_id = message.chat.id
    edit_choice = message.text
    
    edit_map = {
        "📛 Name": "name",
        "🎂 Age": "age", 
        "⚧️ Gender": "gender",
        "📍 Location": "location",
        "📸 Photo": "photo",
        "🎨 Interests": "interests",
        "🎯 Looking For": "looking_for"
    }
    
    edit_field = edit_map.get(edit_choice, edit_choice.lower())
    
    if edit_field in ['name', 'age', 'location', 'interests']:
        if edit_field == 'age':
            msg = bot.reply_to(message, "Please enter your new age:")
            bot.register_next_step_handler(msg, save_edit, edit_field)
        else:
            msg = bot.reply_to(message, f"Please enter your new {edit_field}:")
            bot.register_next_step_handler(msg, save_edit, edit_field)
    elif edit_field == 'gender':
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add("👨 Male", "👩 Female")
        msg = bot.reply_to(message, "Please select your gender:", reply_markup=markup)
        bot.register_next_step_handler(msg, save_edit, edit_field)
    elif edit_field == 'photo':
        msg = bot.reply_to(message, "Please send your new photo:")
        bot.register_next_step_handler(msg, save_edit, edit_field)
    elif edit_field == 'looking_for':
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add("💑 Dating", "👥 Friends")
        msg = bot.reply_to(message, "What are you looking for?", reply_markup=markup)
        bot.register_next_step_handler(msg, save_edit, edit_field)
    else:
        msg = bot.reply_to(message, "Invalid choice. Please choose again.")
        bot.register_next_step_handler(msg, handle_edit_choice)

def save_edit(message, edit_field):
    chat_id = message.chat.id
    new_value = message.text if message.content_type == 'text' else None
    
    # Handle different field types
    if edit_field == 'age':
        if not new_value.isdigit():
            msg = bot.reply_to(message, "Invalid age. Please enter a number:")
            bot.register_next_step_handler(msg, save_edit, edit_field)
            return
        new_value = int(new_value)
        if not (13 <= new_value <= 120):
            msg = bot.reply_to(message, "Age must be between 13-120. Please enter a valid age:")
            bot.register_next_step_handler(msg, save_edit, edit_field)
            return
    
    elif edit_field == 'photo':
        if message.content_type != 'photo':
            msg = bot.reply_to(message, "Please send a photo.")
            bot.register_next_step_handler(msg, save_edit, edit_field)
            return
        new_value = message.photo[-1].file_id
    
    elif edit_field == 'gender':
        gender_map = {"👨 Male": "M", "👩 Female": "F", "M": "M", "F": "F"}
        new_value = gender_map.get(new_value, new_value.upper())
        if new_value not in ['M', 'F']:
            msg = bot.reply_to(message, "Invalid gender. Please select Male or Female:")
            bot.register_next_step_handler(msg, save_edit, edit_field)
            return
    
    elif edit_field == 'looking_for':
        looking_for_map = {"💑 Dating": "1", "👥 Friends": "2", "Dating": "1", "Friends": "2"}
        new_value = looking_for_map.get(new_value, new_value)
        if new_value not in ['1', '2']:
            msg = bot.reply_to(message, "Invalid choice. Please select Dating or Friends:")
            bot.register_next_step_handler(msg, save_edit, edit_field)
            return
    
    elif edit_field == 'interests':
        valid, interests_result = validate_interests(new_value)
        if not valid:
            msg = bot.reply_to(message, interests_result)
            bot.register_next_step_handler(msg, save_edit, edit_field)
            return
        new_value = ', '.join(interests_result)
    
    elif edit_field == 'location':
        new_value = sanitize_text(new_value)
        if not new_value:
            msg = bot.reply_to(message, "Please provide a valid location.")
            bot.register_next_step_handler(msg, save_edit, edit_field)
            return
    
    # Update database
    field_map = {
        'name': 'name',
        'age': 'age',
        'gender': 'gender',
        'location': 'location',
        'photo': 'photo',
        'interests': 'interests',
        'looking_for': 'looking_for'
    }
    
    db_field = field_map.get(edit_field)
    if db_field:
        success = update_user_field(chat_id, db_field, new_value)
        if success:
            # Update cache
            user_data_obj = user_data.get(chat_id) or {}
            user_data_obj[edit_field] = new_value
            user_data.set(chat_id, user_data_obj)
            
            bot.reply_to(message, f"✅ Your {edit_field.replace('_', ' ')} has been updated.")
        else:
            bot.reply_to(message, f"❌ Error updating your {edit_field.replace('_', ' ')}.")
    
    # Return to profile view
    my_profile(message)

# View profiles command
@bot.message_handler(commands=['view_profiles'])
def show_profiles(message):
    chat_id = message.chat.id
    
    # Rate limiting
    if not rate_limiter.is_allowed(chat_id):
        bot.send_message(chat_id, "⏳ Too many requests. Please wait a moment.")
        return
    
    user_info = get_user_info(chat_id)
    if user_info:
        gender_preference = get_gender_preference(user_info)
        matched_profiles = get_matched_profiles(user_info, gender_preference)
        
        if matched_profiles:
            # Store in user data
            user_data_obj = user_data.get(chat_id) or {}
            user_data_obj['matched_profiles'] = matched_profiles
            user_data_obj['current_profile_index'] = -1
            user_data.set(chat_id, user_data_obj)
            
            # Show first profile
            display_next_profile(chat_id)
        else:
            bot.reply_to(message, 
                "No profiles found right now. 😔\n\n"
                "Try:\n"
                "• Improving your profile with /my_profile\n"
                "• Adjusting preferences with /preferences\n"
                "• Checking back later"
            )
    else:
        bot.reply_to(message, "Please set up your profile first using /start.")

# Random chat command
@bot.message_handler(commands=['random'])
def ask_match_preference(message):
    chat_id = message.chat.id
    
    # Rate limiting
    if not rate_limiter.is_allowed(chat_id):
        bot.send_message(chat_id, "⏳ Too many requests. Please wait a moment.")
        return
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("👨 Men"), types.KeyboardButton("👩 Women"), types.KeyboardButton("👥 Both"))
    
    # Load saved preference if exists
    user_pref = user_cache.get(chat_id)
    if user_pref and 'gender_preference' in user_pref:
        pref = user_pref['gender_preference']
        pref_text = {"M": "👨 Men", "F": "👩 Women", "BOTH": "👥 Both"}.get(pref, "👥 Both")
        default_text = f"Who would you like to chat with? (Current: {pref_text})"
    else:
        default_text = "Who would you like to chat with?"
    
    msg = bot.reply_to(message, default_text, reply_markup=markup)
    bot.register_next_step_handler(msg, find_compatible_random_chat)

def find_compatible_random_chat(message):
    chat_id = message.chat.id
    gender_preference = message.text
    
    # Rate limiting
    if not rate_limiter.is_allowed(chat_id):
        bot.send_message(chat_id, "⏳ Too many requests. Please wait a moment.")
        return
    
    # Map emoji/text to gender codes
    gender_map = {
        "👨 Men": "M",
        "👩 Women": "F", 
        "👥 Both": "BOTH",
        "M": "M",
        "F": "F",
        "Both": "BOTH",
        "BOTH": "BOTH"
    }
    
    gender_preference = gender_map.get(gender_preference, "BOTH")
    
    # Save preference
    user_cache.set(chat_id, {'gender_preference': gender_preference})
    
    with pending_users_lock:
        if chat_id in pending_users:
            bot.reply_to(message, "⏳ You're already in the queue. Please wait for a match.")
            return
    
    user_info = get_user_info(chat_id)
    if not user_info:
        bot.reply_to(message, "❌ Please set up your profile using /start.")
        return
    
    # Get compatible matches
    matched_profiles = get_matched_profiles(user_info, gender_preference, limit=10)
    
    if matched_profiles:
        # Weighted random selection based on compatibility
        profiles = [p[0] for p in matched_profiles]
        scores = [p[1] for p in matched_profiles]
        
        # Normalize scores for probability
        total_score = sum(scores)
        if total_score > 0:
            probabilities = [score/total_score for score in scores]
            chosen_idx = random.choices(range(len(profiles)), weights=probabilities)[0]
            partner_info = profiles[chosen_idx]
            partner_chat_id = partner_info['chat_id']
            
            with pending_users_lock:
                if partner_chat_id in pending_users:
                    pending_users.remove(partner_chat_id)
                    
                    # Create chat session
                    with active_chats_lock:
                        active_chats[chat_id] = partner_chat_id
                        active_chats[partner_chat_id] = chat_id
                    
                    # Show match notification
                    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
                    markup.add("🚪 End Chat")
                    
                    # Calculate common interests
                    user_interests = set(user_info['interests'].split(', '))
                    partner_interests = set(partner_info['interests'].split(', '))
                    common_interests = user_interests & partner_interests
                    
                    welcome_msg = (
                        f"🎉 You've been matched with {partner_info['name']}!\n\n"
                        f"💬 Start chatting now! (Type 'End Chat' to stop)\n\n"
                    )
                    
                    if common_interests:
                        welcome_msg += f"🎯 Shared interests: {', '.join(common_interests)[:50]}"
                    
                    bot.send_message(chat_id, welcome_msg, reply_markup=markup)
                    
                    partner_welcome = (
                        f"🎉 You've been matched with {user_info['name']}!\n\n"
                        f"💬 Start chatting now! (Type 'End Chat' to stop)\n\n"
                    )
                    
                    if common_interests:
                        partner_welcome += f"🎯 Shared interests: {', '.join(common_interests)[:50]}"
                    
                    bot.send_message(partner_chat_id, partner_welcome, reply_markup=markup)
                else:
                    pending_users.append(chat_id)
                    queue_info = get_queue_info()
                    bot.reply_to(message, queue_info)
        else:
            with pending_users_lock:
                pending_users.append(chat_id)
            queue_info = get_queue_info()
            bot.reply_to(message, queue_info)
    else:
        with pending_users_lock:
            pending_users.append(chat_id)
        queue_info = get_queue_info()
        bot.reply_to(message, queue_info)

# Profile quality command
@bot.message_handler(commands=['quality'])
def show_profile_quality(message):
    """Show profile quality score"""
    chat_id = message.chat.id
    
    # Rate limiting
    if not rate_limiter.is_allowed(chat_id):
        bot.send_message(chat_id, "⏳ Too many requests. Please wait a moment.")
        return
    
    user_info = get_user_info(chat_id)
    
    if user_info:
        quality = get_profile_quality(user_info)
        
        quality_report = (
            f"📊 Your Profile Quality:\n\n"
            f"⭐ Rating: {quality['rating']}\n"
            f"📈 Score: {quality['score']}/100 ({quality['percentage']:.0f}%)\n\n"
        )
        
        # Add tips for improvement
        if quality['percentage'] < 75:
            quality_report += "💡 Tips to improve:\n"
            if not user_info.get('photo'):
                quality_report += "• Add a profile photo (+30 points)\n"
            interests_count = len(user_info.get('interests', '').split(', '))
            if interests_count < 5:
                quality_report += f"• Add more interests (current: {interests_count}, +5 each)\n"
            if ',' not in user_info.get('location', ''):
                quality_report += "• Share your location coordinates (+10 points)\n"
        
        bot.send_message(chat_id, quality_report)
    else:
        bot.reply_to(message, "No profile found. Use /start to create one.")

# Preferences command
@bot.message_handler(commands=['preferences'])
def set_preferences(message):
    """Set user matching preferences"""
    chat_id = message.chat.id
    
    # Rate limiting
    if not rate_limiter.is_allowed(chat_id):
        bot.send_message(chat_id, "⏳ Too many requests. Please wait a moment.")
        return
    
    # Load current preferences
    current_prefs = user_cache.get(chat_id) or {}
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_gender_m = InlineKeyboardButton("👨 Men", callback_data="pref_gender_M")
    btn_gender_f = InlineKeyboardButton("👩 Women", callback_data="pref_gender_F")
    btn_gender_both = InlineKeyboardButton("👥 Both", callback_data="pref_gender_BOTH")
    btn_age = InlineKeyboardButton("🎂 Age Range", callback_data="pref_age")
    btn_distance = InlineKeyboardButton("📍 Max Distance", callback_data="pref_distance")
    btn_clear = InlineKeyboardButton("🗑️ Clear All", callback_data="pref_clear")
    
    markup.add(btn_gender_m, btn_gender_f, btn_gender_both)
    markup.add(btn_age, btn_distance, btn_clear)
    
    # Show current preferences
    prefs_text = "Current preferences:\n"
    if current_prefs.get('gender_preference'):
        gender_text = {"M": "👨 Men", "F": "👩 Women", "BOTH": "👥 Both"}.get(current_prefs['gender_preference'], "👥 Both")
        prefs_text += f"• Gender: {gender_text}\n"
    if current_prefs.get('max_age_diff'):
        prefs_text += f"• Max age difference: {current_prefs['max_age_diff']} years\n"
    if current_prefs.get('max_distance'):
        prefs_text += f"• Max distance: {current_prefs['max_distance']} km\n"
    
    if prefs_text == "Current preferences:\n":
        prefs_text = "No preferences set. Using default settings."
    
    bot.send_message(chat_id, f"⚙️ Set your matching preferences:\n\n{prefs_text}", reply_markup=markup)

# Filter command
@bot.message_handler(commands=['filter'])
def set_filters(message):
    """Set profile filters"""
    chat_id = message.chat.id
    
    # Rate limiting
    if not rate_limiter.is_allowed(chat_id):
        bot.send_message(chat_id, "⏳ Too many requests. Please wait a moment.")
        return
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_interests = InlineKeyboardButton("🎯 Filter by Interests", callback_data="filter_interests")
    btn_age_range = InlineKeyboardButton("🎂 Age Range", callback_data="filter_age")
    btn_distance = InlineKeyboardButton("📍 Max Distance", callback_data="filter_distance")
    btn_active = InlineKeyboardButton("🟢 Active Users", callback_data="filter_active")
    btn_clear = InlineKeyboardButton("🗑️ Clear Filters", callback_data="filter_clear")
    
    markup.add(btn_interests, btn_age_range, btn_distance, btn_active, btn_clear)
    
    bot.send_message(chat_id, "🔍 Filter profiles:", reply_markup=markup)

# Database fix command
@bot.message_handler(commands=['fixdb'])
def fix_database(message):
    """Admin command to manually fix database schema"""
    chat_id = message.chat.id
    
    # Replace with your admin chat ID
    ADMIN_CHAT_ID = 916638938  # Replace with your chat ID
    if chat_id != ADMIN_CHAT_ID:
        bot.send_message(chat_id, "❌ Unauthorized.")
        return
    
    try:
        bot.send_message(chat_id, "🔄 Checking and fixing database schema...")
        
        # Reinitialize database to trigger column checks
        success = init_database(DATABASE_URL)
        
        if success:
            bot.send_message(chat_id, "✅ Database schema checked and fixed successfully!")
        else:
            bot.send_message(chat_id, "❌ Failed to fix database schema. Check logs.")
            
    except Exception as e:
        logger.error(f"Error in /fixdb: {e}")
        bot.send_message(chat_id, f"❌ Error: {e}")

# Callback handlers
@bot.callback_query_handler(func=lambda call: call.data.startswith('like_') or call.data.startswith('dislike_') or call.data.startswith('note_'))
def handle_inline_response(call):
    try:
        action, other_user_chat_id = call.data.split('_')
        chat_id = call.message.chat.id

        user_info = get_user_info(chat_id)
        liked_user_info = get_user_info(other_user_chat_id)

        if not user_info:
            bot.send_message(chat_id, "Your profile information could not be retrieved.")
            return

        if not liked_user_info:
            bot.send_message(chat_id, "The selected profile information could not be retrieved.")
            return

        if action == 'like':
            handle_like_action(chat_id, other_user_chat_id, user_info, liked_user_info)
        elif action == 'dislike':
            handle_dislike_action(chat_id)
        elif action == 'note':
            handle_send_note_action(chat_id, other_user_chat_id)
        else:
            bot.answer_callback_query(call.id, "Invalid action.")

    except Exception as e:
        logger.error(f"Error in handle_inline_response: {e}")
        bot.send_message(call.message.chat.id, "An unexpected error occurred.")

def handle_like_action(liker_chat_id, liked_chat_id, user_info, liked_user_info):
    try:
        # Notify the liked user with action buttons
        if liked_user_info:
            markup = InlineKeyboardMarkup()
            btn_see_who = InlineKeyboardButton("👀 See Who Liked You", callback_data="view_likes")
            btn_dislike = InlineKeyboardButton("❌ Dislike", callback_data=f"dislike_{liker_chat_id}")
            markup.add(btn_see_who, btn_dislike)

            bot.send_message(
                liked_chat_id,
                "Someone liked your profile! Use the buttons below:",
                reply_markup=markup
            )

        # Save the like in the database
        save_like(liker_chat_id, liked_chat_id)

        # Check for mutual like
        with get_db() as db:
            mutual_like = db.query(Like).filter(
                Like.liker_chat_id == liked_chat_id,
                Like.liked_chat_id == liker_chat_id
            ).first()
        
        if mutual_like:
            bot.send_message(liker_chat_id, f"You and {liked_user_info['name']} liked each other! Start chatting.")
            bot.send_message(liked_chat_id, f"You and {user_info['name']} liked each other! Start chatting.")
        
        # Show the next profile
        display_next_profile(liker_chat_id)

    except Exception as e:
        logger.error(f"Error in handle_like_action: {e}")
        bot.send_message(liker_chat_id, "An unexpected error occurred. Please try again later.")

def handle_dislike_action(chat_id):
    try:
        # Just display the next profile
        display_next_profile(chat_id)
    except Exception as e:
        logger.error(f"Error in handle_dislike_action: {e}")
        bot.send_message(chat_id, "An unexpected error occurred. Please try again later.")

def handle_send_note_action(liker_chat_id, liked_chat_id):
    try:
        # Store the liked chat ID for note input
        user_data_obj = user_data.get(liker_chat_id) or {}
        user_data_obj['current_liked_chat_id'] = liked_chat_id
        user_data.set(liker_chat_id, user_data_obj)
        
        bot.send_message(liker_chat_id, "✍️ Please type your note:")
        
        # Register next step handler
        def save_note_wrapper(message):
            save_note(message, liked_chat_id)
        
        bot.register_next_step_handler_by_chat_id(liker_chat_id, save_note_wrapper)
    except Exception as e:
        logger.error(f"Error in handle_send_note_action: {e}")
        bot.send_message(liker_chat_id, "An unexpected error occurred. Please try again later.")

def save_note(message, liked_chat_id):
    try:
        chat_id = message.chat.id
        note = message.text
        
        if not note:
            bot.send_message(chat_id, "❌ Note cannot be empty.")
            return
            
        user_info = get_user_info(chat_id)
        liked_user_info = get_user_info(liked_chat_id)
        
        if liked_user_info:
            # Save note with the like
            save_like(chat_id, liked_chat_id, note)
            
            # Notify the user who received the note
            note_message = f"📩 Someone sent you a note:\n\n{note}\n\nFrom: {user_info['name']}"
            bot.send_message(liked_chat_id, note_message)
            
            bot.send_message(chat_id, "✅ Your note has been sent!")
            display_next_profile(chat_id)
    except Exception as e:
        logger.error(f"Error in save_note: {e}")
        bot.send_message(chat_id, "An unexpected error occurred. Please try again later.")
        display_next_profile(chat_id)

@bot.callback_query_handler(func=lambda call: call.data == "next_profile")
def handle_next_profile(call):
    """Handle next profile button"""
    chat_id = call.message.chat.id
    display_next_profile(chat_id)

@bot.callback_query_handler(func=lambda call: call.data == "view_likes")
def handle_view_likes_callback(call):
    """Handle view likes button"""
    chat_id = call.message.chat.id
    offset = 0
    limit = 5
    display_likes(chat_id, offset, limit)

def display_likes(chat_id, offset, limit):
    """Display likes with pagination"""
    try:
        likes = get_likes_for_user(chat_id, limit, offset)

        if not likes:
            bot.send_message(chat_id, "No one has liked your profile yet.")
            return

        for like in likes:
            profile_details = f"{like['name']}, {like['age']}, {like['location']}, {like['interests']}\nUsername: @{like['username'] if like['username'] else 'No username'}"

            if like['note']:
                profile_details += f"\n\n📝 Note: {like['note']}"

            try:
                markup = generate_like_dislike_buttons(like['liker_chat_id'], chat_id)
                bot.send_photo(chat_id, like['photo'], caption=profile_details, reply_markup=markup)
            except Exception as photo_error:
                logger.error(f"Error sending photo: {photo_error}")
                bot.send_message(chat_id, f"{profile_details}\n\n(⚠️ Unable to load photo)")

        # Check if there are more likes
        with get_db() as db:
            total_likes = db.query(Like).filter(Like.liked_chat_id == chat_id).count()

        # Create navigation buttons if there are more likes
        markup = InlineKeyboardMarkup()

        if offset + limit < total_likes:
            markup.add(InlineKeyboardButton("Previous", callback_data=f"view_likes_previous:{offset + limit}"))

        if offset > 0:
            prev_offset = max(offset - limit, 0)
            markup.add(InlineKeyboardButton("Next", callback_data=f"view_likes_previous:{prev_offset}"))

        if markup.keyboard:
            bot.send_message(chat_id, "Use the buttons below to navigate likes:", reply_markup=markup)
    except Exception as e:
        logger.error(f"Error in display_likes: {e}")
        bot.send_message(chat_id, "An error occurred while fetching likes. Please try again later.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("view_likes_previous"))
def handle_view_likes_pagination(call):
    """Handle pagination for likes"""
    try:
        chat_id = call.message.chat.id
        data = call.data.split(":")
        offset = int(data[1])
        limit = 5
        display_likes(chat_id, offset, limit)
    except Exception as e:
        logger.error(f"Error in handle_view_likes_pagination: {e}")
        bot.send_message(chat_id, "An error occurred while fetching likes. Please try again later.")

def generate_like_dislike_buttons(liker_id, liked_id):
    """Generate inline buttons for Like and Dislike actions"""
    user_likes[liked_id] = liker_id

    markup = InlineKeyboardMarkup()
    like_button = InlineKeyboardButton("👍 Like", callback_data=f"like_{liker_id}")
    dislike_button = InlineKeyboardButton("👎 Dislike", callback_data=f"dislike_{liker_id}")
    report_button = InlineKeyboardButton("🚩 Report", callback_data=f"report_{liked_id}")
    markup.row(like_button, dislike_button)
    markup.add(report_button)
    return markup

@bot.callback_query_handler(func=lambda call: call.data.startswith("report_"))
def handle_report(call):
    try:
        reporter_id = call.from_user.id
        reported_id = user_likes.get(reporter_id)

        if not reported_id:
            bot.answer_callback_query(call.id, "⚠️ Error: Could not determine reported user.")
            return

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Spam", callback_data=f"violation_spam_{reported_id}"))
        markup.add(InlineKeyboardButton("Harassment", callback_data=f"violation_harassment_{reported_id}"))
        markup.add(InlineKeyboardButton("Other", callback_data=f"violation_other_{reported_id}"))

        bot.send_message(reporter_id, "⚠️ Please select a reason for reporting:", reply_markup=markup)

    except Exception as e:
        logger.error(f"Error in handle_report: {e}")
        bot.answer_callback_query(call.id, "❌ An error occurred. Please try again.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("violation_"))
def handle_violation(call):
    try:
        data_parts = call.data.split('_')
        violation_type = data_parts[1]
        reported_id = int(data_parts[2])
        reporter_id = call.from_user.id

        if reporter_id == reported_id:
            bot.answer_callback_query(call.id, "❌ You cannot report yourself.")
            return

        save_report(reporter_id, reported_id, violation_type)
        bot.answer_callback_query(call.id, "✅ Thank you! Your report has been submitted.")
        check_reports(reported_id, reporter_id)

    except Exception as e:
        logger.error(f"Error in handle_violation: {e}")
        bot.answer_callback_query(call.id, "❌ An error occurred. Please try again.")

def check_reports(reported_chat_id, reporter_chat_id):
    try:
        with get_db() as db:
            reports = db.query(Report).filter(Report.reported_chat_id == reported_chat_id).all()
            report_count = len(reports)
        
        if report_count >= 3:
            bot.send_message(
                reported_chat_id,
                f"Warning: You have received {report_count} reports. Please adhere to the guidelines.",
            )
        
        if report_count >= 5:
            bot.send_message(
                reported_chat_id,
                f"You have been banned for receiving 5 reports.",
            )

            try:
                with get_db() as db:
                    banned = BannedUser(user_id=reported_chat_id)
                    db.add(banned)
                    db.commit()
            except:
                pass

        bot.send_message(reporter_chat_id, "Finding your next match...")
        # This needs to be adapted to work with the new system
        # find_random_chat(types.Message(chat=types.Chat(id=reporter_chat_id), text="M, F, or Both"))

    except Exception as e:
        logger.error(f"Error processing check_reports: {e}")

# Community functions
@bot.message_handler(commands=['community'])
def community_options(message):
    chat_id = message.chat.id
    
    # Rate limiting
    if not rate_limiter.is_allowed(chat_id):
        bot.send_message(chat_id, "⏳ Too many requests. Please wait a moment.")
        return
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("Create Community"), types.KeyboardButton("List Communities"))
    msg = bot.send_message(chat_id, "Choose an option:", reply_markup=markup)
    bot.register_next_step_handler(msg, handle_community_choice)

def handle_community_choice(message):
    chat_id = message.chat.id
    choice = message.text

    if choice == "Create Community":
        send_creation_instructions(message)
    elif choice == "List Communities":
        list_communities(message)
    else:
        bot.send_message(chat_id, "Invalid choice. Please try again.")

def send_creation_instructions(message):
    chat_id = message.chat.id
    instructions = (
        "To add your group to the bot, please provide the following information:\n"
        "1. Group Name\n"
        "2. Group Description\n"
        "3. Group Profile Picture\n"
        "4. Group Invite Link\n"
        "Please send the group name first:"
    )
    msg = bot.send_message(chat_id, instructions)
    bot.register_next_step_handler(msg, ask_group_name)

def ask_group_name(message):
    chat_id = message.chat.id
    user_data.set(chat_id, {'group_name': message.text})
    msg = bot.send_message(chat_id, "Please enter the group's description:")
    bot.register_next_step_handler(msg, ask_group_description)

def ask_group_description(message):
    chat_id = message.chat.id
    user_data_obj = user_data.get(chat_id) or {}
    user_data_obj['group_description'] = message.text
    user_data.set(chat_id, user_data_obj)
    msg = bot.send_message(chat_id, "Please send the group's profile picture:")

@bot.message_handler(content_types=['photo'])
def handle_group_photo(message):
    chat_id = message.chat.id
    user_data_obj = user_data.get(chat_id)
    if user_data_obj and 'group_description' in user_data_obj:
        file_info = bot.get_file(message.photo[-1].file_id)
        user_data_obj['group_photo'] = file_info.file_id
        user_data.set(chat_id, user_data_obj)
        msg = bot.send_message(chat_id, "Please enter the group's invite link:")
        bot.register_next_step_handler(msg, register_group)
    else:
        bot.send_message(chat_id, "Please start the community creation process with /community.")

def register_group(message):
    chat_id = message.chat.id
    invite_link = message.text
    user_data_obj = user_data.get(chat_id)
    
    if not user_data_obj:
        bot.send_message(chat_id, "Error: No group data found. Please start over.")
        return
    
    group_name = user_data_obj.get('group_name', 'Unnamed Group')
    group_description = user_data_obj.get('group_description', 'No description')
    group_photo = user_data_obj.get('group_photo', '')

    try:
        with get_db() as db:
            group = Group(
                name=group_name,
                description=group_description,
                photo=group_photo,
                invite_link=invite_link,
                created_at=datetime.utcnow(),
                created_by=chat_id
            )
            db.add(group)
            db.commit()
            bot.send_message(chat_id, "✅ Your group has been registered successfully!")
    except Exception as err:
        logger.error(f"Error registering group: {err}")
        bot.send_message(chat_id, f"Error: {err}")

def list_communities(message):
    chat_id = message.chat.id
    try:
        with get_db() as db:
            groups = db.query(Group).all()

        if groups:
            for group in groups:
                markup = types.InlineKeyboardMarkup()
                button = types.InlineKeyboardButton("Check out the group", url=group.invite_link)
                markup.add(button)
                caption = f"Name: {group.name}\nDescription: {group.description}"
                
                try:
                    if group.photo:
                        bot.send_photo(chat_id, group.photo, caption=caption, reply_markup=markup)
                    else:
                        bot.send_message(chat_id, f"{caption}\n\n{group.invite_link}", reply_markup=markup)
                except:
                    bot.send_message(chat_id, f"{caption}\n\n{group.invite_link}", reply_markup=markup)
        else:
            bot.send_message(chat_id, "No communities found.")
    except Exception as e:
        logger.error(f"Error listing communities: {e}")
        bot.send_message(chat_id, "Error loading communities.")

# Message relay for active chats
@bot.message_handler(func=lambda message: True)
def relay_message(message):
    chat_id = message.chat.id
    
    with active_chats_lock:
        if chat_id in active_chats:
            partner_chat_id = active_chats[chat_id]
            
            if message.text and message.text.lower() == 'end chat':
                end_chat(chat_id)
            else:
                # Relay the message
                try:
                    if message.text:
                        bot.send_message(partner_chat_id, message.text)
                    elif message.photo:
                        bot.send_photo(partner_chat_id, message.photo[-1].file_id)
                    elif message.sticker:
                        bot.send_sticker(partner_chat_id, message.sticker.file_id)
                except Exception as e:
                    logger.error(f"Error relaying message: {e}")
                    bot.send_message(chat_id, "Error sending message. The chat may have ended.")
        else:
            # Handle other messages
            pass

def end_chat(chat_id):
    try:
        with active_chats_lock:
            if chat_id in active_chats:
                partner_chat_id = active_chats[chat_id]
                
                # Remove from active chats
                del active_chats[chat_id]
                if partner_chat_id in active_chats:
                    del active_chats[partner_chat_id]
                
                # Send end chat messages
                markup = types.InlineKeyboardMarkup()
                like_button = InlineKeyboardButton("👍 Like", callback_data=f"like_{partner_chat_id}")
                dislike_button = InlineKeyboardButton("👎 Dislike", callback_data=f"dislike_{partner_chat_id}")
                markup.row(like_button, dislike_button)
                
                end_msg = "Chat ended. How was your conversation?"
                bot.send_message(chat_id, end_msg, reply_markup=markup)
                bot.send_message(partner_chat_id, end_msg, reply_markup=markup)
                
                logger.info(f"Chat ended between {chat_id} and {partner_chat_id}")
            else:
                bot.send_message(chat_id, "❌ You are not in a chat currently.")

    except Exception as e:
        logger.error(f"Error in end_chat: {e}")

# Tip system
def send_tips():
    while True:
        time.sleep(86400)  # 24 hours
        for chat_id in list(users_interacted):
            try:
                index = tip_index.get(chat_id, 0)
                if index < len(tips):
                    bot.send_message(chat_id, tips[index])
                    tip_index[chat_id] = (index + 1) % len(tips)
            except Exception as e:
                logger.error(f"Error sending tip to {chat_id}: {e}")
                # Remove from set if user blocked bot
                users_interacted.discard(chat_id)

def start_tip_thread():
    tip_thread = threading.Thread(target=send_tips)
    tip_thread.daemon = True
    tip_thread.start()

# Help command
@bot.message_handler(commands=['help'])
def help_command(message):
    try:
        help_text = (
            "🤖 *MatchBot Help*\n\n"
            "🚀 *Getting Started:*\n"
            "/start - Create or edit your profile\n"
            "/setup - Quick or complete profile setup\n"
            "/my_profile - View and edit your profile\n\n"
            "🔍 *Finding Matches:*\n"
            "/view_profiles - Browse compatible profiles\n" 
            "/random - Chat with a random user\n"
            "/preferences - Set your matching preferences\n"
            "/filter - Filter profiles\n\n"
            "📊 *Profile Management:*\n"
            "/quality - Check your profile quality score\n"
            "/edit_profile - Edit specific profile fields\n\n"
            "👥 *Community:*\n"
            "/community - Create or join communities\n\n"
            "🛠️ *Support:*\n"
            "/help - This help message\n"
            "Contact: @meh9061\n\n"
            "💡 *Tips:*\n"
            "• Complete your profile for better matches\n"
            "• Set preferences to find what you want\n"
            "• Be respectful in chats\n"
        )

        bot.send_message(message.chat.id, help_text)
    except Exception as e:
        logger.error(f"Error in help_command: {e}")
        bot.send_message(message.chat.id, "Something went wrong. Please try again.")

# View likes command
@bot.message_handler(commands=['view_likes'])
def handle_view_likes(message):
    """Fetch and display profiles of users who liked the current user, with pagination."""
    try:
        chat_id = message.chat.id
        
        # Rate limiting
        if not rate_limiter.is_allowed(chat_id):
            bot.send_message(chat_id, "⏳ Too many requests. Please wait a moment.")
            return
            
        offset = 0
        limit = 5
        display_likes(chat_id, offset, limit)
    except Exception as e:
        logger.error(f"Error in /view_likes: {e}")
        bot.send_message(chat_id, "An error occurred while fetching your likes. Please try again later.")

# Main execution
if __name__ == '__main__':
    logger.info("🤖 Bot starting...")
    
    # Start tip thread
    start_tip_thread()
    
    # Start polling with better error handling
    poll_count = 0
    while True:
        try:
            poll_count += 1
            logger.info(f"🔄 Starting bot polling (attempt {poll_count})...")
            
            bot.polling(
                none_stop=True,
                interval=0,
                timeout=30,
                skip_pending=True,
                allowed_updates=None
            )
            
        except Exception as e:
            logger.error(f"❌ Bot polling error: {e}")
            logger.info("⏳ Restarting in 10 seconds...")
            
            # Cleanup
            try:
                bot.stop_polling()
            except:
                pass
            
            time.sleep(10)
            
            # Exponential backoff
            if poll_count > 5:
                wait_time = min(60, 10 * (2 ** (poll_count - 5)))
                logger.info(f"⏰ Exponential backoff: waiting {wait_time} seconds")
                time.sleep(wait_time)
