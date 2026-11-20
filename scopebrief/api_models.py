from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from .documents import DOCUMENT_CHARS
from .identity import ProjectRole, Role

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=40)]
QuestionText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=2, max_length=600)
]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=240)]
Status = Literal["answered", "partial", "insufficient"]
SourceKey = Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]+/[a-z0-9-]+$", max_length=81)]
MAX_SCOPE = 12


class Ask(BaseModel):
    question: QuestionText
    project_ids: list[Slug] = Field(min_length=1, max_length=MAX_SCOPE)


class SharedLogin(BaseModel):
    role: Role
    key: str = Field(default="", max_length=512)


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=128)


class Activation(Credentials):
    code: str = Field(min_length=10, max_length=80)
    name: str = Field(min_length=2, max_length=60)


class Publish(BaseModel):
    project_id: Slug
    key: Slug
    title: Title
    body: str = Field(min_length=1, max_length=DOCUMENT_CHARS)
    source_name: str = Field(default="", max_length=180)
    change_note: ShortText = ""
    expected_revision: int | None = Field(default=None, ge=1)
    create_only: bool = False


class Archive(BaseModel):
    archived: bool


class ProjectInput(BaseModel):
    id: Slug
    name: Title
    description: ShortText = ""
    aliases: list[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=48)]
    ] = Field(
        default_factory=list,
        max_length=8,
    )
    color: Literal["teal", "violet", "amber"] = "violet"


class ProjectGrants(BaseModel):
    grants: dict[Slug, ProjectRole] = Field(default_factory=dict, max_length=200)


class InviteInput(ProjectGrants):
    label: Title


class MemberInput(ProjectGrants):
    enabled: bool


class FeedbackInput(BaseModel):
    rating: Literal["helpful", "review"]
    note: ShortText = ""


class CaseInput(Ask):
    title: Title
    expected_status: Status = "answered"
    required_sources: list[SourceKey] = Field(default_factory=list, max_length=12)
    phrase: ShortText = ""
    feedback_run_id: str | None = Field(default=None, max_length=32)
