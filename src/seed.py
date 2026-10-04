import os
import pandas as pd
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from src.database import engine, create_db_tables, Employee, LeaveType, LeaveEntitlement, LeaveRequest, PublicHoliday

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

TABLE_FILES = [
    (Employee, "employees.xlsx"),
    (LeaveType, "leave_types.xlsx"),
    (LeaveEntitlement, "leave_entitlements.xlsx"),
    (LeaveRequest, "leave_requests.xlsx"),
    (PublicHoliday, "public_holidays.xlsx"),
]

def seed_db_from_excel():
    create_db_tables()

    with Session(engine) as session:
        for model_class, filename in TABLE_FILES:
            table_name = model_class.__tablename__
            
            # check if table is empty
            count = session.scalar(select(func.count()).select_from(model_class))
            if count == 0:
                filepath = os.path.join(DATA_DIR, filename)
                if os.path.exists(filepath):
                    df = pd.read_excel(filepath)
                    # write to sql
                    df.to_sql(table_name, con=engine, if_exists="append", index=False)
                    print(f"Seeded table '{table_name}' from {filename}.")


if __name__ == "__main__":
    seed_db_from_excel()