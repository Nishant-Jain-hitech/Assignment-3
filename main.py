from datetime import timedelta
from typing import Any
from datetime import date, datetime
from typing import List, Optional
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy import Column, Integer, String, create_engine, Date, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base, Session
import re


DATABASE_URL = "sqlite:///./tasksdb.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


app = FastAPI()


@app.get("/")
async def root():
    return {"message": "Hello"}


class TaskDB(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(100), nullable=False)
    description = Column(String(255), nullable=True)
    priority = Column(String, nullable=False)
    status = Column(String, nullable=False)
    due_date = Column(Date, nullable=False)
    completed_at = Column(DateTime, nullable=True)


    @property
    def is_overdue(self):
        if self.status !="completed" and self.due_date<date.today():
            return True
        return False


    @property
    def days_left(self):
        if self.status=="completed":
            return None
        if not self.due_date:
            return None
        return (self.due_date-date.today()).days
    


Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    priority: str
    status: str = "pending"
    due_date: date
    completed_at: Optional[datetime] = None

    @field_validator("priority")
    def validate_priority(cls, value):
        if value.lower() not in ["high", "medium", "low"]:
            raise HTTPException(
                status_code=422,
                detail="Bhai kya kar rha h, {} koi priority nhi h ,high/medium/low dal".format(
                    value
                ),
            )
        return value.lower()

    @field_validator("status")
    def validate_status(cls, value):
        if value.lower() not in ["pending", "in_progress", "completed"]:
            raise HTTPException(
                status_code=422,
                detail="Bhai kya kar rha h, {} koi status nhi h ,pending/in_progress/completed dal".format(
                    value
                ),
            )
        return value.lower()

    @field_validator("title")
    def validate_titel(cls, value):
        if len(value) < 5:
            raise HTTPException(status_code=422, detail="5 se zyada characters likhna!")

        if value.isnumeric():
            raise HTTPException(status_code=422, detail="Sirf digits nhi ho sakte")

        if not value.istitle():
            raise HTTPException(status_code=422, detail="title ko capitalize kar!")

        if bool(re.search(r"[^a-zA-Z0-9]", value)):
            raise HTTPException(
                status_code=422, detail="special characters nhi chalenge!"
            )
        return value.title()

    @model_validator(mode="after")
    def validate_model(self):
        priority = self.priority
        due_date = self.due_date

        if priority == "high" and self.description is None:
            raise ValueError("High priority task me description dede bhai")

        if priority == "low" and (due_date - date.today()).days > 30:
            raise ValueError("low priority ko 30 din se zyada mat latkana")
            
        return self


class TaskResponse(BaseModel):
    id: int
    title: str
    description: Optional[str]
    priority: str
    status: Optional[str]
    due_date: date
    completed_at: Optional[datetime]
    is_overdue:Optional[bool]
    days_left:Optional[int]



@app.post("/tasks",response_model=TaskResponse)
def create_task(task:TaskCreate,db:Session=Depends(get_db)):
    db_task = TaskDB(**task.model_dump())
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    return db_task




@app.get("/tasks", response_model=List[TaskResponse] | dict)
def get_tasks(
    status: str | None = None,
    priority: str | None = None,
    overdue: bool | None = None,
    page: int | None = 1,
    limit: int | None = 10,
    starts: str | None = None,
    search: str | None = None,
    ends: str | None = None,
    db: Session = Depends(get_db),
):
    tasks = db.query(TaskDB).all()
    return tasks




@app.get("/tasks/stats", response_model=dict)
def get_stats(db: Session = Depends(get_db)):
    total_tasks = db.query(TaskDB).count()
    # print(total_tasks)
    pending_tasks = db.query(TaskDB).filter(TaskDB.status == "pending").count()
    in_progress_tasks = db.query(TaskDB).filter(TaskDB.status == "in_progress").count()
    completed_tasks = db.query(TaskDB).filter(TaskDB.status == "completed").count()
    overdue_tasks = db.query(TaskDB).filter(TaskDB.due_date < date.today()).count()
    high_and_pending = (
        db.query(TaskDB)
        .filter(TaskDB.priority == "high", TaskDB.status == "pending")
        .count()
    )

    return {
        "total": total_tasks,
        "pending": pending_tasks,
        "in_progress": in_progress_tasks,
        "completed": completed_tasks,
        "overdue": overdue_tasks,
        "high_priority_pending": high_and_pending,
    }



@app.get("/tasks/{task_id}", response_model=TaskResponse | dict)
def get_task_by_id(task_id: int, db: Session = Depends(get_db)):
    task = db.query(TaskDB).filter(TaskDB.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Kya bhai kuchh bhi maang rha h")
    return task



@app.put("/tasks/{task_id}", response_model=TaskResponse | dict)
def update_task(task_id: int, task: TaskCreate, db: Session = Depends(get_db)):
    db_task = db.query(TaskDB).filter(TaskDB.id == task_id).first()
    if not db_task:
        return {"message": "jo nhi h usko update kese kru bhai"}

    if db_task.status.lower() == "pending" and task.status.lower() == "completed":
        return {"message": "pending se completed pe jump nhi kar sakta"}
    elif db_task.status.lower() == "completed":
        return {"message": "ab kya change kar rha h, complete ho gya h"}
    elif db_task.status.lower() == "in_progress" and task.status.lower() == "pending":
        return {"message": "in_progress se pending pe jaega kya"}

    db_task.title = task.title
    db_task.description = task.description
    db_task.priority = task.priority
    db_task.status = task.status
    db_task.due_date = task.due_date
    if db_task.status == "completed":
        db_task.completed_at = datetime.now()
    else:
        db_task.completed_at = task.completed_at
    db.commit()
    db.refresh(db_task)
    return db_task


@app.delete("/tasks/{task_id}", response_model=dict)
def delete_task(task_id: int, db: Session = Depends(get_db)):
    db_task = db.query(TaskDB).filter(TaskDB.id == task_id).first()
    if not db_task:
        return {"message": "mat kar bhai ise delete, h hi nhi"}
    else:
        db.delete(db_task)
        db.commit()
        raise HTTPException(status_code=204, detail="ho gya bhai delete!")