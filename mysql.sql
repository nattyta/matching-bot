CREATE DATABASE telegram_bot;
USE telegram_bot;

CREATE TABLE users (
    chat_id BIGINT PRIMARY KEY,
    name VARCHAR(255),
    age VARCHAR(255),
    gender VARCHAR(255),
    location VARCHAR(255),
    photo VARCHAR(255),
    interests TEXT
);


