from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Date, Time, DateTime, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    position = Column(String(100), default="")
    hourly_rate = Column(Float, nullable=False, default=16.0)
    target_hours = Column(Float, nullable=False, default=40.0)
    availability = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Employee id={self.id} name={self.name!r}>"


class Shift(Base):
    __tablename__ = "shifts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(Integer, nullable=False)
    date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    break_minutes = Column(Integer, default=0)
    notes = Column(String(500), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Shift id={self.id} emp_id={self.employee_id} date={self.date}>"
