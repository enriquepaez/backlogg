# Re-export shared models for convenience within the people domain.
from backlogg.shared.models import Credit, Person

__all__ = ["Person", "Credit"]
