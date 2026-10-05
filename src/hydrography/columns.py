"""Column names used by the hydrography data files."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HydrographyColumns:
    """Map hydrography fields to their names in the source data."""

    otto_code: str = "cobacia"
    river_code: str = "cocursodag"
    upstream_area: str = "nuareamont"
    stretch_code: str = "cotrecho"
    geometry: str = "geometry"
    source_node: str = "noorigem"
    target_node: str = "nodestino"
    downstream_code: str = "cocdadesag"
    reach_length: str = "nucomptrec"

    @property
    def reach_code(self) -> str:
        """Return the source column for the reach identifier."""
        return self.stretch_code


HGM_COLUMNS = (
    "cobacia",
    "cocursodag",
    "hig_upa_area_km2",
    "hig_upa_tc_armycorps",
    "hig_upn_length_km",
    "hig_upa_reliefratio",
    "hig_upa_reachgradient",
)

HGM_LABELS = {
    "cobacia": "Ottobacia",
    "cocursodag": "Código do Rio",
    "hig_upa_area_km2": "Área a Montante (km²)",
    "hig_upa_tc_armycorps": "Tempo de Concentração",
    "hig_upn_length_km": "Comprimento a Montante (km)",
    "hig_upa_reliefratio": "Relação de relevo (m/m)",
    "hig_upa_reachgradient": "Gradiente do canal principal (m/km)",
}
