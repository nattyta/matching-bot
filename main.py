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
import threading
import os
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
import keepalive

# Import SQLAlchemy models
from sqlalchemy.orm import Session
from models import get_db, User, Like, Report, BannedUser, Group, init_database

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

# In-memory storage
user_data = {}
pending_users = []
users_interacted = set()
tip_index = {}
user_likes = {}
active_chats = {}

tips = [
    "Do you know you can join or create a community about whatever you like? Just use the command /community!",
    "Do you know you can have a random chat with someone? Just go to the command /random!"
]

# Database helper functions
def get_user_info(chat_id):
    """Get user info using SQLAlchemy"""
    try:
        db: Session = next(get_db())
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
    finally:
        try:
            db.close()
        except:
            pass
    return None

def save_user_to_db(chat_id, user_data_dict):
    """Save user to database using SQLAlchemy"""
    try:
        db: Session = next(get_db())
        
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
    except Exception as e:
        logger.error(f"Error saving user to DB: {e}")
        return False
    finally:
        try:
            db.close()
        except:
            pass

def update_user_field(chat_id, field, value):
    """Update specific user field"""
    try:
        db: Session = next(get_db())
        user = db.query(User).filter(User.chat_id == chat_id).first()
        if user:
            setattr(user, field, value)
            db.commit()
            return True
        return False
    except Exception as e:
        logger.error(f"Error updating user field: {e}")
        return False
    finally:
        try:
            db.close()
        except:
            pass

def check_banned(chat_id):
    """Check if user is banned"""
    try:
        db: Session = next(get_db())
        banned = db.query(BannedUser).filter(BannedUser.user_id == chat_id).first()
        return banned is not None
    except Exception as e:
        logger.error(f"Error checking banned: {e}")
        return False
    finally:
        try:
            db.close()
        except:
            pass

def save_like(liker_chat_id, liked_chat_id, note=None):
    """Save like to database"""
    try:
        db: Session = next(get_db())
        
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
    finally:
        try:
            db.close()
        except:
            pass

def get_likes_for_user(chat_id, limit=5, offset=0):
    """Get likes for a user with pagination"""
    try:
        db: Session = next(get_db())
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
    finally:
        try:
            db.close()
        except:
            pass

def save_report(reporter_id, reported_id, violation_type):
    """Save report to database"""
    try:
        db: Session = next(get_db())
        
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
    finally:
        try:
            db.close()
        except:
            pass

def calculate_distance(location1, location2):
    try:
        coords_1 = tuple(map(float, location1.split(',')))
        coords_2 = tuple(map(float, location2.split(',')))
        return geodesic(coords_1, coords_2).kilometers
    except ValueError:
        return float('inf')
    except Exception as e:
        logger.error(f"Error in calculate_distance: {e}")
        return float('inf')

def interest_similarity(interests1, interests2):
    try:
        return len(set(interests1) & set(interests2))
    except Exception as e:
        logger.error(f"Error in interest_similarity: {e}")
        return 0

def get_matched_profiles(user_info, gender_preference):
    try:
        db: Session = next(get_db())
        all_users = db.query(User).filter(User.chat_id != user_info['chat_id']).all()
        
        matched_profiles = []
        for user in all_users:
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
            if gender_preference == 'BOTH' or partner_info['gender'] == gender_preference:
                distance = calculate_distance(user_info['location'], partner_info['location'])
                similarity = interest_similarity(user_info['interests'].split(', '), partner_info['interests'].split(', '))
                matched_profiles.append((partner_info, distance, similarity))
        
        matched_profiles.sort(key=lambda x: (x[1], -x[2]))
        return matched_profiles
    except Exception as e:
        logger.error(f"Error in get_matched_profiles: {e}")
        return []
    finally:
        try:
            db.close()
        except:
            pass

def send_tips():
    while True:
        for chat_id in users_interacted:
            index = tip_index.get(chat_id, 0)
            bot.send_message(chat_id, tips[index])
            tip_index[chat_id] = (index + 1) % len(tips)
        time.sleep(86400)  # Send a tip every 24 hours (86400 seconds)

def start_tip_thread():
    tip_thread = threading.Thread(target=send_tips)
    tip_thread.daemon = True
    tip_thread.start()

# Database fix command
@bot.message_handler(commands=['fixdb'])
def fix_database(message):
    """Admin command to manually fix database schema"""
    chat_id = message.chat.id
    
    # Replace with your admin chat ID or remove this check if you want anyone to use it
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

@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        chat_id = message.chat.id
        username = message.from_user.username

        # Check if the user is banned
        if check_banned(chat_id):
            bot.send_message(chat_id, "❌ You have been banned and cannot use this bot.")
            return  # Stop execution

        # Initialize user data if not already stored
        if chat_id not in user_data:
            user_data[chat_id] = {'username': username}

        # Show profile setup option
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add('Set Up Your Profile')
        msg = bot.reply_to(message, "Welcome! Please set up your profile.", reply_markup=markup)
        bot.register_next_step_handler(msg, ask_name)

    except Exception as e:
        logger.error(f"Error in send_welcome: {e}")
        bot.reply_to(message, "An unexpected error occurred. Please try again later.")

def ask_name(message):
    try:
        if message.text == 'Set Up Your Profile':
            chat_id = message.chat.id
            msg = bot.reply_to(message, "Please enter your name:")
            bot.register_next_step_handler(msg, ask_age)
    except Exception as e:
        logger.error(f"Error in ask_name: {e}")
        bot.reply_to(message, "An unexpected error occurred. Please try again later.")

def ask_age(message):
    try:
        chat_id = message.chat.id
        user_data[chat_id]['name'] = message.text
        msg = bot.reply_to(message, "Please enter your age:")
        bot.register_next_step_handler(msg, validate_age)
    except Exception as e:
        logger.error(f"Error in ask_age: {e}")
        bot.reply_to(message, "An unexpected error occurred. Please try again later.")

def validate_age(message):
    try:
        chat_id = message.chat.id
        if message.text.isdigit():
            user_data[chat_id]['age'] = message.text
            ask_gender(message)
        else:
            msg = bot.reply_to(message, "Invalid input. Please enter a valid number for your age:")
            bot.register_next_step_handler(msg, ask_age)
    except Exception as e:
        logger.error(f"Error in validate_age: {e}")
        bot.reply_to(message, "An unexpected error occurred. Please try again later.")

def ask_gender(message):
    try:
        chat_id = message.chat.id
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add(types.KeyboardButton("M"), types.KeyboardButton("F"))
        msg = bot.reply_to(message, "Please enter your gender (M or F):", reply_markup=markup)
        bot.register_next_step_handler(msg, validate_gender)
    except Exception as e:
        logger.error(f"Error in ask_gender: {e}")
        bot.reply_to(message, "An unexpected error occurred. Please try again later.")

def validate_gender(message):
    try:
        chat_id = message.chat.id
        gender = message.text.upper()
        if gender in ['M', 'F']:
            user_data[chat_id]['gender'] = gender
            ask_looking_for(message)
        else:
            msg = bot.reply_to(message, "Invalid input. Please enter 'M' or 'F'.")
            bot.register_next_step_handler(msg, ask_gender)
    except Exception as e:
        logger.error(f"Error in validate_gender: {e}")
        bot.reply_to(message, "An unexpected error occurred. Please try again later.")

def ask_looking_for(message):
    try:
        chat_id = message.chat.id
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add("1", "2")
        msg = bot.reply_to(message, "What are you looking for?\n1: Dating (matches with opposite gender)\n2: Friends (matches with both genders)", reply_markup=markup)
        bot.register_next_step_handler(msg, validate_looking_for)
    except Exception as e:
        logger.error(f"Error in ask_looking_for: {e}")
        bot.reply_to(message, "An unexpected error occurred. Please try again later.")

def validate_looking_for(message):
    try:
        chat_id = message.chat.id
        looking_for = message.text
        if looking_for in ['1', '2']:
            user_data[chat_id]['looking_for'] = looking_for
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            location_button = types.KeyboardButton("Share Location", request_location=True)
            markup.add(location_button)
            msg = bot.reply_to(message, "Please share your location or type it in:", reply_markup=markup)
            bot.register_next_step_handler(msg, handle_location_or_prompt_for_location)
        else:
            msg = bot.reply_to(message, "Invalid input. Please enter '1' or '2'.")
            bot.register_next_step_handler(msg, ask_looking_for)
    except Exception as e:
        logger.error(f"Error in validate_looking_for: {e}")
        bot.reply_to(message, "An unexpected error occurred. Please try again later.")

def handle_location_or_prompt_for_location(message):
    try:
        chat_id = message.chat.id
        if message.location:
            user_data[chat_id]['location'] = f"{message.location.latitude}, {message.location.longitude}"
        else:
            user_data[chat_id]['location'] = message.text
        msg = bot.reply_to(message, "Almost done! Please send a photo of yourself:")
        bot.register_next_step_handler(msg, ask_photo)
    except Exception as e:
        logger.error(f"Error in handle_location_or_prompt_for_location: {e}")
        bot.reply_to(message, "An unexpected error occurred. Please try again later.")

def ask_photo(message):
    try:
        chat_id = message.chat.id
        if message.content_type == 'photo':
            user_data[chat_id]['photo'] = message.photo[-1].file_id
            msg = bot.reply_to(message, "Almost done! Please enter your interests (separate keywords with commas):")
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

        # Ensure user_data exists for this chat_id
        if chat_id not in user_data:
            user_data[chat_id] = {}

        # Check if 'username' is missing and fetch from the database
        if 'username' not in user_data[chat_id]:
            user_info = get_user_info(chat_id)
            if user_info and 'username' in user_info:
                user_data[chat_id]['username'] = user_info['username']
            else:
                user_data[chat_id]['username'] = message.from_user.username or "Unknown"

        # Process interests
        user_data[chat_id]['interests'] = [interest.strip() for interest in message.text.split(',')]
        
        profile_summary = (
            f"Name: {user_data[chat_id]['name']}\n"
            f"Age: {user_data[chat_id]['age']}\n"
            f"Gender: {user_data[chat_id]['gender']}\n"
            f"Location: {user_data[chat_id]['location']}\n"
            f"Looking for: {'Dating' if user_data[chat_id]['looking_for'] == '1' else 'Friends'}\n"
            f"Interests: {', '.join(user_data[chat_id]['interests'])}"
        )
        bot.send_photo(chat_id, user_data[chat_id]['photo'], caption=f"Profile setup complete!\n\n{profile_summary}\n\n"
                                                                     "Commands:\n"
                                                                     "/my_profile - View and edit your profile\n"
                                                                     "/view_profiles - See other user profiles\n"
                                                                     "/random - Chat with a random user who's online\n"
                                                                     "/help - Get help")

        # Insert or update user data in the database
        success = save_user_to_db(chat_id, {
            'username': user_data[chat_id]['username'],
            'name': user_data[chat_id]['name'],
            'age': user_data[chat_id]['age'],
            'gender': user_data[chat_id]['gender'],
            'location': user_data[chat_id]['location'],
            'photo': user_data[chat_id]['photo'],
            'interests': ', '.join(user_data[chat_id]['interests']),
            'looking_for': user_data[chat_id]['looking_for']
        })

        if not success:
            bot.send_message(chat_id, "⚠️ There was an error saving your profile to the database.")

        logger.info(f"User data for {chat_id}: {user_data[chat_id]}")
    except Exception as e:
        logger.error(f"Error in ask_interests: {e}")
        bot.reply_to(message, "An unexpected error occurred. Please try again later.")

@bot.message_handler(commands=['profile'])
def show_stored_profile(message):
    try:
        chat_id = message.chat.id
        user_info = get_user_info(chat_id)
        if user_info:
            profile_summary = (
                f"Name: {user_info['name']}\n"
                f"Age: {user_info['age']}\n"
                f"Gender: {user_info['gender']}\n"
                f"Location: {user_info['location']}\n"
                f"Interests: {', '.join(user_info['interests'].split(', '))}"
            )
            bot.send_photo(chat_id, user_info['photo'], caption=f"{profile_summary}")
        else:
            bot.reply_to(message, "You need to set up your profile first.")
    except Exception as e:
        logger.error(f"Error in show_stored_profile: {e}")
        bot.reply_to(message, "An unexpected error occurred. Please try again later.")

def show_next_profile(chat_id):
    try:
        if not pending_users:
            bot.send_message(chat_id, "No more profiles to view try again later.")
            return

        next_user_chat_id = pending_users.pop(0)
        user_info = get_user_info(next_user_chat_id)

        if user_info:
            profile_summary = (
                f"Name: {user_info['name']}\n"
                f"Age: {user_info['age']}\n"
                f"Gender: {user_info['gender']}\n"
                f"Location: {user_info['location']}\n"
                f"Interests: {', '.join(user_info['interests'].split(', '))}"
            )
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("Like", callback_data=f"like_{next_user_chat_id}"),
                types.InlineKeyboardButton("Write a note", callback_data=f"note_{next_user_chat_id}"),
                types.InlineKeyboardButton("Dislike", callback_data=f"dislike_{next_user_chat_id}")
            )
            bot.send_photo(chat_id, user_info['photo'], caption=f"{profile_summary}", reply_markup=markup)
        else:
            show_next_profile(chat_id)
    except Exception as e:
        logger.error(f"Error in show_next_profile: {e}")
        bot.send_message(chat_id, "An unexpected error occurred. Please try again later.")
        show_next_profile(chat_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('like_') or call.data.startswith('dislike_') or call.data.startswith('note_'))
def handle_inline_response(call):
    try:
        # Extract action and target chat ID from callback data
        action, other_user_chat_id = call.data.split('_')
        chat_id = call.message.chat.id

        # Retrieve user and liked user info
        user_info = get_user_info(chat_id)
        liked_user_info = get_user_info(other_user_chat_id)

        if not user_info:
            bot.send_message(chat_id, "Your profile information could not be retrieved.")
            return

        if not liked_user_info:
            bot.send_message(chat_id, "The selected profile information could not be retrieved.")
            return

        # Handle actions
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
        bot.send_message(call.message.chat.id, "An unexpected error occurred. Please try again later.")

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
        db: Session = next(get_db())
        mutual_like = db.query(Like).filter(
            Like.liker_chat_id == liked_chat_id,
            Like.liked_chat_id == liker_chat_id
        ).first()
        
        if mutual_like:
            bot.send_message(liker_chat_id, f"You and {liked_user_info['name']} liked each other! Start chatting.")
            bot.send_message(liked_chat_id, f"You and {user_info['name']} liked each other! Start chatting.")
        
        db.close()

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
        user_data[liker_chat_id]['current_liked_chat_id'] = liked_chat_id
        bot.send_message(liker_chat_id, "✍️ Please type your note:")
        
        # Register next step handler
        bot.register_next_step_handler_by_chat_id(liker_chat_id, save_note)
    except Exception as e:
        logger.error(f"Error in handle_send_note_action: {e}")
        bot.send_message(liker_chat_id, "An unexpected error occurred. Please try again later.")

def save_note(message):
    try:
        chat_id = message.chat.id
        note = message.text
        
        # Get the liked chat ID from user_data
        liked_chat_id = user_data.get(chat_id, {}).get('current_liked_chat_id')
        if not liked_chat_id:
            bot.send_message(chat_id, "❌ No profile selected to send a note.")
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
            show_next_profile(chat_id)
    except Exception as e:
        logger.error(f"Error in save_note: {e}")
        bot.send_message(chat_id, "An unexpected error occurred. Please try again later.")
        show_next_profile(chat_id)

@bot.message_handler(commands=['my_profile'])
def my_profile(message):
    chat_id = message.chat.id
    user_info = get_user_info(chat_id)
    if user_info:
        profile_summary = (
            f"Name: {user_info['name']}\n"
            f"Age: {user_info['age']}\n"
            f"Gender: {user_info['gender']}\n"
            f"Location: {user_info['location']}\n"
            f"Looking for: {'Dating' if user_info['looking_for'] == '1' else 'Friends'}\n"
            f"Interests: {', '.join(user_info['interests'].split(', '))}"
        )
        bot.send_photo(chat_id, user_info['photo'], caption=f"Your profile:\n\n{profile_summary}")
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("/edit_profile")
        bot.send_message(chat_id, "You can edit your profile using the button below.", reply_markup=markup)
    else:
        bot.reply_to(message, "No profile found. Please set up your profile using /start.")

@bot.message_handler(commands=['edit_profile'])
def edit_profile(message):
    chat_id = message.chat.id
    if chat_id not in user_data:
        user_data[chat_id] = {}
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("Name", "Age", "Gender", "Location", "Photo", "Interests", "Looking for")
    msg = bot.reply_to(message, "What would you like to edit?", reply_markup=markup)
    bot.register_next_step_handler(msg, handle_edit_choice)

def handle_edit_choice(message):
    chat_id = message.chat.id
    edit_choice = message.text.lower()
    if edit_choice in ['name', 'age', 'gender', 'location', 'photo', 'interests', 'looking for']:
        if edit_choice == 'looking for':
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            markup.add("Dating", "Friends")
            msg = bot.reply_to(message, "What are you looking for? (Dating or Friends):", reply_markup=markup)
            bot.register_next_step_handler(msg, save_edit, edit_choice)
        else:
            msg = bot.reply_to(message, f"Please enter your new {edit_choice}:")
            bot.register_next_step_handler(msg, save_edit, edit_choice)
    else:
        msg = bot.reply_to(message, "Invalid choice. Please choose again.")
        bot.register_next_step_handler(msg, handle_edit_choice)

def save_edit(message, edit_choice):
    chat_id = message.chat.id
    new_value = message.text
    if edit_choice == 'age' and not new_value.isdigit():
        msg = bot.reply_to(message, "Invalid input. Please enter a valid number for your age:")
        bot.register_next_step_handler(msg, save_edit, edit_choice)
        return
    if edit_choice == 'photo' and message.content_type != 'photo':
        msg = bot.reply_to(message, "Please send a photo.")
        bot.register_next_step_handler(msg, save_edit, edit_choice)
        return

    if edit_choice == 'photo':
        new_value = message.photo[-1].file_id
    elif edit_choice == 'interests':
        new_value = ', '.join([interest.strip() for interest in new_value.split(',')])
    elif edit_choice == 'looking for':
        new_value = '1' if new_value.lower() == 'dating' else '2'

    # Update database
    field_map = {
        'name': 'name',
        'age': 'age',
        'gender': 'gender',
        'location': 'location',
        'photo': 'photo',
        'interests': 'interests',
        'looking for': 'looking_for'
    }
    
    db_field = field_map.get(edit_choice)
    if db_field:
        success = update_user_field(chat_id, db_field, new_value)
        if success:
            user_data[chat_id][edit_choice.replace(" ", "_")] = new_value
            bot.reply_to(message, f"Your {edit_choice} has been updated.")
        else:
            bot.reply_to(message, f"Error updating your {edit_choice}.")
    
    # Return to /my_profile after editing
    my_profile(message)

@bot.message_handler(commands=['view_profiles'])
def show_profiles(message):
    chat_id = message.chat.id
    try:
        user_info = get_user_info(chat_id)
        if user_info:
            gender_preference = get_gender_preference(user_info)
            matched_profiles = get_matched_profiles(user_info, gender_preference)
            if matched_profiles:
                if chat_id not in user_data:
                    user_data[chat_id] = {}
                user_data[chat_id]['matched_profiles'] = matched_profiles
                user_data[chat_id]['current_profile_index'] = 0
                display_profile(chat_id, matched_profiles[0][0])
            else:
                bot.reply_to(message, "No matched profiles found.")
        else:
            bot.reply_to(message, "No profile found. Please set up your profile using /start.")
    except Exception as e:
        logger.error(f"Error in show_profiles: {e}")
        bot.reply_to(message, "An unexpected error occurred. Please try again later.")

def get_gender_preference(user_info):
    if user_info['looking_for'] == '2':
        return 'BOTH'
    else:
        return 'F' if user_info['gender'] == 'M' else 'M'

def display_profile(chat_id, profile):
    try:
        profile_summary = (
            f"Name: {profile['name']}\n"
            f"Age: {profile['age']}\n"
            f"Gender: {profile['gender']}\n"
            f"Location: {profile['location']}\n"
            f"Interests: {', '.join(profile['interests'].split(', '))}"
        )
        bot.send_photo(chat_id, profile['photo'], caption=f"Matched profile:\n\n{profile_summary}")

        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        btn_like = types.KeyboardButton("👍 Like")
        btn_dislike = types.KeyboardButton("👎 Dislike")
        btn_note = types.KeyboardButton("✍️ Write Note")
        markup.add(btn_like, btn_dislike, btn_note)

        bot.send_message(chat_id, "Do you like this profile?", reply_markup=markup)
    except Exception as e:
        logger.error(f"Error in display_profile: {e}")
        display_next_profile(chat_id)

@bot.message_handler(func=lambda message: message.text in ["👍 Like", "👎 Dislike", "✍️ Write Note"])
def handle_text_response(message):
    chat_id = message.chat.id

    try:
        # Ensure user has matched profiles stored
        if chat_id not in user_data or 'matched_profiles' not in user_data[chat_id]:
            return

        # Get the current profile index safely
        current_index = user_data[chat_id].get('current_profile_index', -1)
        matched_profiles = user_data[chat_id]['matched_profiles']

        # Ensure index is within range
        if current_index < 0 or current_index >= len(matched_profiles):
            return

        # Extract the correct profile data from tuple
        profile_tuple = matched_profiles[current_index]

        if isinstance(profile_tuple, tuple) and len(profile_tuple) > 0:
            if isinstance(profile_tuple[0], dict):
                profile_data = profile_tuple[0]
            else:
                return
        else:
            return

        # Retrieve the matched user's chat ID
        other_user_chat_id = profile_data.get('chat_id')
        if not isinstance(other_user_chat_id, int):
            return

        # Handle user actions
        if message.text == "👍 Like":
            handle_like(chat_id, other_user_chat_id)
        elif message.text == "👎 Dislike":
            display_next_profile(chat_id)
        elif message.text == "✍️ Write Note":
            user_data[chat_id]['current_liked_chat_id'] = other_user_chat_id
            bot.send_message(chat_id, "✍️ Please type your note:")
            bot.register_next_step_handler(message, handle_note_input)

    except Exception as e:
        logger.error(f"Error in handle_text_response: {e}")

def handle_like(liker_chat_id, liked_chat_id):
    try:
        # Retrieve user info
        user_info = get_user_info(liker_chat_id)
        liked_user_info = get_user_info(liked_chat_id)

        if not user_info:
            bot.send_message(liker_chat_id, "Your profile information could not be retrieved.")
            return

        if liked_user_info:
            # Notify the liked user with the updated button
            markup = InlineKeyboardMarkup()
            btn_see_who = InlineKeyboardButton("👀 See Who Liked You", callback_data="view_likes")
            btn_dislike = InlineKeyboardButton("❌ Dislike", callback_data=f"dislike_{liker_chat_id}")
            markup.add(btn_see_who, btn_dislike)

            bot.send_message(
                liked_chat_id,
                "Someone liked your profile! Use the buttons below:",
                reply_markup=markup
            )

        # Save like in the database
        save_like(liker_chat_id, liked_chat_id)

        # Show the next profile to the liker
        display_next_profile(liker_chat_id)

    except Exception as e:
        logger.error(f"Error in handle_like: {e}")
        bot.send_message(liker_chat_id, "An unexpected error occurred. Please try again later.")
        display_next_profile(liker_chat_id)

def handle_note_input(message):
    chat_id = message.chat.id
    note_text = message.text.strip()
    
    # Get the liked chat ID from user_data
    liked_chat_id = user_data.get(chat_id, {}).get('current_liked_chat_id')
    if not liked_chat_id:
        bot.send_message(chat_id, "❌ No profile selected to send a note.")
        return
    
    # Save note with like
    save_like(chat_id, liked_chat_id, note_text)
    
    # Notify the recipient
    user_info = get_user_info(chat_id)
    if user_info:
        note_message = f"📩 Someone sent you a note:\n\n{note_text}\n\nFrom: {user_info['name']}"
        bot.send_message(liked_chat_id, note_message)
    
    bot.send_message(chat_id, "✅ Your note has been sent!")
    display_next_profile(chat_id)

def display_next_profile(chat_id):
    try:
        # Ensure user data exists
        if chat_id not in user_data or 'matched_profiles' not in user_data[chat_id]:
            return

        matched_profiles = user_data[chat_id]['matched_profiles']
        current_index = user_data[chat_id].get('current_profile_index', -1)

        # Ensure there are more profiles to display
        if current_index + 1 < len(matched_profiles):
            # Move to the next profile
            current_index += 1
            user_data[chat_id]['current_profile_index'] = current_index

            # Extract profile correctly
            profile_tuple = matched_profiles[current_index]
            if isinstance(profile_tuple, tuple) and len(profile_tuple) > 0 and isinstance(profile_tuple[0], dict):
                profile_data = profile_tuple[0]
            else:
                return

            # Display the profile
            display_profile(chat_id, profile_data)
        else:
            bot.send_message(chat_id, "No more profiles to display.")

    except Exception as e:
        logger.error(f"Error in display_next_profile: {e}")

@bot.message_handler(commands=['view_likes'])
def handle_view_likes(message):
    """Fetch and display profiles of users who liked the current user, with pagination."""
    try:
        chat_id = message.chat.id if hasattr(message, 'chat') else message.message.chat.id
        offset = 0
        limit = 5

        # Call the helper function to show likes
        display_likes(chat_id, offset, limit)
    except Exception as e:
        logger.error(f"Error in /view_likes: {e}")
        bot.send_message(chat_id, "An error occurred while fetching your likes. Please try again later.")

def display_likes(chat_id, offset, limit):
    """Helper function to display likes with pagination, including notes if available."""
    try:
        # Fetch likes from database
        likes = get_likes_for_user(chat_id, limit, offset)

        if not likes:
            bot.send_message(chat_id, "No one has liked your profile yet.")
            return

        # Display each liker's profile
        for like in likes:
            profile_details = f"{like['name']}, {like['age']}, {like['location']}, {like['interests']}\nUsername: @{like['username'] if like['username'] else 'No username'}"

            # Include note if available
            if like['note']:
                profile_details += f"\n\n📝 Note: {like['note']}"

            try:
                bot.send_photo(
                    chat_id,
                    like['photo'],
                    caption=profile_details,
                    reply_markup=generate_like_dislike_buttons(like['liker_chat_id'], chat_id)
                )
            except Exception as photo_error:
                logger.error(f"Error sending photo: {photo_error}")
                bot.send_message(chat_id, f"{profile_details}\n\n(⚠️ Unable to load photo)")

        # Check if there are more likes
        db: Session = next(get_db())
        total_likes = db.query(Like).filter(Like.liked_chat_id == chat_id).count()
        db.close()

        # Create navigation buttons if there are more likes
        markup = InlineKeyboardMarkup()

        if offset + limit < total_likes:
            # Add "Previous" button to fetch older likes
            markup.add(InlineKeyboardButton("Previous", callback_data=f"view_likes_previous:{offset + limit}"))

        if offset > 0:
            # Add "Next" button to fetch newer likes
            prev_offset = max(offset - limit, 0)
            markup.add(InlineKeyboardButton("Next", callback_data=f"view_likes_previous:{prev_offset}"))

        if markup.keyboard:
            bot.send_message(chat_id, "Use the buttons below to navigate likes:", reply_markup=markup)
    except Exception as e:
        logger.error(f"Error in display_likes: {e}")
        bot.send_message(chat_id, "An error occurred while fetching likes. Please try again later.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("view_likes_previous"))
def handle_view_likes_callback(call):
    """Handle 'Previous' button to paginate through likes."""
    try:
        chat_id = call.message.chat.id
        data = call.data.split(":")
        offset = int(data[1])
        limit = 5

        # Call the helper function to display likes with updated offset
        display_likes(chat_id, offset, limit)
    except Exception as e:
        logger.error(f"Error in handle_view_likes_callback: {e}")
        bot.send_message(chat_id, "An error occurred while fetching likes. Please try again later.")

def generate_like_dislike_buttons(liker_id, liked_id):
    """Generate inline buttons for Like and Dislike actions."""
    user_likes[liked_id] = liker_id

    markup = InlineKeyboardMarkup()
    like_button = InlineKeyboardButton("👍 Like", callback_data=f"like_{liker_id}")
    dislike_button = InlineKeyboardButton("👎 Dislike", callback_data=f"dislike_{liker_id}")
    report_button = InlineKeyboardButton("🚩 Report", callback_data=f"report_{liked_id}")
    markup.row(like_button, dislike_button)
    markup.add(report_button)
    return markup

@bot.callback_query_handler(func=lambda call: call.data.startswith("like_") or call.data.startswith("dislike_"))
def handle_like_dislike(call):
    try:
        liker_id = call.from_user.id
        liked_disliked_id = int(call.data.split("_")[1])
        action = call.data.split("_")[0]

        if action == "like":
            bot.answer_callback_query(call.id, "You liked the person!")
            bot.send_message(liked_disliked_id, "Someone liked you!")
        elif action == "dislike":
            bot.answer_callback_query(call.id, "You disliked the person!")

        # Match with the next profile
        bot.send_message(liker_id, "Finding your next match...")
        find_random_chat(types.Message(chat=types.Chat(id=liker_id), text="M, F, or Both"))
    except Exception as e:
        logger.error(f"Error in handle_like_dislike: {e}")

@bot.message_handler(commands=['help'])
def help_command(message):
    try:
        help_text = (
            "Welcome to our bot! Here's how to use it:\n\n"
            "1️⃣ *Create a Community*: Use /community to create your own community or to join communities you like.\n\n"
            "2️⃣ *View and Match Profiles*: Use /view_profiles to browse through profiles. You can like, dislike, or report profiles.\n\n"
            "3️⃣ *Random Chats*: Use /random to chat with random users within the bot.\n\n"
            "4️⃣ *Submit a Complaint*: To report issues or provide feedback, please send your concerns directly to @meh9061.\n\n"
            "5️⃣ *Contact Us*: For any inquiries, you can reach us at:\n"
            "   - 📧 Email: natnaeltakele36@gmail.com\n"
            "   - 📞 Phone: +251935519061\n\n"
            "We're here to help you! 😊"
        )

        bot.send_message(message.chat.id, help_text)
    except Exception as e:
        logger.error(f"Error in help_command: {e}")
        bot.send_message(message.chat.id, "Something went wrong. Please try again.")

@bot.message_handler(commands=['community'])
def community_options(message):
    chat_id = message.chat.id
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
    user_data[chat_id] = {'group_name': message.text}
    msg = bot.send_message(chat_id, "Please enter the group's description:")
    bot.register_next_step_handler(msg, ask_group_description)

def ask_group_description(message):
    chat_id = message.chat.id
    user_data[chat_id]['group_description'] = message.text
    msg = bot.send_message(chat_id, "Please send the group's profile picture:")

@bot.message_handler(content_types=['photo'])
def handle_group_photo(message):
    chat_id = message.chat.id
    if chat_id in user_data and 'group_description' in user_data[chat_id]:
        file_info = bot.get_file(message.photo[-1].file_id)
        user_data[chat_id]['group_photo'] = file_info.file_id
        msg = bot.send_message(chat_id, "Please enter the group's invite link:")
        bot.register_next_step_handler(msg, register_group)
    else:
        bot.send_message(chat_id, "Please start the community creation process with /community.")

def register_group(message):
    chat_id = message.chat.id
    invite_link = message.text
    group_name = user_data[chat_id]['group_name']
    group_description = user_data[chat_id]['group_description']
    group_photo = user_data[chat_id]['group_photo']

    try:
        db: Session = next(get_db())
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
        bot.send_message(chat_id, "Your group has been registered successfully!")
    except Exception as err:
        logger.error(f"Error registering group: {err}")
        bot.send_message(chat_id, f"Error: {err}")
    finally:
        try:
            db.close()
        except:
            pass

def list_communities(message):
    chat_id = message.chat.id
    try:
        db: Session = next(get_db())
        groups = db.query(Group).all()

        if groups:
            for group in groups:
                markup = types.InlineKeyboardMarkup()
                button = types.InlineKeyboardButton("Check out the group", url=group.invite_link)
                markup.add(button)
                caption = f"Name: {group.name}\nDescription: {group.description}"
                
                try:
                    bot.send_photo(chat_id, group.photo, caption=caption, reply_markup=markup)
                except:
                    bot.send_message(chat_id, f"{caption}\n\n{group.invite_link}", reply_markup=markup)
        else:
            bot.send_message(chat_id, "No communities found.")
    except Exception as e:
        logger.error(f"Error listing communities: {e}")
        bot.send_message(chat_id, "Error loading communities.")
    finally:
        try:
            db.close()
        except:
            pass

@bot.message_handler(commands=['random'])
def ask_match_preference(message):
    chat_id = message.chat.id
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("M"), types.KeyboardButton("F"), types.KeyboardButton("Both"))
    msg = bot.reply_to(message, "Who would you like to be matched with? (M, F, or Both):", reply_markup=markup)
    bot.register_next_step_handler(msg, find_random_chat)

def find_random_chat(message):
    chat_id = message.chat.id
    gender_preference = message.text.upper()

    if chat_id not in user_data:
        user_data[chat_id] = {}

    if chat_id in pending_users:
        bot.reply_to(message, "You are already in the queue. Please wait for a match.")
        return

    user_info = get_user_info(chat_id)
    if not user_info:
        bot.reply_to(message, "Please set up your profile using /start.")
        return

    matched_profiles = get_matched_profiles(user_info, gender_preference)
    
    if matched_profiles:
        partner_info = matched_profiles[0][0]
        partner_chat_id = partner_info['chat_id']

        if partner_chat_id in pending_users:
            pending_users.remove(partner_chat_id)
            
            if partner_chat_id not in user_data:
                user_data[partner_chat_id] = {}

            user_data[chat_id]['partner'] = partner_chat_id
            user_data[partner_chat_id]['partner'] = chat_id

            show_profiles(chat_id, partner_chat_id)

            bot.send_message(chat_id, "You have been matched! Say hi to your new friend.")
            bot.send_message(partner_chat_id, "You have been matched! Say hi to your new friend.")

            end_markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            end_markup.add("End")
            bot.send_message(chat_id, "Type 'End' to end the chat.", reply_markup=end_markup)
            bot.send_message(partner_chat_id, "Type 'End' to end the chat.", reply_markup=end_markup)

        else:
            pending_users.append(chat_id)
            bot.reply_to(message, "Waiting for a match...")
    else:
        pending_users.append(chat_id)
        bot.reply_to(message, "Waiting for a match...")

def show_profiles(chat_id, partner_chat_id):
    user_info = get_user_info(chat_id)
    partner_info = get_user_info(partner_chat_id)
    
    if user_info and partner_info:
        user_profile_summary = (
            f"Name: {user_info['name']}\n"
            f"Age: {user_info['age']}\n"
            f"Gender: {user_info['gender']}\n"
            f"Location: {user_info['location']}\n"
            f"Looking for: {'Dating' if user_info['looking_for'] == '1' else 'Friends'}\n"
            f"Interests: {', '.join(user_info['interests'].split(', '))}"
        )
        partner_profile_summary = (
            f"Name: {partner_info['name']}\n"
            f"Age: {partner_info['age']}\n"
            f"Gender: {partner_info['gender']}\n"
            f"Location: {partner_info['location']}\n"
            f"Looking for: {'Dating' if partner_info['looking_for'] == '1' else 'Friends'}\n"
            f"Interests: {', '.join(partner_info['interests'].split(', '))}"
        )

        bot.send_photo(chat_id, partner_info['photo'], caption=f"Your match's profile:\n\n{partner_profile_summary}")
        bot.send_photo(partner_chat_id, user_info['photo'], caption=f"Your match's profile:\n\n{user_profile_summary}")

@bot.message_handler(func=lambda message: True)
def relay_message(message):
    chat_id = message.chat.id
    if chat_id in user_data and 'partner' in user_data[chat_id]:
        partner_chat_id = user_data[chat_id]['partner']
        if message.text.lower() == 'end':
            end_chat(chat_id)
        else:
            bot.send_message(partner_chat_id, message.text)

def end_chat(chat_id):
    try:
        if chat_id in user_data and 'partner' in user_data[chat_id]:
            partner_chat_id = user_data[chat_id]['partner']

            markup = generate_like_dislike_buttons(chat_id, partner_chat_id)
            partner_markup = generate_like_dislike_buttons(partner_chat_id, chat_id)

            bot.send_message(partner_chat_id, "Do you like the person you just talked with?", reply_markup=markup)
            bot.send_message(chat_id, "Do you like the person you just talked with?", reply_markup=partner_markup)

            user_data[chat_id].pop('partner', None)
            if partner_chat_id in user_data:
                user_data[partner_chat_id].pop('partner', None)

        else:
            bot.send_message(chat_id, "❌ You are not in a chat currently.")

    except Exception as e:
        logger.error(f"Error in end_chat: {e}")

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
        db: Session = next(get_db())
        reports = db.query(Report).filter(Report.reported_chat_id == reported_chat_id).all()
        report_count = len(reports)
        db.close()
        
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
                db: Session = next(get_db())
                banned = BannedUser(user_id=reported_chat_id)
                db.add(banned)
                db.commit()
                db.close()
            except:
                pass

        bot.send_message(reporter_chat_id, "Finding your next match...")
        find_random_chat(types.Message(chat=types.Chat(id=reporter_chat_id), text="M, F, or Both"))

    except Exception as e:
        logger.error(f"Error processing check_reports: {e}")
    finally:
        try:
            db.close()
        except:
            pass

# Start the bot with proper error handling
if __name__ == '__main__':
    logger.info("Bot starting...")
    
    # Remove any existing webhook first (important!)
    try:
        bot.remove_webhook()
        time.sleep(1)
    except:
        pass
    
    # Start tip thread
    start_tip_thread()
    
    # Start polling with skip_pending to avoid 409 error
    while True:
        try:
            logger.info("Starting bot polling...")
            bot.polling(none_stop=True, interval=0, timeout=20, skip_pending=True)
        except Exception as e:
            logger.error(f"Bot polling error: {e}")
            logger.info("Restarting in 5 seconds...")
            time.sleep(5)
