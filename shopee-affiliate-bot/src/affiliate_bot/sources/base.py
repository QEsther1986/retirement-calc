"""商品來源的共同介面。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..config import Config
from ..models import Product


class ProductSource(ABC):
    """所有商品來源都要實作 fetch()。"""

    name = "base"

    def __init__(self, config: Config):
        self.config = config

    @abstractmethod
    def fetch(self, limit: int) -> list[Product]:
        """取回候選商品清單（還沒篩選、還沒評分）。"""

    def describe(self) -> str:
        return self.name
