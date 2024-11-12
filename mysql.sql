-- Create the users table
CREATE TABLE users (
    chat_id BIGINT PRIMARY KEY,
    name VARCHAR(255),
    age VARCHAR(10),
    gender VARCHAR(10),
    location VARCHAR(255),
    photo VARCHAR(255),
    interests TEXT,
    looking_for VARCHAR(50)
);

-- Create the likes table
CREATE TABLE likes (
    liker_chat_id BIGINT,
    liked_chat_id BIGINT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (liker_chat_id, liked_chat_id),
    FOREIGN KEY (liker_chat_id) REFERENCES users(chat_id) ON DELETE CASCADE,
    FOREIGN KEY (liked_chat_id) REFERENCES users(chat_id) ON DELETE CASCADE
);

-- Create the groups table
CREATE TABLE groups (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255),
    description TEXT,
    photo VARCHAR(255),
    invite_link VARCHAR(255)
);