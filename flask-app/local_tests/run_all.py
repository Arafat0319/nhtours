import sys

from db_validate import run as run_db_validate
from validate_trip_fields import run as run_trip_fields
from setup_test_trip import run as run_setup_trip
from installment_plan_check import run as run_installment_plan
from booking_flow_check import run as run_booking_flow


def main():
    ok = True

    print("== Database validation ==")
    if not run_db_validate():
        ok = False

    print("== Ensure test trip exists ==")
    if not run_setup_trip():
        ok = False

    print("== Trip field validation ==")
    if not run_trip_fields():
        ok = False

    print("== Booking flow check ==")
    if not run_booking_flow():
        ok = False

    print("== Installment plan check ==")
    if not run_installment_plan():
        ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
