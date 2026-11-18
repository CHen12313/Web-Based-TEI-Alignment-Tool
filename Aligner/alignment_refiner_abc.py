from abc import ABC, abstractmethod
from data_classes import AlignedPair
from typing import List

class AlignmentRefiner(ABC):
    @abstractmethod
    def refine(self, aligned_pairs: List[AlignedPair]) -> List[AlignedPair]:
        """Take a list of aligned pairs and return a refined list."""
        ...

