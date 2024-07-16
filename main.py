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
    bot.send_photo(chat_id, user_data[chat_id]['photo'], caption=f"Profile setup complete!\n\n{profile_summary}\n\n"
                                                                 "Commands:\n"
                                                                 "/my_profile - View and edit your profile\n"
                                                                 "/view_profile - See other user profiles\n"
                                                                 "/random - Chat with a random user who's online\n"
                                                                 "/help - Get help")

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
    profile = cursor.fetchone()
    if profile:
        return {
            'chat_id': profile[0],
            'name': profile[1],
            'age': profile[2],
            'gender': profile[3],
            'location': profile[4],
            'photo': profile[5],
            'interests': profile[6],
            'looking_for': profile[7]
        }
    return None

def calculate_distance(location1, location2):
    try:
        coords_1 = tuple(map(float, location1.split(',')))
        coords_2 = tuple(map(float, location2.split(',')))
        return geodesic(coords_1, coords_2).kilometers
    except ValueError:
        return float('inf')

def interest_similarity(interests1, interests2):
    return len(set(interests1) & set(interests2))

def get_matched_profiles(user_info, gender_preference):
    cursor.execute('SELECT * FROM users WHERE chat_id != %s', (user_info['chat_id'],))
    all_profiles = cursor.fetchall()
    matched_profiles = []
    for profile in all_profiles:
        partner_info = {
            'chat_id': profile[0],
            'name': profile[1],
            'age': profile[2],
            'gender': profile[3],
            'location': profile[4],
            'photo': profile[5],
            'interests': profile[6],
            'looking_for': profile[7]
        }
        if gender_preference == 'BOTH' or partner_info['gender'] == gender_preference:
            distance = calculate_distance(user_info['location'], partner_info['location'])
            similarity = interest_similarity(user_info['interests'].split(', '), partner_info['interests'].split(', '))
            matched_profiles.append((partner_info, distance, similarity))
    matched_profiles.sort(key=lambda x: (x[1], -x[2]))
    return matched_profiles

def show_next_profile(chat_id):
    if not pending_users:
        bot.send_message(chat_id, "No more profiles to view.")
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


@bot.callback_query_handler(func=lambda call: call.data.startswith('like_') or call.data.startswith('dislike_') or call.data.startswith('note_'))
def handle_profile_response(call):
    action, other_user_chat_id = call.data.split('_')
    chat_id = call.message.chat.id

    if action == 'like':
        cursor.execute('INSERT INTO likes (liker_chat_id, liked_chat_id) VALUES (%s, %s)', (chat_id, other_user_chat_id))
        conn.commit()
        user_info = get_user_info(chat_id)
        liked_user_info = get_user_info(other_user_chat_id)
        if liked_user_info:
            like_message = f"{user_info['name']} ({user_info['chat_id']}) liked your profile!\nTelegram username: @{call.message.chat.username}"
            bot.send_message(other_user_chat_id, like_message)
            cursor.execute('SELECT * FROM likes WHERE liker_chat_id = %s AND liked_chat_id = %s', (other_user_chat_id, chat_id))
            if cursor.fetchone():
                bot.send_message(chat_id, f"You and {liked_user_info['name']} liked each other! Send a message to start chatting.")
                bot.send_message(other_user_chat_id, f"You and {user_info['name']} liked each other! Send a message to start chatting.")
        show_next_profile(chat_id)

    elif action == 'dislike':
        show_next_profile(chat_id)
    
    elif action == 'note':
        msg = bot.send_message(chat_id, "Please write your note:")
        bot.register_next_step_handler(msg, save_note, other_user_chat_id)

def save_note(message, other_user_chat_id):
    chat_id = message.chat.id
    note = message.text
    user_info = get_user_info(chat_id)
    liked_user_info = get_user_info(other_user_chat_id)
    if liked_user_info:
        note_message = f"Someone sent you a note:\n\n{note}\n\n{user_info['name']} ({user_info['chat_id']})\nTelegram username: @{message.chat.username}"
        bot.send_message(other_user_chat_id, note_message)
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
        new_value = '1' if new_value.lower() == 'dating' else '0'

    cursor.execute(f'UPDATE users SET {edit_choice.replace(" ", "_")} = %s WHERE chat_id = %s', (new_value, chat_id))
    conn.commit()
    user_data[chat_id][edit_choice.replace(" ", "_")] = new_value
    bot.reply_to(message, f"Your {edit_choice} has been updated.")
    # Return to /my_profile after editing
    my_profile(message)

@bot.message_handler(commands=['view_profiles'])
def show_profiles(message):
    chat_id = message.chat.id
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

def get_gender_preference(user_info):
    if user_info['looking_for'] == '2':
        return 'Both'
    else:
        return 'F' if user_info['gender'] == 'M' else 'M'

def display_profile(chat_id, profile):
    profile_summary = (
        f"Name: {profile['name']}\n"
        f"Age: {profile['age']}\n"
        f"Gender: {profile['gender']}\n"
        f"Location: {profile['location']}\n"
        f"Interests: {', '.join(profile['interests'].split(', '))}"
    )
    bot.send_photo(chat_id, profile['photo'], caption=f"Matched profile:\n\n{profile_summary}")

    markup = types.InlineKeyboardMarkup()
    btn_like = types.InlineKeyboardButton("👍", callback_data=f"like_{profile['chat_id']}")
    btn_dislike = types.InlineKeyboardButton("👎", callback_data="dislike")
    btn_note = types.InlineKeyboardButton("✍️💌", callback_data=f"note_{profile['chat_id']}")
    markup.add(btn_like, btn_dislike, btn_note)

    bot.send_message(chat_id, "Do you like this profile?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    if call.data.startswith("like_"):
        handle_like(call)
    elif call.data == "dislike":
        handle_dislike(call)
    elif call.data.startswith("note_"):
        handle_note_request(call)

def handle_like(call):
    chat_id = call.message.chat.id
    other_user_chat_id = call.data.split('_')[1]
    user_info = get_user_info(chat_id)
    liked_user_info = get_user_info(other_user_chat_id)
    
    if liked_user_info:
        like_message = (
            f"Someone liked your profile!\n\n"
            f"Name: {user_info['name']}\n"
            f"Age: {user_info['age']}\n"
            f"Gender: {user_info['gender']}\n"
            f"Location: {user_info['location']}\n"
            f"Interests: {', '.join(user_info['interests'].split(', '))}\n"
            f"Telegram username: @{call.message.chat.username if call.message.chat.username else 'N/A'}"
        )
        bot.send_message(other_user_chat_id, like_message)
        
        cursor.execute('INSERT INTO likes (liker_chat_id, liked_chat_id) VALUES (%s, %s)', (chat_id, other_user_chat_id))
        conn.commit()
        
        cursor.execute('SELECT * FROM likes WHERE liker_chat_id = %s AND liked_chat_id = %s', (other_user_chat_id, chat_id))
        if cursor.fetchone():
            bot.send_message(chat_id, f"Someone liked back your profile! Start chatting with @{liked_user_info['name']}.")
            bot.send_message(other_user_chat_id, f"Someone liked back your profile! Start chatting with @{user_info['name']}.")
    
    display_next_profile(chat_id)

def handle_dislike(call):
    chat_id = call.message.chat.id
    display_next_profile(chat_id)

def handle_note_request(call):
    chat_id = call.message.chat.id
    other_user_chat_id = call.data.split('_')[1]
    msg = bot.send_message(chat_id, "Please write your note:")
    bot.register_next_step_handler(msg, save_note, other_user_chat_id)

def save_note(message, other_user_chat_id):
    chat_id = message.chat.id
    note = message.text
    user_info = get_user_info(chat_id)
    liked_user_info = get_user_info(other_user_chat_id)
    if liked_user_info:
        note_message = (
            f"Someone wrote you a note:\n\n{note}\n\n"
            f"Name: {user_info['name']}\n"
            f"Age: {user_info['age']}\n"
            f"Gender: {user_info['gender']}\n"
            f"Location: {user_info['location']}\n"
            f"Interests: {', '.join(user_info['interests'].split(', '))}\n"
            f"Telegram username: @{message.chat.username if message.chat.username else 'N/A'}"
        )
        bot.send_message(other_user_chat_id, note_message)
        display_next_profile(chat_id)

def display_next_profile(chat_id):
    current_index = user_data[chat_id]['current_profile_index']
    matched_profiles = user_data[chat_id]['matched_profiles']
    if current_index + 1 < len(matched_profiles):
        user_data[chat_id]['current_profile_index'] += 1
        display_profile(chat_id, matched_profiles[current_index + 1][0])
    else:
        bot.send_message(chat_id, "No more profiles to display.")






@bot.message_handler(commands=['help'])
def help_command(message):
    chat_id = message.chat.id
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("How to use the bot", "Complain", "Contact us")
    msg = bot.send_message(chat_id, "Choose an option:", reply_markup=markup)
    bot.register_next_step_handler(msg, handle_help_choice)

def handle_help_choice(message):
    chat_id = message.chat.id
    choice = message.text.lower()
    
    if choice == 'how to use the bot':
        bot.send_message(chat_id, 
                         "Instructions on how to use the bot:\n\n"
                         "1. Use /start to set up your profile.\n"
                         "2. Use /random to find a match.\n"
                         "3. Follow the prompts to chat with your match.\n"
                         "4. Use 'End' to end the chat and /edit_profile to edit your profile.\n\n"
                         "For any help, please contact @meh9061.")
    elif choice == 'complain':
        bot.send_message(chat_id, "If you have a complaint, please contact @meh9061.")
    elif choice == 'contact us':
        bot.send_message(chat_id, "For any inquiries, please contact us at 0935519061.")
    else:
        msg = bot.send_message(chat_id, "Invalid choice. Please choose again.")
        bot.register_next_step_handler(msg, handle_help_choice)


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
    user_info = get_user_info(chat_id)

    if 'partner' in user_data[chat_id]:
        partner_chat_id = user_data[chat_id]['partner']
        partner_info = get_user_info(partner_chat_id)

        if action == "Like":
            like_message = (
                f"The person you just talked to liked your profile!\n\n"
                f"Name: {user_info['name']}\n"
                f"Age: {user_info['age']}\n"
                f"Gender: {user_info['gender']}\n"
                f"Location: {user_info['location']}\n"
                f"Interests: {', '.join(user_info['interests'].split(', '))}\n"
                f"Telegram username: @{user_info['username'] if user_info['username'] else 'N/A'}"
            )
            bot.send_message(partner_chat_id, like_message)

            cursor.execute('INSERT INTO likes (liker_chat_id, liked_chat_id) VALUES (%s, %s)', (chat_id, partner_chat_id))
            conn.commit()

            cursor.execute('SELECT * FROM likes WHERE liker_chat_id = %s AND liked_chat_id = %s', (partner_chat_id, chat_id))
            if cursor.fetchone():
                bot.send_message(chat_id, f"The person you just talked to liked back your profile! Start chatting with @{partner_info['username']}.")
                bot.send_message(partner_chat_id, f"The person you just talked to liked back your profile! Start chatting with @{user_info['username']}.")

        next_random_match(chat_id)
    elif action == "Next":
        next_random_match(chat_id)

def next_random_match(chat_id):
    if chat_id in pending_users:
        pending_users.remove(chat_id)
    bot.send_message(chat_id, "Finding a new match...")
    find_random_chat(types.Message(chat=types.Chat(id=chat_id), text='Both'))




# Start the bot polling
bot.polling()