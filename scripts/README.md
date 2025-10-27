# Python几何数据处理工具

这是一个用于处理SQL Server数据库中geometry字段坐标数据的Python工具。该工具可以简化LINESTRING几何数据，通过删除共线的中间点来减少冗余坐标。

## 功能特性

- 🔄 自动处理SQL Server数据库中的geometry字段数据
- 📐 识别并删除LINESTRING中共线的冗余点
- 🎯 将大于5个点的几何图形简化为5个点（闭合四边形）
- 🔒 保留SRID值，避免坐标系丢失
- 📊 详细的日志记录，包含处理进度和统计信息
- ⚙️ 灵活的YAML配置文件
- 🛡️ 错误处理和异常日志

## 安装依赖

### 前置要求

1. Python 3.7+
2. ODBC Driver for SQL Server

在Linux系统上安装ODBC驱动：
```bash
# Ubuntu/Debian
curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add -
curl https://packages.microsoft.com/config/ubuntu/$(lsb_release -rs)/prod.list > /etc/apt/sources.list.d/mssql-release.list
apt-get update
ACCEPT_EULA=Y apt-get install -y msodbcsql17

# CentOS/RHEL
curl https://packages.microsoft.com/config/rhel/8/prod.repo > /etc/yum.repos.d/mssql-release.repo
yum remove unixODBC-utf16 unixODBC-utf16-devel
ACCEPT_EULA=Y yum install -y msodbcsql17
```

### 安装Python依赖

```bash
cd scripts
pip install -r requirements.txt
```

## 配置

在 `config/config.yml` 文件中配置数据库连接信息和几何处理参数：

```yaml
# SQL Server Database Configuration
database:
  server: sqlservers
  username: sa
  password: "123456"
  database: chengtai

# Table Configuration
table:
  name: chengtai
  primary_key: gid
  geometry_field: geom

# Geometry Configuration
geometry:
  srid: 4326  # 坐标系SRID，根据实际情况修改
  target_point_count: 5  # 目标点数（闭合四边形）
  collinearity_tolerance: 0.000001  # 共线性判断容差
```

### 配置说明

- **database.server**: SQL Server服务器地址
- **database.username**: 数据库用户名
- **database.password**: 数据库密码
- **database.database**: 数据库名称
- **table.name**: 包含geometry字段的表名
- **table.primary_key**: 主键字段名
- **table.geometry_field**: geometry字段名
- **geometry.srid**: 空间参考标识符（SRID），必须与数据库中的SRID一致
- **geometry.target_point_count**: 目标点数，默认为5（闭合四边形）
- **geometry.collinearity_tolerance**: 共线性判断的容差值，用于判断点是否在一条直线上

## 使用方法

```bash
cd scripts
python geometry_processor.py
```

## 处理逻辑

1. **读取数据**: 从SQL Server数据库读取所有geometry字段数据
2. **解析几何**: 解析LINESTRING格式的坐标数据
3. **判断处理**:
   - 如果点数 = 5: 跳过，不更新
   - 如果点数 < 5: 记录警告，跳过
   - 如果点数 > 5: 进行简化处理
4. **简化算法**:
   - 识别共线的点（使用向量叉积方法计算点到直线的距离）
   - 删除直线中间的冗余点
   - 保留端点，确保形成闭合环
   - 简化到5个点（4个顶点 + 起点重合）
5. **更新数据库**: 使用配置的SRID更新简化后的geometry数据

## 日志输出

日志文件保存在 `scripts/logs/` 目录下，文件名格式为：`geometry_process_YYYYMMDD_HHMMSS.log`

日志内容包括：
- 每条记录的处理开始
- 原始点数和处理后点数
- 删除的中间点数量
- 是否跳过或更新
- 处理进度（当前/总数，百分比）
- 异常错误信息

示例日志：
```
2025-01-27 10:34:42,659 - GeometryProcessor - INFO 开始处理GID=456的数据
2025-01-27 10:34:42,659 - GeometryProcessor - INFO GID=456的数据有5个点
2025-01-27 10:34:42,659 - GeometryProcessor - INFO   --------------------已跳过--------------------
2025-01-27 10:34:42,659 - GeometryProcessor - INFO - 处理进度: 2770/3244 (85.4%)
2025-01-27 10:34:42,659 - GeometryProcessor - INFO - 开始处理GID=77988: 原始点数=7，已处理2个在直线中间的点，需要更新的点数5个
2025-01-27 10:34:42,659 - GeometryProcessor - INFO - 更新GID=77988的坐标，更新后坐标数 5 个
2025-01-27 10:34:42,659 - GeometryProcessor - INFO   --------------------已完成GID=77988的更新--------------------
2025-01-27 10:34:42,659 - GeometryProcessor - INFO - 处理进度: 2771/3244 (85.4%)
```

## 算法说明

### 共线性判断

使用向量叉积法判断三个点是否共线：

对于点A、B、C，计算点B到直线AC的距离：

```
距离 = |叉积(AB, AC)| / |AC|
```

如果距离小于配置的容差值（`collinearity_tolerance`），则认为B在直线AC上。

### 简化策略

1. 从第二个点开始，依次检查每个点与前后点是否共线
2. 如果共线，删除该点
3. 重复此过程直到点数达到目标值（5个点）
4. 确保首尾点相同，形成闭合环

## 注意事项

1. 运行前请确保配置文件中的SRID值与数据库中的实际SRID一致
2. 建议在运行前对数据库进行备份
3. 容差值（`collinearity_tolerance`）需要根据实际坐标系统和精度要求调整
4. 如果无法简化到目标点数，该记录会被跳过并记录警告日志
5. 脚本会自动创建logs目录，如果不存在的话

## 故障排除

### 连接错误

如果遇到 "ODBC Driver not found" 错误，请确保已安装正确版本的ODBC驱动。

### SRID错误

如果更新后SRID变为0，请检查配置文件中的SRID值是否正确。

### 简化失败

如果某些几何图形无法简化到目标点数，可能是因为：
- 几何图形不是标准的矩形或四边形
- 容差值设置不合理
- 几何图形本身就有复杂的形状

可以调整 `collinearity_tolerance` 参数来改变简化的激进程度。

## 技术栈

- **pyodbc**: SQL Server连接和查询
- **PyYAML**: YAML配置文件解析
- **logging**: Python标准日志模块
- **自定义几何算法**: 基于向量叉积的共线性判断

## 许可证

本工具作为项目的一部分，遵循项目的许可证。
