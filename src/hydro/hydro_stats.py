from functools import lru_cache, partial
from collections.abc import Sequence

import pandas as pd
import matplotlib.pyplot as plt
from tqdm.auto import tqdm

from .hidro import DataStatus, Hidro, SeriesType


class HydroStats:

    # Define a threshold for the discharge series lenght in comparison to the stage series
    DISCHARGE_STAGE_LENGHT_THRESHOLD = 0.8

    def __init__(self, hidro: Hidro):
        self.hidro = hidro

    @staticmethod
    def calc_exceedance_curve(df: pd.Series) -> pd.Series:
        exceedance_vals = {i: df.quantile(1-i/100) for i in range(1, 101)}
        s = pd.Series(exceedance_vals)
        s.index.name = "Permanência"
        return s
    

    @staticmethod
    def _calc_quantiles(df: pd.DataFrame, val_col: str) -> pd.DataFrame:
        funcs = [
            "max",
            ("q90", lambda x: x.quantile(0.9)), 
            ("q75", lambda x: x.quantile(0.75)), 
            ("mediana", lambda x: x.quantile(0.5)),
            ("MLT", lambda x: x.mean()),
            ("q25", lambda x: x.quantile(0.25)), 
            ("q10", lambda x: x.quantile(0.1)), 
            "min", 
        ]

        # Create or update month and day columns
        df["mes"] = df.index.month
        df["dia"] = df.index.day

        df = df.groupby(["mes", "dia"])[val_col].agg(funcs)
        df["max_mensal"] = df.groupby("mes")["max"].transform("max")
        df["min_mensal"] = df.groupby("mes")["min"].transform("min")

        return df
    


    @staticmethod
    def calc_series_stats(series: pd.DataFrame, val_col: str, status_col: str | None) -> dict:
        if series is None or len(series) == 0:
            return {
                "Inicio": "",
                "Fim": "",
                "Anos": 0,
                "Falhas (%)": 0,
                "Consist (%)": 0,
                "Anos (Efet.)": 0,
            }

        # Count the number of days with data in each month to calculate complete months
        total_days = (series.index.max() - series.index.min()).days + 1
        
        # Group by status
        if status_col is not None:
            data_status_count = series.groupby(status_col).size()
            verified = data_status_count.get(2, 0)
        else:
            verified = 0

        years = round(total_days / 365, 1)
        failures = round(100 * ((total_days - len(series)) / total_days), 1)
        return {
            "Inicio": series.index.min().strftime("%Y/%m"),
            "Fim": series.index.max().strftime("%Y/%m"),
            "Anos": years,
            "Falhas (%)": failures,
            "Consist (%)": round(100 * float(verified / len(series)), 1),
            "Anos (Efet.)": round(years * (1 - failures / 100), 1)
        }




    # def _stats_by_series_type(self, station: int, series_type: SeriesType) -> dict | None:
    #     """Get statistics for a given station and series type.

    #     Args:
    #         station (int): station number
    #         series_type (SeriesType): series type

    #     Returns:
    #         Dict: station statistics

    #     """
    #     q = self.hidro.get_series(station, series_type, data_status="combined")

    #     if q is None:
    #         return {
    #             "Inicio": "",
    #             "Fim": "",
    #             "Anos": 0,
    #             "Falhas(%)": 0,
    #             "Consistido (%)": 0,
    #         }

    #     # Count the number of days with data in each month to calculate complete months
    #     total_days = (q.index.max() - q.index.min()).days + 1
        
    #     # Group by status
    #     data_status_count = q.groupby("NivelConsistencia").size()
    #     verified = data_status_count.get(2, 0)

    #     return {
    #         "Inicio": q.index.min().strftime("%Y/%m"),
    #         "Fim": q.index.max().strftime("%Y/%m"),
    #         "Anos": round(total_days / 365, 1),
    #         "Falhas(%)": round(100 * ((total_days - len(q)) / total_days), 2),
    #         "Consistido (%)": round(100 * float(verified / len(q)), 1),
    #     }

    @lru_cache(maxsize=512)
    def _get_single_station_stats(self, station: int) -> pd.DataFrame:
        """Get statistics for a given station.

        Args:
            station (int): station number

        Returns:
            Dict: station statistics

        """
        # Get stats for state and discharge
        stage_stats = self._stats_by_series_type(station, "cota")
        discharge_stats = self._stats_by_series_type(station, "vazao")

        # Create a one-row dataframe with stats for both series
        df = pd.DataFrame({
            ("cota", key): [value]
            for key, value in stage_stats.items()
        } | {
            ("vazao", key): [value]
            for key, value in discharge_stats.items()
        }, index=[station])

        df.index.name = "EstacaoCodigo"

        discharge_years = df["vazao"]["Anos"] * (1 - df["vazao"]["Falhas(%)"] / 100)
        stage_years = df["cota"]["Anos"] * (1 - df["cota"]["Falhas(%)"] / 100)


        # Calculate the relation between discharge and stage
        df["Vazao/Cota (%)"] = 100 * (discharge_years / stage_years).round(2)
    
        return df

    def get_station_stats(
        self,
        stations: int | Sequence[int],
    ) -> pd.DataFrame:
        """Get statistics for one or more stations.

        Args:
            stations: A single station code or a sequence of station codes.

        Returns:
            A DataFrame indexed by station code.
        """

        if isinstance(stations, int):
            return self._get_single_station_stats(stations)

        # Loop through the stations to update the stats
        bar = tqdm(total=len(stations))
        dfs = []

        for station in stations:
            bar.desc = f"Station {station}"
            dfs.append(self._get_single_station_stats(station))
            bar.update(1)

        return pd.concat(dfs, axis=0)

 
    def calc_duration_curve(
        self, station: int, series_type: SeriesType, data_status: DataStatus
    ) -> pd.DataFrame:
        """Calculate the duration curve for a given station and series type.

        Args:
            station (int): station number
            series_type (SeriesType): series type "vazao" | "cota"

        Returns:
            pd.DataFrame: duration curve
        """
        series = self.hidro.get_series(station, series_type, data_status)

        stats = HydroStats._calc_quantiles(series, "val")

        return stats


    def _calc_stage_duration_curve(self, station: int, data_status: DataStatus) -> pd.DataFrame:
        """
        """
        # First, retrieve the series
        stage_series = self.hidro.get_series(station, "cota", data_status)
        if stage_series is None:
            return pd.DataFrame()

        discharge_series = self.hidro.get_series(station, "vazao", data_status)
    
        # Check if the discharge series is long enough (in comparison to stage)
        discharge_perc = len(discharge_series) / len(stage_series) if discharge_series is not None else 0

        # Switch the method to "cota" if discharge series is too short
        method = "cota" if discharge_perc < HydroStats.DISCHARGE_STAGE_LENGHT_THRESHOLD else "vazao"

        if method == "vazao":
            try:
                print(f"Applying DISCHARGE method for station {station} - {discharge_perc:.1f}%")
                discharge_stats = HydroStats._calc_quantiles(discharge_series, "val")

                # Define a partial function to convert discharge to stage
                q_to_h = partial(self.hidro.compute_stage_from_flow, station=station)

                # Convert every column from discharge to stage
                stages_as_list = [q_to_h(discharge_stats[c]) for c in discharge_stats.columns]
                stage_stats = pd.concat(stages_as_list, axis=1)

                status = "OK"

            except Exception as e:
                status = "Problema na curva chave"
                method = "cota"

        if method == "cota":
            print(f"Applying STAGE method for station {station}")
            stage_stats = HydroStats._calc_quantiles(stage_series, "val")

        stage_stats[["EstacaoCodigo", "metodo", "tipo_grafico"]] = [station, method, ""]
        return stage_stats.reset_index(drop=False)

    def calc_stage_duration_curve(self, stations: Sequence[int], data_status: DataStatus) -> pd.DataFrame:
        bar = tqdm(total=len(stations))
        dfs = []
        for station in stations:
            bar.desc = f"Station {station}"
            dfs.append(self._calc_stage_duration_curve(station, data_status))
            bar.update(1)

        return pd.concat(dfs, axis=0)
    
    @staticmethod
    def plot_duration_curve(station: int, stats: pd.DataFrame):
        stats = stats[stats["EstacaoCodigo"] == station]

        # Remove 29 feb
        stats["dia"] = stats.index.get_level_values("dia").to_list()
        stats["mes"] = stats.index.get_level_values("mes").to_list()
        stats = stats[~((stats["dia"] == 29) & (stats["mes"] == 2))]

        stats.index = pd.to_datetime("2026-" + stats["mes"].astype(str) + "-" + stats["dia"].astype(str))

        fig, ax = plt.subplots(figsize=(10, 5))
        stats[["min", "max"]].plot(ax=ax, color=["red", "blue"])

        stats[["MLT"]].plot(ax=ax, color="lightblue", linestyle="--")
        # Draw a filled area between stats[q10] and stats[q90]
        ax.fill_between(stats.index, stats["q10"], stats["q90"], color="lightblue", alpha=0.2)
        

        # title = f"Estação {station} / Método de cálculo: {stats['metodo'].iloc[0]}\n"
        
        # ax.set_title(title)

        fig.tight_layout()
        return fig
    
