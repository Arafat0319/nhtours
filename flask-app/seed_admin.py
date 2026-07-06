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
        admin = User(username=os.environ.get('ADMIN_USERNAME', 'admin'))
        pw = os.environ.get('ADMIN_INITIAL_PASSWORD')
        if not pw:
            print('Set ADMIN_INITIAL_PASSWORD env var to create admin (min 12 chars).')
            return
        admin.set_password(pw)
        db.session.add(admin)
        db.session.commit()
        print(f'Admin user created: {admin.username}')

if __name__ == '__main__':
    seed_admin()
