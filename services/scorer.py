from decimal import ROUND_HALF_UP, Decimal

from contracts import DiscoveryJSON, DimensionScore


class Scorer:
    """
    Fórmula: Σ(score × peso) / Σ(pesos)
    Ejemplo: Sofía = (5×3 + 5×3 + 5×3 + 4×3 + 5×2 + 5×2 + 5×2 + 5×1) / 19 = 92/19 = 4.84
    Nunca llama a la IA.
    """

    def calculate(self, scores: list[DimensionScore], discovery: DiscoveryJSON) -> tuple[Decimal, Decimal]:
        peso_map = {d.id: d.peso for d in discovery.dimensions}
        total = Decimal(str(discovery.total_weight))
        weighted_sum = sum(s.score * Decimal(str(peso_map[s.dimension_id])) for s in scores)
        weighted = (weighted_sum / total).quantize(Decimal("0.01"), ROUND_HALF_UP)
        normalized = (weighted / Decimal("5")).quantize(Decimal("0.0001"), ROUND_HALF_UP)
        return weighted, normalized
