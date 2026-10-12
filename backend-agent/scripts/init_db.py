"""数据库初始化脚本。

功能：
1. 创建数据库 Ai_Farm_Manage（utf8mb4）；
2. 按架构文档 6.3 创建全部表（SQLAlchemy create_all）；
3. 对 sensor_reading 执行按月分区（原生 ALTER TABLE，失败降级普通表并打日志）；
4. 写入种子数据：用户/阈值配置/药剂/知识文档/地块/设备/传感器演示数据/天气缓存。

用法：
    python scripts/init_db.py          # 幂等初始化（已有种子则跳过）
    python scripts/init_db.py --reset  # 删除重建数据库（演示数据重置）
"""
import argparse
import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus

# 保证以任意工作目录运行均可导入 app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymysql
from sqlalchemy import insert, text
from sqlalchemy.orm import Session

from app.core.config import BASE_DIR, settings
from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.models import (
    Alert,
    AlertPushRecord,
    CaseImage,
    CaseLibrary,
    ChatMessage,
    ChatSession,
    CollectedImage,
    ConfidenceThresholdConfig,
    DailyBrief,
    Device,
    DeviceHeartbeatLog,
    DiagnosisResult,
    DiagnosisTask,
    DiagnosisTaskImage,
    EnvironmentThresholdConfig,
    ExportLog,
    FarmOperationRecord,
    HarvestRestriction,
    KnowledgeDocument,
    LanggraphCheckpoint,
    LanggraphCheckpointBlob,
    LanggraphCheckpointWrite,
    Pesticide,
    Plot,
    PreventionPlan,
    SensorReading,
    SysUser,
    WaterFertilizerAdvice,
    WeatherForecastCache,
)

# 知识文档存放目录
KNOWLEDGE_DIR = BASE_DIR / "uploads" / "knowledge"


def create_database() -> None:
    """创建业务数据库（utf8mb4 字符集）。

    使用不含库名的连接串连上 MySQL 服务端后执行 CREATE DATABASE IF NOT EXISTS。

    Raises:
        pymysql.err.OperationalError: MySQL 服务不可达或账号密码错误时抛出。
    """
    password = quote_plus(settings.db_password)
    conn = pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        charset="utf8mb4",
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{settings.db_name}` "
                "DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_unicode_ci"
            )
        conn.commit()
        print(f"[1/6] 数据库 {settings.db_name} 就绪（utf8mb4）")
    finally:
        conn.close()


def create_tables() -> None:
    """创建全部业务表（幂等，已存在跳过）。

    Raises:
        Exception: 建表失败（如 MySQL 版本不支持 JSON 类型）时抛出。
    """
    Base.metadata.create_all(bind=engine)
    print("[2/6] 全部业务表创建完成（create_all）")


def apply_sensor_partition() -> None:
    """对 sensor_reading 执行按月分区（RANGE TO_DAYS(reported_at)）。

    生成本月至未来 4 个月的分区与 MAXVALUE 兜底分区；
    分区失败（如表已有数据冲突/权限不足）时打印警告并降级为普通表。

    Raises:
        Exception: ALTER 语句执行失败时捕获并降级，不中断初始化流程。
    """
    today_value = date.today()
    partition_items = []
    # 自本月起至未来 4 个月，每月一个分区（边界=下月第一天）
    for offset in range(5):
        month_index = today_value.month - 1 + offset
        year = today_value.year + month_index // 12
        month = month_index % 12 + 1
        if month == 12:
            next_year, next_month = year + 1, 1
        else:
            next_year, next_month = year, month + 1
        boundary = f"{next_year:04d}-{next_month:02d}-01"
        partition_items.append(
            f"PARTITION p{year:04d}{month:02d} VALUES LESS THAN (TO_DAYS('{boundary}'))"
        )
    partition_items.append("PARTITION pmax VALUES LESS THAN (MAXVALUE)")
    partition_clause = ",\n    ".join(partition_items)
    sql = (
        "ALTER TABLE sensor_reading PARTITION BY RANGE (TO_DAYS(reported_at)) (\n    "
        f"{partition_clause}\n)"
    )
    try:
        with engine.begin() as conn:
            conn.execute(text(sql))
        print("[3/6] sensor_reading 按月分区成功（5+MAXVALUE 个分区）")
    except Exception as exc:  # 降级为普通表
        print(f"[3/6] [WARN] sensor_reading 分区失败，降级为普通表：{exc}")


# ---------------- 种子数据 ----------------


def seed_users(session: Session) -> None:
    """写入种子用户：农场主 owner/123456 与家庭成员 member/123456。

    Args:
        session: 数据库会话。
    """
    if session.query(SysUser).filter(SysUser.username == "owner").first() is not None:
        print("[4/6] 种子用户已存在，跳过")
        return
    session.add_all(
        [
            SysUser(
                username="owner",
                password_hash=hash_password("123456"),
                nickname="农场主",
                role="owner",
                wx_bind_status=0,
                status=1,
            ),
            SysUser(
                username="member",
                password_hash=hash_password("123456"),
                nickname="家人小王",
                role="member",
                wx_bind_status=0,
                status=1,
            ),
        ]
    )
    session.commit()
    print("[4/6] 种子用户写入：owner/123456（农场主）、member/123456（家人小王）")


def seed_confidence_thresholds(session: Session) -> None:
    """写入置信度阈值分病种配置：常见病 0.85 / 默认 0.90 / 罕见病 0.95。

    Args:
        session: 数据库会话。
    """
    if session.query(ConfidenceThresholdConfig).count() > 0:
        return
    session.add_all(
        [
            ConfidenceThresholdConfig(disease_category="common", threshold=0.85, enabled=1),
            ConfidenceThresholdConfig(disease_category="default", threshold=0.90, enabled=1),
            ConfidenceThresholdConfig(disease_category="rare", threshold=0.95, enabled=1),
        ]
    )
    session.commit()


def seed_environment_thresholds(session: Session) -> None:
    """写入环境阈值默认模板：番茄/黄瓜 + 结果期各一组（plot_id=NULL）。

    Args:
        session: 数据库会话。
    """
    if session.query(EnvironmentThresholdConfig).filter(
        EnvironmentThresholdConfig.is_default_template == 1
    ).count() > 0:
        return
    templates = []
    # 番茄+结果期：temp 12-30 / humidity 40-85 / soil_moisture 30-80
    for metric, max_value, min_value in [("temp", 30, 12), ("humidity", 85, 40), ("soil_moisture", 80, 30)]:
        templates.append(
            EnvironmentThresholdConfig(
                plot_id=None,
                crop_name="番茄",
                growth_stage="结果期",
                metric=metric,
                max_value=max_value,
                min_value=min_value,
                is_default_template=1,
                enabled=1,
            )
        )
    # 黄瓜+结果期：temp 15-32 / humidity 50-90 / soil_moisture 35-85
    for metric, max_value, min_value in [("temp", 32, 15), ("humidity", 90, 50), ("soil_moisture", 85, 35)]:
        templates.append(
            EnvironmentThresholdConfig(
                plot_id=None,
                crop_name="黄瓜",
                growth_stage="结果期",
                metric=metric,
                max_value=max_value,
                min_value=min_value,
                is_default_template=1,
                enabled=1,
            )
        )
    session.add_all(templates)
    session.commit()


def seed_knowledge_and_pesticides(session: Session) -> None:
    """写入 3 篇植保知识文档（番茄早疫病/晚疫病/白粉病）与 8 条常见药剂。

    知识文档正文落盘至 uploads/knowledge/*.txt 供后续 RAG 切片；
    药剂覆盖 allowed/restricted/banned 三类管控级别。

    Args:
        session: 数据库会话。
    """
    if session.query(KnowledgeDocument).count() > 0:
        print("[4/6] 知识文档/药剂已存在，跳过")
        return
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)

    doc1_text = (
        "番茄早疫病识别与防治。番茄早疫病又称轮纹病，由茄链格孢菌引起，是番茄生产中最常见的叶部病害之一。"
        "一、发病症状：叶片受害初期出现深褐色或黑色小斑点，后扩大为圆形或椭圆形病斑，直径一至三厘米，"
        "边缘深褐色，中央灰褐色，具有明显的同心轮纹，形似靶状，病斑表面常着生黑色霉层。"
        "茎部受害多发生在分枝处，病斑为灰褐色椭圆形，稍凹陷，也具轮纹，严重时易从病部折断。"
        "果实受害多从蒂部附近开始，形成圆形凹陷病斑，带有同心轮纹并覆盖黑霉，后期果实开裂。"
        "二、发病规律：病菌以菌丝体和分生孢子在病残体或种子上越冬，借气流、雨水传播。"
        "高温高湿利于发病，温度二十至二十五摄氏度、相对湿度百分之八十以上时最易流行，"
        "连作地块、密植通风不良、底叶老衰的植株发病重。结果期是发病高峰，需重点巡查。"
        "三、防治方法：农业防治上选用抗病品种，实行两年以上轮作，及时整枝打杈摘除老叶病叶，"
        "加强通风降湿，避免叶面长时间结露。药剂防治上，发病初期可选用代森锰锌、百菌清等保护性杀菌剂，"
        "或嘧菌酯、吡唑醚菌酯等内吸性杀菌剂交替喷雾，每七天左右一次，连续二至三次，注意轮换用药延缓抗性。"
        "用药后须遵守安全间隔期，采收前按规定停药，保证农产品质量安全。"
    )
    doc2_text = (
        "番茄晚疫病识别与防治。番茄晚疫病由致病疫霉菌引起，是一种毁灭性病害，流行速度快，"
        "短时间内可造成整棚绝收，是番茄生产中需要重点防范的病害。"
        "一、发病症状：主要为害叶片和果实，也可侵染茎秆。叶片受害多从叶尖或叶缘开始，"
        "初为暗绿色水浸状不规则病斑，扩大后变为褐色，湿度大时病斑边缘可见白色稀疏霉层，干燥时病斑干枯呈青白色，脆而易裂。"
        "茎秆和叶柄受害形成黑褐色条斑，病部凹陷，植株易从病部弯折。果实受害多发生在青果上，"
        "病斑初为油浸状暗绿色，后变为暗褐色至棕褐色，边缘不明显，果面粗糙不平，质地坚硬，湿度大时长出白霉，果实迅速腐烂。"
        "二、发病规律：病菌主要在保护地番茄或马铃薯块茎上越冬，借气流雨水传播。"
        "白天气温二十四摄氏度以下、夜间十摄氏度以上，相对湿度百分之七十五以上持续数小时即可侵染，"
        "连阴雨天气、棚内结露时间长时极易暴发流行。"
        "三、防治方法：发现中心病株立即拔除并带出棚外深埋，全棚及时喷药封锁。"
        "可选用烯酰吗啉、氟菌霜霉威、霜脲氰等药剂交替使用，每五至七天一次，连续三至四次。"
        "同时加强通风排湿，控制浇水量，采用膜下滴灌降低棚内湿度。"
        "注意用药安全间隔期，近期安排采收的地块应优先采用生物农药或提前采收后再用药。"
    )
    doc3_text = (
        "番茄白粉病识别与防治。番茄白粉病由番茄白粉菌等真菌引起，近年来在保护地番茄上发生日趋严重，"
        "主要侵染叶片，也可为害叶柄和茎部，一般不为害果实。"
        "一、发病症状：发病初期叶片正面出现白色小粉点，后逐渐扩展为近圆形白色粉状霉斑，"
        "霉斑相互连接后覆盖叶片大部分乃至整个叶面，如同撒上一层白粉。"
        "发病后期粉层变灰白色，叶片枯黄卷曲脱落，植株早衰，产量明显下降。"
        "与灰叶斑病不同之处在于白粉病病斑表面有明显白色粉状物，边缘不清晰，手抹可去除粉层但很快重现。"
        "二、发病规律：病菌以闭囊壳随病残体在土壤中越冬，也可在保护地番茄上周年循环为害。"
        "分生孢子借气流传播，萌发侵染不需要叶面水膜，在相对湿度百分之四十至九十范围内均可发病，"
        "温度二十至二十八摄氏度、棚内闷热、昼夜温差大、光照不足、氮肥偏施时发病重。"
        "三、防治方法：农业防治上加强棚室通风透光，合理密植，平衡施肥避免偏施氮肥，"
        "收获后及时清除病残体并消毒。发病初期喷施醚菌酯、乙嘧酚磺酸酯或硫磺类制剂，"
        "每七至十天一次，连续二至三次，注意保护剂与治疗剂交替使用，"
        "并严格遵守药剂安全间隔期规定，采收期慎用高残留药剂。"
    )
    docs = [
        ("番茄早疫病识别与防治", "disease_map", "doc_tomato_early_blight.txt", doc1_text),
        ("番茄晚疫病识别与防治", "disease_map", "doc_tomato_late_blight.txt", doc2_text),
        ("番茄白粉病识别与防治", "disease_map", "doc_tomato_powdery_mildew.txt", doc3_text),
    ]
    doc_models = []
    for title, category, file_name, content in docs:
        file_path = KNOWLEDGE_DIR / file_name
        file_path.write_text(content, encoding="utf-8")
        doc_models.append(
            KnowledgeDocument(
                title=title,
                category=category,
                file_url=f"/uploads/knowledge/{file_name}",
                milvus_collection="knowledge_docs",
                chunk_count=0,
                embed_status="pending",
            )
        )
    session.add_all(doc_models)
    session.flush()  # 取得文档ID供药剂名录引用

    pesticides = [
        ("吡虫啉", "吡虫啉", 7, "allowed", ["蚜虫", "白粉虱", "蓟马"]),
        ("多菌灵", "多菌灵", 14, "allowed", ["早疫病", "白粉病", "炭疽病"]),
        ("克百威", "克百威", 999, "banned", ["地下害虫", "线虫"]),
        ("甲拌磷", "甲拌磷", 999, "banned", ["地下害虫", "蚜虫"]),
        ("毒死蜱", "毒死蜱", 21, "restricted", ["菜青虫", "小菜蛾"]),
        ("代森锰锌", "代森锰锌", 7, "allowed", ["早疫病", "晚疫病", "霜霉病"]),
        ("阿维菌素", "阿维菌素", 14, "restricted", ["红蜘蛛", "斑潜蝇", "茶黄螨"]),
        ("嘧菌酯", "嘧菌酯", 3, "allowed", ["白粉病", "早疫病", "晚疫病"]),
    ]
    regulation_doc = doc_models[0]
    for name, ingredient, interval, flag, targets in pesticides:
        session.add(
            Pesticide(
                name=name,
                active_ingredient=ingredient,
                safety_interval_days=interval,
                forbidden_flag=flag,
                target_pests={"targets": targets},
                source_doc_id=regulation_doc.id,
            )
        )
    session.commit()
    print("[4/6] 知识文档 3 篇 + 药剂 8 条写入完成")


def seed_plots_and_devices(session: Session) -> None:
    """写入 2 个示例地块与 2 台示例设备，并落初始心跳日志。

    Args:
        session: 数据库会话。
    """
    if session.query(Plot).count() > 0:
        print("[4/6] 示例地块/设备已存在，跳过")
        return
    plot_tomato = Plot(
        name="番茄1号棚",
        type="greenhouse",
        lng=None,
        lat=None,
        area_mu=1.2,
        soil_type="壤土",
        crop_name="番茄",
        crop_variety="粉果番茄",
        growth_stage="结果期",
        planted_at=date.today() - timedelta(days=75),
        remark="示范棚，重点巡查对象",
        status=1,
    )
    plot_corn = Plot(
        name="玉米东地",
        type="open_field",
        lng=116.397428,
        lat=39.909230,
        area_mu=3.5,
        soil_type="沙壤土",
        crop_name="玉米",
        crop_variety="郑单958",
        growth_stage="拔节期",
        planted_at=date.today() - timedelta(days=40),
        remark="露天地块，地图选点",
        status=1,
    )
    session.add_all([plot_tomato, plot_corn])
    session.flush()

    now_value = datetime.now()
    device_sensor = Device(
        device_no="ENV-SENSOR-001",
        name="番茄1号棚环境传感器",
        type="env_sensor",
        plot_id=plot_tomato.id,
        protocol="MQTT",
        vendor="演示厂商A",
        collect_schedule={"interval_minutes": 15, "metrics": ["temp", "humidity", "soil_moisture"]},
        config={"report_unit": "metric"},
        status="online",
        last_heartbeat_at=now_value,
    )
    device_camera = Device(
        device_no="CAM-RTSP-001",
        name="玉米东地摄像头",
        type="camera",
        plot_id=plot_corn.id,
        protocol="RTSP",
        vendor="演示厂商B",
        collect_schedule={"times_per_day": 3, "trigger": "event"},
        config={"stream": "rtsp://demo.local/stream1"},
        status="online",
        last_heartbeat_at=now_value,
    )
    session.add_all([device_sensor, device_camera])
    session.flush()

    session.add_all(
        [
            DeviceHeartbeatLog(device_id=device_sensor.id, heartbeat_at=now_value, status="online"),
            DeviceHeartbeatLog(device_id=device_camera.id, heartbeat_at=now_value, status="online"),
        ]
    )
    session.commit()
    print("[4/6] 示例地块 2 个 + 设备 2 台 + 心跳日志写入完成")


def seed_sensor_data(session: Session) -> None:
    """写入番茄1号棚近 7 天传感器演示数据（15 分钟间隔，含日变化曲线）。

    temp 呈正弦日变化（午后高温），humidity 反相变化，soil_moisture 缓慢下降；
    最近 4 条 temp 固定为 33℃，用于演示环境越限报警（番茄结果期上限 30℃）。

    Args:
        session: 数据库会话。
    """
    plot_tomato = session.query(Plot).filter(Plot.name == "番茄1号棚").first()
    device_sensor = session.query(Device).filter(Device.device_no == "ENV-SENSOR-001").first()
    if plot_tomato is None or device_sensor is None:
        print("[4/6] [WARN] 缺少番茄1号棚或环境传感器，跳过传感器演示数据")
        return
    if session.query(SensorReading).filter(SensorReading.plot_id == plot_tomato.id).count() > 0:
        print("[4/6] 传感器演示数据已存在，跳过")
        return

    rows = []
    current_time = datetime.now()
    # 生成近 7 天（含今天已过去的时点）的 15 分钟整点序列
    start_time = (current_time - timedelta(days=7)).replace(minute=0, second=0, microsecond=0)
    time_points = []
    point = start_time
    while point <= current_time:
        time_points.append(point)
        point += timedelta(minutes=15)

    total_points = len(time_points)
    for index, ts in enumerate(time_points):
        # 日变化相位：正午 13 点为温度峰，凌晨 4 点为温度谷
        day_progress = (ts.hour * 60 + ts.minute) / 1440.0
        temp_wave = 7.5 * math.sin(2 * math.pi * (day_progress - 0.29))
        base_temp = 22.0 + temp_wave + 0.3 * math.sin(index)
        humidity_value = max(30.0, min(95.0, 66.0 - 11.0 * math.sin(2 * math.pi * (day_progress - 0.29))))
        # 墒情缓慢下降并周期性回升（模拟滴灌）
        soil_value = max(30.0, min(85.0, 62.0 - 6.0 * math.sin(2 * math.pi * day_progress) - index % 96 * 0.02))
        rows.append(
            {"device_id": device_sensor.id, "plot_id": plot_tomato.id, "metric": "temp",
             "value": round(base_temp, 1), "unit": "℃", "reported_at": ts}
        )
        rows.append(
            {"device_id": device_sensor.id, "plot_id": plot_tomato.id, "metric": "humidity",
             "value": round(humidity_value, 1), "unit": "%RH", "reported_at": ts}
        )
        rows.append(
            {"device_id": device_sensor.id, "plot_id": plot_tomato.id, "metric": "soil_moisture",
             "value": round(soil_value, 1), "unit": "%", "reported_at": ts}
        )

    # 最近 4 条温度设为 33℃ 触发越限演示
    for row in rows[-12:]:
        if row["metric"] == "temp":
            row["value"] = 33.0

    session.execute(insert(SensorReading), rows)
    session.commit()
    print(f"[4/6] 传感器演示数据写入完成：{total_points} 个时点 × 3 指标（最近 4 条 temp=33℃ 演示越限）")


def seed_weather(session: Session) -> None:
    """写入番茄1号棚/玉米东地未来 7 天天气缓存（静态模拟值）。

    Args:
        session: 数据库会话。
    """
    if session.query(WeatherForecastCache).count() > 0:
        print("[4/6] 天气缓存已存在，跳过")
        return
    plots = session.query(Plot).all()
    conditions = ["晴", "多云", "阴", "小雨", "多云", "晴", "多云转晴"]
    today_value = date.today()
    for plot in plots:
        for day_offset, condition in enumerate(conditions):
            forecast_date = today_value + timedelta(days=day_offset)
            session.add(
                WeatherForecastCache(
                    plot_id=plot.id,
                    data_type="weather_forecast",
                    forecast_date=forecast_date,
                    data_json={
                        "condition": condition,
                        "temp_high": round(26.0 + 2.5 * math.sin(day_offset), 1),
                        "temp_low": round(15.0 + 1.8 * math.cos(day_offset), 1),
                        "precipitation_mm": 0.0 if "雨" not in condition else 8.5,
                        "wind": "东南风3级" if day_offset % 2 == 0 else "南风2级",
                    },
                    source_api="static_demo",
                )
            )
    session.commit()
    print("[4/6] 天气缓存写入完成：2 地块 × 未来 7 天")


def verify() -> None:
    """初始化结果自检：输出表清单与关键种子记录计数。

    Raises:
        Exception: 连接失败时抛出。
    """
    with engine.connect() as conn:
        tables = [row[0] for row in conn.execute(text("SHOW TABLES"))]
        print(f"[5/6] 当前库内表数量：{len(tables)}")
        for table_name in sorted(tables):
            print(f"      - {table_name}")
        user_count = conn.execute(text("SELECT COUNT(*) FROM sys_user")).scalar()
        plot_count = conn.execute(text("SELECT COUNT(*) FROM plot")).scalar()
        device_count = conn.execute(text("SELECT COUNT(*) FROM device")).scalar()
        reading_count = conn.execute(text("SELECT COUNT(*) FROM sensor_reading")).scalar()
        print(
            f"[6/6] 种子自检：用户 {user_count}，地块 {plot_count}，设备 {device_count}，"
            f"传感器读数 {reading_count}"
        )


def reset_database() -> None:
    """删除并重建数据库（--reset 模式）。

    Raises:
        pymysql.err.OperationalError: MySQL 不可达时抛出。
    """
    conn = pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        charset="utf8mb4",
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS `{settings.db_name}`")
        conn.commit()
        print("已删除旧数据库，准备重建")
    finally:
        conn.close()


def main() -> None:
    """初始化脚本主流程入口。

    依次执行：建库 → 建表 → 分区 → 种子数据 → 自检。

    Raises:
        Exception: 任一数据库操作失败时抛出并以非零码退出。
    """
    parser = argparse.ArgumentParser(description="农场智能管护系统数据库初始化脚本")
    parser.add_argument("--reset", action="store_true", help="删除并重建数据库（危险操作）")
    args = parser.parse_args()

    if args.reset:
        reset_database()

    print("========== 农场智能管护系统 数据库初始化开始 ==========")
    create_database()
    create_tables()
    apply_sensor_partition()

    session = SessionLocal()
    try:
        seed_users(session)
        seed_confidence_thresholds(session)
        seed_environment_thresholds(session)
        seed_knowledge_and_pesticides(session)
        seed_plots_and_devices(session)
        seed_sensor_data(session)
        seed_weather(session)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    verify()
    print("========== 数据库初始化完成 ==========")


if __name__ == "__main__":
    main()
