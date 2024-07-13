import random
import mysql.connector
from telebot import TeleBot
from constant import API_KEY
from telebot import types
from geopy.distance import geodesic

bot = TeleBot(API_KEY, parse_mode=None)

conn = mysql.connector.connect(
    host="127.0.0.1",
    user="root",
    password="Jj1995@idk",
    database="telegram_bot"
)
cursor = conn.cursor()

user_data = {}
pending_users = []

@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id
    if chat_id not in user_data:
        user_data[chat_id] = {}
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add('Set Up Your Profile')
    msg = bot.reply_to(message, "Welcome! Please set up your profile.", reply_markup=markup)
    bot.register_next_step_handler(msg, ask_name)

def ask_name(message):
    if message.text == 'Set Up Your Profile':
        chat_id = message.chat.id
        msg = bot.reply_to(message, "Please enter your name:")
        bot.register_next_step_handler(msg, ask_age)

def ask_age(message):
    chat_id = message.chat.id
    user_data[chat_id]['name'] = message.text
    msg = bot.reply_to(message, "Please enter your age:")
    bot.register_next_step_handler(msg, validate_age)

def validate_age(message):
    chat_id = message.chat.id
    if message.text.isdigit():
        user_data[chat_id]['age'] = message.text
        ask_gender(message)
    else:
        msg = bot.reply_to(message, "Invalid input. Please enter a valid number for your age:")
        bot.register_next_step_handler(msg, ask_age)

def ask_gender(message):
    chat_id = message.chat.id
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("M"), types.KeyboardButton("F"))
    msg = bot.reply_to(message, "Please enter your gender (M or F):", reply_markup=markup)
    bot.register_next_step_handler(msg, validate_gender)

def validate_gender(message):
    chat_id = message.chat.id
    gender = message.text.upper()
    if gender in ['M', 'F']:
        user_data[chat_id]['gender'] = gender
        ask_looking_for(message)
    else:
        msg = bot.reply_to(message, "Invalid input. Please enter 'M' or 'F'.")
        bot.register_next_step_handler(msg, ask_gender)

def ask_looking_for(message):
    chat_id = message.chat.id
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("1", "2")
    msg = bot.reply_to(message, "What are you looking for?\n1: Dating (matches with opposite gender)\n2: Friends (matches with both genders)", reply_markup=markup)
    bot.register_next_step_handler(msg, validate_looking_for)

def validate_looking_for(message):
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

def handle_location_or_prompt_for_location(message):
    chat_id = message.chat.id
    if message.location:
        user_data[chat_id]['location'] = f"{message.location.latitude}, {message.location.longitude}"
    else:
        user_data[chat_id]['location'] = message.text
    msg = bot.reply_to(message, "Almost done! Please send a photo of yourself:")
    bot.register_next_step_handler(msg, ask_photo)

def ask_photo(message):
    chat_id = message.chat.id
    if message.content_type == 'photo':
        user_data[chat_id]['photo'] = message.photo[-1].file_id
        msg = bot.reply_to(message, "Almost done! Please enter your interests (separate keywords with commas):")
        bot.register_next_step_handler(msg, ask_interests)
    else:
        msg = bot.reply_to(message, "Please send a photo.")
        bot.register_next_step_handler(msg, ask_photo)

def ask_interests(message):
    chat_id = message.chat.id
    user_data[chat_id]['interests'] = [interest.strip() for interest in message.text.split(',')]
    profile_summary = (
        f"Name: {user_data[chat_id]['name']}\n"
        f"Age: {user_data[chat_id]['age']}\n"
        f"Gender: {user_data[chat_id]['gender']}\n"
        f"Location: {user_data[chat_id]['location']}\n"
        f"Looking for: {'Dating' if user_data[chat_id]['looking_for'] == '1' else 'Friends'}\n"
        f"Interests: {', '.join(user_data[chat_id]['interests'])}"
    )
    bot.send_photo(chat_id, user_data[chat_id]['photo'], caption=f"Profile setup complete!\n\n{profile_summary}")

    cursor.execute('''INSERT INTO users (chat_id, name, age, gender, location, photo, interests, looking_for)
                      VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                      ON DUPLICATE KEY UPDATE
                      name = VALUES(name),
                      age = VALUES(age),
                      gender = VALUES(gender),
                      location = VALUES(location),
                      photo = VALUES(photo),
                      interests = VALUES(interests),
                      looking_for = VALUES(looking_for)''',
                   (chat_id,
                    user_data[chat_id]['name'],
                    user_data[chat_id]['age'],
                    user_data[chat_id]['gender'],
                    user_data[chat_id]['location'],
                    user_data[chat_id]['photo'],
                    ', '.join(user_data[chat_id]['interests']),
                    user_data[chat_id]['looking_for']))
    conn.commit()

    print(f"User data for {chat_id}: {user_data[chat_id]}")

@bot.message_handler(commands=['profile'])
def show_stored_profile(message):
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
        bot.send_photo(chat_id, user_info['photo'], caption=f"Your stored profile:\n\n{profile_summary}")
    else:
        bot.reply_to(message, "No profile found. Please set up your profile using /start.")

def get_user_info(chat_id):
    cursor.execute('SELECT * FROM users WHERE chat_id = %s', (chat_id,))
    result = cursor.fetchone()
    if result:
        user_info = {
            'chat_id': result[0],
            'name': result[1],
            'age': result[2],
            'gender': result[3],
            'location': result[4],
            'photo': result[5],
            'interests': result[6],
            'looking_for': result[7]
        }
        return user_info
    return None

def interest_similarity(interests1, interests2):
    set1 = set(interests1)
    set2 = set(interests2)
    return len(set1 & set2) / len(set1 | set2)

def calculate_distance(loc1, loc2):
    try:
        coords_1 = tuple(map(float, loc1.split(", ")))
        coords_2 = tuple(map(float, loc2.split(", ")))
        return geodesic(coords_1, coords_2).kilometers
    except ValueError:
        return float('inf')

def get_matched_profiles(user_info, gender_preference):
    if gender_preference == 'M':
        gender_condition = 'gender = "M"'
    elif gender_preference == 'F':
        gender_condition = 'gender = "F"'
    else:
        gender_condition = 'gender IN ("M", "F")'

    looking_for = user_info['looking_for']
    if looking_for == '1':
        cursor.execute(f'SELECT * FROM users WHERE {gender_condition} AND looking_for = %s', ('1',))
    else:
        cursor.execute(f'SELECT * FROM users WHERE {gender_condition} AND looking_for = %s', ('2',))

    results = cursor.fetchall()
    matched_profiles = []

    for result in results:
        other_user_info = {
            'chat_id': result[0],
            'name': result[1],
            'age': result[2],
            'gender': result[3],
            'location': result[4],
            'photo': result[5],
            'interests': result[6],
            'looking_for': result[7]
        }
        age_difference = abs(int(user_info['age']) - int(other_user_info['age']))
        distance = calculate_distance(user_info['location'], other_user_info['location'])
        similarity_score = interest_similarity(user_info['interests'].split(', '), other_user_info['interests'].split(', '))
        matched_profiles.append((other_user_info, age_difference, distance, similarity_score))

    matched_profiles.sort(key=lambda x: (x[1], x[2], -x[3]))
    return matched_profiles

##my profile 

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
            f"Interests: {', '.join(user_info['interests'])}"
        ) 

        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add('Edit Name', 'Edit Age', 'Edit Gender', 'Edit Location', 'Edit Interests')

        # Send the profile picture along with the profile summary
        bot.send_photo(chat_id, user_info['photo'], caption=f"Your stored profile:\n\n{profile_summary}", reply_markup=markup)
        msg = bot.send_message(chat_id, "Choose what you want to edit:", reply_markup=markup)
        bot.register_next_step_handler(msg, edit_profile)
    else:
        bot.reply_to(message, "No profile found. Please set up your profile using /start.")

def edit_profile(message):
    chat_id = message.chat.id
    if message.text == 'Edit Name':
        msg = bot.reply_to(message, "Please enter your new name:")
        bot.register_next_step_handler(msg, update_name)
    elif message.text == 'Edit Age':
        msg = bot.reply_to(message, "Please enter your new age:")
        bot.register_next_step_handler(msg, validate_and_update_age)
    elif message.text == 'Edit Gender':
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add(types.KeyboardButton("M"), types.KeyboardButton("F"))
        msg = bot.reply_to(message, "Please enter your new gender (M or F):", reply_markup=markup)
        bot.register_next_step_handler(msg, validate_and_update_gender)
    elif message.text == 'Edit Location':
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        location_button = types.KeyboardButton("Share Location", request_location=True)
        markup.add(location_button)
        msg = bot.reply_to(message, "Please share your new location or type it in:", reply_markup=markup)
        bot.register_next_step_handler(msg, update_location)
    elif message.text == 'Edit Interests':
        msg = bot.reply_to(message, "Please enter your new interests (separate keywords with commas):")
        bot.register_next_step_handler(msg, update_interests)
    else:
        bot.reply_to(message, "Invalid option")

def update_name(message):
    chat_id = message.chat.id
    new_name = message.text
    cursor.execute('UPDATE users SET name = %s WHERE chat_id = %s', (new_name, chat_id))
    conn.commit()
    bot.reply_to(message, f"Your name has been updated to {new_name}")

def validate_and_update_age(message):
    chat_id = message.chat.id
    if message.text.isdigit():
        new_age = message.text
        cursor.execute('UPDATE users SET age = %s WHERE chat_id = %s', (new_age, chat_id))
        conn.commit()
        bot.reply_to(message, f"Your age has been updated to {new_age}")
    else:
        msg = bot.reply_to(message, "Invalid input. Please enter a valid number for your age:")
        bot.register_next_step_handler(msg, validate_and_update_age)

def validate_and_update_gender(message):
    chat_id = message.chat.id
    gender = message.text.upper()
    if gender in ['M', 'F']:
        cursor.execute('UPDATE users SET gender = %s WHERE chat_id = %s', (gender, chat_id))
        conn.commit()
        bot.reply_to(message, f"Your gender has been updated to {gender}")
    else:
        msg = bot.reply_to(message, "Invalid input. Please enter 'M' or 'F'.")
        bot.register_next_step_handler(msg, validate_and_update_gender)

def update_location(message):
    chat_id = message.chat.id
    if message.location:
        new_location = f"{message.location.latitude}, {message.location.longitude}"
    else:
        new_location = message.text
    cursor.execute('UPDATE users SET location = %s WHERE chat_id = %s', (new_location, chat_id))
    conn.commit()
    bot.reply_to(message, f"Your location has been updated to {new_location}")

def update_interests(message):
    chat_id = message.chat.id
    new_interests = [interest.strip() for interest in message.text.split(',')]
    cursor.execute('UPDATE users SET interests = %s WHERE chat_id = %s', (', '.join(new_interests), chat_id))
    conn.commit()
    bot.reply_to(message, f"Your interests have been updated to {', '.join(new_interests)}")


@bot.message_handler(commands=['view_profiles'])
def show_profiles(message):
    chat_id = message.chat.id
    user_info = get_user_info(chat_id)
    if user_info:
        matched_profiles = get_matched_profiles(user_info)
        if matched_profiles:
            if chat_id not in user_data:
                user_data[chat_id] = {}
            user_data[chat_id]['matched_profiles'] = matched_profiles
            user_data[chat_id]['current_profile_index'] = 0
            display_profile(chat_id, matched_profiles[0])
        else:
            bot.reply_to(message, "No matched profiles found.")
    else:
        bot.reply_to(message, "No profile found. Please set up your profile using /start.")

def display_profile(chat_id, profile):
    profile_summary = (
        f"Name: {profile['name']}\n"
        f"Age: {profile['age']}\n"
        f"Gender: {profile['gender']}\n"
        f"Location: {profile['location']}\n"
        f"Interests: {', '.join(profile['interests'])}"
    )
    bot.send_photo(chat_id, profile['photo'], caption=f"Matched profile:\n\n{profile_summary}")

    markup = types.InlineKeyboardMarkup()
    btn_like = types.InlineKeyboardButton("Like", callback_data="like")
    btn_dislike = types.InlineKeyboardButton("Dislike", callback_data="dislike")
    markup.add(btn_like, btn_dislike)

    bot.send_message(chat_id, "Do you like this profile?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    if call.data == "like":
        handle_like(call)
    elif call.data == "dislike":
        handle_dislike(call)

def handle_like(call):
    chat_id = call.message.chat.id
    current_index = user_data[chat_id]['current_profile_index']
    matched_profiles = user_data[chat_id]['matched_profiles']
    liked_profile = matched_profiles[current_index]
    msg = bot.send_message(chat_id, "Write a short message to this person:")
    bot.register_next_step_handler(msg, handle_short_message, liked_profile)

def handle_dislike(call):
    chat_id = call.message.chat.id
    display_next_profile(chat_id)

def handle_short_message(message, liked_profile):
    chat_id = message.chat.id
    short_message = message.text
    bot.send_message(liked_profile['chat_id'], f"Someone wrote you a text. @{message.from_user.username if message.from_user.username else 'Unknown'}: {short_message}")

    # Ask for telegram username if not set
    if not message.from_user.username:
        msg = bot.send_message(chat_id, "Please set your Telegram username in your profile settings.")
        bot.register_next_step_handler(msg, handle_username)
    else:
        display_next_profile(chat_id)

def display_next_profile(chat_id):
    current_index = user_data[chat_id]['current_profile_index']
    matched_profiles = user_data[chat_id]['matched_profiles']
    if current_index + 1 < len(matched_profiles):
        user_data[chat_id]['current_profile_index'] += 1
        display_profile(chat_id, matched_profiles[current_index + 1])
    else:
        bot.send_message(chat_id, "No more profiles to display.")


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
    if chat_id in user_data and 'partner' in user_data[chat_id]:
        partner_chat_id = user_data[chat_id]['partner']
        bot.send_message(partner_chat_id, "The chat has been ended by your partner.")
        bot.send_message(chat_id, "You have ended the chat.")
        del user_data[chat_id]['partner']
        del user_data[partner_chat_id]['partner']

        like_next_markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        like_next_markup.add("Like", "Next")
        bot.send_message(chat_id, "Do you want to like this profile or move to the next match?", reply_markup=like_next_markup)
        bot.send_message(partner_chat_id, "Do you want to like this profile or move to the next match?", reply_markup=like_next_markup)

@bot.message_handler(func=lambda message: message.text in ["Like", "Next"])
def handle_like_next(message):
    chat_id = message.chat.id
    action = message.text
    if action == "Like":
        partner_chat_id = user_data[chat_id]['partner']
        partner_info = get_user_info(partner_chat_id)
        user_info = get_user_info(chat_id)
        bot.send_message(partner_chat_id, f"The person you just talked to liked your profile!\n\n{user_info['name']} ({user_info['gender']}, {user_info['age']})\nInterests: {', '.join(user_info['interests'].split(', '))}")
        bot.send_message(chat_id, "You liked their profile!")
        next_random_match(chat_id)
    elif action == "Next":
        next_random_match(chat_id)

def next_random_match(chat_id):
    if chat_id in pending_users:
        pending_users.remove(chat_id)
    bot.send_message(chat_id, "Finding a new match...")
    find_random_chat(types.Message(chat=types.Chat(id=chat_id), text='Both'))

bot.polling()