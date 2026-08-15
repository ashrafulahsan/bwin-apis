"""Search-engine metadata carried by anything with a public URL.

A blog post needs these columns; so will CMS pages and course landing pages.
Defining them once as a mixin means the three cannot drift apart, and a client
rendering `<head>` reads the same field names whatever it is rendering.

Every field is nullable except `meta_robots`, because an author who fills none
of them should still get a correct page: the read schema derives the missing
values from the content itself - see `app.shared.schemas.seo`.
"""

from sqlalchemy import String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

SEO_TITLE_MAX_LENGTH = 255
SEO_DESCRIPTION_MAX_LENGTH = 500
SEO_KEYWORDS_MAX_LENGTH = 255
SEO_URL_MAX_LENGTH = 500
SEO_ROBOTS_MAX_LENGTH = 100

#: Lengths search engines actually display. Not enforced - an author may have
#: a reason to go longer - but used when a value is derived, and reported in
#: the OpenAPI descriptions so the choice is informed.
RECOMMENDED_META_TITLE_LENGTH = 60
RECOMMENDED_META_DESCRIPTION_LENGTH = 160

#: What a page gets when nobody says otherwise: visible, and links followed.
DEFAULT_META_ROBOTS = "index, follow"

#: The directives a `meta_robots` value may be built from. An allowlist
#: because a typo here is invisible - "nofollw" silently indexes a page the
#: author meant to hide, and nothing in the response would say so.
ROBOTS_DIRECTIVES = frozenset(
    {
        "index",
        "noindex",
        "follow",
        "nofollow",
        "all",
        "none",
        "noarchive",
        "nosnippet",
        "noimageindex",
        "notranslate",
    }
)


class SEOFieldsMixin:
    """Columns describing how a piece of content appears in search and shares.

    Split into three groups: the `meta_*` fields feed the standard tags, the
    `og_*` fields feed Open Graph previews on social platforms, and
    `canonical_url` names the address that should be treated as authoritative
    when the same content is reachable from more than one URL.
    """

    meta_title: Mapped[str | None] = mapped_column(
        String(SEO_TITLE_MAX_LENGTH),
        default=None,
        doc="Overrides the content title in search results.",
    )
    meta_description: Mapped[str | None] = mapped_column(
        String(SEO_DESCRIPTION_MAX_LENGTH),
        default=None,
        doc="The snippet under the title in search results.",
    )
    meta_keywords: Mapped[str | None] = mapped_column(
        String(SEO_KEYWORDS_MAX_LENGTH),
        default=None,
        doc="Comma separated. Ignored by most engines, still asked for.",
    )
    canonical_url: Mapped[str | None] = mapped_column(
        String(SEO_URL_MAX_LENGTH),
        default=None,
        doc="Authoritative address when the content is reachable twice.",
    )

    og_title: Mapped[str | None] = mapped_column(
        String(SEO_TITLE_MAX_LENGTH), default=None
    )
    og_description: Mapped[str | None] = mapped_column(
        Text,
        default=None,
        doc="Open Graph description, shown in social previews.",
    )
    og_image_url: Mapped[str | None] = mapped_column(
        String(SEO_URL_MAX_LENGTH), default=None
    )

    meta_robots: Mapped[str] = mapped_column(
        String(SEO_ROBOTS_MAX_LENGTH),
        default=DEFAULT_META_ROBOTS,
        server_default=text(f"'{DEFAULT_META_ROBOTS}'"),
        nullable=False,
        doc="Crawler directives, e.g. 'noindex, nofollow' for a draft.",
    )

    @property
    def is_indexable(self) -> bool:
        """Whether the robots directives let this content into an index."""
        directives = {part.strip().lower() for part in self.meta_robots.split(",")}
        return not directives & {"noindex", "none"}
