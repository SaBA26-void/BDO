from functools import wraps
from sqlalchemy.orm import Session
from src.database import engine


def with_session(func):
    """Decorator that automatically injects and manages a database session if not provided."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if kwargs.get("session") is not None:
            return func(*args, **kwargs)
        with Session(engine) as session:
            kwargs["session"] = session
            return func(*args, **kwargs)
    return wrapper
