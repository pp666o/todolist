from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

#postgresql://username:password@localhost/todo_db
SQLALCHEMY_DATABASE_URL = "postgresql://localhost/todo_db"
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

#dependency: for getting db session in api
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()