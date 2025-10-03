from sqlmodel import SQLModel, Field, create_engine, Session
from typing import Optional
from datetime import datetime

DB_URL = os.getenv("DB_URL", "sqlite:///./app.db")
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})

class Guestbook(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=30, index=True)
    message: str = Field(max_length=500)
    ip_addr: str = Field(max_length=45)
    created_at: datetime = Field(default_factory=datetime.utcnow)

def init_db():
    SQLModel.metadata.create_all(engine)

def get_session():
    return Session(engine)
