"""CN3S rainfall-runoff model (Curve Number with Three-Step Antecedent Precipitation).

Deterministic monthly rainfall-runoff model developed by Taborga & Freitas (1987),
widely applied to Brazilian river basins. Combines the SCS Curve Number method with
a three-step antecedent precipitation index to adjust runoff potential dynamically.

References:
    Taborga, J. & Freitas, M. A. S. (1987). Simulacao da Lamina de Escoamento Mensal.
    III Simposio Luso-Brasileiro de Hidraulica e Recursos Hidricos, v. 2, p. 558-570.
"""

from cn3s.core import CN3S, CN3SParams

__all__ = ["CN3S", "CN3SParams"]
