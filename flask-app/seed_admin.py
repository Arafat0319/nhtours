from app import create_app, db
from app.models import User

app = create_app()

def seed_admin():
    with app.app_context():
        # Check if admin exists
        admin = User.query.filter_by(username='admin').first()
        if admin:
            print('Admin user already exists.')
            return

        # Create admin user
        # In a real scenario, password should be from env or input
        admin = User(username='admin')
        admin.set_password('admin123') # Default password
        db.session.add(admin)
        db.session.commit()
        print('Admin user created successfully.')
        print('Username: admin')
        print('Password: admin123')

if __name__ == '__main__':
    seed_admin()
