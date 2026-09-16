from sqlalchemy import Column, Integer, String, Boolean, DateTime, ARRAY
from sqlalchemy.dialects.postgresql import JSONB

from sqlalchemy.sql import func
from sqlalchemy.orm import declarative_base

Base = declarative_base()



class DataFile(Base):
    __tablename__ = "datafiles"

    # clickup identity
    task_id = Column(String(30), primary_key=True)
    task_name = Column(String(255))

    # clickup state
    status = Column(String(30))
    archived = Column(Boolean)
    assignees = Column(ARRAY(String))

    # file information
    file_name = Column(String(255))
    file_directory = Column(String(550))
    category = Column(String(50))

    # created/changed
    date_received = Column(DateTime(timezone=True))
    date_task_created = Column(String(20))
    date_task_updated =  Column(String(20))

    date_created = Column(DateTime(timezone=True), server_default=func.now())
    date_modified = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # datacard
    datacard = Column(ARRAY(String(30)))

    # checksum
    checksum = Column(String(64), nullable=False)
    
    # raw task data from clickup 
    raw_json = Column(JSONB, nullable=False)
