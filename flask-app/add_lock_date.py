
from app import create_app, db
from sqlalchemy import text

app = create_app()

with app.app_context():
    with db.engine.connect() as conn:
        try:
            # Check if column exists
            result = conn.execute(text("PRAGMA table_info(trips)"))
            columns = [row[1] for row in result.fetchall()]
            
            if 'participants_request_lock_date' not in columns:
                print("Adding participants_request_lock_date column to trips table...")
                conn.execute(text("ALTER TABLE trips ADD COLUMN participants_request_lock_date DATETIME"))
                print("Column added successfully.")
            else:
                print("Column participants_request_lock_date already exists.")
                
        except Exception as e:
            print(f"An error occurred: {e}")
