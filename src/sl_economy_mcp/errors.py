"""Problems we expect, each with a message written for the person asking.

Anything that is not one of these is a bug in this project, and its details
are kept out of the assistant's answer.
"""


class ExpectedProblem(Exception):
    """Base class. The message is plain English and safe to show."""


class InvalidRequest(ExpectedProblem):
    """The request itself doesn't work: a bad date, an unknown currency."""


class SourceUnavailable(ExpectedProblem):
    """CBSL's website could not be reached or returned an error."""


class PageChanged(ExpectedProblem):
    """The page loaded, but no longer looks the way this code expects."""


class NoData(ExpectedProblem):
    """CBSL answered properly but has nothing for the dates asked for."""
