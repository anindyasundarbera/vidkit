"""The *timeframe*: which days a video is about.

A timeframe is the second half of what makes a video **aimable**. It is declared
once — in the spec, or as a default in the story manifest — in either spelling:

* relative   ``{days: 28, as_of: 2026-10-06}``   ("the last 28 days")
* explicit   ``{start: 2026-09-08, end: 2026-10-06}``

Both resolve to a single frozen :class:`Timeframe`, so no two parts of the
pipeline can disagree about the window. Providers read it as ``ctx.timeframe``
and hand the resolved dates to their data source instead of hard-coding
``?days=28`` in a URL.

The same grammar (:func:`find_window_claims`) reads a window back *out of
narration*, which is how :mod:`vidkit.verify` catches a video that says "the last
28 days" while its spec says 90. The spoken forms are documented in
``docs/authoring/stories-and-timeframes.md``.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any

from .errors import SpecError

# --------------------------------------------------------------------------- #
# The resolved window
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Timeframe:
    """One concrete window. Built from either spelling; never ambiguous.

    ``days`` counts inclusively: ``{days: 28, as_of: 2026-10-06}`` spans
    2026-09-09 … 2026-10-06, which is 28 calendar days.
    """

    start: date
    end: date
    as_of: date | None = None
    declared: str = ""               # how it was written, for the report
    source: str = "spec"             # spec | story | override
    floating: bool = False           # True when no as_of was written down

    @property
    def label_with_source(self) -> str:
        return f"{self.label()} [{self.source}]"

    @property
    def days(self) -> int:
        """Inclusive day count (a one-day window is 1, not 0)."""
        return (self.end - self.start).days + 1

    def label(self) -> str:
        """Human label, e.g. ``2026-09-09 to 2026-10-06 (28 days)``."""
        unit = "day" if self.days == 1 else "days"
        return f"{self.start.isoformat()} to {self.end.isoformat()} ({self.days} {unit})"

    def prose(self) -> str:
        """Spelled-out form, safe to paste into narration.

        ``8 September 2026 to 6 October 2026`` — parses back exactly, so a
        scaffolded story passes its own timeframe check by construction.
        """
        return (f"{self.start.day} {calendar.month_name[self.start.month]} "
                f"{self.start.year} to {self.end.day} "
                f"{calendar.month_name[self.end.month]} {self.end.year}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "days": self.days,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "declared": self.declared,
            "source": self.source,
            "label": self.label(),
        }

    def as_prompt(self) -> dict[str, Any]:
        """The shape a provider forwards to a data source — data, not decoration."""
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "days": self.days,
            "as_of": (self.as_of or self.end).isoformat(),
            "label": self.label(),
        }

    def matches(self, other: "Timeframe") -> bool:
        return self.start == other.start and self.end == other.end

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.label()


def from_relative(days: int, as_of: date, *, source: str = "spec",
                  floating: bool = False) -> Timeframe:
    """``days`` days ending on ``as_of``, inclusive."""
    if days < 1:
        raise SpecError(f"timeframe.days must be >= 1 (got {days})")
    end = as_of
    start = _add_days(end, -(days - 1))
    return Timeframe(start=start, end=end, as_of=as_of, floating=floating,
                     declared=f"days={days} as_of={as_of.isoformat()}", source=source)


def from_absolute(start: date, end: date, *, as_of: date | None = None,
                  source: str = "spec") -> Timeframe:
    if start > end:
        raise SpecError(
            f"timeframe.start ({start.isoformat()}) must not be after "
            f"timeframe.end ({end.isoformat()})"
        )
    return Timeframe(start=start, end=end, as_of=as_of or end,
                     declared=f"start={start.isoformat()} end={end.isoformat()}",
                     source=source)


# --------------------------------------------------------------------------- #
# Parsing the declared form
# --------------------------------------------------------------------------- #
_SHORTHAND_DATE = r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})"
_SHORTHAND_ANY = r"\d{4}[-/]\d{1,2}[-/]\d{1,2}"


def _date(value: Any, where: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (tuple, list)) and len(value) == 3:
        y, mo, d = value
        try:
            return date(int(y), int(mo), int(d))
        except (TypeError, ValueError) as exc:
            raise SpecError(
                f"{where}: {y}-{mo}-{d} is not a real date ({exc})") from exc
    text = str(value).strip()
    m = re.fullmatch(_SHORTHAND_DATE, text)
    if m:
        return _date((int(m.group(1)), int(m.group(2)), int(m.group(3))), where)
    m = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)\.?\s+(\d{4})", text)
    if m:
        month = _month_number(m.group(2))
        if month is None:
            raise SpecError(f"{where}: unknown month {m.group(2)!r}")
        return _date((int(m.group(3)), month, int(m.group(1))), where)
    raise SpecError(
        f"{where}: {text!r} is not a date — use YYYY-MM-DD "
        "(a relative window uses `days` + `as_of` instead)"
    )


_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
_MONTHS.update({"sept": 9})


def _month_number(name: str) -> int | None:
    return _MONTHS.get(name.strip().rstrip(".").lower())


def parse_timeframe(raw: Any, *, where: str = "timeframe", source: str = "spec",
                    default_as_of: date | None = None) -> Timeframe | None:
    """Parse one declared timeframe. ``None``/empty means "not declared".

    Accepted spellings::

        {days: 28, as_of: 2026-10-06}       # relative; as_of defaults to today
        {days: 28}                         # allowed, but "floating" — see below
        {start: 2026-09-08, end: 2026-10-06}
        28d   2026-09-08..2026-10-06   2026-09-08    # shorthand string

    When a relative window has no ``as_of`` it resolves against ``default_as_of``
    (today, normally) and is marked ``floating`` — the same spec would mean a
    different window tomorrow, so :mod:`vidkit.spec` refuses to let narration
    spell out an end date it cannot guarantee.
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if default_as_of is not None:
        default_as_of = _date(default_as_of, f"{where}.as_of")

    if isinstance(raw, dict):
        known = {"days", "as_of", "start", "end", "weeks", "months"}
        unknown = sorted(set(raw) - known)
        if unknown:
            raise SpecError(
                f"{where}: unknown key(s) {', '.join(unknown)} — "
                "use days/as_of or start/end"
            )
        written = _present(raw, "as_of")
        as_of = _date(raw["as_of"], f"{where}.as_of") if written else default_as_of
        relative = [k for k in ("days", "weeks", "months") if _present(raw, k)]
        if _present(raw, "start") or _present(raw, "end"):
            if relative:
                raise SpecError(f"{where}: use either days/as_of or start/end, not both")
            # A lone `start:` is a typo, not a one-day window: silently rendering a
            # one-day video from a half-written range is exactly the kind of thing
            # this engine exists to refuse.
            if not (_present(raw, "start") and _present(raw, "end")):
                raise SpecError(f"{where}: start and end must be given together")
            start = _date(raw["start"], f"{where}.start")
            end = _date(raw["end"], f"{where}.end")
            return from_absolute(start, end, as_of=as_of, source=source)
        if relative:
            end_on = as_of or date.today()
            n = _window_days(raw, end_on, where)
            return from_relative(n, end_on, source=source, floating=not written)
        raise SpecError(f"{where}: needs `days` (with optional `as_of`) or `start`/`end`")

    if isinstance(raw, (date, datetime)):
        d = _date(raw, where)
        return from_absolute(d, d, source=source)

    text = str(raw).strip()
    m = re.fullmatch(r"(\d+)\s*([dwmy])", text, re.I)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        end_on = default_as_of or date.today()
        days = n if unit == "d" else n * 7 if unit == "w" else _span_days(
            end_on, n, "months" if unit == "m" else "years")
        return from_relative(days, end_on, source=source, floating=default_as_of is None)
    m = re.fullmatch(
        rf"\s*((?:{_SHORTHAND_ANY}|\d{{1,2}}\s+[A-Za-z]+\.?\s+\d{{4}}))\s*"
        rf"(?:\.\.|to|through|until|,|[\u2013\u2014]|--)\s*"
        rf"((?:{_SHORTHAND_ANY}|\d{{1,2}}\s+[A-Za-z]+\.?\s+\d{{4}}))\s*", text, re.I)
    if m:
        return from_absolute(_date(m.group(1), where), _date(m.group(2), where),
                              as_of=default_as_of, source=source)
    d = _date(text, where)
    return from_absolute(d, d, as_of=default_as_of, source=source)


def _present(raw: dict[str, Any], key: str) -> bool:
    """Is ``key`` written down? ``0``/``null`` count as *present* so they can be
    reported as the mistakes they are, rather than looking like an absent key."""
    return key in raw and raw[key] is not None


def _count(value: Any, where: str) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise SpecError(f"{where}: {value!r} is not a number of days ({exc})") from exc
    if n < 1:
        raise SpecError(f"{where}: the window must be >= 1 day (got {n})")
    return n


def _window_days(raw: dict[str, Any], end_on: date, where: str) -> int:
    """The day count a declared window asks for, inclusive of both ends."""
    if _present(raw, "days"):
        return _count(raw["days"], f"{where}.days")
    if _present(raw, "weeks"):
        return _count(raw["weeks"], f"{where}.weeks") * 7
    return _span_days(end_on, _count(raw["months"], f"{where}.months"), "months")


def _add_days(d: date, n: int) -> date:
    return date.fromordinal(d.toordinal() + n)


def _add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    year = d.year + m // 12
    month = m % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _span_days(as_of: date, n: int, unit: str) -> int:
    """Inclusive day count of the ``n``-unit window ending on ``as_of``.

    Months and years are *calendared*, not multiplied: "the last 6 months" from
    2026-10-06 spans 2026-04-06 … 2026-10-06, which is 184 days, not 180.
    """
    if n < 1:
        raise SpecError(f"timeframe: {n} {unit} is not a window")
    if unit == "months":
        return (as_of - _add_months(as_of, -n)).days + 1
    if unit == "years":
        return (as_of - _add_months(as_of, -12 * n)).days + 1
    raise SpecError(f"timeframe: unknown unit {unit!r}")


# --------------------------------------------------------------------------- #
# Reading a window back out of narration
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class WindowClaim:
    """A window a line of narration asserts.

    ``exact`` means both endpoints are known from the text. ``end_anchor`` is an
    end date mentioned alongside a relative claim ("the last 28 days to
    2026-10-06"); when it is absent, only the day count can be compared and the
    check says so rather than guessing.
    """

    raw: str
    start: date | None = None
    end: date | None = None
    days: int | None = None
    exact: bool = False
    end_anchor: date | None = None

    def label(self) -> str:
        if self.exact and self.start and self.end:
            return f"{self.start.isoformat()} to {self.end.isoformat()}"
        if self.end_anchor and self.days:
            return f"the {self.days} days to {self.end_anchor.isoformat()}"
        if self.days:
            return f"a {self.days}-day window"
        return self.raw


_QTY = (r"(\d{1,4}"
        r"|(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)"
        r"(?:[-\s](?:one|two|three|four|five|six|seven|eight|nine))?"
        r"|(?:ten|eleven|twelve|a|an|one|two|three|four|five|six|seven|eight|nine))")
_UNIT = r"(days?|weeks?|months?|years?)"
_ISO = r"(\d{4})[-/ ](\d{1,2})[-/ ](\d{1,2})"
_SPELLED = (r"(\d{1,2})\s+([A-Za-z]{3,9})\.?(?:\s+(\d{4}))?")
_RANGE_SEP = r"(?:\s+to\s+|\s+through\s+|\s+until\s+|\s*[\u2013\u2014]\s*|\s*--\s*|\s*\.\.\s*|\s*,\s*)"

_REL_ISO = re.compile(rf"\b{_ISO}{_RANGE_SEP}{_ISO}\b")
_REL_SPELLED = re.compile(rf"\b{_SPELLED}{_RANGE_SEP}{_SPELLED}\b", re.I)
_NUM_SEP = r"(?:\s*[-\u2013]\s*|\s+)"
_REL_N = re.compile(
    rf"\b(?:the\s+)?(?:last|past|previous|preceding|trailing|final)\s+"
    rf"{_QTY}{_NUM_SEP}{_UNIT}\b", re.I)
_REL_BARE = re.compile(
    r"\b(?:the\s+)?(?:last|past|previous|preceding|trailing|final)\s+"
    r"(day|week|month|year)\b", re.I)
_REL_WINDOW = re.compile(rf"\b{_QTY}[-\s](?:{_UNIT}\s*)?(?:window|period|span|stretch)\b",
                         re.I)

_ANCHOR = re.compile(
    rf"\b(?:as\s+of|as\s+at|ending|through|up\s+to|to)\s+"
    rf"(?:{_ISO}|{_SPELLED})\b", re.I)
_UNIT_DAYS = {"day": 1, "week": 7, "month": None, "year": None}


def _number(text: str) -> int:
    parts = re.split(r"[-\s]+", text.strip().lower())
    total = 0
    for p in parts:
        if p.isdigit():
            total += int(p)
        elif p in _NUM_WORDS:
            total += _NUM_WORDS[p]
        else:
            raise SpecError(f"cannot read the number {text!r} in narration")
    return total


_NUM_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}


def _spanned_days(as_of: date, n: int, unit: str) -> int:
    unit = unit.rstrip("s")
    if unit == "day":
        return n
    if unit == "week":
        return n * 7
    return _span_days(as_of, n, "months" if unit == "month" else "years")


def _iso_match(m: re.Match[str], offset: int = 0) -> date:
    y, mo, d = (int(m.group(offset + 1)), int(m.group(offset + 2)),
                int(m.group(offset + 3)))
    return _date((y, mo, d), "narration")


def _spelled_match(groups: tuple, *, fallback_year: int) -> date:
    day, name, year = groups[0], groups[1], groups[2]
    month = _month_number(name)
    if month is None:
        raise SpecError(f"narration states an unknown month {name!r}")
    return _date((int(year) if year else fallback_year, month, int(day)),
                 "narration")


def find_window_claims(text: str, *, as_of: date | None = None) -> list[WindowClaim]:
    """Every window the text asserts, in written order.

    Returns ``[]`` when the text is silent about time, which is not a failure —
    it only means there is nothing to cross-check.
    """
    claims: list[WindowClaim] = []
    taken: list[tuple[int, int]] = []

    def fresh(start: int, end: int) -> bool:
        if any(start < b and end > a for a, b in taken):
            return False
        taken.append((start, end))
        return True

    def span(start: date, end: date) -> int:
        return (max(start, end) - min(start, end)).days + 1

    def relative(n: int, unit: str) -> int:
        return _spanned_days(as_of or date.today(), n, unit)

    for m in _REL_ISO.finditer(text):
        if not fresh(*m.span()):
            continue
        start, end = _iso_match(m), _iso_match(m, 3)
        claims.append(WindowClaim(m.group(0).strip(), start=min(start, end),
                                  end=max(start, end), days=span(start, end),
                                  exact=True))
    fallback = (as_of or date.today()).year
    for m in _REL_SPELLED.finditer(text):
        if not fresh(*m.span()):
            continue
        start = _spelled_match(m.groups()[:3], fallback_year=fallback)
        end = _spelled_match(m.groups()[3:], fallback_year=start.year)
        claims.append(WindowClaim(m.group(0).strip(), start=min(start, end),
                                  end=max(start, end), days=span(start, end),
                                  exact=True))
    for pattern, has_unit in ((_REL_N, True), (_REL_BARE, False), (_REL_WINDOW, True)):
        for m in pattern.finditer(text):
            if not fresh(*m.span()):
                continue
            groups = m.groups()
            if has_unit:
                n, unit = _number(groups[0]), groups[1] or "days"
            else:
                n, unit = 1, groups[0]
            claims.append(WindowClaim(m.group(0).strip(), days=relative(n, unit)))

    anchors = [m for m in _ANCHOR.finditer(text)]
    if anchors:
        m = anchors[-1]
        anchor = (_iso_match(m) if m.group(1)
                  else _spelled_match(m.groups()[-3:], fallback_year=fallback))
        claims = [replace(c, end_anchor=anchor) if not c.exact else c for c in claims]
    return claims


# --------------------------------------------------------------------------- #
def timeframe_matches(tf: Timeframe, claim: WindowClaim) -> tuple[bool, str]:
    """Does narration's claim agree with the resolved window? (ok, detail)."""
    if claim.exact and claim.start and claim.end:
        ok = claim.start == tf.start and claim.end == tf.end
        return ok, (f"narration says {claim.label()}, "
                    f"spec says {tf.label()}")
    if claim.end_anchor and claim.days:
        ok = claim.end_anchor == tf.end and claim.days == tf.days
        return ok, (f"narration says {claim.label()}, "
                    f"spec says {tf.label()}")
    if claim.days:
        ok = claim.days == tf.days
        return ok, (f"narration says {claim.label()}, "
                    f"spec says {tf.label()}"
                    + ("" if ok else " (spell the dates, or pin as_of in the spec,"
                                     " to compare more precisely)"))
    return True, f"narration claim {claim.raw!r} carries no measurable window"
