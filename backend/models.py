from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["严重", "轻微", "一般"]


class MemberBase(BaseModel):
    name: Optional[str] = None
    full_name: Optional[str] = None
    initial: Optional[str] = None
    birth_date: Optional[str] = None
    sex: Optional[str] = None
    blood_type: Optional[str] = None
    role: Optional[str] = None
    species: Optional[str] = None
    sort_order: Optional[int] = None
    breed: Optional[str] = None
    home_date: Optional[str] = None
    chip_id: Optional[str] = None
    doctor: Optional[str] = None
    allergies: Optional[list[str]] = None
    chronic: Optional[list[str]] = None
    notes: Optional[str] = None


class MemberCreate(MemberBase):
    key: Optional[str] = None
    name: str
    species: str = "human"


class MemberUpdate(MemberBase):
    archived_at: Optional[str] = None


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    name: str
    full_name: Optional[str] = None
    initial: Optional[str] = None
    birth_date: Optional[str] = None
    sex: Optional[str] = None
    blood_type: Optional[str] = None
    role: Optional[str] = None
    species: str
    sort_order: int = 0
    breed: Optional[str] = None
    home_date: Optional[str] = None
    chip_id: Optional[str] = None
    doctor: Optional[str] = None
    allergies: list[str] = Field(default_factory=list)
    chronic: list[str] = Field(default_factory=list)
    notes: Optional[str] = None
    archived_at: Optional[str] = None
    latest_kpis: list[dict[str, Any]] = Field(default_factory=list)
    next_reminder: Optional[dict[str, Any]] = None


class VisitCreate(BaseModel):
    member_key: str
    date: str
    type: Optional[str] = None
    hospital: Optional[str] = None
    department: Optional[str] = None
    doctor: Optional[str] = None
    chief_complaint: Optional[str] = None
    severity: Optional[Severity] = None
    diagnosis: list[str] = Field(default_factory=list)
    notes: Optional[str] = None
    note_full: Optional[str] = None
    source_file: Optional[str] = None


class VisitOut(VisitCreate):
    id: int


class VisitUpdate(BaseModel):
    date: Optional[str] = None
    type: Optional[str] = None
    hospital: Optional[str] = None
    department: Optional[str] = None
    doctor: Optional[str] = None
    chief_complaint: Optional[str] = None
    severity: Optional[Severity] = None
    diagnosis: Optional[list[str]] = None
    notes: Optional[str] = None
    note_full: Optional[str] = None
    source_file: Optional[str] = None


class LabCreate(BaseModel):
    panel: str
    test_name: str
    value: Optional[str] = None
    unit: Optional[str] = None
    ref_low: Optional[str] = None
    ref_high: Optional[str] = None
    status: Optional[str] = None
    source_file: Optional[str] = None


class LabOut(LabCreate):
    id: int
    member_key: str
    visit_id: Optional[int] = None
    date: str


class LabRecordCreate(LabCreate):
    member_key: str
    visit_id: Optional[int] = None
    date: str


class LabUpdate(BaseModel):
    visit_id: Optional[int] = None
    date: Optional[str] = None
    panel: Optional[str] = None
    test_name: Optional[str] = None
    value: Optional[str] = None
    unit: Optional[str] = None
    ref_low: Optional[str] = None
    ref_high: Optional[str] = None
    status: Optional[str] = None
    source_file: Optional[str] = None


class MedCreate(BaseModel):
    member_key: str
    visit_id: Optional[int] = None
    name: str
    dose: Optional[str] = None
    freq: Optional[str] = None
    route: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    ongoing: bool = False
    category: Optional[str] = None
    notes: Optional[str] = None


class MedUpdate(BaseModel):
    name: Optional[str] = None
    dose: Optional[str] = None
    freq: Optional[str] = None
    route: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    ongoing: Optional[bool] = None
    category: Optional[str] = None
    notes: Optional[str] = None


class MedOut(MedCreate):
    id: int


class WeightCreate(BaseModel):
    member_key: str
    date: str
    weight_kg: float
    notes: Optional[str] = None


class WeightOut(WeightCreate):
    id: int


class ReminderCreate(BaseModel):
    member_key: str
    date: str
    title: str
    kind: str
    priority: str = "normal"
    done: bool = False
    notes: Optional[str] = None


class ReminderUpdate(BaseModel):
    member_key: Optional[str] = None
    date: Optional[str] = None
    title: Optional[str] = None
    kind: Optional[str] = None
    priority: Optional[str] = None
    done: Optional[bool] = None
    notes: Optional[str] = None


class ReminderOut(ReminderCreate):
    id: int
    done: bool = False
    done_at: Optional[str] = None
    source: str = "manual"
    rule_key: Optional[str] = None
    auto_key: Optional[str] = None


class AttachmentCreate(BaseModel):
    title: str
    org: Optional[str] = None
    tag: Optional[str] = None
    filename: Optional[str] = None
    file_path: Optional[str] = None
    notes: Optional[str] = None


class AttachmentOut(AttachmentCreate):
    id: int
    member_key: str
    visit_id: Optional[int] = None
    date: str


class AttachmentRecordCreate(AttachmentCreate):
    member_key: str
    visit_id: Optional[int] = None
    date: str


class AttachmentUpdate(BaseModel):
    visit_id: Optional[int] = None
    date: Optional[str] = None
    title: Optional[str] = None
    org: Optional[str] = None
    tag: Optional[str] = None
    filename: Optional[str] = None
    file_path: Optional[str] = None
    notes: Optional[str] = None
