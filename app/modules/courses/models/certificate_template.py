"""Certificate template model: the design a course certificate is issued from."""

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.courses.constants import (
    CERTIFICATE_CODE_MAX_LENGTH,
    CERTIFICATE_NAME_MAX_LENGTH,
    CertificateOrientation,
    CertificatePageSize,
    CertificateStatus,
    CertificateType,
)


class CertificateTemplate(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """A reusable certificate design, referenced by `courses.certificate_template_id`.

    The design is stored as `html_content` plus `css_content` rather than a
    flat image, so an issued certificate can be re-rendered at any size and
    the placeholder values substituted at issue time. `placeholders` records
    which tokens the HTML actually uses, which is what lets an editor show
    the author the list instead of making them remember it.
    """

    name: Mapped[str] = mapped_column(
        String(CERTIFICATE_NAME_MAX_LENGTH), nullable=False
    )
    code: Mapped[str] = mapped_column(
        String(CERTIFICATE_CODE_MAX_LENGTH),
        unique=True,
        index=True,
        nullable=False,
        doc="Stable identifier for referencing a template from code or import.",
    )
    description: Mapped[str | None] = mapped_column(Text, default=None)
    template_type: Mapped[str] = mapped_column(
        String(20),
        default=CertificateType.COMPLETION.value,
        server_default=CertificateType.COMPLETION.value,
        nullable=False,
        index=True,
    )

    # -- Page geometry -----------------------------------------------------
    orientation: Mapped[str] = mapped_column(
        String(20),
        default=CertificateOrientation.LANDSCAPE.value,
        server_default=CertificateOrientation.LANDSCAPE.value,
        nullable=False,
    )
    page_size: Mapped[str] = mapped_column(
        String(20),
        default=CertificatePageSize.A4.value,
        server_default=CertificatePageSize.A4.value,
        nullable=False,
    )
    width_mm: Mapped[int | None] = mapped_column(
        Integer, default=None, doc="Overrides `page_size` for a custom sheet."
    )
    height_mm: Mapped[int | None] = mapped_column(Integer, default=None)

    # -- Markup ------------------------------------------------------------
    html_content: Mapped[str | None] = mapped_column(Text, default=None)
    css_content: Mapped[str | None] = mapped_column(Text, default=None)
    placeholders: Mapped[list | None] = mapped_column(
        JSON,
        default=None,
        doc="Tokens the markup substitutes, e.g. student_name, course_title.",
    )
    design_config: Mapped[dict | None] = mapped_column(
        JSON, default=None, doc="Visual editor state: element positions, layers."
    )

    # -- Artwork -----------------------------------------------------------
    background_image_url: Mapped[str | None] = mapped_column(String(500), default=None)
    border_image_url: Mapped[str | None] = mapped_column(String(500), default=None)
    logo_url: Mapped[str | None] = mapped_column(String(500), default=None)
    seal_image_url: Mapped[str | None] = mapped_column(String(500), default=None)
    preview_image_url: Mapped[str | None] = mapped_column(String(500), default=None)

    # -- Typography and colour --------------------------------------------
    font_family: Mapped[str | None] = mapped_column(String(100), default=None)
    heading_font_family: Mapped[str | None] = mapped_column(String(100), default=None)
    primary_color: Mapped[str | None] = mapped_column(String(20), default=None)
    secondary_color: Mapped[str | None] = mapped_column(String(20), default=None)
    text_color: Mapped[str | None] = mapped_column(String(20), default=None)
    background_color: Mapped[str | None] = mapped_column(String(20), default=None)

    # -- Signatory and issuer ---------------------------------------------
    signature_image_url: Mapped[str | None] = mapped_column(String(500), default=None)
    signature_name: Mapped[str | None] = mapped_column(String(150), default=None)
    signature_designation: Mapped[str | None] = mapped_column(String(255), default=None)
    second_signature_image_url: Mapped[str | None] = mapped_column(
        String(500), default=None
    )
    second_signature_name: Mapped[str | None] = mapped_column(String(150), default=None)
    second_signature_designation: Mapped[str | None] = mapped_column(
        String(255), default=None
    )
    issuer_name: Mapped[str | None] = mapped_column(String(150), default=None)
    organization_name: Mapped[str | None] = mapped_column(String(255), default=None)
    organization_address: Mapped[str | None] = mapped_column(Text, default=None)

    # -- Numbering and verification ---------------------------------------
    certificate_number_prefix: Mapped[str | None] = mapped_column(
        String(50), default=None
    )
    certificate_number_format: Mapped[str | None] = mapped_column(
        String(100),
        default=None,
        doc="Pattern for the serial, e.g. '{prefix}-{year}-{sequence:06d}'.",
    )
    verification_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    verification_url_pattern: Mapped[str | None] = mapped_column(
        String(500), default=None
    )
    qr_code_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    qr_code_position: Mapped[str | None] = mapped_column(String(20), default=None)

    # -- Lifecycle ---------------------------------------------------------
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
        doc="Used by a course that names no template of its own.",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=CertificateStatus.DRAFT.value,
        server_default=CertificateStatus.DRAFT.value,
        nullable=False,
        index=True,
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    # -- Audit -------------------------------------------------------------
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    __table_args__ = (
        Index("ix_certificate_templates_status_is_active", "status", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<CertificateTemplate {self.code}>"
