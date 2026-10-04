import os
from datetime import datetime
from typing import Optional, List
from sqlalchemy import create_engine, String, Integer, Float, Boolean, ForeignKey, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


class Employee(Base):
    __tablename__ = 'employees'

    employee_id: Mapped[str] = mapped_column(String, primary_key=True)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    department_code: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    department_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    job_title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    employment_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    start_date: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    probation_end_date: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    manager_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String, default="active")

    entitlements: Mapped[List["LeaveEntitlement"]] = relationship(back_populates="employee")
    requests: Mapped[List["LeaveRequest"]] = relationship(back_populates="employee")

    @property
    def department(self) -> Optional[str]:
        return self.department_name

    @property
    def position(self) -> Optional[str]:
        return self.job_title

    @property
    def hire_date(self) -> Optional[str]:
        return self.start_date


class LeaveType(Base):
    __tablename__ = 'leave_types'

    code: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    day_unit: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    annual_limit_days: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    self_service: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    assistant_supported: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    policy_reference: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    @property
    def leave_type_id(self) -> str:
        return self.code

    @property
    def name_ka(self) -> str:
        return self.name


class LeaveEntitlement(Base):
    __tablename__ = "leave_entitlements"

    entitlement_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_id: Mapped[str] = mapped_column(String, ForeignKey("employees.employee_id"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    leave_type: Mapped[str] = mapped_column(String, ForeignKey("leave_types.code"), nullable=False)
    entitled_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    carried_over_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    used_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pending_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    remaining_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    employee: Mapped["Employee"] = relationship(back_populates="entitlements")
    leave_type_obj: Mapped["LeaveType"] = relationship()

    @property
    def leave_type_id(self) -> str:
        return self.leave_type


class LeaveRequest(Base):
    __tablename__ = "leave_requests"

    request_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[str] = mapped_column(String, ForeignKey("employees.employee_id"), nullable=False)
    leave_type: Mapped[str] = mapped_column(String, ForeignKey("leave_types.code"), nullable=False)
    start_date: Mapped[str] = mapped_column(String, nullable=False)
    end_date: Mapped[str] = mapped_column(String, nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_days: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, default="PENDING")
    created_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_via: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    reviewed_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    employee: Mapped["Employee"] = relationship(back_populates="requests")
    leave_type_obj: Mapped["LeaveType"] = relationship()

    @property
    def leave_type_id(self) -> str:
        return self.leave_type


class PublicHoliday(Base):
    __tablename__ = "public_holidays"

    holiday_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    name_ka: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    name_en: Mapped[Optional[str]] = mapped_column(String, nullable=True)


DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "leave_system.db")

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

engine = create_engine(f"sqlite:///{DB_PATH}", echo=True)

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
