"""Menu model: one link in a navigation tree."""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.categories.models.category import Category
from app.modules.menus.constants import (
    MENU_ICON_MAX_LENGTH,
    MENU_IMAGE_MAX_LENGTH,
    MENU_LINK_MAX_LENGTH,
    MENU_TITLE_MAX_LENGTH,
)


class Menu(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """One item in a menu, optionally nested under another item.

    The tree is a self-referencing parent pointer, as in the categories
    module: navigations are small and shallow, and a parent pointer is the one
    shape that cannot get out of step with itself. The service enforces what
    the column cannot - that an item is never its own ancestor, and never
    lands in a different menu from its parent.

    `menu_category_id` says which navigation this belongs to. It is a row in
    `categories` from the Menu Category taxonomy; a foreign key can name a
    table but never a subset of one, so the service checks the taxonomy on
    every write.
    """

    title: Mapped[str] = mapped_column(String(MENU_TITLE_MAX_LENGTH), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)

    icon: Mapped[str | None] = mapped_column(
        String(MENU_ICON_MAX_LENGTH),
        default=None,
        doc="Icon name, resolved by the front end - not a file.",
    )
    image: Mapped[str | None] = mapped_column(
        String(MENU_IMAGE_MAX_LENGTH),
        default=None,
        doc="Path or URL of an image shown beside the item.",
    )
    link: Mapped[str | None] = mapped_column(
        String(MENU_LINK_MAX_LENGTH),
        default=None,
        doc=(
            "Where the item goes: an internal slug or a full URL. Null for a "
            "heading that only opens its children."
        ),
    )

    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        # `RESTRICT`, so removing a parent cannot silently take its whole
        # branch with it. The service refuses and says what is in the way.
        ForeignKey("menus.id", ondelete="RESTRICT"),
        default=None,
        doc="Null for a top-level item.",
    )
    menu_category_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        # `RESTRICT`, as everywhere else that points at a category: retiring a
        # menu category must not take the items filed under it.
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    order: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
        doc="Position among siblings, ascending. Positive; the service assigns "
        "the next free number when none is given.",
    )

    # -- Audit ----------------------------------------------------------
    # `SET NULL` rather than `CASCADE`: deleting the administrator who built a
    # navigation must not delete the navigation along with them.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
    )

    menu_category: Mapped[Category] = relationship(
        lazy="selectin", foreign_keys=lambda: [Menu.menu_category_id]
    )
    children: Mapped[list["Menu"]] = relationship(
        back_populates="parent",
        lazy="raise",
        # The parent side owns the foreign key, so the direction has to be
        # spelled out on a self-referencing relationship.
        foreign_keys=lambda: [Menu.parent_id],
        order_by=lambda: [Menu.order, Menu.title],
    )
    parent: Mapped["Menu | None"] = relationship(
        back_populates="children",
        remote_side=lambda: [Menu.id],
        lazy="selectin",
        foreign_keys=lambda: [Menu.parent_id],
    )

    __table_args__ = (
        # `order` was specified as a positive number, so the database says so
        # too. The schema rejects zero and below before it gets here; this
        # catches the writes that never went through a schema - a fix-up in
        # psql, a future job, a seeder.
        CheckConstraint('"order" > 0', name="order_positive"),
        # "The children of this item, in order", which is every tree read.
        Index("ix_menus_parent_id_order", "parent_id", "order"),
        # The whole of one navigation, in order - what rendering a menu asks
        # for.
        Index("ix_menus_menu_category_id_order", "menu_category_id", "order"),
    )

    # -- Derived state --------------------------------------------------

    @property
    def is_root(self) -> bool:
        return self.parent_id is None

    def __repr__(self) -> str:
        return f"<Menu {self.title}>"
