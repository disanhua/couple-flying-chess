"""Geometry processing tool for simplifying SQL Server geometry LINESTRING data.

This script reads geometry data from a SQL Server database using the configuration
from ``config/config.yml`` and simplifies LINESTRING geometries that contain
more than five points by removing redundant colinear points while keeping the
start and end points intact. Updates are written back to the database with the
configured SRID preserved.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

import pyodbc
import yaml

Point = Tuple[float, float]


@dataclass
class DatabaseConfig:
    server: str
    username: str
    password: str
    database: str
    driver: str = "ODBC Driver 17 for SQL Server"


@dataclass
class TableConfig:
    name: str
    primary_key: str
    geometry_field: str


@dataclass
class GeometryConfig:
    srid: int
    target_point_count: int = 5
    collinearity_tolerance: float = 1e-6


class GeometryProcessor:
    def __init__(self, base_path: Path) -> None:
        self.base_path = base_path
        self.config = self._load_config()
        self.logger = self._setup_logger()

    def _load_config(self) -> Tuple[DatabaseConfig, TableConfig, GeometryConfig]:
        config_path = self.base_path.parent / "config" / "config.yml"
        if not config_path.exists():
            raise FileNotFoundError(f"配置文件未找到: {config_path}")

        with config_path.open(encoding="utf-8") as f:
            raw_config = yaml.safe_load(f) or {}

        db_config = raw_config.get("database", {})
        table_config = raw_config.get("table", {})
        geom_config = raw_config.get("geometry", {})

        required_db_keys = {"server", "username", "password", "database"}
        missing_db = required_db_keys - db_config.keys()
        if missing_db:
            raise KeyError(f"数据库配置缺少以下字段: {', '.join(sorted(missing_db))}")

        required_table_keys = {"name", "primary_key", "geometry_field"}
        missing_table = required_table_keys - table_config.keys()
        if missing_table:
            raise KeyError(f"数据表配置缺少以下字段: {', '.join(sorted(missing_table))}")

        if "srid" not in geom_config:
            raise KeyError("几何配置缺少 srid 字段")

        database = DatabaseConfig(
            server=db_config["server"],
            username=db_config["username"],
            password=db_config["password"],
            database=db_config["database"],
            driver=db_config.get("driver", "ODBC Driver 17 for SQL Server"),
        )

        table = TableConfig(
            name=table_config["name"],
            primary_key=table_config["primary_key"],
            geometry_field=table_config["geometry_field"],
        )

        geometry = GeometryConfig(
            srid=int(geom_config["srid"]),
            target_point_count=int(geom_config.get("target_point_count", 5)),
            collinearity_tolerance=float(
                geom_config.get("collinearity_tolerance", 1e-6)
            ),
        )

        if geometry.target_point_count < 3:
            raise ValueError("目标点数不能少于 3")

        return database, table, geometry

    def _setup_logger(self) -> logging.Logger:
        log_dir = self.base_path / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = log_dir / f"geometry_process_{timestamp}.log"

        logger = logging.getLogger("GeometryProcessor")
        logger.setLevel(logging.INFO)

        # 清理旧的 handler，避免重复日志
        logger.handlers.clear()

        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s %(message)s")

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        logger.info("日志文件: %s", log_file)
        return logger

    def run(self) -> None:
        db_config, table_config, geometry_config = self.config

        connection_string = (
            f"DRIVER={{{db_config.driver}}};"
            f"SERVER={db_config.server};"
            f"DATABASE={db_config.database};"
            f"UID={db_config.username};"
            f"PWD={db_config.password};"
            "TrustServerCertificate=yes;"
        )

        self.logger.info("正在连接到 SQL Server: %s", db_config.server)
        with pyodbc.connect(connection_string) as connection:
            select_cursor = connection.cursor()
            update_cursor = connection.cursor()

            total_rows = self._get_total_count(select_cursor, table_config)
            if total_rows == 0:
                self.logger.info("未找到任何需要处理的数据")
                return

            self.logger.info("共需处理 %d 条数据", total_rows)

            select_sql = (
                f"SELECT {table_config.primary_key} AS gid, "
                f"{table_config.geometry_field}.STAsText() AS wkt "
                f"FROM {table_config.name}"
            )
            select_cursor.execute(select_sql)

            for index, row in enumerate(select_cursor.fetchall(), start=1):
                gid = row.gid
                wkt = row.wkt

                try:
                    self._process_single_row(
                        gid=gid,
                        wkt=wkt,
                        update_cursor=update_cursor,
                        table_config=table_config,
                        geometry_config=geometry_config,
                        current=index,
                        total=total_rows,
                    )
                except Exception as exc:  # pylint: disable=broad-except
                    self.logger.exception("处理 GID=%s 时发生异常: %s", gid, exc)

            connection.commit()

    def _get_total_count(self, cursor: pyodbc.Cursor, table_config: TableConfig) -> int:
        cursor.execute(f"SELECT COUNT(*) FROM {table_config.name}")
        result = cursor.fetchone()
        return int(result[0]) if result else 0

    def _process_single_row(
        self,
        *,
        gid: int,
        wkt: str,
        update_cursor: pyodbc.Cursor,
        table_config: TableConfig,
        geometry_config: GeometryConfig,
        current: int,
        total: int,
    ) -> None:
        points = self._parse_linestring(wkt)
        original_count = len(points)

        self.logger.info("开始处理GID=%s的数据", gid)
        self.logger.info("GID=%s的数据有%d个点", gid, original_count)

        if original_count == geometry_config.target_point_count:
            self.logger.info("  --------------------已跳过--------------------")
            self._log_progress(current, total)
            return

        if original_count < geometry_config.target_point_count:
            self.logger.warning(
                "GID=%s 的点数少于目标点数 %d，跳过更新",
                gid,
                geometry_config.target_point_count,
            )
            self._log_progress(current, total)
            return

        simplified, removed = self._simplify_points(points, geometry_config)

        if simplified is None:
            self.logger.warning("GID=%s 无法简化到 %d 个点，跳过更新", gid, geometry_config.target_point_count)
            self._log_progress(current, total)
            return

        self.logger.info(
            "- 开始处理GID=%s: 原始点数=%d，已处理%d个在直线中间的点，需要更新的点数%d个",
            gid,
            original_count,
            removed,
            len(simplified),
        )

        updated_wkt = self._format_linestring(simplified)
        update_sql = (
            f"UPDATE {table_config.name} "
            f"SET {table_config.geometry_field} = geometry::STGeomFromText(?, ?) "
            f"WHERE {table_config.primary_key} = ?"
        )
        update_cursor.execute(update_sql, (updated_wkt, geometry_config.srid, gid))

        self.logger.info("- 更新GID=%s的坐标，更新后坐标数 %d 个", gid, len(simplified))
        self.logger.info("  --------------------已完成GID=%s的更新--------------------", gid)
        self._log_progress(current, total)

    def _parse_linestring(self, wkt: str) -> List[Point]:
        if not wkt:
            raise ValueError("WKT 数据为空")

        header = "LINESTRING"
        if not wkt.upper().startswith(header):
            raise ValueError(f"不支持的几何类型: {wkt}")

        if "EMPTY" in wkt.upper():
            raise ValueError("LINESTRING 为空")

        start = wkt.find("(")
        end = wkt.rfind(")")
        if start == -1 or end == -1 or start >= end:
            raise ValueError(f"WKT 格式不正确: {wkt}")

        coordinate_text = wkt[start + 1 : end]
        point_strings = [part.strip() for part in coordinate_text.split(",") if part.strip()]

        points: List[Point] = []
        for point_text in point_strings:
            parts = point_text.split()
            if len(parts) < 2:
                raise ValueError(f"坐标点格式错误: {point_text}")
            x_str, y_str = parts[:2]
            points.append((float(x_str), float(y_str)))
        return points

    def _simplify_points(
        self, points: Sequence[Point], geometry_config: GeometryConfig
    ) -> Tuple[List[Point] | None, int]:
        if len(points) <= geometry_config.target_point_count:
            closed_points = self._ensure_closed_ring(list(points))
            return closed_points, 0

        working_points = self._ensure_closed_ring(self._remove_consecutive_duplicates(points))
        removed_total = 0

        max_iterations = len(working_points) * 2
        iteration = 0

        while len(working_points) > geometry_config.target_point_count and iteration < max_iterations:
            iteration += 1
            removed_in_iteration = False

            for idx in range(1, len(working_points) - 1):
                prev_point = working_points[idx - 1]
                current_point = working_points[idx]
                next_point = working_points[idx + 1]

                if self._is_colinear(prev_point, current_point, next_point, geometry_config.collinearity_tolerance):
                    del working_points[idx]
                    removed_total += 1
                    removed_in_iteration = True
                    break

            if not removed_in_iteration:
                break

        working_points = self._ensure_closed_ring(working_points)

        if len(working_points) == geometry_config.target_point_count:
            return working_points, removed_total

        return None, removed_total

    def _ensure_closed_ring(self, points: Sequence[Point]) -> List[Point]:
        if not points:
            return []

        closed = list(points)
        if not self._points_are_same(closed[0], closed[-1]):
            closed.append(closed[0])
        return closed

    def _remove_consecutive_duplicates(self, points: Sequence[Point]) -> List[Point]:
        if not points:
            return []

        deduped: List[Point] = [points[0]]
        for point in points[1:]:
            if not self._points_are_same(deduped[-1], point):
                deduped.append(point)
        return deduped

    def _is_colinear(
        self,
        point_a: Point,
        point_b: Point,
        point_c: Point,
        tolerance: float,
    ) -> bool:
        if self._points_are_same(point_a, point_c):
            return True

        line_length = self._distance(point_a, point_c)
        if line_length == 0:
            return True

        area = abs(
            (point_b[0] - point_a[0]) * (point_c[1] - point_a[1])
            - (point_b[1] - point_a[1]) * (point_c[0] - point_a[0])
        )
        distance = area / line_length
        return distance <= tolerance

    def _points_are_same(self, point_a: Point, point_b: Point, tol: float = 1e-12) -> bool:
        return math.isclose(point_a[0], point_b[0], abs_tol=tol) and math.isclose(
            point_a[1], point_b[1], abs_tol=tol
        )

    def _distance(self, point_a: Point, point_b: Point) -> float:
        return math.hypot(point_b[0] - point_a[0], point_b[1] - point_a[1])

    def _format_linestring(self, points: Iterable[Point]) -> str:
        coordinate_parts = [f"{x:.15f} {y:.15f}" for x, y in points]
        return f"LINESTRING ({', '.join(coordinate_parts)})"

    def _log_progress(self, current: int, total: int) -> None:
        percentage = (current / total * 100) if total else 100.0
        self.logger.info("- 处理进度: %d/%d (%.1f%%)", current, total, percentage)


def main() -> None:
    script_path = Path(__file__).resolve()
    processor = GeometryProcessor(script_path.parent)
    processor.run()


if __name__ == "__main__":
    main()
