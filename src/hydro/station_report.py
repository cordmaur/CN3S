"""Readable Word reports accompanying station exceedance results."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
from docx import Document
from docx.enum.section import WD_ORIENT
from docx.shared import Cm, Pt

if TYPE_CHECKING:
    from .exceedance import ExceedanceResult
    from .station import Station


def conversion_reason(status: str) -> str:
    """
    Explain discharge-to-stage availability in Portuguese.

    Args:
        status: Original conversion diagnostic retained in metadata.json.

    Returns:
        Explanation for technicians, retaining unexpected diagnostics verbatim.

    """
    if status == "Ok":
        return "Há referências de cota obtidas pela conversão das vazões com a curva-chave."
    if status == "No discharge observations":
        return "Não há observações de vazão utilizáveis para calcular cotas pela curva-chave."
    if "No rating curves for station" in status:
        return "Não há curva-chave cadastrada para converter as vazões em cotas."
    return f"A conversão de vazão em cota não foi possível. Diagnóstico original: {status}"


def save_station_report(
    station: Station,
    path: str | Path,
    *,
    result: ExceedanceResult | None = None,
    chart_path: str | Path | None = None,
    error: str | None = None,
) -> Path:
    """
    Write station identity, source coverage, method rationale, and an annual chart.

    Args:
        station: Station with inventory and, when loading succeeded, source statistics.
        path: Destination report.docx file.
        result: Calculated references, or None when calculation failed.
        chart_path: Annual chart PNG generated from the same result, when available.
        error: Loading, calculation, or plotting failure to disclose in the report.

    Returns:
        Path to the Word document, including reports without usable observations.

    """
    document = Document()
    section = document.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = Cm(29.7), Cm(21)
    section.top_margin = section.bottom_margin = Cm(1.4)
    section.left_margin = section.right_margin = Cm(1.5)
    document.styles["Normal"].font.name = "Calibri"
    document.styles["Normal"].font.size = Pt(10)
    document.add_heading(f"Estação {station.code} — {station.name}", 0)
    document.add_paragraph(
        "Análise de permanência • Gerado em "
        + pd.Timestamp.now(tz="America/Sao_Paulo").strftime("%d/%m/%Y %H:%M %Z")
    )
    # Inventory fields are included only when present; do not infer basin descriptors.
    inventory = station.info.iloc[0]
    details = [
        f"{label}: {inventory[name]}"
        for name, label in (
            ("Latitude", "Latitude (graus)"),
            ("Longitude", "Longitude (graus)"),
            ("Altitude", "Altitude (m)"),
            ("AreaDrenagem", "Área de drenagem (km²)"),
            ("RioNome", "Rio"),
            ("MunicipioNome", "Município"),
        )
        if name in inventory and pd.notna(inventory[name])
    ]
    if details:
        document.add_paragraph(" | ".join(details))

    document.add_heading("Método e diagnóstico", 1)
    if result is None:
        document.add_paragraph("Não foi possível calcular referências de permanência.")
    else:
        method = (
            "Cotas derivadas das vazões (from_discharge)."
            if result.plot_method == "from_discharge"
            else "Estatísticas calculadas diretamente das cotas observadas (direct)."
        )
        document.add_paragraph(f"Método utilizado: {method}")
        document.add_paragraph(conversion_reason(result.status["C_from_Q"]))
        document.add_paragraph(
            f"Referências calculadas em {result.calculated_at}. "
            f"Período solicitado: {result.period['start'] or 'início disponível'} até "
            f"{result.period['end'] or 'fim disponível'}. Fonte: {result.source}. "
            "No agrupamento diário, Hidro tem preferência quando as fontes coincidem."
        )
    if error:
        document.add_paragraph(f"Limitação registrada: {error}")

    document.add_heading("Disponibilidade por fonte", 1)
    document.add_paragraph(
        "Estatísticas dos registros carregados, antes da união das fontes. "
        "Falhas são dias ausentes dentro do intervalo observado; anos efetivos representam "
        "a cobertura útil. Ausência de dados não significa ausência de estação cadastrada."
    )
    if station.stats is None:
        document.add_paragraph("Não foi possível obter estatísticas das fontes.")
    else:
        for variable, label in (("cota", "Cotas (cm)"), ("vazao", "Vazões (m³/s)")):
            document.add_heading(label, 2)
            table = document.add_table(rows=1, cols=8)
            table.style = "Light Shading Accent 1"
            headers = (
                "Código",
                "Fonte",
                "Início",
                "Fim",
                "Anos",
                "Falhas (%)",
                "Consist. (%)",
                "Anos efetivos",
            )
            for cell, text in zip(table.rows[0].cells, headers, strict=True):
                cell.text = text
            for code, row in station.stats.iterrows():
                metrics = row[variable]
                values = [str(code), str(row[("Fonte", "")])]
                values.extend(
                    str(metrics[name]) or "Sem dados"
                    for name in (
                        "Inicio",
                        "Fim",
                        "Anos",
                        "Falhas (%)",
                        "Consist (%)",
                        "Anos (Efet.)",
                    )
                )
                for cell, text in zip(table.add_row().cells, values, strict=True):
                    cell.text = text
        document.add_paragraph(
            "Consistência: percentual de registros Hidro de nível 2; o valor zero da "
            "Telemetria não representa avaliação de qualidade. Campos numéricos zerados "
            "com início/fim sem dados indicam ausência de observações."
        )

    document.add_page_break()
    document.add_heading("Gráfico anual de cotas", 1)
    if chart_path is not None:
        document.add_picture(str(chart_path), width=Cm(26.5))
        document.add_paragraph(
            "Cotas em centímetros. As curvas históricas usam os registros disponíveis "
            "para cada dia do calendário, sem preencher lacunas. O dia 29/02 não integra "
            "a climatologia diária. C95 é a cota com 95% de permanência; não corresponde "
            "a um limite oficial de alerta ou inundação. As séries anuais sobrepostas "
            "combinam Hidro e Telemetria, com preferência por Hidro nos dias coincidentes; "
            "a ausência de sobreposição pode indicar falta de dados recentes."
        )
    else:
        document.add_paragraph(
            "Gráfico indisponível. Consulte o diagnóstico e a disponibilidade acima."
        )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(path))
    return path
