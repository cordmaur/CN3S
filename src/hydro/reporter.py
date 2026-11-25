"""Batch calculation, persistence, and export of hydrological references."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from tqdm.auto import tqdm

from .exceedance import ExceedanceAnalysis, ExceedanceResult
from .hidro import SeriesType, Source

if TYPE_CHECKING:
    from matplotlib.figure import Figure

    from .station import Station

# Sanitization to be applied to the final series, e.g.:
# {13990000: {"cota": {"2015-03-01": 1786}, ...}}
SanitizationList = dict[int, dict[SeriesType, dict[str, float]]]


class Reporter:
    """
    Compute, persist, load, and export references for multiple stations.

    Delegates per-station computation to ExceedanceAnalysis and persistence
    to ExceedanceResult. Owns only batch coordination and report generation.
    """

    def __init__(self, sanitization: SanitizationList | None = None) -> None:
        """
        Initialize batch storage and optional per-station corrections.

        Args:
            sanitization: Observation replacements by station, measurement, and date.

        """
        self.results: dict[int, ExceedanceResult] = {}
        self.errors: dict[int, str] = {}
        self.sanitization = sanitization if sanitization else {}

    def results_summary(self) -> pd.DataFrame:
        """
        Combine whole-record statistics for all stations and variables.

        Returns:
            One row per station with Q/C statistics in flat columns.

        """
        if not self.results:
            msg = "No results to summarize. Run calculate_exceedances() first."
            raise ValueError(msg)
        return pd.concat([result.summary for result in self.results.values()])

    # ─── Batch Computation ─────────────────────────────────────────

    def calculate_exceedances(
        self, stations: list[Station], source: Source = "hidro/telemetria"
    ) -> None:
        """
        Calculate all three variables using caller-owned stations/connectors.

        Args:
            stations: Stations containing the intended historical records.
            source: Historical-first merge policy or an explicit single source.

        """
        for station in tqdm(stations, desc="Computing exceedances"):
            try:
                if station.code in self.sanitization:
                    station.sanitization = self.sanitization[station.code]
                analysis = ExceedanceAnalysis(station)
                self.results[station.code] = analysis.calculate(source=source)
                self.errors.pop(station.code, None)
            except Exception as exc:  # noqa: PERF203 — isolate failures by station in a research batch.
                self.errors[station.code] = str(exc)

    # ─── Batch Persistence ─────────────────────────────────────────

    def save_all(self, base_path: str | Path) -> Path:
        """
        Save each station's complete result in its own subdirectory.

        Args:
            base_path: Root directory for scientific tables and metadata.json.

        Returns:
            Root directory containing the saved stations and any batch errors.

        """
        base_path = Path(base_path)

        if not self.results:
            msg = "No results to save. Run calculate_exceedances() first."
            raise ValueError(msg)

        for code, result in self.results.items():
            result.save(base_path / str(code))

        # Persist error log if any
        if self.errors:
            errors_path = base_path / "_errors.json"

            errors_path.write_text(json.dumps(self.errors, ensure_ascii=False, indent=2))

        return base_path

    @classmethod
    def load_all(cls, base_path: str | Path) -> Reporter:
        """
        Reconstruct a Reporter from a folder of saved results.

        Scans all subfolders containing metadata.json and loads each as a
        ExceedanceResult, keyed by the station code in metadata.

        Args:
            base_path: Root directory containing station subdirectories.

        Returns:
            Batch with loaded results and any per-station loading errors.

        """
        base_path = Path(base_path)
        reporter = cls()

        for subfolder in sorted(base_path.iterdir()):
            if not subfolder.is_dir():
                continue
            if not (subfolder / "metadata.json").exists():
                continue

            try:
                result = ExceedanceResult.load(subfolder)
                reporter.results[result.station_code] = result

            except Exception as e:
                print(f"Failed to load {subfolder.name}: {e}")
                reporter.errors[int(subfolder.name)] = str(e)

        return reporter

    # ─── Plotting ──────────────────────────────────────────────────

    def plot_station_chart(self, station: int, ax: plt.Axes | None = None) -> Figure:
        """
        Plot saved stage climatology without requiring a database.

        Args:
            station: Saved station code.
            ax: Optional existing axes.

        Returns:
            Figure suitable for image, PDF, or HTML export.

        """
        if ax is None:
            fig, ax = plt.subplots(figsize=(15, 5))
        else:
            fig = ax.get_figure()
        result = self.results[station]
        result.plot_daily_climatology(ax)
        for label, value in result.stage_references().items():
            ax.axhline(value, linestyle="--", label=label)
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=4)
        fig.tight_layout()
        return fig

    # ─── Report Export ─────────────────────────────────────────────

    def export_report(
        self,
        output_dir: str | Path,
        report_format: str = "html",
        filename: str | None = None,
        image_format: Literal["png", "jpg", "svg"] = "png",
        dpi: int = 150,
        *,
        close_figures: bool = True,
    ) -> Path:
        """
        Export duration-curve charts to a report (HTML, PDF, or images).

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
            msg = "No results to export. Run calculate_exceedances() or load_all() first."
            raise ValueError(msg)

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if report_format == "html":
            return self._export_html_report(
                output_dir=output_dir,
                filename=filename or "exceedance_report.html",
                image_format=image_format,
                dpi=dpi,
                close_figures=close_figures,
            )

        if report_format == "pdf":
            return self._export_pdf_report(
                output_dir=output_dir,
                filename=filename or "exceedance_report.pdf",
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

        msg = f'Unsupported format: {report_format}. Expected "html", "pdf", or "images".'
        raise ValueError(msg)

    # ─── Private Export Helpers ────────────────────────────────────
    def create_dataframe(self, station_codes: list[int]) -> pd.DataFrame:
        """
        Combine selected stations' daily climatology with station identity.

        Args:
            station_codes: Stations to include.

        Returns:
            Rounded statistics indexed by station, month, and day.

        """
        df = pd.concat(
            {
                code: result.daily_curve
                for code, result in self.results.items()
                if code in station_codes
            },
            names=["station_code"],
        )
        return df.round()

    def _export_pdf_report(
        self,
        output_dir: Path,
        filename: str,
        *,
        close_figures: bool,
    ) -> Path:
        """
        Export saved reference charts as a multipage PDF.

        Args:
            output_dir: Destination directory.
            filename: PDF filename.
            close_figures: Release figures after writing.

        Returns:
            Written PDF path.

        """
        pdf_path = output_dir / filename

        with PdfPages(str(pdf_path)) as pdf:
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
        *,
        close_figures: bool,
    ) -> Path:
        """
        Export saved reference charts in a standalone HTML report.

        Args:
            output_dir: Destination directory.
            filename: HTML filename.
            image_format: Chart image format.
            dpi: Raster resolution.
            close_figures: Release figures after writing.

        Returns:
            Written HTML path.

        """
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
        *,
        close_figures: bool,
    ) -> list[Path]:
        """
        Render each station to an image file.

        Args:
            output_dir: Image destination directory.
            image_format: Image format extension.
            dpi: Raster resolution.
            close_figures: Release figures after writing.

        Returns:
            Paths of exported images.

        """
        output_dir.mkdir(parents=True, exist_ok=True)
        image_paths: list[Path] = []

        for station in tqdm(self.results, desc="Exporting charts"):
            fig = self.plot_station_chart(station)
            image_path = output_dir / f"{station}.{image_format}"
            fig.savefig(str(image_path), dpi=dpi, bbox_inches="tight")
            if close_figures:
                plt.close(fig)
            image_paths.append(image_path)

        return image_paths

    def _build_html_content(self, image_paths: list[Path]) -> str:
        """
        Embed chart images in a portable HTML document.

        Args:
            image_paths: Previously rendered chart files.

        Returns:
            HTML containing base64-encoded chart images.

        """
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
        """Return the number of loaded stations and recorded failures."""
        return f"Reporter({len(self.results)} stations loaded, {len(self.errors)} errors)"
