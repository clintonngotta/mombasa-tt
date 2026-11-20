"""What other parts of the system may want to know about a competition, sent inside the transaction
that made it true. Receivers that raise undo the result with everything else."""

from django.dispatch import Signal

# A match of a draw (a tie, for team events) has an official result. Argument: match.
match_decided = Signal()
# One rubber of a tie has an official result. Arguments: rubber, and tie_decided when it settles the tie
# (match_decided follows).
rubber_decided = Signal()
# The official result of a decided match (or of one of its rubbers) was replaced. Arguments: match, result.
result_corrected = Signal()
# An event was completed or cancelled, on its own or with its tournament. Arguments: event, actor.
event_closed = Signal()
