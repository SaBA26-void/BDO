import os
import sys
import pandas as pd
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from src.database import engine, create_db_tables, Employee, LeaveType, LeaveEntitlement, LeaveRequest, PublicHoliday

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def seed_db_from_excel():
    create_db_tables()

    with Session(engine) as session:
        # seed Employees
        emp_count = session.scalar(select(func.count()).select_from(Employee))
        if emp_count == 0:
            filepath = os.path.join(DATA_DIR, "employees.xlsx")
            if os.path.exists(filepath):
                df = pd.read_excel(filepath)
                if 'start_date' in df.columns:
                    df['start_date'] = pd.to_datetime(df['start_date']).dt.strftime('%Y-%m-%d')
                if 'probation_end_date' in df.columns:
                    df['probation_end_date'] = pd.to_datetime(df['probation_end_date']).dt.strftime('%Y-%m-%d')
                df.to_sql(Employee.__tablename__, con=engine, if_exists="append", index=False)
                print("Seeded table 'employees' from employees.xlsx.", file=sys.stderr)

        # seed Leave Types
        lt_count = session.scalar(select(func.count()).select_from(LeaveType))
        if lt_count == 0:
            filepath = os.path.join(DATA_DIR, "leave_types.xlsx")
            if os.path.exists(filepath):
                df = pd.read_excel(filepath)
                df.to_sql(LeaveType.__tablename__, con=engine, if_exists="append", index=False)
                print("Seeded table 'leave_types' from leave_types.xlsx.", file=sys.stderr)

        # seed Leave Requests
        req_count = session.scalar(select(func.count()).select_from(LeaveRequest))
        req_df = None
        filepath_req = os.path.join(DATA_DIR, "leave_requests.xlsx")
        if req_count == 0 and os.path.exists(filepath_req):
            req_df = pd.read_excel(filepath_req)
            if 'start_date' in req_df.columns:
                req_df['start_date'] = pd.to_datetime(req_df['start_date']).dt.strftime('%Y-%m-%d')
            if 'end_date' in req_df.columns:
                req_df['end_date'] = pd.to_datetime(req_df['end_date']).dt.strftime('%Y-%m-%d')
            if 'created_at' in req_df.columns:
                req_df['created_at'] = pd.to_datetime(req_df['created_at']).dt.strftime('%Y-%m-%d %H:%M:%S')
            
            req_df['status'] = req_df['status'].str.upper()
            req_df['requested_days'] = req_df['days']
            req_df['reason'] = req_df['comment']
            
            req_df.to_sql(LeaveRequest.__tablename__, con=engine, if_exists="append", index=False)
            print("Seeded table 'leave_requests' from leave_requests.xlsx.", file=sys.stderr)
        elif os.path.exists(filepath_req):
            req_df = pd.read_excel(filepath_req)
            if 'start_date' in req_df.columns:
                req_df['start_date'] = pd.to_datetime(req_df['start_date']).dt.strftime('%Y-%m-%d')

        # seed Leave Entitlements
        ent_count = session.scalar(select(func.count()).select_from(LeaveEntitlement))
        if ent_count == 0:
            filepath = os.path.join(DATA_DIR, "leave_entitlements.xlsx")
            if os.path.exists(filepath):
                df = pd.read_excel(filepath)
                df['total_days'] = df['entitled_days'] + df['carried_over_days']

                # Compute used, pending, and remaining days from requests if available
                used_days_list = []
                pending_days_list = []
                remaining_days_list = []

                for _, row in df.iterrows():
                    emp_id = row['employee_id']
                    yr = row['year']
                    lt_code = row['leave_type']
                    tot = row['total_days']

                    used = 0
                    pending = 0

                    if req_df is not None and not req_df.empty:
                        # filter requests for this employee, leave_type and year
                        req_subset = req_df[
                            (req_df['employee_id'] == emp_id) &
                            (req_df['leave_type'] == lt_code) &
                            (pd.to_datetime(req_df['start_date']).dt.year == yr)
                        ]
                        
                        approved_reqs = req_subset[req_subset['status'].str.lower() == 'approved']
                        pending_reqs = req_subset[req_subset['status'].str.lower() == 'pending']

                        used = int(approved_reqs['days'].sum()) if not approved_reqs.empty else 0
                        pending = int(pending_reqs['days'].sum()) if not pending_reqs.empty else 0

                    rem = tot - used - pending

                    used_days_list.append(used)
                    pending_days_list.append(pending)
                    remaining_days_list.append(rem)

                df['used_days'] = used_days_list
                df['pending_days'] = pending_days_list
                df['remaining_days'] = remaining_days_list

                df.to_sql(LeaveEntitlement.__tablename__, con=engine, if_exists="append", index=False)
                print("Seeded table 'leave_entitlements' from leave_entitlements.xlsx.", file=sys.stderr)

        # seed Public Holidays
        hol_count = session.scalar(select(func.count()).select_from(PublicHoliday))
        if hol_count == 0:
            filepath = os.path.join(DATA_DIR, "public_holidays.xlsx")
            if os.path.exists(filepath):
                df = pd.read_excel(filepath)
                if 'date' in df.columns:
                    df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
                df['name_ka'] = df['name']
                df.to_sql(PublicHoliday.__tablename__, con=engine, if_exists="append", index=False)
                print("Seeded table 'public_holidays' from public_holidays.xlsx.", file=sys.stderr)


if __name__ == "__main__":
    seed_db_from_excel()
