import logging

from dataclasses import dataclass, field

from .context import Context

log = logging.getLogger("datainbox.pipeline")


CLIENT_INBOX = "433537c3-29b7-494d-afae-0d9603649c30"
NDT = "c3996547-1060-4905-9480-a78e1b1059c7"
CONT = "5f8a6f81-11c1-4723-a460-b0b3a37a4870"
COBRA = "d77a3950-440a-4455-b4b2-d0932fc884f8"
FLEX = "273b7935-a060-49b4-84e8-3fdb7bc49549"

_DELIMITERS = (" ", "_", "-", ".")


@dataclass(frozen=True)
class CategoryRule:
    """One category's match criteria.

    Args:
        category_id:  the drop-down option id to write to ``file_category``.
        priority:     higher wins. Ties fall back to position in the rule list.
        label:        human name, for logging only.
        substrings:   match against filename tokens. A value containing a space
                      is matched as a phrase across consecutive tokens.
        folder_names: match (case-insensitively) against any one path component.
    """

    category_id: str
    priority: int
    label: str = ""
    substrings: tuple[str, ...] = ()
    folder_names: tuple[str, ...] = ()


DEFAULT_RULES: tuple[CategoryRule, ...] = (
    CategoryRule(
        category_id=NDT,
        priority=100,
        label="NDT",
        substrings=("nd", "ndt", "discrimination", "testing"),
        folder_names=("Uploaded ND Testing Inbox",),
    ),
    CategoryRule(
        category_id=CONT,
        priority=90,
        label="CONT",
        substrings=(
            "cont", "contribution", "contributions", "payroll",
            "ih", "deposit", "deposits",
        ),
    ),
    CategoryRule(
        category_id=COBRA,
        priority=80,
        label="COBRA",
        substrings=(
            "in", "initial notice", "new hire", "nh", "npm", "qb", "term",
        ),
    ),
    CategoryRule(
        category_id=FLEX,
        priority=70,
        label="FLEX",
        substrings=(
            "ia", "demoelec", "demo_elec", "demoelect", "demo_elect",
            "enroll", "enrollment", "cafeteria", "cafeteriaplan", "fsahsa",
            "eli", "xml", "flex", "demo", "(edited)",
        ),
    ),
)


def tokenize(text: str) -> tuple[str, ...]:
    """Lowercase ``text`` and split it on every delimiter, dropping empties."""
    text = (text or "").lower()
    for delimiter in _DELIMITERS:
        text = text.replace(delimiter, "|")

    return tuple(t for t in text.split("|") if t)


def _phrase_in(tokens: tuple[str, ...], phrase: tuple[str, ...]) -> bool:
    """True if ``phrase`` appears as a run of consecutive ``tokens``."""
    if not phrase:
        return False

    n = len(phrase)
    return any(tokens[i:i + n] == phrase for i in range(len(tokens) - n + 1))


def _matches(rule: CategoryRule, tokens: tuple[str, ...], folders: frozenset[str]) -> bool:
    for substring in rule.substrings:
        if _phrase_in(tokens, tokenize(substring)):
            return True

    for folder_name in rule.folder_names:
        if folder_name.strip().lower() in folders:
            return True

    return False


def categorize(
    filename: str,
    directory: str,
    rules: tuple[CategoryRule, ...] = DEFAULT_RULES,
    default: str = CLIENT_INBOX,
) -> str:
    """Resolve the ``file_category`` option id for a file.

    Rules are tried highest ``priority`` first and the first match wins;
    ``default`` (CLIENT_INBOX) is returned when nothing matches.
    """

    tokens = tokenize(filename)
    folders = frozenset(part.strip().lower() for part in (directory or "").split("/") if part.strip())

    for rule in sorted(rules, key=lambda r: -r.priority):
        if _matches(rule, tokens, folders):
            log.info(f"categorized {filename!r} in {directory!r} as {rule.label or rule.category_id}")
            return rule.category_id

    log.info(f"no category rule matched {filename!r} in {directory!r}, defaulting to CLIENT_INBOX")
    return default


def add_tags(ctx: Context) -> bool:
    task_id = ctx.task_id

    filename = ctx.datafile.ftp_filename
    directory = ctx.datafile.ftp_directory

    if ".pgp" in filename:
        ctx.services.clickup.tag(task_id, "decrypt")

    if "/Snow Globe Theater - RMRSNOW/" in directory or \
       "/Orange Tree Co-RMROTREE/" in directory or \
       "testsite" in ctx.username:
        ctx.services.clickup.tag(task_id, "debug")

    return True


def set_status(ctx: Context) -> bool:
    task_id = ctx.task_id

    directory = ctx.datafile.ftp_directory

    if any([sub in directory for sub in ["archived", "termed"]]):
        ctx.services.clickup.set_status(task_id, "TERMED CLIENT")