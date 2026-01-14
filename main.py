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
        
        user_data_obj['interests'] = interests_result
        user_data.set(chat_id, user_data_obj)
        
        # Save to database
        save_user_to_db(chat_id, user_data_obj)
        
        # Show profile summary
        profile_summary = (
            f"🎉 Profile Setup Complete!\n\n"
            f"👤 Name: {user_data_obj['name']}\n"
            f"🎂 Age: {user_data_obj['age']}\n"
            f"⚧️ Gender: {user_data_obj['gender']}\n"
            f"📍 Location: {user_data_obj['location']}\n"
            f"🎯 Looking for: {'💑 Dating' if user_data_obj['looking_for'] == '1' else '👥 Friends'}\n"
            f"🎨 Interests: {', '.join(user_data_obj['interests'])}\n\n"
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
                    
                    welcome_msg = (
                        f"🎉 You've been matched with {partner_info['name']}!\n\n"
                        f"💬 Start chatting now! (Type 'End Chat' to stop)\n\n"
                        f"🎯 Shared interests: {len(set(user_info['interests'].split(', ')) & set(partner_info['interests'].split(', ')))}"
                    )
                    
                    bot.send_message(chat_id, welcome_msg, reply_markup=markup)
                    bot.send_message(partner_chat_id, 
                        f"🎉 You've been matched with {user_info['name']}!\n\n"
                        f"💬 Start chatting now! (Type 'End Chat' to stop)\n\n"
                        f"🎯 Shared interests: {len(set(partner_info['interests'].split(', ')) & set(user_info['interests'].split(', ')))}",
                        reply_markup=markup
                    )
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

# New commands for better UX
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

# Existing callback handlers (you need to keep these)
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

@bot.callback_query_handler(func=lambda call: call.data == "next_profile")
def handle_next_profile(call):
    """Handle next profile button"""
    chat_id = call.message.chat.id
    display_next_profile(chat_id)

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
                    bot.send_message(partner_chat_id, f"{message.text}")
                except Exception as e:
                    logger.error(f"Error relaying message: {e}")
                    bot.send_message(chat_id, "Error sending message. The chat may have ended.")
        else:
            # Handle other messages if needed
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

# Keep existing community functions (add them here if they're missing)
@bot.message_handler(commands=['community'])
def community_options(message):
    # Your existing community code here
    pass

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
