"""Batch orchestrator for duration-curve computation and reporting."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Literal, TypeAlias

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure
from tqdm.auto import tqdm

from .duration_curve import (
    DurationCurveReporter,
    DurationCurveResult,
    Method,
)
from .hidro import SeriesType, Source
from .station import Station

ReportFormat: TypeAlias = Literal["html", "pdf", "images"]

# Sanitization to be applied to the final series, e.g.:
# {13990000: {"cota": {"2015-03-01": 1786}, ...}}
SanitizationList = dict[int, dict[SeriesType, dict[str, float]]]

class Reporter:
    """Batch orchestrator: computes, persists, loads, and exports duration curves
    for multiple stations.

    Delegates per-station computation to DurationCurveReporter and persistence
    to DurationCurveResult. Owns only batch coordination and report generation.
    """

    def __init__(self, sanitization: SanitizationList | None = None):
        self.results: dict[int, DurationCurveResult] = {}
        self.errors: dict[int, str] = {}
        self.sanitization=sanitization if sanitization else {}

    def results_summary(self) -> pd.DataFrame():
        if not self.results:
            raise ValueError("No results to summarize. Run calculate_duration_curves() first.")

        return pd.DataFrame.from_dict(
            {
                code: {
                    "Nome": result.station_name,
                    "Descrição": result.description.split(" - ")[0],
                    "Inicio": result.stats["Inicio"],
                    "Fim": result.stats["Fim"],
                    "Anos": result.stats["Anos"],
                    "Falhas (%)": result.stats["Falhas (%)"],
                    "Consist (%)": result.stats["Consist (%)"],
                    "Anos (Efet.)": result.stats["Anos (Efet.)"],
                    "Metodo": result.method,
                    "Fonte": result.source,
                }
                for code, result in self.results.items()
            },
            orient="index",
        )


    # ─── Batch Computation ─────────────────────────────────────────

    def calculate_duration_curves(
        self,
        stations: list[int] | tuple[int, ...],
        series_type: SeriesType = "cota",
        source: Source | None = None,
        method: Method = "from_discharge",
    ) -> None:
        """Compute duration curves for a batch of stations.

        Args:
            stations: Station codes to process.
            series_type: Target series type ("cota" or "vazao").
            source: Data source override. If None, each station selects its best.
            method: Calculation method ("direct" or "from_discharge").

        Returns:
            Dictionary mapping station code → DurationCurveResult.
        """
        for code in tqdm(stations, desc="Computing duration curves"):
            print(f"Processing station {code}")
            try:
                station = Station(code, self.sanitization.get(code))
                dcr = DurationCurveReporter(station)
                dcr.create_duration_curve(
                    series_type=series_type,
                    source=source,
                    method=method,
                )
                self.results[code] = dcr.results

            except Exception as e:
                print(f"Station {code} failed: {e}")
                self.errors[code] = str(e)


    # ─── Batch Persistence ─────────────────────────────────────────

    def save_all(self, base_path: str | Path) -> Path:
        """Save all results to subfolders named by station code.

        Structure:
            base_path/
            ├── 12345/
            │   ├── curve.parquet
            │   ├── stats.parquet
            │   └── meta.json
            └── 67890/
                └── ...
        """
        base_path = Path(base_path)

        if not self.results:
            raise ValueError("No results to save. Run calculate_duration_curves() first.")

        for code, result in self.results.items():
            result.save(base_path / str(code))

        # Persist error log if any
        if self.errors:
            errors_path = base_path / "_errors.json"
            import json
            errors_path.write_text(
                json.dumps(self.errors, ensure_ascii=False, indent=2)
            )

        return base_path

    @classmethod
    def load_all(cls, base_path: str | Path) -> "Reporter":
        """Reconstruct a Reporter from a folder of saved results.

        Scans all subfolders containing meta.json and loads each as a
        DurationCurveResult, keyed by EstacaoCodigo from the curve DataFrame.
        """
        base_path = Path(base_path)
        reporter = cls()

        for subfolder in sorted(base_path.iterdir()):
            if not subfolder.is_dir():
                continue
            if not (subfolder / "meta.json").exists():
                continue

            try:
                result = DurationCurveResult.load(subfolder)
                reporter.results[result.station_code] = result

            except Exception as e:
                print(f"Failed to load {subfolder.name}: {e}")
                reporter.errors[int(subfolder.name)] = str(e)

        return reporter

    # ─── Plotting ──────────────────────────────────────────────────

    def plot_station_chart(
        self,
        station: int,
        ax: plt.Axes | None = None,
    ) -> None:
        """Plot the duration-curve chart for a single station.

        Works entirely from DurationCurveResult — no Station instance needed.
        """
        if station not in self.results:
            raise ValueError(
                f"No results for station {station}. "
                f"Available: {list(self.results.keys())}"
            )

        result = self.results[station]
        curve = result.df.copy()

        # Remove Feb 29 to align annual curves
        curve["dia"] = curve.index.get_level_values("dia").to_list()
        curve["mes"] = curve.index.get_level_values("mes").to_list()
        curve = curve[~((curve["dia"] == 29) & (curve["mes"] == 2))]

        curve.index = pd.to_datetime(
            "2026-" + curve["mes"].astype(str) + "-" + curve["dia"].astype(str)
        )

        if ax is None:
            fig, ax = plt.subplots(figsize=(15, 5))
        else:
            fig = ax.get_figure()

        curve[["min", "max"]].plot(ax=ax, color=["red", "blue"])
        curve[["MLT"]].plot(ax=ax, color="lightblue", linestyle="--")
        ax.fill_between(
            curve.index, curve["q10"], curve["q90"],
            color="lightblue", alpha=0.2,
        )

        # Build title from DurationCurveResult metadata
        title = f"Estação {result.station_code} - {result.station_name}\n"
        if "/" in result.method:
            title += "Permanência de cotas obtidas a partir da vazão\n"
        else:
            title += f"Permanência de {result.series_type}\n"
        title += result.description

        ax.set_title(title)
        ax.set_xlabel("")
        ax.set_ylabel("Cota" if result.series_type == "cota" else "Vazão (m³/s)")

        fig.tight_layout()


    # ─── Report Export ─────────────────────────────────────────────

    def export_report(
        self,
        output_dir: str | Path,
        report_format: ReportFormat = "html",
        filename: str | None = None,
        image_format: Literal["png", "jpg", "svg"] = "png",
        dpi: int = 150,
        close_figures: bool = True,
    ) -> Path:
        """Export duration-curve charts to a report (HTML, PDF, or images).

        Args:
            output_dir: Directory where the report will be saved.
            report_format: Export format ("html", "pdf", or "images").
            filename: Optional output filename.
            image_format: Image format for raster charts.
            dpi: Image resolution.
            close_figures: Whether to close matplotlib figures after saving.

        Returns:
            Path to the generated report or image directory.
        """
        if not self.results:
            raise ValueError(
                "No results to export. Run calculate_duration_curves() or load_all() first."
            )

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if report_format == "html":
            return self._export_html_report(
                output_dir=output_dir,
                filename=filename or "duration_curve_report.html",
                image_format=image_format,
                dpi=dpi,
                close_figures=close_figures,
            )

        if report_format == "pdf":
            return self._export_pdf_report(
                output_dir=output_dir,
                filename=filename or "duration_curve_report.pdf",
                close_figures=close_figures,
            )

        if report_format == "images":
            self._export_chart_images(
                output_dir=output_dir,
                image_format=image_format,
                dpi=dpi,
                close_figures=close_figures,
            )
            return output_dir

        raise ValueError(
            f'Unsupported format: {report_format}. Expected "html", "pdf", or "images".'
        )

    # ─── Private Export Helpers ────────────────────────────────────
    def create_dataframe(self, station_codes: list[int]) -> pd.DataFrame:
        """Export duration-curve data to a CSV file."""
        df = pd.concat(
            [result.df for code, result in self.results.items() if code in station_codes]
        )
        return df.round()


    def _export_pdf_report(
        self,
        output_dir: Path,
        filename: str,
        close_figures: bool,
    ) -> Path:
        pdf_path = output_dir / filename

        with PdfPages(pdf_path) as pdf:
            for station in tqdm(self.results, desc="Exporting PDF"):
                fig = self.plot_station_chart(station)
                pdf.savefig(fig, bbox_inches="tight")
                if close_figures:
                    plt.close(fig)

        return pdf_path

    def _export_html_report(
        self,
        output_dir: Path,
        filename: str,
        image_format: str,
        dpi: int,
        close_figures: bool,
    ) -> Path:
        image_dir = output_dir / "images"
        image_paths = self._export_chart_images(
            output_dir=image_dir,
            image_format=image_format,
            dpi=dpi,
            close_figures=close_figures,
        )

        html_path = output_dir / filename
        html_content = self._build_html_content(image_paths)
        html_path.write_text(html_content, encoding="utf-8")
        return html_path

    def _export_chart_images(
        self,
        output_dir: Path,
        image_format: str,
        dpi: int,
        close_figures: bool,
    ) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        image_paths: list[Path] = []

        for station in tqdm(self.results, desc="Exporting charts"):
            fig = self.plot_station_chart(station)
            image_path = output_dir / f"{station}.{image_format}"
            fig.savefig(image_path, dpi=dpi, bbox_inches="tight")
            if close_figures:
                plt.close(fig)
            image_paths.append(image_path)

        return image_paths

    def _build_html_content(self, image_paths: list[Path]) -> str:
        html_parts = [
            "<html>",
            "<head>",
            '<meta charset="utf-8">',
            "<title>Curvas de Permanência</title>",
            """
            <style>
                body { font-family: Arial, sans-serif; margin: 32px; color: #222; }
                h1 { margin-bottom: 32px; }
                .chart { margin-bottom: 48px; page-break-inside: avoid; }
                .chart img { width: 95%; max-width: 1400px; border: 1px solid #ddd; }
            </style>
            """,
            "</head>",
            "<body>",
            "<h1>Relatório de Curvas de Permanência</h1>",
        ]

        for image_path in image_paths:
            station_code = image_path.stem
            mime = f"image/{image_path.suffix.lstrip('.')}"
            img_data = base64.b64encode(image_path.read_bytes()).decode("utf-8")

            html_parts.append(
                f'<div class="chart">'
                f"<h3>Estação {station_code}</h3>"
                f'<img src="data:{mime};base64,{img_data}">'
                f"</div>"
            )

        html_parts.extend(["</body>", "</html>"])
        return "\n".join(html_parts)

    # ─── Utilities ─────────────────────────────────────────────────

    @property
    def station_codes(self) -> list[int]:
        """List of station codes with computed results."""
        return list(self.results.keys())

    def __repr__(self) -> str:
        return (
            f"Reporter({len(self.results)} stations loaded, "
            f"{len(self.errors)} errors)"
        )