/**
 * 文件说明：三维园区沙盘场景构建（纯 three.js，无 Vue 依赖）。
 * 程序化生成：地面网格、地块发光多边形（大棚拱顶 / 露天田垄）、设备脉冲标记、
 * 预警呼吸光环、地块名称标签。数据驱动：setPlots 增量更新状态，不重建对象。
 */
import * as THREE from 'three'

/** 地块可视状态 */
export type PlotVisualState = 'ok' | 'warn' | 'alert'

/** 三维地块输入 */
export interface ParkPlotInput {
  /** 地块 ID */
  plotId: number
  /** 地块名称 */
  name: string
  /** 类型：greenhouse / open_field */
  type: string
  /** 可视状态 */
  state: PlotVisualState
  /** 温度文本（详情卡展示用，可空） */
  tempText?: string
  /** 湿度文本（详情卡展示用，可空） */
  humText?: string
  /** 预警标题（详情卡展示用，可空） */
  alertTitle?: string
  /** 土壤墒情（0-100，可空） */
  soilMoisture?: number | null
  /** 活跃病虫害预警数 */
  pestAlertCount?: number
  /** 最新预警标题列表（详情面板用） */
  alertTitles?: string[]
}

/** 状态主色板（与大屏 2D 配色一致） */
const STATE_COLORS: Record<PlotVisualState, number> = {
  ok: 0x35d0ba,
  warn: 0xfac775,
  alert: 0xf0655f,
}

/** 地块排布：3 列 × N 行网格 */
const COLS = 3
/** 列间距（世界单位） */
const COL_GAP = 17
/** 行间距（世界单位） */
const ROW_GAP = 15
/** 地块宽（X 方向） */
const PLOT_W = 13
/** 地块深（Z 方向） */
const PLOT_D = 9.5
/** 地块台面高度 */
const PLOT_H = 0.5

/**
 * 单个地块的三维对象集合与动态元素引用。
 */
interface PlotVisual {
  /** 地块 ID */
  plotId: number
  /** 地块中心世界坐标 */
  center: THREE.Vector3
  /** 台面网格（拾取用） */
  base: THREE.Mesh
  /** 发光描边 */
  edge: THREE.LineLoop
  /** 台面材质 */
  baseMat: THREE.MeshStandardMaterial
  /** 描边材质 */
  edgeMat: THREE.LineBasicMaterial
  /** 预警呼吸光环（仅 alert 显示） */
  ring: THREE.Mesh
  /** 环材质 */
  ringMat: THREE.MeshBasicMaterial
  /** 设备辉光精灵列表 */
  glows: THREE.Sprite[]
  /** 当前状态 */
  state: PlotVisualState
  /** 动画相位 */
  phase: number
  /** 待释放的几何体 */
  geometries: THREE.BufferGeometry[]
  /** 待释放的材质 */
  materials: THREE.Material[]
  /** 待释放的纹理 */
  textures: THREE.Texture[]
}

/**
 * 园区场景内容句柄。
 */
export interface ParkSceneContent {
  /** 场景根组 */
  group: THREE.Group
  /** 全量替换地块列表（结构变化时重建，状态变化时增量更新） */
  setPlots(plots: ParkPlotInput[]): void
  /** 每帧动画（elapsed 单位秒） */
  update(elapsed: number): void
  /** 可拾取对象列表 */
  pickables(): THREE.Object3D[]
  /** 按地块 ID 取中心坐标（无则 null） */
  plotCenter(plotId: number): THREE.Vector3 | null
  /** 显示/关闭地块三维详情层（传 null 关闭；重复调用会重建详情层） */
  showDetail(plotId: number | null): void
  /** 释放全部资源 */
  dispose(): void
}

/**
 * 生成圆角矩形 Shape。
 * @param w 宽
 * @param d 深
 * @param r 圆角半径
 * @returns 形状
 */
function roundedRect(w: number, d: number, r: number): THREE.Shape {
  const s = new THREE.Shape()
  const x = w / 2
  const z = d / 2
  s.moveTo(-x + r, -z)
  s.lineTo(x - r, -z)
  s.quadraticCurveTo(x, -z, x, -z + r)
  s.lineTo(x, z - r)
  s.quadraticCurveTo(x, z, x - r, z)
  s.lineTo(-x + r, z)
  s.quadraticCurveTo(-x, z, -x, z - r)
  s.lineTo(-x, -z + r)
  s.quadraticCurveTo(-x, -z, -x + r, -z)
  return s
}

/**
 * 用 Canvas 2D 绘制中文文本标签纹理。
 * @param text 文本
 * @param color 文本颜色
 * @returns 纹理
 */
function makeLabelTexture(text: string, color = '#d7ecff'): THREE.Texture {
  const canvas = document.createElement('canvas')
  canvas.width = 256
  canvas.height = 64
  const ctx = canvas.getContext('2d')
  if (ctx) {
    ctx.font = '28px "Microsoft YaHei", sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillStyle = color
    ctx.shadowColor = 'rgba(0, 0, 0, 0.9)'
    ctx.shadowBlur = 6
    ctx.fillText(text, 128, 34, 240)
  }
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  return tex
}

/**
 * 生成科技风地面纹理：深空底色 + 青色网格线。
 * @returns 纹理
 */
function makeTechGroundTexture(): THREE.Texture {
  const canvas = document.createElement('canvas')
  canvas.width = 256
  canvas.height = 256
  const ctx = canvas.getContext('2d')
  if (ctx) {
    ctx.fillStyle = '#0a1626'
    ctx.fillRect(0, 0, 256, 256)
    /* 细网格 */
    ctx.strokeStyle = 'rgba(46, 197, 255, 0.10)'
    ctx.lineWidth = 1
    for (let i = 0; i <= 256; i += 32) {
      ctx.beginPath()
      ctx.moveTo(i + 0.5, 0)
      ctx.lineTo(i + 0.5, 256)
      ctx.stroke()
      ctx.beginPath()
      ctx.moveTo(0, i + 0.5)
      ctx.lineTo(256, i + 0.5)
      ctx.stroke()
    }
    /* 主网格 */
    ctx.strokeStyle = 'rgba(46, 197, 255, 0.26)'
    for (let i = 0; i <= 256; i += 128) {
      ctx.beginPath()
      ctx.moveTo(i + 0.5, 0)
      ctx.lineTo(i + 0.5, 256)
      ctx.stroke()
      ctx.beginPath()
      ctx.moveTo(0, i + 0.5)
      ctx.lineTo(256, i + 0.5)
      ctx.stroke()
    }
    /* 稀疏发光节点 */
    for (let i = 0; i < 14; i++) {
      const x = Math.round(Math.random() * 16) * 16
      const y = Math.round(Math.random() * 16) * 16
      ctx.fillStyle = 'rgba(53, 208, 186, 0.5)'
      ctx.fillRect(x - 1, y - 1, 3, 3)
    }
  }
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.wrapS = THREE.RepeatWrapping
  tex.wrapT = THREE.RepeatWrapping
  tex.repeat.set(12, 12)
  return tex
}

/**
 * 生成径向辉光精灵纹理。
 * @returns 纹理
 */
function makeGlowTexture(): THREE.Texture {
  const canvas = document.createElement('canvas')
  canvas.width = 64
  canvas.height = 64
  const ctx = canvas.getContext('2d')
  if (ctx) {
    const g = ctx.createRadialGradient(32, 32, 2, 32, 32, 30)
    g.addColorStop(0, 'rgba(255, 255, 255, 1)')
    g.addColorStop(0.35, 'rgba(255, 255, 255, 0.5)')
    g.addColorStop(1, 'rgba(255, 255, 255, 0)')
    ctx.fillStyle = g
    ctx.fillRect(0, 0, 64, 64)
  }
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  return tex
}

/**
 * 构建三维园区沙盘。
 * @returns 场景内容句柄
 */
export function createParkScene(): ParkSceneContent {
  const group = new THREE.Group()
  const sharedGeometries: THREE.BufferGeometry[] = []
  const sharedMaterials: THREE.Material[] = []
  const sharedTextures: THREE.Texture[] = []
  /** 地块可视对象（按 plotId） */
  const plots = new Map<number, PlotVisual>()
  /** 地块容器组（重建时整体移除） */
  const plotGroup = new THREE.Group()
  group.add(plotGroup)
  /** 详情层容器 */
  const detailGroup = new THREE.Group()
  group.add(detailGroup)
  /** 当前详情层根对象 */
  let detailRoot: THREE.Group | null = null
  /** 详情层数值标签（浮动动画用） */
  const detailFloats: { sprite: THREE.Sprite; baseY: number; phase: number }[] = []
  /** 输入数据缓存（详情层构建用） */
  const inputsCache = new Map<number, ParkPlotInput>()

  /* ---------- 地面（科技网格）/ 道路 / 边界 / 树木 ---------- */
  const groundGeo = new THREE.CircleGeometry(95, 64)
  const groundTex = makeTechGroundTexture()
  const groundMat = new THREE.MeshStandardMaterial({
    map: groundTex,
    roughness: 0.85,
    metalness: 0.2,
    emissive: 0x0a2540,
    emissiveIntensity: 0.35,
  })
  const ground = new THREE.Mesh(groundGeo, groundMat)
  ground.rotation.x = -Math.PI / 2
  ground.position.y = -0.05
  ground.receiveShadow = true
  group.add(ground)
  sharedGeometries.push(groundGeo)
  sharedMaterials.push(groundMat)
  sharedTextures.push(groundTex)

  /* 园区边界光环 */
  const boundGeo = new THREE.RingGeometry(32.6, 33.2, 96)
  boundGeo.rotateX(-Math.PI / 2)
  const boundMat = new THREE.MeshBasicMaterial({
    color: 0x2ea7e0,
    transparent: true,
    opacity: 0.55,
    side: THREE.DoubleSide,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  })
  const boundary = new THREE.Mesh(boundGeo, boundMat)
  boundary.position.y = 0.04
  group.add(boundary)
  sharedGeometries.push(boundGeo)
  sharedMaterials.push(boundMat)

  /* 全息雷达扫描波（绕 Y 轴旋转的楔形光扇） */
  const sweepCanvas = document.createElement('canvas')
  sweepCanvas.width = 256
  sweepCanvas.height = 256
  const swctx = sweepCanvas.getContext('2d')
  if (swctx) {
    const grad = swctx.createConicGradient(0, 128, 128)
    grad.addColorStop(0, 'rgba(53, 208, 186, 0.5)')
    grad.addColorStop(0.14, 'rgba(53, 208, 186, 0)')
    grad.addColorStop(1, 'rgba(53, 208, 186, 0)')
    swctx.fillStyle = grad
    swctx.beginPath()
    swctx.arc(128, 128, 127, 0, Math.PI * 2)
    swctx.fill()
  }
  const sweepTex = new THREE.CanvasTexture(sweepCanvas)
  sweepTex.colorSpace = THREE.SRGBColorSpace
  const sweepGeo = new THREE.PlaneGeometry(58, 58)
  const sweepMat = new THREE.MeshBasicMaterial({
    map: sweepTex,
    transparent: true,
    opacity: 0.42,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    side: THREE.DoubleSide,
  })
  const sweepGroup = new THREE.Group()
  sweepGroup.rotation.x = -Math.PI / 2
  sweepGroup.position.y = 0.05
  const sweepPlane = new THREE.Mesh(sweepGeo, sweepMat)
  sweepGroup.add(sweepPlane)
  group.add(sweepGroup)
  sharedGeometries.push(sweepGeo)
  sharedMaterials.push(sweepMat)
  sharedTextures.push(sweepTex)

  /* 道路：地块行间主路 + 两条支路（科技灰 + 青色光带中线） */
  const roadMat = new THREE.MeshStandardMaterial({ color: 0x101822, roughness: 0.9, metalness: 0.1 })
  const laneMat = new THREE.MeshBasicMaterial({ color: 0x35d0ba })
  sharedMaterials.push(roadMat, laneMat)
  const roadSegs: { x: number; z: number; w: number; d: number }[] = [
    { x: 0, z: 0, w: 130, d: 4.2 },
    { x: -30, z: -20, w: 3.4, d: 44 },
    { x: 30, z: 20, w: 3.4, d: 44 },
  ]
  for (const seg of roadSegs) {
    const geo = new THREE.PlaneGeometry(seg.w, seg.d)
    sharedGeometries.push(geo)
    const road = new THREE.Mesh(geo, roadMat)
    road.rotation.x = -Math.PI / 2
    road.position.set(seg.x, 0.01, seg.z)
    road.receiveShadow = true
    group.add(road)
  }
  /* 主路中线虚线 */
  const dashGeo = new THREE.PlaneGeometry(2.2, 0.22)
  sharedGeometries.push(dashGeo)
  for (let i = -14; i <= 14; i++) {
    const dash = new THREE.Mesh(dashGeo, laneMat)
    dash.rotation.x = -Math.PI / 2
    dash.position.set(i * 4.6, 0.02, 0)
    group.add(dash)
  }

  /* 树木：树干 + 双层树冠（夜色深绿），环绕场地外圈 */
  const trunkGeo = new THREE.CylinderGeometry(0.14, 0.2, 1.1, 6)
  const trunkMat = new THREE.MeshStandardMaterial({ color: 0x3a2c1c, roughness: 0.9 })
  const leafGeo = new THREE.ConeGeometry(1.05, 1.6, 8)
  const leafMat = new THREE.MeshStandardMaterial({
    color: 0x1f4a38,
    roughness: 0.9,
    emissive: 0x0d3324,
    emissiveIntensity: 0.5,
  })
  const leaf2Geo = new THREE.ConeGeometry(0.75, 1.3, 8)
  sharedGeometries.push(trunkGeo, leafGeo, leaf2Geo)
  sharedMaterials.push(trunkMat, leafMat)
  for (let i = 0; i < 30; i++) {
    const angle = (i / 30) * Math.PI * 2
    const radius = 38 + (i % 3) * 8
    const tx = Math.cos(angle) * radius
    const tz = Math.sin(angle) * radius
    const s = 1.2 + ((i * 5) % 7) / 12
    const trunk = new THREE.Mesh(trunkGeo, trunkMat)
    trunk.position.set(tx, 0.5 * s, tz)
    trunk.scale.setScalar(s)
    trunk.castShadow = true
    const leaf = new THREE.Mesh(leafGeo, leafMat)
    leaf.position.set(tx, 1.7 * s, tz)
    leaf.scale.setScalar(s)
    leaf.castShadow = true
    const leaf2 = new THREE.Mesh(leaf2Geo, leafMat)
    leaf2.position.set(tx, 2.6 * s, tz)
    leaf2.scale.setScalar(s)
    leaf2.castShadow = true
    group.add(trunk, leaf, leaf2)
  }

  /* ---------- 预置共享纹理 ---------- */
  const glowTex = makeGlowTexture()
  sharedTextures.push(glowTex)

  /**
   * 计算第 i 个地块的中心坐标。
   * @param i 序号
   * @returns 中心坐标
   */
  function plotCenterByIndex(i: number): THREE.Vector3 {
    const col = i % COLS
    const row = Math.floor(i / COLS)
    return new THREE.Vector3((col - (COLS - 1) / 2) * COL_GAP, 0, (row - 0.5) * ROW_GAP)
  }

  /**
   * 释放单个地块的全部资源并从场景移除。
   * @param v 地块可视对象
   */
  function disposePlot(v: PlotVisual): void {
    plotGroup.remove(v.base.parent ?? v.base)
    for (const g of v.geometries) g.dispose()
    for (const m of v.materials) m.dispose()
    for (const t of v.textures) t.dispose()
  }

  /**
   * 构建单个地块的可视对象。
   * @param input 地块输入
   * @param i 序号
   * @returns 可视对象
   */
  function buildPlot(input: ParkPlotInput, i: number): PlotVisual {
    const center = plotCenterByIndex(i)
    const color = STATE_COLORS[input.state]
    const holder = new THREE.Group()
    holder.position.copy(center)
    const geometries: THREE.BufferGeometry[] = []
    const materials: THREE.Material[] = []
    const textures: THREE.Texture[] = []
    const glows: THREE.Sprite[] = []

    /* 地块垫层（拾取体）：深色中性垫，状态色只由描边/光环表达 */
    const baseGeo = new THREE.ExtrudeGeometry(roundedRect(PLOT_W, PLOT_D, 1.6), {
      depth: PLOT_H,
      bevelEnabled: false,
    })
    baseGeo.rotateX(-Math.PI / 2)
    const baseMat = new THREE.MeshStandardMaterial({
      color: 0x1a2734,
      roughness: 0.9,
      metalness: 0.15,
      emissive: 0x0a1826,
      emissiveIntensity: 0.4,
    })
    const base = new THREE.Mesh(baseGeo, baseMat)
    base.position.y = 0
    base.receiveShadow = true
    base.userData.plotId = input.plotId
    holder.add(base)
    geometries.push(baseGeo)
    materials.push(baseMat)

    /* 发光描边（由地块轮廓点直接生成闭环） */
    const edgePts = roundedRect(PLOT_W, PLOT_D, 1.6)
      .getPoints(16)
      .map((p) => new THREE.Vector3(p.x, 0, p.y))
    const edgeGeo = new THREE.BufferGeometry().setFromPoints(edgePts)
    const edgeMat = new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.95 })
    const edge = new THREE.LineLoop(edgeGeo, edgeMat)
    edge.position.y = PLOT_H + 0.03
    holder.add(edge)
    geometries.push(edgeGeo)
    materials.push(edgeMat)

    /* 名称标签 */
    const labelTex = makeLabelTexture(input.name)
    const labelMat = new THREE.SpriteMaterial({ map: labelTex, transparent: true, depthWrite: false })
    const label = new THREE.Sprite(labelMat)
    label.scale.set(7, 1.75, 1)
    label.position.set(0, PLOT_H + 2.6, 0)
    holder.add(label)
    textures.push(labelTex)
    materials.push(labelMat)

    /* 地块主体建模：大棚=双联拱棚，露天=土壤苗床 */
    if (input.type === 'greenhouse') {
      /* 双联拱棚：两栋并排，各带拱肋/棚膜/端墙/棚内作物 */
      const GH_LEN = PLOT_W * 0.82
      const GH_R = 1.9
      const GH_Z = [-2.15, 2.15]
      const coverGeo = new THREE.CylinderGeometry(GH_R, GH_R, GH_LEN, 20, 1, true, 0, Math.PI)
      coverGeo.rotateZ(Math.PI / 2)
      const coverMat = new THREE.MeshPhysicalMaterial({
        color: 0x9fd4ff,
        transparent: true,
        opacity: 0.2,
        roughness: 0.15,
        metalness: 0.1,
        side: THREE.DoubleSide,
        clearcoat: 0.7,
        emissive: 0x1a6fa8,
        emissiveIntensity: 0.5,
      })
      geometries.push(coverGeo)
      materials.push(coverMat)
      /* 拱肋曲线（共享一条 TubeGeometry） */
      const ribPts: THREE.Vector3[] = []
      for (let s = 0; s <= 20; s++) {
        const t = (s / 20) * Math.PI
        ribPts.push(new THREE.Vector3(0, Math.sin(t) * GH_R, -Math.cos(t) * GH_R))
      }
      const ribGeo = new THREE.TubeGeometry(new THREE.CatmullRomCurve3(ribPts), 24, 0.035, 6, false)
      const steelMat = new THREE.MeshStandardMaterial({ color: 0xaab8c2, roughness: 0.4, metalness: 0.8 })
      geometries.push(ribGeo)
      materials.push(steelMat)
      const cropGeo = new THREE.ConeGeometry(0.2, 0.44, 6)
      const cropMat = new THREE.MeshStandardMaterial({
        color: 0x3f9f4f,
        roughness: 0.85,
        emissive: 0x1f8a45,
        emissiveIntensity: 0.65,
      })
      geometries.push(cropGeo)
      materials.push(cropMat)
      const crops = new THREE.InstancedMesh(cropGeo, cropMat, 36)
      const m4 = new THREE.Matrix4()
      const cq = new THREE.Quaternion()
      const cpos = new THREE.Vector3()
      const cscl = new THREE.Vector3()
      let ci = 0
      for (const gz of GH_Z) {
        /* 棚膜 */
        const cover = new THREE.Mesh(coverGeo, coverMat)
        cover.position.set(0, PLOT_H, gz)
        cover.castShadow = true
        holder.add(cover)
        /* 拱肋 ×5 */
        for (let r = 0; r < 5; r++) {
          const rib = new THREE.Mesh(ribGeo, steelMat)
          rib.position.set(-GH_LEN / 2 + (r * GH_LEN) / 4, PLOT_H, gz)
          holder.add(rib)
        }
        /* 棚内两行作物 */
        for (let row = 0; row < 2; row++) {
          for (let c = 0; c < 9; c++) {
            cpos.set(
              -GH_LEN / 2 + 1 + (c * (GH_LEN - 2)) / 8,
              PLOT_H + 0.22,
              gz + (row === 0 ? -0.5 : 0.5),
            )
            const s = 0.8 + ((ci * 5) % 7) / 25
            cscl.set(s, s, s)
            m4.compose(cpos, cq, cscl)
            crops.setMatrixAt(ci++, m4)
          }
        }
      }
      crops.castShadow = true
      holder.add(crops)
    } else {
      /* 露天：4 条土壤苗床 + 作物垄 */
      const bedGeo = new THREE.BoxGeometry(PLOT_W - 2.4, 0.14, 1.05)
      const bedMat = new THREE.MeshStandardMaterial({ color: 0x4a3826, roughness: 1 })
      geometries.push(bedGeo)
      materials.push(bedMat)
      for (let f = 0; f < 4; f++) {
        const bed = new THREE.Mesh(bedGeo, bedMat)
        bed.position.set(0, PLOT_H + 0.07, -PLOT_D / 2 + 1.5 + (f * (PLOT_D - 3)) / 3)
        bed.castShadow = true
        bed.receiveShadow = true
        holder.add(bed)
      }
      const cropGeo = new THREE.ConeGeometry(0.2, 0.46, 6)
      const cropMat = new THREE.MeshStandardMaterial({
        color: 0x3f9f4f,
        roughness: 0.85,
        emissive: 0x1f8a45,
        emissiveIntensity: 0.65,
      })
      const crops = new THREE.InstancedMesh(cropGeo, cropMat, 48)
      const m4 = new THREE.Matrix4()
      const cq = new THREE.Quaternion()
      const cpos = new THREE.Vector3()
      const cscl = new THREE.Vector3()
      let ci = 0
      for (let row = 0; row < 4; row++) {
        for (let c = 0; c < 12; c++) {
          cpos.set(
            -PLOT_W / 2 + 1.6 + (c * (PLOT_W - 3.2)) / 11,
            PLOT_H + 0.3,
            -PLOT_D / 2 + 1.5 + (row * (PLOT_D - 3)) / 3,
          )
          const s = 0.8 + ((ci * 5) % 7) / 25
          cscl.set(s, s, s)
          m4.compose(cpos, cq, cscl)
          crops.setMatrixAt(ci++, m4)
        }
      }
      crops.castShadow = true
      holder.add(crops)
      geometries.push(cropGeo)
      materials.push(cropMat)
    }

    /* 设备脉冲标记（地块两端各一个） */
    const poleGeo = new THREE.CylinderGeometry(0.07, 0.09, 1.7, 8)
    const poleMat = new THREE.MeshStandardMaterial({ color: 0x8fb8dd, roughness: 0.4, metalness: 0.6 })
    for (const dx of [-PLOT_W / 2 + 1.2, PLOT_W / 2 - 1.2]) {
      const pole = new THREE.Mesh(poleGeo, poleMat)
      pole.position.set(dx, PLOT_H + 0.85, -PLOT_D / 2 + 1.2)
      holder.add(pole)
      const glowMat = new THREE.SpriteMaterial({
        map: glowTex,
        color,
        transparent: true,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      })
      const glow = new THREE.Sprite(glowMat)
      glow.position.set(dx, PLOT_H + 1.85, -PLOT_D / 2 + 1.2)
      glow.scale.set(1.1, 1.1, 1)
      holder.add(glow)
      glows.push(glow)
      materials.push(glowMat)
    }
    geometries.push(poleGeo)
    materials.push(poleMat)

    /* 预警呼吸光环 */
    const ringGeo = new THREE.RingGeometry(PLOT_W / 2 + 0.6, PLOT_W / 2 + 1.3, 48)
    ringGeo.rotateX(-Math.PI / 2)
    const ringMat = new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    })
    const ring = new THREE.Mesh(ringGeo, ringMat)
    ring.position.y = PLOT_H + 0.06
    holder.add(ring)
    geometries.push(ringGeo)
    materials.push(ringMat)

    plotGroup.add(holder)
    return {
      plotId: input.plotId,
      center,
      base,
      edge,
      baseMat,
      edgeMat,
      ring,
      ringMat,
      glows,
      state: input.state,
      phase: (i * 1.7) % (Math.PI * 2),
      geometries,
      materials,
      textures,
    }
  }

  /**
   * 释放详情层对象树上的几何体/材质/纹理。
   * @param root 根对象
   */
  function disposeObjectTree(root: THREE.Object3D): void {
    root.traverse((o) => {
      const anyObj = o as THREE.Mesh & { material?: THREE.Material | THREE.Material[] }
      anyObj.geometry?.dispose()
      const mat = anyObj.material
      if (Array.isArray(mat)) {
        for (const m of mat) {
          const sm = m as THREE.SpriteMaterial
          sm.map?.dispose()
          m.dispose()
        }
      } else if (mat) {
        ;(mat as THREE.SpriteMaterial).map?.dispose()
        mat.dispose()
      }
    })
  }

  /**
   * 构建地块三维详情层：大棚拱肋骨架 + 内部作物垄 + 传感器数值标签。
   * @param input 地块输入
   * @returns 详情层根组（局部坐标=地块中心）
   */
  function buildDetail(input: ParkPlotInput): THREE.Group {
    const g = new THREE.Group()
    const archR = (PLOT_D / 2) * 0.82
    const span = PLOT_W * 0.8

    if (input.type === 'greenhouse') {
      /* 拱肋：沿跨度均布的半圆弧线 */
      const SEG = 24
      const ribMat = new THREE.LineBasicMaterial({ color: 0x7fd0ff, transparent: true, opacity: 0.8 })
      const ribCount = 7
      const ribGeo = new THREE.BufferGeometry()
      const allRibs: number[] = []
      for (let r = 0; r < ribCount; r++) {
        const x = -span / 2 + (r * span) / (ribCount - 1)
        for (let s = 0; s < SEG; s++) {
          const t0 = (s / SEG) * Math.PI
          const t1 = ((s + 1) / SEG) * Math.PI
          allRibs.push(
            x, PLOT_H + 0.1 + Math.sin(t0) * archR, -Math.cos(t0) * archR,
            x, PLOT_H + 0.1 + Math.sin(t1) * archR, -Math.cos(t1) * archR,
          )
        }
      }
      ribGeo.setAttribute('position', new THREE.Float32BufferAttribute(allRibs, 3))
      g.add(new THREE.LineSegments(ribGeo, ribMat))

      /* 脊线 */
      const ridgeGeo = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(-span / 2, PLOT_H + 0.1 + archR, 0),
        new THREE.Vector3(span / 2, PLOT_H + 0.1 + archR, 0),
      ])
      g.add(new THREE.Line(ridgeGeo, ribMat))
    }

    /* 内部作物垄（InstancedMesh 锥体模拟植株） */
    const rows = input.type === 'greenhouse' ? 2 : 4
    const perRow = input.type === 'greenhouse' ? 9 : 10
    const cropGeo = new THREE.ConeGeometry(0.26, 0.62, 6)
    const cropMat = new THREE.MeshStandardMaterial({
      color: 0x3f9f4f,
      roughness: 0.85,
      emissive: 0x1f8a45,
      emissiveIntensity: 0.7,
    })
    const crops = new THREE.InstancedMesh(cropGeo, cropMat, rows * perRow)
    const m = new THREE.Matrix4()
    const q = new THREE.Quaternion()
    const pos = new THREE.Vector3()
    const scl = new THREE.Vector3()
    let idx = 0
    for (let r = 0; r < rows; r++) {
      const z = -PLOT_D / 2 + 2 + (r * (PLOT_D - 4)) / Math.max(rows - 1, 1)
      for (let c = 0; c < perRow; c++) {
        const x = -span / 2 + 0.8 + (c * (span - 1.6)) / (perRow - 1)
        const jitter = (((r * perRow + c) * 7) % 13) / 13 - 0.5
        pos.set(x + jitter * 0.5, PLOT_H + 0.32, z + jitter * 0.4)
        const s = 0.8 + (((r * perRow + c) * 5) % 9) / 30
        scl.set(s, s, s)
        m.compose(pos, q, scl)
        crops.setMatrixAt(idx++, m)
      }
    }
    crops.instanceMatrix.needsUpdate = true
    g.add(crops)

    /* 传感器桩 + 实时数值浮动标签 */
    const stakeGeo = new THREE.CylinderGeometry(0.05, 0.05, 1.1, 6)
    const stakeMat = new THREE.MeshStandardMaterial({ color: 0x8fb8dd, roughness: 0.4, metalness: 0.6 })
    const sensors: { dx: number; text: string; color: string }[] = [
      { dx: -span / 4, text: input.tempText ? `温 ${input.tempText}` : '温 --', color: '#35d0ba' },
      { dx: span / 4, text: input.humText ? `湿 ${input.humText}` : '湿 --', color: '#4ea6ff' },
    ]
    for (const sen of sensors) {
      const stake = new THREE.Mesh(stakeGeo, stakeMat)
      stake.position.set(sen.dx, PLOT_H + 0.55, 0)
      g.add(stake)
      const glowMat = new THREE.SpriteMaterial({
        map: glowTex,
        color: 0x35d0ba,
        transparent: true,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      })
      const glow = new THREE.Sprite(glowMat)
      glow.position.set(sen.dx, PLOT_H + 1.25, 0)
      glow.scale.set(0.9, 0.9, 1)
      g.add(glow)
      const tex = makeLabelTexture(sen.text, sen.color)
      const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false })
      const sprite = new THREE.Sprite(mat)
      sprite.scale.set(4.6, 1.15, 1)
      sprite.center.set(0.5, 0)
      const baseY = PLOT_H + 1.5
      sprite.position.set(sen.dx, baseY, 0)
      g.add(sprite)
      detailFloats.push({ sprite, baseY, phase: sen.dx > 0 ? 1.2 : 0 })
    }
    return g
  }

  /**
   * 应用状态到材质（增量更新）。
   * @param v 地块可视对象
   * @param state 目标状态
   */
  function applyState(v: PlotVisual, state: PlotVisualState): void {
    v.state = state
    const color = STATE_COLORS[state]
    /* 垫层保持中性，状态色只上描边/光环/设备辉光 */
    v.edgeMat.color.setHex(color)
    v.ringMat.color.setHex(color)
    for (const g of v.glows) g.material.color.setHex(color)
  }

  /* ---------- 句柄 ---------- */
  return {
    group,
    setPlots(inputs: ParkPlotInput[]): void {
      inputsCache.clear()
      for (const p of inputs) inputsCache.set(p.plotId, p)
      const nextIds = new Set(inputs.map((p) => p.plotId))
      // 移除消失的地块
      for (const [id, v] of plots) {
        if (!nextIds.has(id)) {
          disposePlot(v)
          plots.delete(id)
        }
      }
      // 结构变化（数量/顺序/位置）时全量重建，避免位置错乱
      const structuralChanged =
        plots.size !== inputs.length ||
        inputs.some((p, i) => {
          const v = plots.get(p.plotId)
          return !v || v.center.distanceToSquared(plotCenterByIndex(i)) > 0.01
        })
      if (structuralChanged) {
        for (const [, v] of plots) disposePlot(v)
        plots.clear()
        inputs.forEach((p, i) => plots.set(p.plotId, buildPlot(p, i)))
        return
      }
      // 增量更新状态
      for (const p of inputs) {
        const v = plots.get(p.plotId)
        if (v && v.state !== p.state) applyState(v, p.state)
      }
    },
    update(elapsed: number): void {
      for (const v of plots.values()) {
        // 设备辉光脉冲
        for (const g of v.glows) {
          const s = 1.1 + 0.3 * Math.sin(elapsed * 2.6 + v.phase)
          g.scale.set(s, s, 1)
        }
        if (v.state === 'alert') {
          // 呼吸光环：扩张 + 渐隐循环
          const t = (elapsed * 0.7 + v.phase) % 1
          const scale = 1 + t * 0.9
          v.ring.scale.set(scale, 1, scale)
          v.ringMat.opacity = 0.75 * (1 - t)
          v.edgeMat.opacity = 0.6 + 0.4 * Math.sin(elapsed * 5 + v.phase)
        } else if (v.state === 'warn') {
          v.ringMat.opacity = 0
          v.edgeMat.opacity = 0.7 + 0.3 * Math.sin(elapsed * 2.4 + v.phase)
        } else {
          v.ringMat.opacity = 0
          v.edgeMat.opacity = 0.95
        }
      }
      // 详情层数值标签浮动
      for (const f of detailFloats) {
        f.sprite.position.y = f.baseY + 0.12 * Math.sin(elapsed * 2 + f.phase)
      }
      // 雷达扫描波旋转
      sweepPlane.rotation.z = -elapsed * 0.45
    },
    pickables(): THREE.Object3D[] {
      return [...plots.values()].map((v) => v.base)
    },
    plotCenter(plotId: number): THREE.Vector3 | null {
      return plots.get(plotId)?.center.clone() ?? null
    },
    showDetail(plotId: number | null): void {
      // 重建前先释放旧详情层
      if (detailRoot) {
        detailGroup.remove(detailRoot)
        disposeObjectTree(detailRoot)
        detailRoot = null
      }
      detailFloats.length = 0
      if (plotId === null) return
      const input = inputsCache.get(plotId)
      if (!input || !plots.has(plotId)) return
      detailRoot = buildDetail(input)
      detailGroup.add(detailRoot)
    },
    dispose(): void {
      if (detailRoot) {
        detailGroup.remove(detailRoot)
        disposeObjectTree(detailRoot)
        detailRoot = null
      }
      detailFloats.length = 0
      for (const [, v] of plots) disposePlot(v)
      plots.clear()
      for (const g of sharedGeometries) g.dispose()
      for (const m of sharedMaterials) m.dispose()
      for (const t of sharedTextures) t.dispose()
    },
  }
}
