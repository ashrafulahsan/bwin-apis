"""The demo blog content: an LMS-shaped taxonomy and the posts filed under it.

Specs only - the code that applies them is in `scripts/seed/blogs.py`.

The two taxonomies are the ones the blogs module looks up by slug,
`blog_category` and `blog_tag`, and both are seeded by migration. What is
here is the vocabulary inside them, and posts that between them cover every
state a listing has to render.
"""

from typing import TypedDict

from app.modules.blogs.constants import BlogStatus
from app.modules.categories.constants import CategoryStatus


class DemoCategory(TypedDict, total=False):
    name: str
    description: str
    parent: str
    status: CategoryStatus


#: The `blog_category` taxonomy - what a post is about, one per post. Parents
#: come before their children, which is all the ordering the seeding loop
#: needs to resolve `parent` by name.
DEMO_BLOG_CATEGORIES: list[DemoCategory] = [
    {
        "name": "Teaching and Instruction",
        "description": "Running a course: planning it, delivering it, marking it.",
    },
    {
        "name": "Course Design",
        "description": "Structuring modules and lessons, and the path between them.",
        "parent": "Teaching and Instruction",
    },
    {
        "name": "Assessment and Grading",
        "description": "Quizzes, rubrics, feedback and certificates.",
        "parent": "Teaching and Instruction",
    },
    {
        "name": "Learning Experience",
        "description": "The course seen from the student's side of the screen.",
    },
    {
        "name": "Student Engagement",
        "description": "Getting a cohort to show up, and to keep showing up.",
        "parent": "Learning Experience",
    },
    {
        "name": "Accessibility",
        "description": "Making a course work for every student who enrols.",
        "parent": "Learning Experience",
    },
    {
        "name": "Platform and Product",
        "description": "What changed in the platform, and how to use it.",
    },
    {
        "name": "Release Notes",
        "description": "What shipped, when, and what it replaces.",
        "parent": "Platform and Product",
    },
    {
        "name": "Integrations",
        "description": "Connecting the LMS to the tools a school already runs.",
        "parent": "Platform and Product",
    },
    # Retired rather than deleted, so the demo data covers the case the blogs
    # module refuses: an inactive category cannot be assigned to a post.
    {
        "name": "Exam Prep",
        "description": "Folded into Assessment and Grading. Kept for old posts.",
        "parent": "Learning Experience",
        "status": CategoryStatus.INACTIVE,
    },
]

#: The `blog_tag` taxonomy - finer labels, any number per post. Flat, because
#: tags are for finding things and a nested tag is a category wearing a hat.
#:
#: No tag repeats a category name. It would be allowed - names are unique
#: within a taxonomy, not across them - but slugs are unique across the whole
#: `categories` table, so the second one would quietly become `-2`.
DEMO_BLOG_TAGS: list[DemoCategory] = [
    {"name": "Onboarding", "description": "A student's first week."},
    {"name": "Instructor Tips", "description": "Practical advice for teaching staff."},
    {"name": "Quiz Design", "description": "Writing questions worth answering."},
    {"name": "Rubrics", "description": "Marking consistently, and showing the work."},
    {"name": "Learning Analytics", "description": "What the course data says."},
    {"name": "Certificates", "description": "Credentials a student can show."},
    {"name": "Video Lessons", "description": "Recorded material and its captions."},
    {"name": "Live Classes", "description": "Scheduled sessions and attendance."},
    {"name": "Mobile Learning", "description": "Studying on a phone, often offline."},
    {"name": "SCORM", "description": "Interoperating with older courseware."},
]


class DemoBlog(TypedDict, total=False):
    title: str
    slug: str
    excerpt: str
    content: str
    category: str
    tags: list[str]
    author: str
    featured: bool
    image: tuple[str, str]
    keywords: str
    robots: str
    status: BlogStatus
    #: Days from now for `published_at` - negative is in the past, positive
    #: schedules the post. Ignored while the post is a draft.
    days: int


#: Posts covering every state a listing has to render: live, featured,
#: scheduled, archived and still in draft. Each is written by the demo
#: account that would really have written it, including an Editor's draft,
#: which is as far as an Editor can take one.
DEMO_BLOGS: list[DemoBlog] = [
    {
        "title": "Designing a Course Outline Students Actually Finish",
        "slug": "designing-a-course-outline-students-actually-finish",
        "excerpt": (
            "Completion is decided in the outline, before a single lesson is "
            "recorded. Four habits that keep a cohort moving to the last module."
        ),
        "content": """<p>Most courses lose students in week three, and the
reason is usually visible in the outline. A module that takes ninety minutes
sits next to one that takes six hours, and nothing on the page warns
anyone.</p>

<h2>Size the modules honestly</h2>
<p>Write the real time each module takes next to its title, then look at the
list. If the numbers swing wildly the course does not have a difficulty
curve, it has a cliff. Split the long modules until nothing exceeds an
evening of work.</p>

<h2>Open with something finishable</h2>
<p>The first lesson should be completable in one sitting and should produce
something the student can see. Momentum in week one is worth more than
coverage.</p>

<h2>Say what each module is for</h2>
<p>One sentence per module, phrased as what the student will be able to do.
If that sentence is hard to write, the module is doing too many things.</p>

<h2>Leave the last week light</h2>
<p>Students arrive at the final module tired. Put the assessment there and
little else, and completion moves without a single change to the
material.</p>""",
        "category": "Course Design",
        "tags": ["Instructor Tips", "Onboarding"],
        "author": "instructor@bwin.example.com",
        "featured": True,
        "image": (
            "/media/blog/course-outline-planning.jpg",
            "An instructor mapping course modules on a whiteboard.",
        ),
        "keywords": "course design, completion, module planning, lms",
        "status": BlogStatus.PUBLISHED,
        "days": -21,
    },
    {
        "title": "Writing Quiz Questions That Measure Understanding",
        "slug": "writing-quiz-questions-that-measure-understanding",
        "excerpt": (
            "A quiz everyone passes and a quiz everyone fails tell you the "
            "same thing: nothing. Here is what to change."
        ),
        "content": """<p>A quiz is an instrument, and most quizzes are badly
calibrated. They measure whether a student read the slides last night, not
whether they understood them.</p>

<h2>Make the wrong answers mean something</h2>
<p>Every distractor should be a mistake a real student makes. When one of
them is chosen by a third of the cohort you have found the misconception
worth teaching to, which a plausible but invented distractor can never tell
you.</p>

<h2>Ask for the reason, not the fact</h2>
<p>"Which of these is a primary key?" tests recall. "This table has two
candidate keys, which one should be primary and why?" tests the thing you
actually taught.</p>

<h2>Publish the rubric with the question</h2>
<p>For anything marked by hand, students should see the rubric before they
answer. Marking gets faster, appeals get rarer, and the rubric itself gets
better because everyone has read it.</p>

<h2>Read the item analysis</h2>
<p>A question that strong and weak students answer identically is not
discriminating between them. Rewrite it or drop it.</p>""",
        "category": "Assessment and Grading",
        "tags": ["Quiz Design", "Rubrics"],
        "author": "lead.instructor@bwin.example.com",
        "image": (
            "/media/blog/quiz-item-analysis.jpg",
            "An item analysis chart open on a laptop screen.",
        ),
        "keywords": "quiz design, assessment, rubrics, item analysis",
        "status": BlogStatus.PUBLISHED,
        "days": -14,
    },
    {
        "title": "Keeping a Cohort Talking After Week Three",
        "slug": "keeping-a-cohort-talking-after-week-three",
        "excerpt": (
            "Discussion boards go quiet on a schedule. Four things that keep "
            "a cohort in conversation past the point where it usually stops."
        ),
        "content": """<p>Enrolment enthusiasm carries a discussion board for
about two weeks. After that, participation is something you design for or
something you lose.</p>

<h2>Ask questions with no answer key</h2>
<p>"What did the reading say?" produces eleven versions of the same summary.
"Where would this approach fail in your own work?" produces a conversation,
because no two students have the same work.</p>

<h2>Reply in public, and early</h2>
<p>The first week sets the norm. An instructor who answers three threads on
the board teaches the cohort that the board is read; one who answers by
email teaches them that it is not.</p>

<h2>Give the quiet students a smaller room</h2>
<p>Groups of four get contributions from people who will never post to a
group of forty. Rotate the groups so they do not calcify.</p>

<h2>Take the live session agenda from the board</h2>
<p>Students post more when posting visibly changes what happens next. Pull
the week's agenda from the threads rather than the syllabus and say where it
came from.</p>""",
        "category": "Student Engagement",
        "tags": ["Live Classes", "Instructor Tips"],
        "author": "content@bwin.example.com",
        "keywords": "student engagement, discussion boards, cohort, retention",
        "status": BlogStatus.PUBLISHED,
        "days": -9,
    },
    {
        "title": "Captions, Transcripts, and the Students You Never Hear From",
        "slug": "captions-transcripts-and-the-students-you-never-hear-from",
        "excerpt": (
            "Accessibility work is usually described as a legal obligation. "
            "It is also the cheapest engagement improvement available."
        ),
        "content": """<p>The students who need captions rarely ask for them.
They enrol, find the videos hard going, and drift out of the course without
ever filing the complaint that would have told you.</p>

<h2>Captions are used by everyone</h2>
<p>Watch where captions get switched on and it is not only students with
hearing loss. It is the commuter on a loud bus, the student reading in a
second language, and anyone skimming a lecture for one specific point.</p>

<h2>Transcripts make video searchable</h2>
<p>A forty minute lecture is opaque to search until it has a transcript.
After that, a student looking for the five minutes about deadlock recovery
can actually find them.</p>

<h2>Alternative text is part of the lesson</h2>
<p>A diagram described as "diagram.png" is missing from the course for anyone
using a screen reader. Describing what it shows takes a sentence, and usually
improves the caption for everyone.</p>

<h2>Check it on a phone</h2>
<p>Most accessibility failures are also mobile failures: text too small to
read, controls too close together, a player that hides its caption button.
Fixing one usually fixes the other.</p>""",
        "category": "Accessibility",
        "tags": ["Video Lessons", "Mobile Learning"],
        "author": "content@bwin.example.com",
        "image": (
            "/media/blog/captioned-lecture.jpg",
            "A lecture video playing with captions enabled on a phone.",
        ),
        "keywords": "accessibility, captions, transcripts, alt text",
        "status": BlogStatus.PUBLISHED,
        "days": -5,
    },
    {
        "title": "What Course Analytics Can and Cannot Tell You",
        "slug": "what-course-analytics-can-and-cannot-tell-you",
        "excerpt": (
            "Time on page is not attention and completion is not learning. A "
            "short guide to reading the dashboard sceptically."
        ),
        "content": """<p>Every LMS dashboard reports numbers that look like
learning and are not. Knowing which is which is most of the skill.</p>

<h2>Time on page measures a browser tab</h2>
<p>A student with the lesson open in one tab and a film in another produces
an excellent engagement figure. Treat a long duration as a question, not an
achievement.</p>

<h2>Completion measures compliance</h2>
<p>Marking a video watched says the progress bar reached the end. Pair it
with something that cannot be produced without understanding - a question, a
submission, an explanation - before calling it learning.</p>

<h2>Drop-off points are the honest signal</h2>
<p>The place a cohort stops is real, repeatable and usually specific: one
lesson, one assignment, one week. That is where to spend your editing
time.</p>

<h2>Compare cohorts, not students</h2>
<p>Individual figures are noisy and inviting to over-read. Two cohorts taking
the same course either side of a change is a comparison that means
something.</p>""",
        "category": "Learning Experience",
        "tags": ["Learning Analytics", "Instructor Tips"],
        "author": "lead.instructor@bwin.example.com",
        "keywords": "learning analytics, engagement, completion, dashboards",
        "status": BlogStatus.PUBLISHED,
        "days": -2,
    },
    {
        "title": "August Release: Gradebook Exports and Faster Video Uploads",
        "slug": "august-release-gradebook-exports-and-faster-video-uploads",
        "excerpt": (
            "Scheduled exports, resumable uploads and a quieter notification "
            "digest. What changed this month, and what it replaces."
        ),
        "content": """<p>This month's release is mostly about the two things
instructors do at the end of a term: getting marks out, and getting video
in.</p>

<h2>Scheduled gradebook exports</h2>
<p>A gradebook can now be exported on a schedule to CSV or XLSX, with the
same column selection every time. A department running a weekly report no
longer needs someone to remember to run it.</p>

<h2>Resumable video uploads</h2>
<p>Uploads resume after a dropped connection rather than starting again. On
the connections most of our campuses actually have, that is the difference
between uploading a lecture once and uploading it three times.</p>

<h2>A quieter digest</h2>
<p>Discussion notifications are batched into one daily digest by default.
Per-thread notifications are still available, and anyone who had them on
keeps them.</p>

<h2>Deprecations</h2>
<p>The legacy gradebook import is switched off this month. The archived note
on that change has the migration path.</p>""",
        "category": "Release Notes",
        "tags": ["Learning Analytics", "Video Lessons"],
        "author": "admin@bwin.example.com",
        "featured": True,
        "keywords": "release notes, gradebook export, video upload",
        "status": BlogStatus.PUBLISHED,
        "days": -1,
    },
    {
        "title": "Issuing Certificates Students Want to Share",
        "slug": "issuing-certificates-students-want-to-share",
        "excerpt": (
            "A certificate nobody shares is a PDF nobody opens. What belongs "
            "on one, and what to leave off."
        ),
        "content": """<p>Course certificates are handed out by the thousand
and posted by the dozen. The difference is almost entirely in what the
certificate says.</p>

<h2>Name the skill, not the seat time</h2>
<p>"Attended 40 hours" describes a room. "Can build and deploy a REST API
with automated tests" describes a person, and is what someone reading a
profile is looking for.</p>

<h2>Make it verifiable</h2>
<p>Every certificate needs a public verification URL and an identifier that
resolves to it. Without one it is an image file, and it gets treated as
one.</p>

<h2>Set an expiry only when it is real</h2>
<p>Compliance training expires. An introduction to statistics does not.
Expiring a certificate that should not expire teaches students to distrust
the ones that do.</p>

<h2>Issue it the moment it is earned</h2>
<p>A certificate arriving three weeks after the final assessment misses the
only moment the student was going to post about it.</p>""",
        "category": "Assessment and Grading",
        "tags": ["Certificates", "Rubrics"],
        "author": "instructor@bwin.example.com",
        "keywords": "certificates, credentials, verification",
        # Published with a date in the future: scheduled, so an administrator
        # sees it and a reader does not until the day arrives.
        "status": BlogStatus.PUBLISHED,
        "days": 3,
    },
    {
        "title": "Connecting Live Classes to the Course Timeline",
        "slug": "connecting-live-classes-to-the-course-timeline",
        "excerpt": (
            "Sessions booked in one tool and coursework tracked in another "
            "means two calendars and one confused cohort."
        ),
        "content": """<p>Most schools arrive with a conferencing tool already
chosen and a term of bookings in it. The integration work is not about
replacing that tool, it is about the timeline the student sees.</p>

<h2>One calendar for the student</h2>
<p>Live sessions, deadlines and released modules belong on the same timeline.
Two calendars means the student who checks one misses whichever half they did
not check.</p>

<h2>Attendance should land where the marks are</h2>
<p>If attendance counts towards a grade it has to reach the gradebook
automatically. A spreadsheet copied by hand each week is a reconciliation
error waiting for the end of term.</p>

<h2>Recordings belong to the lesson</h2>
<p>A recording attached to the module it belongs to gets watched. One sitting
in a shared drive folder named by date does not.</p>

<h2>Older courseware still counts</h2>
<p>SCORM packages a department paid for a decade ago need to appear on the
same timeline as everything else, and be tracked the same way.</p>""",
        "category": "Integrations",
        "tags": ["Live Classes", "SCORM", "Mobile Learning"],
        # An Editor writes and revises but does not publish, so a draft is
        # exactly as far as this account can take a post.
        "author": "editor@bwin.example.com",
        "keywords": "integrations, live classes, scorm, calendar",
        "status": BlogStatus.DRAFT,
    },
    {
        "title": "Retiring the Legacy Gradebook Import",
        "slug": "retiring-the-legacy-gradebook-import",
        "excerpt": (
            "The old CSV importer is being switched off. What replaces it, "
            "and what to do with the templates built around it."
        ),
        "content": """<p>The legacy gradebook importer was written against a
column layout we no longer produce, and it has been failing quietly on any
file containing a rubric column. It is now switched off.</p>

<h2>What replaces it</h2>
<p>The current import accepts the same CSV, validates it before writing
anything, and reports the rows it cannot read instead of skipping them. A
dry run shows exactly what would change.</p>

<h2>What to do with old templates</h2>
<p>Templates keep working: the column names are unchanged. The one difference
is that a blank cell now means no mark recorded rather than zero, which is
what most people assumed it meant already.</p>

<h2>If you need the old behaviour</h2>
<p>Export from the current gradebook and reimport, or send the file to
support. Nothing is lost - this note stays online because its URL is in
several help articles.</p>""",
        "category": "Release Notes",
        "tags": ["Learning Analytics"],
        "author": "admin@bwin.example.com",
        "keywords": "gradebook import, deprecation, csv, migration",
        # Still reachable, but no longer worth ranking: the current note is
        # what a search should return.
        "robots": "noindex, follow",
        # Retired, not deleted: the URL still has to resolve for the help
        # articles that link to it.
        "status": BlogStatus.ARCHIVED,
        "days": -400,
    },
]
