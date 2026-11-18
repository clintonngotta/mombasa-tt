"""What other parts of the system may want to know about a competition, sent inside the transaction
that made it true. Receivers that raise undo the result with everything else."""

from django.dispatch import Signal

# A match of a draw (a tie, for team events) has an official result. Argument: match.
match_decided = Signal()
# One rubber of a tie has an official result. Argument: rubber.
rubber_decided = Signal()
