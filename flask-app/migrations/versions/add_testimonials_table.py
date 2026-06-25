"""Add testimonials table and seed defaults

Revision ID: add_testimonials_table
Revises: add_bp_default_fields
Create Date: 2026-06-24 12:00:00.000000

"""
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "add_testimonials_table"
down_revision = "add_bp_default_fields"
branch_labels = None
depends_on = None

DEFAULT_TESTIMONIALS = [
    {
        "quote": (
            "This trip was so exciting thanks to you guys. Everything we did was so cool and I felt so "
            "immersed in Chinese culture. The service was amazing, especially all the help with suitcases "
            "and making sure we arrive everywhere on time."
        ),
        "author_name": "Student",
        "organization": "Ransom Everglades School",
    },
    {
        "quote": (
            "This has been the best trip I have ever been on. We visited so many cool and fun places and I "
            "will definitely coming back"
        ),
        "author_name": "Student",
        "organization": "Ransom Everglades School",
    },
    {
        "quote": (
            "I really enjoyed the trip and thought that the destinations I've been to have been very good "
            "places. The experiences for the most part were unheard of. My favorite parts were the pandas "
            "and the shopping in Shanghai."
        ),
        "author_name": "Student",
        "organization": "Ransom Everglades School",
    },
    {
        "quote": (
            "Thank you so much, I really enjoyed this trip in Shanghai. It has been so fun and I hope to come "
            "back soon. 谢谢你。这是很好玩儿！"
        ),
        "author_name": "Liv B",
        "organization": "Ransom Grade Nine",
    },
    {
        "quote": (
            "我们爱你！谢谢，谢谢！ I loved the energy and I will remember my time in Shanghai! "
            "我很高兴能连接中国和美国！"
        ),
        "author_name": "Leyla Amjad",
        "organization": None,
    },
]


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "testimonials" not in tables:
        op.create_table(
            "testimonials",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("quote", sa.Text(), nullable=False),
            sa.Column("author_name", sa.String(length=128), nullable=False),
            sa.Column("organization", sa.String(length=200), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=True),
            sa.Column("is_default", sa.Boolean(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_testimonials_status"), "testimonials", ["status"], unique=False)

    existing = conn.execute(sa.text("SELECT COUNT(*) FROM testimonials")).scalar()
    if not existing:
        testimonials = sa.table(
            "testimonials",
            sa.column("quote", sa.Text),
            sa.column("author_name", sa.String),
            sa.column("organization", sa.String),
            sa.column("status", sa.String),
            sa.column("is_default", sa.Boolean),
            sa.column("created_at", sa.DateTime),
        )
        now = datetime.utcnow()
        op.bulk_insert(
            testimonials,
            [
                {
                    "quote": item["quote"],
                    "author_name": item["author_name"],
                    "organization": item["organization"],
                    "status": "approved",
                    "is_default": True,
                    "created_at": now,
                }
                for item in DEFAULT_TESTIMONIALS
            ],
        )


def downgrade():
    op.drop_index(op.f("ix_testimonials_status"), table_name="testimonials")
    op.drop_table("testimonials")
