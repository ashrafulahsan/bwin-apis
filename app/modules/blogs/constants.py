"""Constants for the blogs module.

A blog post files itself under the shared category tree rather than under
tables of its own: its category comes from the `blog_category` taxonomy and
its tags from `blog_tag`. That is why there is no `blog_categories` table
here - one vocabulary, one place to manage it, and a taxonomy the categories
module already knows how to nest, rename and retire.

Both taxonomies are seeded by migration, so the module works on a fresh
database without an administrator having to guess the names.
"""

from enum import StrEnum

BLOG_TITLE_MAX_LENGTH = 200
BLOG_SLUG_MAX_LENGTH = 255
BLOG_EXCERPT_MAX_LENGTH = 500
BLOG_IMAGE_URL_MAX_LENGTH = 500
BLOG_IMAGE_ALT_MAX_LENGTH = 255

#: Slugs of the two category types a blog post draws on. Code refers to them
#: by slug rather than by name, so renaming "Blog Category" to "Topics" in an
#: admin screen does not break every blog write.
BLOG_CATEGORY_TYPE_SLUG = "blog_category"
BLOG_TAG_TYPE_SLUG = "blog_tag"

#: Display names used when the taxonomies are seeded.
BLOG_CATEGORY_TYPE_NAME = "Blog Category"
BLOG_TAG_TYPE_NAME = "Blog Tag"

#: Past this, tags stop being a way to find anything and become decoration.
MAX_TAGS_PER_BLOG = 10

#: Average adult reading speed, used to estimate `reading_minutes`.
WORDS_PER_MINUTE = 200


class BlogStatus(StrEnum):
    """Where a post is in its life.

    `DRAFT` is being written and is not public. `PUBLISHED` is live, or
    scheduled - a published post whose `published_at` is still in the future
    is not served as live until that moment passes. `ARCHIVED` was live once
    and has been retired, which is not the same as deleted: its URL still has
    to resolve for anyone holding a link.
    """

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


DEFAULT_BLOG_STATUS = BlogStatus.DRAFT

#: Columns a free-text search looks at.
BLOG_SEARCH_FIELDS = ("title", "slug", "excerpt", "content")
