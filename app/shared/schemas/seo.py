"""Request and response schemas for search-engine metadata.

`SEOMetadata` is what a client sends: every field optional, because asking an
author to fill eight boxes before publishing is how those boxes end up filled
with the title eight times.

`SEOMetadataRead` is what comes back, and it is always complete. Missing
values are derived - the meta title from the content title, the description
from its summary, the Open Graph fields from the meta fields - so a client
rendering `<head>` never has to implement that cascade itself, and two clients
cannot implement it differently.
"""

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.shared.models.seo import (
    DEFAULT_META_ROBOTS,
    RECOMMENDED_META_DESCRIPTION_LENGTH,
    RECOMMENDED_META_TITLE_LENGTH,
    ROBOTS_DIRECTIVES,
    SEO_DESCRIPTION_MAX_LENGTH,
    SEO_KEYWORDS_MAX_LENGTH,
    SEO_TITLE_MAX_LENGTH,
    SEO_URL_MAX_LENGTH,
)

#: Fields the caller may set. Named once so the service can copy exactly these
#: onto a model without listing them a second time.
SEO_FIELDS = (
    "meta_title",
    "meta_description",
    "meta_keywords",
    "canonical_url",
    "og_title",
    "og_description",
    "og_image_url",
    "meta_robots",
)


def normalize_robots(value: str) -> str:
    """Validate and tidy a `meta_robots` value.

    Rejects an unknown directive rather than storing it: a misspelled
    `noindex` fails open, publishing a page the author meant to keep out of
    search, and nothing in a successful response would hint at it.

    Raises `ValueError`, so a bad value comes back as a 422 naming the field,
    like every other schema failure in the project.
    """
    directives = [part.strip().lower() for part in value.split(",") if part.strip()]

    if not directives:
        return DEFAULT_META_ROBOTS

    unknown = [part for part in directives if part not in ROBOTS_DIRECTIVES]
    if unknown:
        raise ValueError(
            f"unknown directive: {', '.join(unknown)}. "
            f"Use one or more of: {', '.join(sorted(ROBOTS_DIRECTIVES))}"
        )

    # Deduplicate, keeping the order the author wrote.
    seen: dict[str, None] = dict.fromkeys(directives)
    return ", ".join(seen)


def shorten(value: str, limit: int) -> str:
    """Trim to `limit`, preferring a word boundary and an ellipsis."""
    stripped = " ".join(value.split())
    if len(stripped) <= limit:
        return stripped

    clipped = stripped[: limit - 1]
    head, separator, _ = clipped.rpartition(" ")

    # Only honour the word boundary when it keeps most of the text.
    if separator and len(head) >= limit // 2:
        clipped = head

    return f"{clipped.rstrip(' ,.;:-')}…"


class SEOMetadata(BaseModel):
    """Search metadata as supplied by an author. Every field is optional."""

    model_config = ConfigDict(from_attributes=True)

    meta_title: str | None = Field(
        default=None,
        max_length=SEO_TITLE_MAX_LENGTH,
        description=(
            "Title shown in search results. Defaults to the content title. "
            f"Around {RECOMMENDED_META_TITLE_LENGTH} characters is displayed."
        ),
    )
    meta_description: str | None = Field(
        default=None,
        max_length=SEO_DESCRIPTION_MAX_LENGTH,
        description=(
            "Snippet shown under the title. Defaults to the summary. "
            f"Around {RECOMMENDED_META_DESCRIPTION_LENGTH} characters is "
            "displayed."
        ),
    )
    meta_keywords: str | None = Field(
        default=None,
        max_length=SEO_KEYWORDS_MAX_LENGTH,
        description="Comma separated keywords.",
    )
    canonical_url: str | None = Field(
        default=None,
        max_length=SEO_URL_MAX_LENGTH,
        description=(
            "Authoritative address for this content, absolute or site "
            "relative, when it is reachable from more than one URL."
        ),
    )
    og_title: str | None = Field(default=None, max_length=SEO_TITLE_MAX_LENGTH)
    og_description: str | None = Field(
        default=None, max_length=SEO_DESCRIPTION_MAX_LENGTH
    )
    og_image_url: str | None = Field(
        default=None,
        max_length=SEO_URL_MAX_LENGTH,
        description="Image used in social previews. Defaults to the cover image.",
    )
    meta_robots: str | None = Field(
        default=None,
        description=(
            "Crawler directives, e.g. `noindex, nofollow`. Defaults to "
            f"`{DEFAULT_META_ROBOTS}`."
        ),
    )

    @field_validator("meta_robots")
    @classmethod
    def _check_robots(cls, value: str | None) -> str | None:
        return normalize_robots(value) if value is not None else None

    @field_validator("canonical_url", "og_image_url")
    @classmethod
    def _check_url(cls, value: str | None) -> str | None:
        """Absolute `http(s)` or site relative, and nothing else.

        A `javascript:` canonical is the kind of thing that ends up rendered
        straight into an attribute, so the scheme is checked here rather than
        wherever the value is eventually printed.
        """
        if value is None:
            return None

        trimmed = value.strip()
        if not trimmed:
            return None

        if trimmed.startswith(("http://", "https://", "/")):
            return trimmed

        raise ValueError("must start with http://, https:// or /")

    @field_validator("*")
    @classmethod
    def _blank_is_absent(cls, value: Any) -> Any:
        """An empty box in a form means "unset", not an empty meta tag."""
        if isinstance(value, str) and not value.strip():
            return None
        return value


class SEOMetadataRead(BaseModel):
    """Search metadata as served: complete, with every gap filled in."""

    meta_title: str
    meta_description: str | None
    meta_keywords: str | None
    canonical_url: str | None
    og_title: str
    og_description: str | None
    og_image_url: str | None
    meta_robots: str
    is_indexable: bool

    @classmethod
    def resolve(
        cls,
        source: Any,
        *,
        title: str,
        summary: str | None = None,
        image_url: str | None = None,
    ) -> Self:
        """Build the served metadata from stored columns plus the content.

        `source` is any object carrying `SEOFieldsMixin`'s columns. The
        derived description is shortened to the length search engines show,
        so falling back to a long summary does not produce a snippet that is
        cut off mid-sentence by the engine instead.
        """
        meta_title = source.meta_title or title

        described = source.meta_description
        if not described and summary:
            described = shorten(summary, RECOMMENDED_META_DESCRIPTION_LENGTH)

        robots = source.meta_robots or DEFAULT_META_ROBOTS
        directives = {part.strip().lower() for part in robots.split(",")}

        return cls(
            meta_title=meta_title,
            meta_description=described,
            meta_keywords=source.meta_keywords,
            canonical_url=source.canonical_url,
            og_title=source.og_title or meta_title,
            og_description=source.og_description or described,
            og_image_url=source.og_image_url or image_url,
            meta_robots=robots,
            is_indexable=not directives & {"noindex", "none"},
        )
