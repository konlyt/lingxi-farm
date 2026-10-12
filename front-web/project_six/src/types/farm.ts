/**
 * 文件说明：农场业务实体类型定义。
 * 依据后端实际返回契约（已逐一 curl 校验）集中声明所有业务数据结构，供 API 层与页面共用。
 */

/** 用户角色：owner 农场主（全部权限）/ member 家庭成员（只读） */
export type UserRole = 'owner' | 'member'

/** 系统用户信息 */
export interface User {
  /** 用户 ID */
  id: number
  /** 登录名 */
  username: string
  /** 昵称 */
  nickname: string
  /** 角色 */
  role: UserRole
  /** 服务号绑定状态：1 已绑定 / 0 未绑定（可选） */
  wx_bind_status?: number
}

/** 地块类型：greenhouse 大棚 / open_field 露天（后端字符串枚举） */
export type PlotType = 'greenhouse' | 'open_field'

/** 地块/棚室档案 */
export interface Plot {
  /** 地块 ID */
  id: number
  /** 名称（唯一） */
  name: string
  /** 类型：greenhouse 大棚 / open_field 露天 */
  type: PlotType
  /** 经度（露天地块） */
  lng?: number | null
  /** 纬度（露天地块） */
  lat?: number | null
  /** 面积（亩） */
  area_mu?: number | null
  /** 土壤类型 */
  soil_type?: string | null
  /** 作物名称 */
  crop_name?: string | null
  /** 作物品种 */
  crop_variety?: string | null
  /** 当前生育期 */
  growth_stage?: string | null
  /** 定植日期 */
  planted_at?: string | null
  /** 备注 */
  remark?: string | null
  /** 状态：1 启用 / 0 停用（软删除） */
  status?: number
  /** 是否存在生效中的采收禁令 */
  has_active_restriction?: boolean
}

/** 采收禁令记录（地块详情 harvest_restrictions 数组项） */
export interface HarvestRestriction {
  /** 记录 ID */
  id: number
  /** 农药名称 */
  pesticide_name: string
  /** 施药日期 */
  applied_at: string
  /** 禁止采收截止日期 */
  ban_until: string
}

/** 采收禁令角标（总览聚合） */
export interface HarvestBanner {
  /** 地块 ID */
  plot_id: number
  /** 地块名称 */
  plot_name: string
  /** 禁止采收截止日期 */
  ban_until: string
  /** 农药名称 */
  pesticide_name?: string
}

/** 地块详情（含最新环境快照与采收禁令） */
export interface PlotDetail extends Plot {
  /** 最新环境快照（平铺 {temp, humidity, soil_moisture}，值为 null 表示缺失） */
  latest_env?: { temp: number | null; humidity: number | null; soil_moisture: number | null } | null
  /** 生效中的采收禁令列表 */
  harvest_restrictions?: HarvestRestriction[]
}

/** 单个环境指标值（后端 realtime.metrics 项） */
export interface MetricValue {
  /** 指标数值（缺失为 null） */
  value: number | null
  /** 单位 */
  unit: string
  /** 是否越限（正常 null / 越限 "high"|"low"，真值判断即视为越限） */
  exceeded: string | boolean | null
  /** 触发的阈值上下限 */
  threshold?: { max: number | null; min: number | null }
  /** 该指标最近上报时间 */
  last_reported_at?: string | null
}

/** 地块实时环境 */
export interface RealtimeEnv {
  /** 地块 ID */
  plot_id: number
  /** 地块名称 */
  plot_name?: string
  /** 指标集合：temp/humidity/light/soil_moisture */
  metrics: Record<string, MetricValue>
}

/** 环境趋势数据 */
export interface EnvTrend {
  /** 时间范围标识（24h/7d） */
  range?: string
  /** 时间轴 */
  times: string[]
  /** 各指标序列 */
  series: {
    /** 温度序列 */
    temp: Array<number | null>
    /** 湿度序列 */
    humidity: Array<number | null>
    /** 土壤墒情序列 */
    soil_moisture: Array<number | null>
  }
}

/** 环境越限报警记录（GET /environment/alarm-records 直接返回数组） */
export interface AlarmRecord {
  /** 记录 ID */
  id: number
  /** 指标键名 */
  metric: string
  /** 越限值 */
  value: number
  /** 单位 */
  unit?: string
  /** 触发的阈值上下限 */
  threshold: { max: number | null; min: number | null }
  /** 越限方向 high/low */
  direction?: string
  /** 预警等级 */
  level?: string
  /** 预警状态 */
  status?: string
  /** 累计触发次数 */
  occurrence_count?: number
  /** 触发时间 */
  triggered_at: string
  /** 恢复时间（未恢复为空） */
  recovered_at?: string | null
}

/** 阈值模板/地块覆盖配置（后端 EnvironmentThresholdConfig 序列化） */
export interface ThresholdTemplate {
  /** 配置 ID */
  id: number
  /** 地块 ID（null 为默认模板） */
  plot_id?: number | null
  /** 作物名称 */
  crop_name: string
  /** 生育期 */
  growth_stage: string
  /** 指标键名 */
  metric: string
  /** 上限 */
  max_value: number | null
  /** 下限 */
  min_value: number | null
  /** 是否默认模板：1 是 / 0 否 */
  is_default_template?: number
  /** 是否启用 */
  enabled: boolean
}

/** 地块级阈值覆盖配置别名 */
export type PlotThreshold = ThresholdTemplate

/** 阈值配置集合（模板 + 地块覆盖） */
export interface ThresholdSettings {
  /** 默认模板列表 */
  templates: ThresholdTemplate[]
  /** 地块覆盖配置列表 */
  plot_configs: PlotThreshold[]
}

/** 阈值新建/编辑载荷（enabled 传输为 0/1，与后端 int 约束对齐） */
export interface ThresholdPayload {
  /** 地块 ID（模板应用时必填） */
  plot_id?: number | null
  /** 作物名称 */
  crop_name: string
  /** 生育期 */
  growth_stage: string
  /** 指标键名 */
  metric: string
  /** 上限 */
  max_value?: number | null
  /** 下限 */
  min_value?: number | null
  /** 是否启用：1 启用 / 0 停用 */
  enabled: number
}

/** 设备统计 */
export interface DeviceStats {
  /** 设备总数 */
  total: number
  /** 在线数 */
  online: number
  /** 离线数 */
  offline: number
}

/** 设备信息（后端实际返回 type: camera/pest_light/spore_trap/env_sensor；protocol: MQTT/RTSP/vendor_api） */
export interface Device {
  /** 设备 ID */
  id: number
  /** 设备编号 */
  device_no: string
  /** 设备名称 */
  name?: string | null
  /** 类型：camera/pest_light/spore_trap/env_sensor */
  type: string
  /** 所属地块 ID */
  plot_id?: number | null
  /** 所属地块名称（列表接口附带） */
  plot_name?: string | null
  /** 接入协议：MQTT/RTSP/vendor_api */
  protocol: string
  /** 厂商 */
  vendor?: string | null
  /** 状态：online 在线 / offline 离线 */
  status?: string
  /** 最近心跳时间 */
  last_heartbeat_at?: string | null
}

/** 设备详情（含最近心跳与采集计划） */
export interface DeviceDetail extends Device {
  /** 采集计划 JSON（对象结构，如 {metrics, interval_minutes}） */
  collect_schedule?: Record<string, unknown> | null
  /** 远程配置 JSON */
  config?: Record<string, unknown> | null
  /** 最近心跳时间字符串数组 */
  recent_heartbeats?: string[]
}

/** 图像上传结果 */
export interface ImageUploadResult {
  /** 图像 ID */
  id: number
  /** 访问地址（相对路径 /uploads/...） */
  url: string
  /** 是否重复图像（感知哈希去重） */
  duplicate: boolean
}

/** 诊断任务图像 */
export interface TaskImage {
  /** 图像 ID */
  id: number
  /** 图像地址 */
  url: string
  /** 来源 device/manual（可选） */
  source?: string
  /** 拍摄时间（可选） */
  captured_at?: string
}

/** 单模型识别结果 */
export interface DiagnosisResultItem {
  /** 模型路径标识（vlm/fused 等） */
  model_path: string
  /** 模型名称（可选） */
  model_name?: string
  /** 识别病名 */
  disease_name: string
  /** 病种分类（可选） */
  disease_category?: string
  /** 置信度 0-1 */
  confidence: number
  /** 原始输出（可选） */
  raw_output?: Record<string, unknown>
}

/** 用药合规校验结果（后端为对象结构） */
export interface ComplianceResult {
  /** 合规说明 */
  notes?: string
  /** 命中的禁限用药列表 */
  banned?: unknown[]
  /** 提及的药剂列表 */
  mentioned?: unknown[]
}

/** 防治方案卡 */
export interface DiagnosisPlan {
  /** 方案明细 JSON（键值形式展示） */
  scheme_json: Record<string, unknown> | null
  /** 用药合规校验结果说明（对象或文本） */
  compliance_result?: string | ComplianceResult | null
  /** 是否拦截禁限用药：1 是 / 0 否 */
  is_forbidden_blocked?: number
  /** 免责声明 */
  disclaimer?: string | null
}

/** 诊断任务关联案例（用于确认/纠正操作） */
export interface CaseRef {
  /** 案例 ID（可确认/纠正时存在） */
  id?: number
  /** 案例状态：pending/confirmed/corrected */
  status: string
  /** AI 初判病名（可选） */
  ai_disease_name?: string
  /** 最终病名（可选） */
  final_disease_name?: string
}

/** 诊断任务详情（后端状态机：pending → running → done/failed） */
export interface DiagnosisTaskDetail {
  /** 任务 ID */
  id: number
  /** 线程 ID */
  thread_id?: string
  /** 地块 ID */
  plot_id?: number
  /** 地块名称 */
  plot_name?: string
  /** 任务状态：pending/running/done/failed */
  status: string
  /** 来源：device/manual */
  source: string
  /** 诊断时生育期 */
  growth_stage?: string | null
  /** 创建时间 */
  created_at: string
  /** 完成时间 */
  finished_at?: string | null
  /** 融合置信度 0-1 */
  fused_confidence?: number | null
  /** 结果档位：high 高置信 / low 低置信 */
  result_level?: string | null
  /** 失败原因 */
  failure_reason?: string | null
  /** 任务图像列表 */
  images: TaskImage[]
  /** 各模型识别结果 */
  results: DiagnosisResultItem[]
  /** 防治方案卡（低置信度为 null） */
  plan: DiagnosisPlan | null
  /** 关联案例 */
  case: CaseRef | null
}

/** 诊断记录列表项 */
export interface DiagnosisRecord {
  /** 任务 ID */
  id: number
  /** 地块 ID */
  plot_id?: number
  /** 地块名称 */
  plot_name: string
  /** 缩略图地址 */
  thumb_url: string
  /** 诊断病名 */
  disease_name: string
  /** 置信度 0-1 */
  confidence: number
  /** 来源：device/manual */
  source: string
  /** 生育期（可选） */
  growth_stage?: string | null
  /** 任务状态：pending/running/done/failed */
  status: string
  /** 结果档位（可选） */
  result_level?: string | null
  /** 案例状态（可选） */
  case_status?: string | null
  /** 案例状态中文展示（可选） */
  case_status_display?: string | null
  /** 创建时间 */
  created_at: string
}

/** 案例统计 */
export interface CaseStats {
  /** 总案例数 */
  total: number
  /** 待确认数 */
  pending: number
  /** 已确认数 */
  confirmed: number
  /** 已纠正数 */
  corrected: number
  /** 各病种样本量（病种名 → 数量） */
  by_category: Record<string, number>
}

/** 案例库列表项 */
export interface CaseItem {
  /** 案例 ID */
  id: number
  /** 关联任务 ID */
  task_id?: number
  /** AI 初判病名 */
  ai_disease_name: string
  /** 最终病名（确认/纠正后） */
  final_disease_name?: string | null
  /** 状态：pending/confirmed/corrected */
  status: string
  /** 来源：device/manual */
  source: string
  /** 病种分类 */
  disease_category: string
  /** 纠正备注 */
  note?: string | null
  /** 创建时间 */
  created_at: string
  /** 图像地址列表 */
  image_urls: string[]
}

/** 预警列表项（后端 status: active/resolved；level: info/warning/critical；overview 聚合不含 plot_name） */
export interface AlertItem {
  /** 预警 ID */
  id: number
  /** 类型：pest/env/weather/device_offline */
  type: string
  /** 等级：info/warning/critical */
  level: string
  /** 地块 ID */
  plot_id?: number
  /** 地块名称（列表/详情接口返回，overview 聚合可能缺失） */
  plot_name?: string
  /** 标题 */
  title: string
  /** 状态：active 未解决 / resolved 已解决 */
  status: string
  /** 累计触发次数 */
  occurrence_count: number
  /** 是否升级过 */
  is_upgraded: boolean
  /** 首次触发时间 */
  first_triggered_at: string
  /** 解决时间（未解决为空） */
  resolved_at?: string | null
}

/** 预警详情 content 快照（各类型字段不同） */
export interface AlertContent {
  /** 病名（pest） */
  disease_name?: string
  /** 置信度（pest） */
  confidence?: number
  /** 病情描述（pest） */
  description?: string
  /** 现场照片地址（pest） */
  latest_image_url?: string
  /** 防治方案 ID（pest） */
  plan_id?: number
  /** 设备 ID（device_offline） */
  device_id?: number
  /** 设备编号（device_offline） */
  device_no?: string
  /** 最近心跳时间（device_offline） */
  last_heartbeat_at?: string
  /** 指标键名（env） */
  metric?: string
  /** 越限值（env） */
  value?: number
  /** 单位（env） */
  unit?: string
  /** 阈值（env） */
  threshold?: { max: number | null; min: number | null }
  /** 越限方向 high/low（env） */
  direction?: string
  /** 最近上报时间（env） */
  latest_reported_at?: string
  /** 其他字段 */
  [key: string]: unknown
}

/** 预警时间线事件（content 为快照对象） */
export interface AlertTimelineEvent {
  /** 事件时间 */
  time: string
  /** 事件名称 */
  event: string
  /** 事件内容快照对象 */
  content: AlertContent
}

/** 预警详情 */
export interface AlertDetail extends AlertItem {
  /** 聚合键 */
  case_key?: string
  /** 关联诊断任务 ID（病虫害预警可跳转诊断详情，无关联为 null） */
  related_task_id?: number | null
  /** 详情快照对象（各类型字段不同） */
  content: AlertContent
  /** 病情变化时间线 */
  timeline: AlertTimelineEvent[]
}

/** 水肥建议单日条目（后端 irrigate/fertilize 为整段文本） */
export interface WaterFertilizerItem {
  /** 日期 */
  date: string
  /** 浇水建议文本 */
  irrigate: string
  /** 施肥建议文本 */
  fertilize: string
}

/** 水肥建议数据（后端双层 data 包装） */
export interface WaterFertilizerAdvice {
  /** 地块 ID */
  plot_id: number
  /** 地块名称 */
  plot_name?: string
  /** 建议日期 */
  advice_date: string
  /** 建议数据体 */
  data: {
    /** 当日总结 */
    summary?: string
    /** 未来 7 天建议列表 */
    items: WaterFertilizerItem[]
    /** 风险提示 */
    risk_notes?: string
    /** 依据 JSON */
    basis_json?: Record<string, unknown> | null
    /** 是否使用了降级数据：1 是 / 0 否 */
    data_fallback_flag: number
    /** 建议天数 */
    horizon_days?: number
    /** 推送状态 */
    push_status?: string
    /** 生成时间 */
    created_at?: string
  }
}

/** 环境调控建议条目 */
export interface EnvironmentAdviceItem {
  /** 时段 */
  time_range: string
  /** 操作建议 */
  action: string
  /** 依据 */
  reason: string
}

/** 环境调控建议（未来 12h） */
export interface EnvironmentAdvice {
  /** 地块 ID */
  plot_id: number
  /** 地块名称 */
  plot_name?: string
  /** 建议列表 */
  items: EnvironmentAdviceItem[]
}

/** 每日简报今日待办项 */
export interface BriefTodoItem {
  /** 地块 ID */
  plot_id: number
  /** 地块名称 */
  plot_name: string
  /** 浇水建议 */
  irrigate: string
  /** 施肥建议 */
  fertilize: string
}

/** 每日简报地块概要项 */
export interface BriefPlotSummary {
  /** 地块 ID */
  plot_id: number
  /** 地块名称 */
  plot_name: string
  /** 作物与生育期描述 */
  crop: string
  /** 环境快照 */
  env: { temp: number | null; humidity: number | null; soil_moisture: number | null }
  /** 活跃预警数 */
  active_alerts: number
}

/** 每日农情简报（后端双层 data 包装） */
export interface DailyBrief {
  /** 简报日期 */
  date: string
  /** 简报数据体 */
  data: {
    /** 简报内容对象 */
    content: {
      /** 今日待办列表 */
      today_todos: BriefTodoItem[]
      /** 各地块概要 */
      plot_summaries: BriefPlotSummary[]
      /** 气象提醒列表 */
      weather_reminders: unknown[]
    }
    /** 推送状态 */
    push_status: string
    /** 推送时间 */
    pushed_at?: string
  }
}

/** 天气条目（总览聚合 items 项） */
export interface WeatherItem {
  /** 地块 ID */
  plot_id: number
  /** 地块名称 */
  plot_name: string
  /** 天气状况 */
  condition: string
  /** 最高温度 */
  temp_high: number
  /** 最低温度 */
  temp_low: number
  /** 降水量 mm */
  precipitation_mm: number
  /** 风向风力 */
  wind: string
}

/** 总览页地块卡片（latest_env 为平铺快照） */
export interface PlotCard {
  /** 地块 ID */
  id: number
  /** 名称 */
  name: string
  /** 类型：greenhouse 大棚 / open_field 露天 */
  type: PlotType
  /** 作物名称 */
  crop_name?: string | null
  /** 生育期 */
  growth_stage?: string | null
  /** 最新环境快照（平铺，值 null 表示缺失） */
  latest_env?: { temp: number | null; humidity: number | null; soil_moisture: number | null } | null
  /** 最近巡检图像 */
  latest_image?: {
    /** 图像地址 */
    url: string
    /** AI 标注病名 */
    ai_label: string
    /** 置信度 */
    confidence: number
    /** 来源 device/manual */
    source: string
    /** 拍摄时间 */
    captured_at?: string
  } | null
  /** 是否存在生效中的采收禁令 */
  has_active_restriction: boolean
}

/** 今日待办项（总览聚合） */
export interface OverviewTodo {
  /** 地块 ID */
  plot_id: number
  /** 地块名称 */
  plot_name: string
  /** 待办标题 */
  title: string
  /** 待办内容 */
  content: string
}

/** 农场总览聚合数据 */
export interface FarmOverview {
  /** 采收禁令角标列表 */
  harvest_banners: HarvestBanner[]
  /** 地块实况卡片 */
  plot_cards: PlotCard[]
  /** 今日待办（对象数组） */
  today_todos: OverviewTodo[]
  /** 最新预警列表 */
  latest_alerts: AlertItem[]
  /** 今日天气（按地块） */
  weather: {
    /** 日期 */
    date: string
    /** 各地块天气条目 */
    items: WeatherItem[]
  }
}

/** 诊断趋势项 */
export interface DiagnosisTrendItem {
  /** 日期 */
  date: string
  /** 数量 */
  count: number
}

/** 病虫害类型分布项 */
export interface DiseaseDistributionItem {
  /** 病名 */
  disease_name: string
  /** 数量 */
  count: number
}

/** 地块虫情密度与墒情项 */
export interface PlotPestDensityItem {
  /** 地块 ID */
  plot_id: number
  /** 地块名称 */
  plot_name: string
  /** 活跃病虫害预警数 */
  pest_alert_count: number
  /** 土壤墒情 */
  soil_moisture: number | null
}

/** 各地块环境实况项 */
export interface DashboardEnvItem {
  /** 地块 ID */
  plot_id: number
  /** 地块名称 */
  plot_name: string
  /** 类型：greenhouse/open_field */
  type: string
  /** 温度 */
  temp: number | null
  /** 湿度 */
  humidity: number | null
}

/** 监测大屏聚合统计 */
export interface DashboardStats {
  /** 诊断趋势（按日） */
  diagnosis_trend: DiagnosisTrendItem[]
  /** 病虫害类型分布 */
  disease_distribution: DiseaseDistributionItem[]
  /** 地块虫情密度与墒情 */
  plot_pest_density: PlotPestDensityItem[]
  /** 设备健康度 */
  device_health: DeviceStats
  /** 最近预警 */
  recent_alerts: AlertItem[]
  /** 各地块环境实况 */
  env_realtime: DashboardEnvItem[]
}

/** 置信度阈值配置（分病种） */
export interface ConfidenceThreshold {
  /** 配置 ID */
  id: number
  /** 病种分类：common/default/rare */
  disease_category: string
  /** 置信度阈值 0-1 */
  threshold: number
  /** 参考样本量基线（可为空） */
  sample_count_baseline: number | null
  /** 是否启用 */
  enabled: boolean
}

/** 家庭成员 */
export interface Member {
  /** 用户 ID */
  id: number
  /** 登录名 */
  username: string
  /** 昵称 */
  nickname: string
  /** 角色 */
  role: UserRole
  /** 状态：1 启用 / 0 停用 */
  status?: number
  /** 服务号绑定状态：1 已绑定 / 0 未绑定 */
  wx_bind_status?: number
  /** 创建时间 */
  created_at?: string
}

/** 服务号绑定状态项 */
export interface WxBindItem {
  /** 用户 ID */
  id: number
  /** 登录名 */
  username?: string
  /** 昵称 */
  nickname: string
  /** 角色 */
  role: UserRole
  /** 绑定状态：1 已绑定 / 0 未绑定 */
  wx_bind_status: number
  /** 微信 openid（未绑定为 null） */
  wx_openid?: string | null
}

/** 会话信息 */
export interface ChatSession {
  /** 会话 ID */
  id: number
  /** 会话标题 */
  title?: string | null
  /** 创建时间 */
  created_at?: string | null
}

/** 会话消息 */
export interface ChatMessage {
  /** 消息 ID */
  id?: number
  /** 角色：user/assistant */
  role: string
  /** 内容类型（text） */
  content_type?: string
  /** 消息内容 */
  content: string
  /** 时间 */
  created_at?: string | null
  /** 是否低置信度回答 */
  low_confidence?: boolean
}

/** 问答响应 */
export interface ChatAnswer {
  /** 会话 ID */
  session_id: number
  /** 回答内容 */
  answer: string
  /** 是否低置信度 */
  low_confidence: boolean
  /** 意图识别结果（可选） */
  intent?: string
}

/** 知识文档 */
export interface KnowledgeDocument {
  /** 文档 ID */
  id: number
  /** 标题 */
  title: string
  /** 分类：disease_map/treatment/pesticide_regulation */
  category: string
  /** 分类中文名 */
  category_display?: string
  /** 文件地址 */
  file_url?: string | null
  /** 切片数量 */
  chunk_count?: number
  /** 向量化状态：pending/done/failed */
  embed_status?: string
  /** 创建时间 */
  created_at?: string | null
}

/** 导出任务（后端状态：pending/done/failed） */
export interface ExportTask {
  /** 任务 ID */
  id: number
  /** 导出类型：diagnosis_cases/env_data */
  export_type: string
  /** 文件地址（完成后存在） */
  file_url?: string | null
  /** 状态：pending/done/failed */
  status: string
  /** 创建时间 */
  created_at: string
}

/** 农事日历事件 */
export interface CalendarEvent {
  /** 日期 YYYY-MM-DD */
  date: string
  /** 事件标题 */
  title: string
  /** 事件类型：irrigate/fertilize/pestcontrol/harvest/farmwork 等 */
  type: string
  /** 地块 ID */
  plot_id?: number
  /** 地块名称 */
  plot_name: string
}

/** 农事提醒 */
export interface CalendarReminder {
  /** 日期 */
  date: string
  /** 标题 */
  title: string
  /** 事件类型 */
  type: string
  /** 地块 ID */
  plot_id?: number
  /** 地块名称 */
  plot_name: string
  /** 剩余天数 */
  days_until: number
}
