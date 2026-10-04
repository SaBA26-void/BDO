import os
from datetime import datetime
from typing import Optional, List
from sqlalchemy import create_engine, String, Integer, Boolean, ForeignKey, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


class Employee(Base):
    __tablename__ = 'employees'

    employee_id: Mapped[str] = mapped_column(String, primary_key=True)
    first_name: Mapped[str] = mapped_column(String, nullable=False)
    last_name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    department: Mapped[str] = mapped_column(String, nullable=False)
    position: Mapped[str] = mapped_column(String, nullable=False)
    hire_date: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, default="EMPLOYEE")

    entitlements: Mapped[List["LeaveEntitlement"]] = relationship(back_populates="employee")
    requests: Mapped[List["LeaveRequest"]] = relationship(back_populates="employee")


class LeaveType(Base):
    __tablename__ = 'leave_types'

    leave_type_id: Mapped[str] = mapped_column(String, primary_key=True)
    code: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name_ka: Mapped[str] = mapped_column(String, nullable=False)
    annual_limit_days: Mapped[int] = mapped_column(Integer, nullable=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class LeaveEntitlement(Base):
    __tablename__ = "leave_entitlements"

    entitlement_id: Mapped[str] = mapped_column(String, primary_key=True)
    employee_id: Mapped[str] = mapped_column(String, ForeignKey("employees.employee_id"), nullable=False)
    leave_type_id: Mapped[str] = mapped_column(String, ForeignKey("leave_types.leave_type_id"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    total_days: Mapped[int] = mapped_column(Integer, nullable=False)
    used_days: Mapped[int] = mapped_column(Integer, default=0)
    pending_days: Mapped[int] = mapped_column(Integer, default=0)
    remaining_days: Mapped[int] = mapped_column(Integer, nullable=False)

    employee: Mapped["Employee"] = relationship(back_populates="entitlements")
    leave_type: Mapped["LeaveType"] = relationship()


class LeaveRequest(Base):
    __tablename__ = "leave_requests"

    request_id: Mapped[str] = mapped_column(String, primary_key=True)
    employee_id: Mapped[str] = mapped_column(String, ForeignKey("employees.employee_id"), nullable=False)
    leave_type_id: Mapped[str] = mapped_column(String, ForeignKey("leave_types.leave_type_id"), nullable=False)
    start_date: Mapped[str] = mapped_column(String, nullable=False)
    end_date: Mapped[str] = mapped_column(String, nullable=False)
    requested_days: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, default="PENDING")
    reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    reviewed_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    reviewed_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    employee: Mapped["Employee"] = relationship(back_populates="requests")
    leave_type: Mapped["LeaveType"] = relationship()


class PublicHoliday(Base):
    __tablename__ = "public_holidays"

    holiday_id: Mapped[str] = mapped_column(String, primary_key=True)
    date: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name_ka: Mapped[str] = mapped_column(String, nullable=False)
    name_en: Mapped[str] = mapped_column(String, nullable=False)


DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "leave_system.db")

# Ensure the data directory exists before connecting
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

engine = create_engine(f"sqlite:///{DB_PATH}", echo=True)

# Enable Foreign Key constraints in SQLite
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.close()

SessionLocal = sessionmaker(bind=engine)


def create_db_tables():
    Base.metadata.create_all(engine)
    print("Database tables created successfully!")


if __name__ == "__main__":
    create_db_tables()