import os
import mysql.connector



DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "port": int(os.getenv("DB_PORT", 3306))
}


# DB_CONFIG = {
#     "host": "localhost",
#     "user": "root",
#     "password": "System.hp@11",
#     "database": "codebuddy"
# }
def get_db():
    return mysql.connector.connect(**DB_CONFIG)
