from datetime import timedelta
from typing import Any
from datetime import date, datetime
from typing import List, Optional
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy import Column, Integer, String, create_engine, Date, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base, Session
import re
# from helperfunction.helper import get_task_or_404, apply_filters, paginate


DATABASE_URL = "sqlite:///./tasksdb.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


app = FastAPI()


@app.get("/")
async def root():
    return {"message": "Hello"}


def get_task_or_404(db, id):
    task=db.query(TaskDB).filter(TaskDB.id==id).first()
    if not task:
        raise HTTPException(status_code=404,detail="Task nhi mila")
    return task


def apply_filters(db, query, filters):
    if query=="status":
        return db.query(TaskDB).filter(TaskDB.status==filters).all()
    if query=="priority":
        return db.query(TaskDB).filter(TaskDB.priority==filters).all()


def paginate(query, page, limit):
    return query[(page - 1) * limit : page * limit]


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


    @staticmethod
    def validate_status_transition(old_status, new_status):
        if old_status=="completed" and new_status!="completed":
            return False 
        if old_status=="pending" and new_status=="completed":
            return False 
        if old_status=="in_progress" and new_status=="pending":
            return False

        return True


    @staticmethod
    def can_create_high_priority(db):
        counter=db.query(TaskDB).filter(TaskDB.priority=="high",TaskDB.status=="pending").count()
        if counter>=5:
            return False
        return True
            

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
    if task.priority=="high" and task.status=="pending":
        if not TaskDB.can_create_high_priority(db):
            raise HTTPException(status_code=422, detail="Bhai 5 se zyada high priority tasks nhi ho sakte")
    db_task = TaskDB(**task.model_dump())
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    return db_task




@app.get("/tasks", response_model=List[TaskResponse] | dict)
def get_tasks(
    status: str | None = None,
    priority: str | None = None,
    page: int | None = 1,
    limit: int | None = 10,
    db: Session = Depends(get_db),
):
    tasks = db.query(TaskDB).all()

    if status:
        status_tasks=apply_filters(db,"status",status)
        return status_tasks
    if priority:
        priority_tasks=apply_filters(db,"priority",priority)
        return priority_tasks
        
    if page and limit:
        paginated_tasks=paginate(tasks,page,limit)
        return paginated_tasks


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
    db_task=get_task_or_404(db,task_id)
    return db_task



@app.put("/tasks/{task_id}", response_model=TaskResponse | dict)
def update_task(task_id: int, task: TaskCreate, db: Session = Depends(get_db)):
    if not TaskDB.can_create_high_priority(db):
        raise HTTPException(status_code=422, detail="Bhai 5 se zyada high priority tasks nhi ho sakte")

    db_task=get_task_or_404(db,task_id)

    if not TaskDB.validate_status_transition(db_task.status,task.status):
        raise HTTPException(status_code=422, detail="Bhai status transition nhi ho sakta")

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
    db_task = get_task_or_404
    if not db_task:
        raise HTTPException(status_code=404, detail="Task h hi nhi!")
    else:
        db.delete(db_task)
        db.commit()
        raise HTTPException(status_code=204, detail="ho gya bhai delete!")