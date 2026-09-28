"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-28

Creates the full schema: users, the centre/test catalogue, bookings, payments
and the webhook idempotency ledger.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import app.models.types as apptypes

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None

BOOKING_STATUS = sa.Enum(
    "PENDING", "CONFIRMED", "FAILED", "CANCELLED", name="booking_status"
)
PAYMENT_STATUS = sa.Enum("PENDING", "SUCCESS", "FAILED", name="payment_status")

ACTIVE_BOOKING = sa.text("status IN ('PENDING', 'CONFIRMED')")
PENDING_PAYMENT = sa.text("status = 'PENDING'")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", apptypes.UTCDateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", apptypes.UTCDateTime(), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(128), nullable=False),
        sa.Column("full_name", sa.String(120), nullable=False),
        sa.Column("phone", sa.String(20), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "centres",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("city", sa.String(80), nullable=False),
        sa.Column("address", sa.String(400), nullable=False),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
    )
    op.create_index("ix_centres_city", "centres", ["city"])
    op.create_index("ix_centres_city_name", "centres", ["city", "name"])

    op.create_table(
        "diagnostic_tests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("preparation", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_diagnostic_tests_code", "diagnostic_tests", ["code"], unique=True)

    op.create_table(
        "centre_tests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("centre_id", sa.Integer(), nullable=False),
        sa.Column("test_id", sa.Integer(), nullable=False),
        sa.Column("price", apptypes.Money(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.ForeignKeyConstraint(["centre_id"], ["centres.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["test_id"], ["diagnostic_tests.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("centre_id", "test_id", name="uq_centre_tests_centre_test"),
        sa.CheckConstraint("price >= 0", name="ck_centre_tests_price_non_negative"),
    )
    op.create_index("ix_centre_tests_centre_id", "centre_tests", ["centre_id"])
    op.create_index("ix_centre_tests_test_id", "centre_tests", ["test_id"])

    op.create_table(
        "bookings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("centre_test_id", sa.Integer(), nullable=False),
        sa.Column("appointment_at", apptypes.UTCDateTime(), nullable=False),
        sa.Column("amount", apptypes.Money(), nullable=False),
        sa.Column("status", BOOKING_STATUS, nullable=False),
        sa.Column("cancellation_reason", sa.String(255), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["centre_test_id"], ["centre_tests.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("amount >= 0", name="ck_bookings_amount_non_negative"),
    )
    op.create_index("ix_bookings_user_id", "bookings", ["user_id"])
    op.create_index("ix_bookings_centre_test_id", "bookings", ["centre_test_id"])
    op.create_index("ix_bookings_status", "bookings", ["status"])
    op.create_index("ix_bookings_user_created", "bookings", ["user_id", "created_at"])
    # One live booking per user/offering/slot.
    op.create_index(
        "uq_bookings_active_slot",
        "bookings",
        ["user_id", "centre_test_id", "appointment_at"],
        unique=True,
        postgresql_where=ACTIVE_BOOKING,
        sqlite_where=ACTIVE_BOOKING,
    )

    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("amount", apptypes.Money(), nullable=False),
        sa.Column("status", PAYMENT_STATUS, nullable=False),
        sa.Column("provider_reference", sa.String(64), nullable=False),
        sa.Column("failure_reason", sa.String(255), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.CheckConstraint("amount >= 0", name="ck_payments_amount_non_negative"),
    )
    op.create_index("ix_payments_booking_id", "payments", ["booking_id"])
    op.create_index("ix_payments_status", "payments", ["status"])
    op.create_index(
        "ix_payments_provider_reference", "payments", ["provider_reference"], unique=True
    )
    # At most one in-flight payment per booking: blocks concurrent double-charge.
    op.create_index(
        "uq_payments_one_pending_per_booking",
        "payments",
        ["booking_id"],
        unique=True,
        postgresql_where=PENDING_PAYMENT,
        sqlite_where=PENDING_PAYMENT,
    )

    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("payment_id", sa.Integer(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("received_at", apptypes.UTCDateTime(), nullable=False),
        sa.Column("processed_at", apptypes.UTCDateTime(), nullable=True),
        sa.Column("outcome", sa.String(32), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="SET NULL"),
    )
    # The UNIQUE constraint that makes webhook delivery idempotent.
    op.create_index("ix_webhook_events_event_id", "webhook_events", ["event_id"], unique=True)
    op.create_index("ix_webhook_events_payment_id", "webhook_events", ["payment_id"])


def downgrade() -> None:
    op.drop_table("webhook_events")
    op.drop_table("payments")
    op.drop_table("bookings")
    op.drop_table("centre_tests")
    op.drop_table("diagnostic_tests")
    op.drop_table("centres")
    op.drop_table("users")
    bind = op.get_bind()
    PAYMENT_STATUS.drop(bind, checkfirst=True)
    BOOKING_STATUS.drop(bind, checkfirst=True)
