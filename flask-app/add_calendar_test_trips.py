from app import create_app, db
from app.models import Trip, City
from datetime import date

app = create_app()
app.app_context().push()

# Ensure we have a city
city = City.query.first()
if not city:
    city = City(name="Test City", country="Test Country")
    db.session.add(city)
    db.session.commit()

# Current date: 2026-01-04 (Simulated or Real, assuming real time matches user prompt metadata)
# User prompt metadata says: 2026-01-04.

# 1. Ongoing Trip (Upcoming)
# Date: 2026-01-01 to 2026-01-10
t1 = Trip(
    title="Ongoing Trip (Test)",
    slug="ongoing-test-2026",
    price=1000,
    start_date=date(2026, 1, 1),
    end_date=date(2026, 1, 10),
    description="This trip is currently happening.",
    capacity=10,
    status='published',
    is_published=True
)
t1.cities.append(city)

# 2. Future Trip (Upcoming)
# Date: 2026-02-01 to 2026-02-10
t2 = Trip(
    title="Future Trip (Test)",
    slug="future-test-2026",
    price=1500,
    start_date=date(2026, 2, 1),
    end_date=date(2026, 2, 10),
    description="This trip hasn't started yet.",
    capacity=10,
    status='published',
    is_published=True
)
t2.cities.append(city)

# 3. Past Trip (Past)
# Date: 2025-12-01 to 2025-12-10
t3 = Trip(
    title="Past Trip (Test)",
    slug="past-test-2025",
    price=800,
    start_date=date(2025, 12, 1),
    end_date=date(2025, 12, 10),
    description="This trip has ended.",
    capacity=10,
    status='published',
    is_published=True
)
t3.cities.append(city)

# Add all
try:
    db.session.add(t1)
    db.session.add(t2)
    db.session.add(t3)
    db.session.commit()
    print("Successfully added: Ongoing Trip, Future Trip, Past Trip")
except Exception as e:
    db.session.rollback()
    print(f"Error adding trips (maybe slugs exist?): {e}")
