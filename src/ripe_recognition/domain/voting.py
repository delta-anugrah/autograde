from dataclasses import dataclass, field


@dataclass
class VoteTracker:
    label: str | None = None
    votes: int = 0
    score: float = 0.0
    processed: bool = False

    def register(self, label: str, score: float) -> int:
        if self.label == label:
            self.votes += 1
        else:
            self.label = label
            self.votes = 1
        self.score = score
        return self.votes
