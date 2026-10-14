/**
 * 文件说明：单棚/地块数字孪生场景构建（纯 three.js，无 Vue 依赖）。
 * 精细化版本：大棚=拱肋骨架 + 侧立柱/纵向栏杆 + 屋顶通风窗（摆动）+ 侧卷膜 +
 * 吊挂补光灯 + 滴灌带 + 茎秆植株 + 水泥基座 + 水塔/空调外机 + 树木/路灯/围栏；
 * 露天=垫高田块 + 地膜苗床 + 小拱棚 + 泵房 + 稻草人 + 防风林 + 围栏 + 土路。
 */
import * as THREE from 'three'

/** 单棚孪生输入数据 */
export interface GreenhouseTwinData {
  /** 棚名 */
  name: string
  /** 温度文本（如 25.4℃） */
  tempText?: string
  /** 湿度文本（如 63%） */
  humText?: string
  /** 土壤墒情 0-100 */
  soilMoisture?: number | null
}

/** 孪生场景类型：greenhouse 拱棚 / open_field 露天地块 */
export type TwinSceneKind = 'greenhouse' | 'open_field'

/** 单棚孪生场景句柄 */
export interface GreenhouseTwinContent {
  /** 场景根组 */
  group: THREE.Group
  /** 数据更新（重建标签文本） */
  setData(data: GreenhouseTwinData): void
  /** 每帧动画 */
  update(elapsed: number): void
  /** 释放全部资源 */
  dispose(): void
}

/** 棚体尺寸（世界单位：米） */
const LEN = 22
/** 拱半径 */
const ARCH_R = 3.6
/** 拱肋数量 */
const RIB_COUNT = 13

/**
 * 用 Canvas 2D 绘制文本标签纹理（带绘制器支持后续重绘）。
 * @param initialText 初始文本
 * @param color 文本色
 */
function makeLiveLabel(initialText: string, color: string) {
  const canvas = document.createElement('canvas')
  canvas.width = 256
  canvas.height = 64
  const ctx = canvas.getContext('2d')
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  const draw = (text: string): void => {
    if (!ctx) return
    ctx.clearRect(0, 0, 256, 64)
    ctx.font = '28px "Microsoft YaHei", sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillStyle = color
    ctx.shadowColor = 'rgba(0, 0, 0, 0.85)'
    ctx.shadowBlur = 6
    ctx.fillText(text, 128, 34, 244)
    tex.needsUpdate = true
  }
  draw(initialText)
  return { tex, draw }
}

/**
 * 生成草地噪点纹理（Canvas 程序化，供草地地面平铺）。
 * @returns 噪点纹理
 */
function makeGrassTexture(): THREE.CanvasTexture {
  const c = document.createElement('canvas')
  c.width = 256
  c.height = 256
  const ctx = c.getContext('2d')
  if (ctx) {
    ctx.fillStyle = '#4e7c3e'
    ctx.fillRect(0, 0, 256, 256)
    /* 深浅草色噪点块 */
    for (let i = 0; i < 2600; i++) {
      const x = Math.random() * 256
      const y = Math.random() * 256
      const shade = Math.random()
      ctx.fillStyle =
        shade > 0.66 ? 'rgba(94,132,64,0.5)' : shade > 0.33 ? 'rgba(66,104,52,0.5)' : 'rgba(120,150,78,0.35)'
      ctx.fillRect(x, y, 2 + Math.random() * 3, 1 + Math.random() * 2)
    }
  }
  const tex = new THREE.CanvasTexture(c)
  tex.wrapS = THREE.RepeatWrapping
  tex.wrapT = THREE.RepeatWrapping
  tex.repeat.set(12, 12)
  tex.colorSpace = THREE.SRGBColorSpace
  return tex
}

/**
 * 构建一棵景观树（树干 + 双层树冠）。
 * @param g 树干几何
 * @param c1 树冠下几何
 * @param c2 树冠上几何
 * @param gm 树干材质
 * @param cm 树冠材质
 * @param x 位置 x
 * @param z 位置 z
 * @param s 整体缩放
 * @returns 树组
 */
function makeTree(
  g: THREE.BufferGeometry,
  c1: THREE.BufferGeometry,
  c2: THREE.BufferGeometry,
  gm: THREE.Material,
  cm: THREE.Material,
  x: number,
  z: number,
  s: number,
): THREE.Group {
  const tree = new THREE.Group()
  const trunk = new THREE.Mesh(g, gm)
  trunk.position.y = 0.55
  trunk.castShadow = true
  tree.add(trunk)
  const low = new THREE.Mesh(c1, cm)
  low.position.y = 1.35
  low.castShadow = true
  tree.add(low)
  const top = new THREE.Mesh(c2, cm)
  top.position.y = 1.95
  top.castShadow = true
  tree.add(top)
  tree.position.set(x, 0, z)
  tree.scale.setScalar(s)
  tree.rotation.y = x * 1.7 + z * 0.9
  return tree
}

/**
 * 构建一盏庭院路灯（灯杆 + 悬臂 + 发光灯头）。
 * @param poleGeo 杆几何
 * @param armGeo 臂几何
 * @param headGeo 头几何
 * @param pm 杆材质
 * @param hm 头材质
 * @param x 位置 x
 * @param z 位置 z
 * @param flip 是否反向（朝 -z）
 * @returns 路灯组
 */
function makeStreetlight(
  poleGeo: THREE.BufferGeometry,
  armGeo: THREE.BufferGeometry,
  headGeo: THREE.BufferGeometry,
  pm: THREE.Material,
  hm: THREE.Material,
  x: number,
  z: number,
  flip: boolean,
): THREE.Group {
  const lamp = new THREE.Group()
  const pole = new THREE.Mesh(poleGeo, pm)
  pole.position.y = 1.7
  pole.castShadow = true
  lamp.add(pole)
  const arm = new THREE.Mesh(armGeo, pm)
  arm.position.set(0.3, 3.25, 0)
  lamp.add(arm)
  const head = new THREE.Mesh(headGeo, hm)
  head.position.set(0.62, 3.16, 0)
  lamp.add(head)
  lamp.position.set(x, 0, z)
  if (flip) {
    lamp.rotation.y = Math.PI
  }
  return lamp
}

/**
 * 构建单棚数字孪生场景（精细化版）。
 * @returns 场景句柄
 */
export function createGreenhouseTwin(): GreenhouseTwinContent {
  const group = new THREE.Group()
  const geometries: THREE.BufferGeometry[] = []
  const materials: THREE.Material[] = []
  const textures: THREE.Texture[] = []

  /** 注册并返回几何（便于统一释放） */
  function track<T extends THREE.BufferGeometry>(g: T): T {
    geometries.push(g)
    return g
  }
  /** 注册并返回材质（便于统一释放） */
  function trackM<T extends THREE.Material>(m: T): T {
    materials.push(m)
    return m
  }

  /* ---------- 浮动标签注册表 ---------- */
  const liveLabels: { sprite: THREE.Sprite; draw: (t: string) => void; baseY: number; phase: number }[] = []

  /**
   * 添加一个浮动标签。
   * @param text 初始文本
   * @param color 文本色
   * @param pos 位置
   * @param scale 宽度
   * @returns 绘制器
   */
  function addLabel(text: string, color: string, pos: THREE.Vector3, scale: number): (t: string) => void {
    const label = makeLiveLabel(text, color)
    textures.push(label.tex)
    const mat = trackM(new THREE.SpriteMaterial({ map: label.tex, transparent: true, depthWrite: false }))
    const sprite = new THREE.Sprite(mat)
    sprite.scale.set(scale, scale / 4, 1)
    sprite.center.set(0.5, 0)
    sprite.position.copy(pos)
    group.add(sprite)
    liveLabels.push({ sprite, draw: label.draw, baseY: pos.y, phase: pos.x * 0.7 + pos.z })
    return label.draw
  }

  /* ---------- 草地地面（噪点纹理） ---------- */
  const grassTex = makeGrassTexture()
  textures.push(grassTex)
  const groundGeo = track(new THREE.PlaneGeometry(90, 90))
  const groundMat = trackM(new THREE.MeshStandardMaterial({ map: grassTex, roughness: 1 }))
  const ground = new THREE.Mesh(groundGeo, groundMat)
  ground.rotation.x = -Math.PI / 2
  ground.receiveShadow = true
  group.add(ground)

  /* ---------- 道路（柏油 + 中线虚线 + 路缘） ---------- */
  const roadGeo = track(new THREE.PlaneGeometry(90, 5.5))
  const roadMat = trackM(new THREE.MeshStandardMaterial({ color: 0x3c4045, roughness: 0.95 }))
  const road = new THREE.Mesh(roadGeo, roadMat)
  road.rotation.x = -Math.PI / 2
  road.position.set(0, 0.01, ARCH_R + 9)
  road.receiveShadow = true
  group.add(road)
  /* 中线虚线（12 段） */
  const dashGeo = track(new THREE.PlaneGeometry(2.2, 0.14))
  const dashMat = trackM(new THREE.MeshStandardMaterial({ color: 0xd8dce0, roughness: 0.9 }))
  for (let i = 0; i < 12; i++) {
    const dash = new THREE.Mesh(dashGeo, dashMat)
    dash.rotation.x = -Math.PI / 2
    dash.position.set(-39 + i * 7, 0.02, ARCH_R + 9)
    group.add(dash)
  }

  /* ---------- 水泥基座（棚下硬化的浅灰台面） ---------- */
  const apronGeo = track(new THREE.BoxGeometry(LEN + 2.4, 0.1, ARCH_R * 2 + 2.4))
  const apronMat = trackM(new THREE.MeshStandardMaterial({ color: 0xb4b8bc, roughness: 0.95 }))
  const apron = new THREE.Mesh(apronGeo, apronMat)
  apron.position.y = 0.05
  apron.receiveShadow = true
  group.add(apron)

  /* ---------- 棚内地面：中央走道 + 4 条苗床 ---------- */
  const walkGeo = track(new THREE.PlaneGeometry(LEN - 1, 1.3))
  const walkMat = trackM(new THREE.MeshStandardMaterial({ color: 0x9aa0a6, roughness: 0.95 }))
  const walk = new THREE.Mesh(walkGeo, walkMat)
  walk.rotation.x = -Math.PI / 2
  walk.position.y = 0.12
  walk.receiveShadow = true
  group.add(walk)

  const bedGeo = track(new THREE.BoxGeometry(LEN - 1.6, 0.16, 1.15))
  const bedMat = trackM(new THREE.MeshStandardMaterial({ color: 0x46331f, roughness: 1 }))
  const BED_Z = [-3, -1.5, 1.5, 3]
  for (const z of BED_Z) {
    const bed = new THREE.Mesh(bedGeo, bedMat)
    bed.position.set(0, 0.18, z)
    bed.castShadow = true
    bed.receiveShadow = true
    group.add(bed)
    /* 滴灌带（每条苗床一根细黑管） */
    const dripGeo = track(new THREE.CylinderGeometry(0.014, 0.014, LEN - 1.8, 5))
    const dripMat = trackM(new THREE.MeshStandardMaterial({ color: 0x1c1c1c, roughness: 0.8 }))
    const drip = new THREE.Mesh(dripGeo, dripMat)
    drip.rotation.z = Math.PI / 2
    drip.position.set(0, 0.28, z + 0.42)
    group.add(drip)
  }

  /* ---------- 拱肋骨架（钢管） ---------- */
  const ribPts: THREE.Vector3[] = []
  for (let s = 0; s <= 24; s++) {
    const t = (s / 24) * Math.PI
    ribPts.push(new THREE.Vector3(0, Math.sin(t) * ARCH_R, -Math.cos(t) * ARCH_R))
  }
  const ribCurve = new THREE.CatmullRomCurve3(ribPts)
  const ribGeo = track(new THREE.TubeGeometry(ribCurve, 32, 0.045, 8, false))
  const steelMat = trackM(new THREE.MeshStandardMaterial({ color: 0xb8c4cc, roughness: 0.35, metalness: 0.85 }))
  for (let r = 0; r < RIB_COUNT; r++) {
    const rib = new THREE.Mesh(ribGeo, steelMat)
    rib.position.x = -LEN / 2 + (r * LEN) / (RIB_COUNT - 1)
    rib.castShadow = true
    group.add(rib)
  }

  /* 纵向檩条（5 根沿弧面均布） */
  const purGeo = track(new THREE.CylinderGeometry(0.035, 0.035, LEN, 6))
  for (const deg of [25, 55, 90, 125, 155]) {
    const t = (deg * Math.PI) / 180
    const pur = new THREE.Mesh(purGeo, steelMat)
    pur.rotation.z = Math.PI / 2
    pur.position.set(0, Math.sin(t) * ARCH_R, -Math.cos(t) * ARCH_R)
    group.add(pur)
  }

  /* ---------- 侧墙立柱（每榀拱位一根，两侧）+ 纵向栏杆 ---------- */
  const postGeo = track(new THREE.CylinderGeometry(0.04, 0.04, 1.35, 6))
  for (let r = 0; r < RIB_COUNT; r++) {
    const x = -LEN / 2 + (r * LEN) / (RIB_COUNT - 1)
    for (const sz of [-ARCH_R + 0.06, ARCH_R - 0.06]) {
      const post = new THREE.Mesh(postGeo, steelMat)
      post.position.set(x, 0.62, sz)
      group.add(post)
    }
  }
  const railGeo = track(new THREE.CylinderGeometry(0.03, 0.03, LEN, 6))
  for (const sz of [-ARCH_R + 0.06, ARCH_R - 0.06]) {
    for (const ry of [0.55, 1.15]) {
      const rail = new THREE.Mesh(railGeo, steelMat)
      rail.rotation.z = Math.PI / 2
      rail.position.set(0, ry, sz)
      group.add(rail)
    }
  }

  /* ---------- 屋脊压条 ---------- */
  const ridgeGeo = track(new THREE.BoxGeometry(LEN, 0.07, 0.18))
  const ridge = new THREE.Mesh(ridgeGeo, steelMat)
  ridge.position.y = ARCH_R + 0.02
  group.add(ridge)

  /* ---------- 屋顶通风窗（交替开向两侧，带摆动动画） ---------- */
  const ventGeo = track(new THREE.BoxGeometry(1.7, 0.025, 1.25))
  const ventMat = trackM(
    new THREE.MeshStandardMaterial({
      color: 0xe6f2ea,
      transparent: true,
      opacity: 0.5,
      roughness: 0.2,
      side: THREE.DoubleSide,
    }),
  )
  /** 通风窗引用（update 中摆动） */
  const vents: { mesh: THREE.Mesh; base: number; phase: number }[] = []
  for (let v = 0; v < 6; v++) {
    const vx = -LEN / 2 + 2.4 + v * 3.4
    const side = v % 2 === 0 ? -1 : 1
    const vent = new THREE.Mesh(ventGeo, ventMat)
    vent.position.set(vx, ARCH_R * 0.86, side * 0.72)
    const base = side * (Math.PI / 5)
    vent.rotation.x = base
    vent.castShadow = false
    group.add(vent)
    vents.push({ mesh: vent, base, phase: vx })
  }

  /* ---------- 侧卷膜（半开状态，两侧） ---------- */
  const curtainGeo = track(new THREE.BoxGeometry(LEN * 0.72, 0.85, 0.02))
  const curtainMat = trackM(
    new THREE.MeshStandardMaterial({
      color: 0xf2f7f4,
      transparent: true,
      opacity: 0.32,
      roughness: 0.3,
      side: THREE.DoubleSide,
    }),
  )
  for (const sz of [-ARCH_R - 0.02, ARCH_R + 0.02]) {
    const curtain = new THREE.Mesh(curtainGeo, curtainMat)
    curtain.position.set(0, 1.06, sz)
    group.add(curtain)
  }

  /* ---------- 透明棚膜 ---------- */
  const coverGeo = track(new THREE.CylinderGeometry(ARCH_R, ARCH_R, LEN, 32, 1, true, 0, Math.PI))
  coverGeo.rotateZ(Math.PI / 2)
  const coverMat = trackM(
    new THREE.MeshPhysicalMaterial({
      color: 0xe6f2ea,
      transparent: true,
      opacity: 0.2,
      roughness: 0.15,
      metalness: 0,
      side: THREE.DoubleSide,
      clearcoat: 0.6,
    }),
  )
  const cover = new THREE.Mesh(coverGeo, coverMat)
  cover.position.y = 0
  group.add(cover)

  /* ---------- 端墙：门 + 风机 + 配电箱 + 空调外机 ---------- */
  const endCapGeo = track(new THREE.CircleGeometry(ARCH_R, 24, 0, Math.PI))
  const endCapMat = trackM(
    new THREE.MeshPhysicalMaterial({
      color: 0xdcebe2,
      transparent: true,
      opacity: 0.14,
      roughness: 0.2,
      side: THREE.DoubleSide,
    }),
  )
  for (const sx of [-LEN / 2, LEN / 2]) {
    const cap = new THREE.Mesh(endCapGeo, endCapMat)
    cap.position.set(sx, 0, 0)
    cap.rotation.y = Math.PI / 2
    group.add(cap)
  }
  /* 门（东端）+ 门框 */
  const doorGeo = track(new THREE.BoxGeometry(0.08, 1.9, 1))
  const doorMat = trackM(new THREE.MeshStandardMaterial({ color: 0x2e3d34, roughness: 0.7 }))
  const door = new THREE.Mesh(doorGeo, doorMat)
  door.position.set(LEN / 2, 0.95, 0)
  group.add(door)
  const frameGeo = track(new THREE.BoxGeometry(0.06, 2.05, 1.2))
  const frameMat = trackM(new THREE.MeshStandardMaterial({ color: 0x9aa8b0, roughness: 0.5, metalness: 0.5 }))
  const frame = new THREE.Mesh(frameGeo, frameMat)
  frame.position.set(LEN / 2 + 0.02, 1.02, 0)
  group.add(frame)
  /* 风机 ×2（西端）+ 旋转扇叶 */
  const fanFrameGeo = track(new THREE.CylinderGeometry(0.42, 0.42, 0.12, 20))
  const fanFrameMat = trackM(new THREE.MeshStandardMaterial({ color: 0x39424a, roughness: 0.6, metalness: 0.4 }))
  const bladeGeo = track(new THREE.BoxGeometry(0.62, 0.09, 0.03))
  const bladeMat = trackM(new THREE.MeshStandardMaterial({ color: 0x9fb2bd, roughness: 0.5, metalness: 0.5 }))
  const fanBlades: THREE.Group[] = []
  for (const fz of [-1.6, 1.6]) {
    const frameFan = new THREE.Mesh(fanFrameGeo, fanFrameMat)
    frameFan.rotation.z = Math.PI / 2
    frameFan.position.set(-LEN / 2, 2.1, fz)
    group.add(frameFan)
    const blades = new THREE.Group()
    for (let b = 0; b < 3; b++) {
      const blade = new THREE.Mesh(bladeGeo, bladeMat)
      blade.rotation.z = (b * Math.PI * 2) / 3
      blades.add(blade)
    }
    blades.position.set(-LEN / 2 - 0.1, 2.1, fz)
    blades.rotation.y = Math.PI / 2
    blades.rotation.order = 'ZYX'
    group.add(blades)
    fanBlades.push(blades)
  }
  /* 配电箱（西端外侧） */
  const boxGeo = track(new THREE.BoxGeometry(0.3, 0.5, 0.36))
  const boxMat = trackM(new THREE.MeshStandardMaterial({ color: 0xdadfe3, roughness: 0.6, metalness: 0.3 }))
  const ebox = new THREE.Mesh(boxGeo, boxMat)
  ebox.position.set(-LEN / 2 - 0.2, 1.5, -2.6)
  group.add(ebox)

  /* ---------- 吊挂补光灯（3 组灯条 + 吊线） ---------- */
  const lightBarGeo = track(new THREE.BoxGeometry(2.4, 0.05, 0.2))
  const lightBarMat = trackM(
    new THREE.MeshStandardMaterial({
      color: 0xfff3c9,
      emissive: 0xffe9a8,
      emissiveIntensity: 0.85,
      roughness: 0.4,
    }),
  )
  const wireGeo = track(new THREE.CylinderGeometry(0.008, 0.008, 1.1, 4))
  const wireMat = trackM(new THREE.MeshStandardMaterial({ color: 0x555b60, roughness: 0.8 }))
  for (const lx of [-LEN / 3, 0, LEN / 3]) {
    const bar = new THREE.Mesh(lightBarGeo, lightBarMat)
    bar.position.set(lx, 2.62, 0)
    group.add(bar)
    for (const wz of [-0.8, 0.8]) {
      const wire = new THREE.Mesh(wireGeo, wireMat)
      wire.position.set(lx, 3.2, wz)
      group.add(wire)
    }
  }

  /* ---------- 作物（实例化：茎秆 + 冠层 + 红果） ---------- */
  const stemGeo = track(new THREE.CylinderGeometry(0.02, 0.025, 0.3, 5))
  const stemMat = trackM(new THREE.MeshStandardMaterial({ color: 0x3e6b2f, roughness: 0.9 }))
  const plantGeo = track(new THREE.IcosahedronGeometry(0.18, 0))
  const plantMat = trackM(
    new THREE.MeshStandardMaterial({
      color: 0x2a6b38,
      roughness: 0.9,
      emissive: 0x0c2f16,
      emissiveIntensity: 0.22,
    }),
  )
  const berryGeo = track(new THREE.SphereGeometry(0.05, 6, 6))
  const berryMat = trackM(new THREE.MeshStandardMaterial({ color: 0xc23b2e, roughness: 0.6 }))
  const ROWS_PER_BED = 2
  const PER_ROW = 15
  const plantCount = BED_Z.length * ROWS_PER_BED * PER_ROW
  const stems = new THREE.InstancedMesh(stemGeo, stemMat, plantCount)
  const plants = new THREE.InstancedMesh(plantGeo, plantMat, plantCount)
  const berries = new THREE.InstancedMesh(berryGeo, berryMat, 42)
  const m4 = new THREE.Matrix4()
  const q = new THREE.Quaternion()
  const pos = new THREE.Vector3()
  const scl = new THREE.Vector3()
  let pIdx = 0
  for (let b = 0; b < BED_Z.length; b++) {
    const bz = BED_Z[b] ?? 0
    for (let row = 0; row < ROWS_PER_BED; row++) {
      const rz = bz + (row === 0 ? -0.28 : 0.28)
      for (let c = 0; c < PER_ROW; c++) {
        const x = -LEN / 2 + 1.2 + (c * (LEN - 2.4)) / (PER_ROW - 1)
        const jitter = ((((b * ROWS_PER_BED + row) * PER_ROW + c) * 7) % 11) / 11 - 0.5
        pos.set(x, 0.46, rz + jitter * 0.12)
        const s = 0.85 + (((((b + 1) * (row + 2) * (c + 3)) * 5) % 9) / 24)
        scl.set(s, s * 1.15, s)
        m4.compose(pos, q, scl)
        plants.setMatrixAt(pIdx, m4)
        /* 茎秆（冠层正下方） */
        pos.set(x, 0.3, rz + jitter * 0.12)
        scl.set(1, 1, 1)
        m4.compose(pos, q, scl)
        stems.setMatrixAt(pIdx, m4)
        /* 稀疏红果 */
        const berrySeed = (b * 31 + row * 17 + c * 7) % 13
        if (berrySeed === 0 && pIdx < plantCount) {
          const bp = new THREE.Vector3(x, 0.56, rz + jitter * 0.12)
          m4.compose(bp, q, new THREE.Vector3(1, 1, 1))
          berries.setMatrixAt((b * ROWS_PER_BED + row) % 42, m4)
        }
        pIdx++
      }
    }
  }
  plants.castShadow = true
  group.add(plants, stems, berries)

  /* ---------- 传感器立杆 + 浮标标签 ---------- */
  const post2Geo = track(new THREE.CylinderGeometry(0.03, 0.03, 1.5, 6))
  const post2Mat = trackM(new THREE.MeshStandardMaterial({ color: 0xe8eef2, roughness: 0.5 }))
  const headGeo = track(new THREE.BoxGeometry(0.16, 0.1, 0.1))
  const headMat = trackM(
    new THREE.MeshStandardMaterial({
      color: 0x35d0ba,
      emissive: 0x35d0ba,
      emissiveIntensity: 0.7,
    }),
  )
  for (const sx of [-LEN / 3, LEN / 3]) {
    for (const sz of [-2.2, 2.2]) {
      const post = new THREE.Mesh(post2Geo, post2Mat)
      post.position.set(sx, 0.85, sz)
      group.add(post)
      const head = new THREE.Mesh(headGeo, headMat)
      head.position.set(sx, 1.65, sz)
      group.add(head)
    }
  }

  /* ---------- 环境设施：水塔 + 周转筐 + 树木 + 路灯 + 围栏 ---------- */
  /* 水塔（西端外侧） */
  const tankGeo = track(new THREE.CylinderGeometry(0.5, 0.5, 1.15, 14))
  const tankMat = trackM(new THREE.MeshStandardMaterial({ color: 0x3f7fbf, roughness: 0.45, metalness: 0.25 }))
  const tank = new THREE.Mesh(tankGeo, tankMat)
  tank.position.set(-LEN / 2 - 2.2, 0.6, 2.6)
  tank.castShadow = true
  group.add(tank)
  const tankLegGeo = track(new THREE.CylinderGeometry(0.05, 0.05, 0.35, 6))
  for (const a of [0, Math.PI / 2, Math.PI, (3 * Math.PI) / 2]) {
    const leg = new THREE.Mesh(tankLegGeo, steelMat)
    leg.position.set(-LEN / 2 - 2.2 + Math.cos(a) * 0.32, 0.17, 2.6 + Math.sin(a) * 0.32)
    group.add(leg)
  }
  /* 周转筐（东端门口） */
  const crateGeo = track(new THREE.BoxGeometry(0.42, 0.26, 0.3))
  const crateMat = trackM(new THREE.MeshStandardMaterial({ color: 0xc98d3c, roughness: 0.85 }))
  const cratePos: [number, number, number][] = [
    [LEN / 2 + 1.2, 0.23, 1.1],
    [LEN / 2 + 1.2, 0.23, 1.6],
    [LEN / 2 + 1.2, 0.49, 1.35],
    [LEN / 2 + 1.75, 0.23, 1.35],
  ]
  for (const [cx, cy, cz] of cratePos) {
    const crate = new THREE.Mesh(crateGeo, crateMat)
    crate.position.set(cx, cy, cz)
    crate.rotation.y = (cx * 13 + cz * 7) % 3
    crate.castShadow = true
    group.add(crate)
  }
  /* 树木（外围一圈 8 棵） */
  const trunkGeo = track(new THREE.CylinderGeometry(0.09, 0.12, 1.1, 6))
  const crownGeoLo = track(new THREE.SphereGeometry(0.62, 8, 7))
  const crownGeoHi = track(new THREE.SphereGeometry(0.42, 8, 7))
  const trunkMat = trackM(new THREE.MeshStandardMaterial({ color: 0x6d4c2c, roughness: 1 }))
  const crownMat = trackM(new THREE.MeshStandardMaterial({ color: 0x39702f, roughness: 1 }))
  const TREE_POS: [number, number, number][] = [
    [-16, -12, 1.1],
    [-6, -13.5, 0.9],
    [5, -12.5, 1.25],
    [15, -13, 1.0],
    [-18, -2, 0.85],
    [18.5, -3, 1.15],
    [-17, 6.5, 1.05],
    [17.5, 7, 0.95],
  ]
  for (const [tx, tz, ts] of TREE_POS) {
    group.add(makeTree(trunkGeo, crownGeoLo, crownGeoHi, trunkMat, crownMat, tx, tz, ts))
  }
  /* 路灯（沿道路 4 盏） */
  const lampPoleGeo = track(new THREE.CylinderGeometry(0.045, 0.06, 3.3, 6))
  const lampArmGeo = track(new THREE.BoxGeometry(0.7, 0.05, 0.05))
  const lampHeadGeo = track(new THREE.BoxGeometry(0.34, 0.07, 0.16))
  const poleMat = trackM(new THREE.MeshStandardMaterial({ color: 0x8b939a, roughness: 0.5, metalness: 0.5 }))
  const headLampMat = trackM(
    new THREE.MeshStandardMaterial({
      color: 0xfff6d8,
      emissive: 0xffedb0,
      emissiveIntensity: 0.6,
      roughness: 0.4,
    }),
  )
  for (const [lx, lz, flip] of [
    [-28, ARCH_R + 12.2, false],
    [-10, ARCH_R + 12.2, false],
    [8, ARCH_R + 12.2, false],
    [26, ARCH_R + 12.2, false],
  ] as [number, number, boolean][]) {
    group.add(makeStreetlight(lampPoleGeo, lampArmGeo, lampHeadGeo, poleMat, headLampMat, lx, lz, flip))
  }
  /* 围栏（棚区周边一圈：立柱实例化 + 双横杆） */
  const fenceW = LEN + 12
  const fenceD = ARCH_R * 2 + 20
  const fpostGeo = track(new THREE.BoxGeometry(0.06, 0.85, 0.06))
  const fpostMat = trackM(new THREE.MeshStandardMaterial({ color: 0xdde2e6, roughness: 0.6 }))
  const frailGeo = track(new THREE.BoxGeometry(1, 0.045, 0.045))
  const frailMat = trackM(new THREE.MeshStandardMaterial({ color: 0xcfd6da, roughness: 0.6 }))
  const hw = fenceW / 2
  const hd = fenceD / 2
  const postsPerSide = 12
  const fpostCount = postsPerSide * 2 + (postsPerSide - 2) * 2
  const fposts = new THREE.InstancedMesh(fpostGeo, fpostMat, fpostCount)
  let fIdx = 0
  for (let i = 0; i < postsPerSide; i++) {
    const t = -hw + (i * fenceW) / (postsPerSide - 1)
    for (const fz of [-hd, hd]) {
      if (fIdx < fpostCount) {
        pos.set(t, 0.42, fz)
        m4.compose(pos, q, scl.set(1, 1, 1))
        fposts.setMatrixAt(fIdx++, m4)
      }
    }
  }
  for (let i = 1; i < postsPerSide - 1; i++) {
    const t = -hd + (i * fenceD) / (postsPerSide - 1)
    for (const fx of [-hw, hw]) {
      if (fIdx < fpostCount) {
        pos.set(fx, 0.42, t)
        m4.compose(pos, q, scl.set(1, 1, 1))
        fposts.setMatrixAt(fIdx++, m4)
      }
    }
  }
  group.add(fposts)
  for (const ry of [0.32, 0.68]) {
    for (const fz of [-hd, hd]) {
      const railX = new THREE.Mesh(frailGeo, frailMat)
      railX.scale.set(fenceW - 0.2, 1, 1)
      railX.position.set(0, ry, fz)
      group.add(railX)
    }
    for (const fx of [-hw, hw]) {
      const railZ = new THREE.Mesh(frailGeo, frailMat)
      railZ.scale.set(fenceD - 0.2, 1, 1)
      railZ.rotation.y = Math.PI / 2
      railZ.position.set(fx, ry, 0)
      group.add(railZ)
    }
  }

  /* ---------- 数据标签（setData 重绘） ---------- */
  let drawName: (t: string) => void
  let drawTemp: (t: string) => void
  let drawHum: (t: string) => void
  let drawSoil: (t: string) => void

  /**
   * 应用数据到标签。
   * @param data 棚数据
   */
  function applyData(data: GreenhouseTwinData): void {
    drawName(data.name)
    drawTemp(`空气温度 ${data.tempText ?? '--'}`)
    drawHum(`空气湿度 ${data.humText ?? '--'}`)
    drawSoil(`基质含水率 ${data.soilMoisture ?? '-'} %`)
  }

  /* 初始占位标签（位置：棚内上空两角 + 中部） */
  drawName = addLabel('温室大棚', '#ffffff', new THREE.Vector3(0, 5.0, 0), 7)
  drawTemp = addLabel('空气温度 --', '#7fe8d8', new THREE.Vector3(-LEN / 3, 2.9, -2.2), 5)
  drawHum = addLabel('空气湿度 --', '#8fd0ff', new THREE.Vector3(LEN / 3, 2.9, 2.2), 5)
  drawSoil = addLabel('基质含水率 --', '#bfe8a8', new THREE.Vector3(0, 3.8, 0), 5.4)

  return {
    group,
    setData(data: GreenhouseTwinData): void {
      applyData(data)
    },
    update(elapsed: number): void {
      for (const f of liveLabels) {
        f.sprite.position.y = f.baseY + 0.08 * Math.sin(elapsed * 1.8 + f.phase)
      }
      for (const blades of fanBlades) {
        blades.rotation.x = elapsed * 3.2
      }
      /* 通风窗缓慢开合呼吸 */
      for (const v of vents) {
        v.mesh.rotation.x = v.base + 0.1 * Math.sin(elapsed * 0.5 + v.phase)
      }
    },
    dispose(): void {
      for (const g of geometries) g.dispose()
      for (const m of materials) m.dispose()
      for (const t of textures) t.dispose()
    },
  }
}

/**
 * 构建露天地块孪生场景（精细化版）：垫高田块 + 地膜苗床 + 小拱棚 +
 * 泵房水塔 + 稻草人 + 防风林 + 围栏 + 土路。
 * @returns 场景句柄
 */
export function createOpenFieldTwin(): GreenhouseTwinContent {
  const group = new THREE.Group()
  const geometries: THREE.BufferGeometry[] = []
  const materials: THREE.Material[] = []
  const textures: THREE.Texture[] = []

  /** 注册并返回几何（便于统一释放） */
  function track<T extends THREE.BufferGeometry>(g: T): T {
    geometries.push(g)
    return g
  }
  /** 注册并返回材质（便于统一释放） */
  function trackM<T extends THREE.Material>(m: T): T {
    materials.push(m)
    return m
  }

  const liveLabels: { sprite: THREE.Sprite; draw: (t: string) => void; baseY: number; phase: number }[] = []

  /**
   * 添加浮动标签。
   * @param text 初始文本
   * @param color 文本色
   * @param pos 位置
   * @param scale 宽度
   * @returns 绘制器
   */
  function addLabel(text: string, color: string, pos: THREE.Vector3, scale: number): (t: string) => void {
    const label = makeLiveLabel(text, color)
    textures.push(label.tex)
    const mat = trackM(new THREE.SpriteMaterial({ map: label.tex, transparent: true, depthWrite: false }))
    const sprite = new THREE.Sprite(mat)
    sprite.scale.set(scale, scale / 4, 1)
    sprite.center.set(0.5, 0)
    sprite.position.copy(pos)
    group.add(sprite)
    liveLabels.push({ sprite, draw: label.draw, baseY: pos.y, phase: pos.x * 0.7 + pos.z })
    return label.draw
  }

  /* ---------- 草地底面（噪点纹理） ---------- */
  const grassTex = makeGrassTexture()
  textures.push(grassTex)
  const groundGeo = track(new THREE.PlaneGeometry(90, 90))
  const groundMat = trackM(new THREE.MeshStandardMaterial({ map: grassTex, roughness: 1 }))
  const ground = new THREE.Mesh(groundGeo, groundMat)
  ground.rotation.x = -Math.PI / 2
  ground.receiveShadow = true
  group.add(ground)

  /* ---------- 土路（南侧进田便道） ---------- */
  const dirtGeo = track(new THREE.PlaneGeometry(90, 3.2))
  const dirtMat = trackM(new THREE.MeshStandardMaterial({ color: 0x8a7a5c, roughness: 1 }))
  const dirt = new THREE.Mesh(dirtGeo, dirtMat)
  dirt.rotation.x = -Math.PI / 2
  dirt.position.set(0, 0.01, FIELD_HALF_W() + 6.5)
  dirt.receiveShadow = true
  group.add(dirt)

  /* ---------- 土壤田块（垫高台面） ---------- */
  const FIELD_LEN = 26
  const FIELD_WID = 17
  const soilGeo = track(new THREE.BoxGeometry(FIELD_LEN, 0.3, FIELD_WID))
  const soilMat = trackM(new THREE.MeshStandardMaterial({ color: 0x5a4630, roughness: 1 }))
  const soil = new THREE.Mesh(soilGeo, soilMat)
  soil.position.y = 0.15
  soil.receiveShadow = true
  soil.castShadow = true
  group.add(soil)

  /* ---------- 苗床 ×6 + 地膜 + 作物垄（实例化） ---------- */
  const bedGeo = track(new THREE.BoxGeometry(FIELD_LEN - 1.6, 0.18, 1.5))
  const bedMat = trackM(new THREE.MeshStandardMaterial({ color: 0x3e2f20, roughness: 1 }))
  const filmGeo = track(new THREE.BoxGeometry(FIELD_LEN - 2.2, 0.02, 1.34))
  const filmMat = trackM(
    new THREE.MeshStandardMaterial({
      color: 0xf0f4f2,
      transparent: true,
      opacity: 0.42,
      roughness: 0.35,
      side: THREE.DoubleSide,
    }),
  )
  const dripGeo = track(new THREE.CylinderGeometry(0.014, 0.014, FIELD_LEN - 1.8, 5))
  const dripMat = trackM(new THREE.MeshStandardMaterial({ color: 0x1c1c1c, roughness: 0.8 }))
  const BED_COUNT = 6
  const BED_STEP = (FIELD_WID - 3) / (BED_COUNT - 1)
  const beds: number[] = []
  for (let b = 0; b < BED_COUNT; b++) {
    const z = -(FIELD_WID - 3) / 2 + b * BED_STEP
    beds.push(z)
    const bed = new THREE.Mesh(bedGeo, bedMat)
    bed.position.set(0, 0.36, z)
    bed.castShadow = true
    bed.receiveShadow = true
    group.add(bed)
    /* 地膜（覆盖苗床顶面，露地覆膜栽培特征） */
    const film = new THREE.Mesh(filmGeo, filmMat)
    film.position.set(0, 0.455, z)
    group.add(film)
    /* 滴灌带 */
    const drip = new THREE.Mesh(dripGeo, dripMat)
    drip.rotation.z = Math.PI / 2
    drip.position.set(0, 0.5, z + 0.56)
    group.add(drip)
  }

  /* ---------- 小拱棚（第 1/3 条苗床：拱架 + 半圆棚膜） ---------- */
  const hoopPts: THREE.Vector3[] = []
  for (let s = 0; s <= 16; s++) {
    const t = (s / 16) * Math.PI
    hoopPts.push(new THREE.Vector3(0, Math.sin(t) * 0.85, -Math.cos(t) * 0.85))
  }
  const hoopCurve = new THREE.CatmullRomCurve3(hoopPts)
  const hoopGeo = track(new THREE.TubeGeometry(hoopCurve, 16, 0.02, 6, false))
  const hoopMat = trackM(new THREE.MeshStandardMaterial({ color: 0x9fb2bd, roughness: 0.5, metalness: 0.4 }))
  const tunnelGeo = track(new THREE.CylinderGeometry(0.85, 0.85, FIELD_LEN - 2.4, 16, 1, true, 0, Math.PI))
  tunnelGeo.rotateZ(Math.PI / 2)
  const tunnelMat = trackM(
    new THREE.MeshPhysicalMaterial({
      color: 0xf2f7f2,
      transparent: true,
      opacity: 0.16,
      roughness: 0.2,
      side: THREE.DoubleSide,
      clearcoat: 0.4,
    }),
  )
  for (const b of [1, 3]) {
    const bz = beds[b] ?? 0
    for (let h = 0; h < 9; h++) {
      const hoop = new THREE.Mesh(hoopGeo, hoopMat)
      hoop.position.set(-FIELD_LEN / 2 + 1.6 + (h * (FIELD_LEN - 3.2)) / 8, 0.45, bz)
      group.add(hoop)
    }
    const tunnel = new THREE.Mesh(tunnelGeo, tunnelMat)
    tunnel.position.set(0, 0.45, bz)
    group.add(tunnel)
  }

  /* ---------- 作物（实例化：茎秆 + 冠层，露地大田株距更密） ---------- */
  const stemGeo = track(new THREE.CylinderGeometry(0.02, 0.026, 0.34, 5))
  const stemMat = trackM(new THREE.MeshStandardMaterial({ color: 0x3e6b2f, roughness: 0.9 }))
  const plantGeo = track(new THREE.IcosahedronGeometry(0.2, 0))
  const plantMat = trackM(
    new THREE.MeshStandardMaterial({
      color: 0x2f7a3c,
      roughness: 0.9,
      emissive: 0x0c2f16,
      emissiveIntensity: 0.18,
    }),
  )
  geometries.push(stemGeo, plantGeo)
  materials.push(stemMat, plantMat)
  const ROWS_PER_BED = 2
  const PER_ROW = 16
  const plantCount = BED_COUNT * ROWS_PER_BED * PER_ROW
  const stems = new THREE.InstancedMesh(stemGeo, stemMat, plantCount)
  const plants = new THREE.InstancedMesh(plantGeo, plantMat, plantCount)
  const m4 = new THREE.Matrix4()
  const q = new THREE.Quaternion()
  const pos = new THREE.Vector3()
  const scl = new THREE.Vector3()
  let pIdx = 0
  for (let b = 0; b < BED_COUNT; b++) {
    const bz = beds[b] ?? 0
    for (let row = 0; row < ROWS_PER_BED; row++) {
      const rz = bz + (row === 0 ? -0.34 : 0.34)
      for (let c = 0; c < PER_ROW; c++) {
        const x = -FIELD_LEN / 2 + 1.3 + (c * (FIELD_LEN - 2.6)) / (PER_ROW - 1)
        const jitter = ((((b * ROWS_PER_BED + row) * PER_ROW + c) * 7) % 11) / 11 - 0.5
        pos.set(x, 0.76, rz + jitter * 0.14)
        const s = 0.85 + (((((b + 1) * (row + 2) * (c + 3)) * 5) % 9) / 22)
        scl.set(s, s * 1.2, s)
        m4.compose(pos, q, scl)
        plants.setMatrixAt(pIdx, m4)
        pos.set(x, 0.52, rz + jitter * 0.14)
        scl.set(1, 1, 1)
        m4.compose(pos, q, scl)
        stems.setMatrixAt(pIdx, m4)
        pIdx++
      }
    }
  }
  plants.castShadow = true
  group.add(plants, stems)

  /* ---------- 泵房 + 水塔（东北角） ---------- */
  const pumpGeo = track(new THREE.BoxGeometry(1.7, 1.25, 1.3))
  const pumpMat = trackM(new THREE.MeshStandardMaterial({ color: 0xe8e4da, roughness: 0.85 }))
  const pump = new THREE.Mesh(pumpGeo, pumpMat)
  pump.position.set(FIELD_LEN / 2 + 2.2, 0.62, -(FIELD_WID / 2) - 2.4)
  pump.castShadow = true
  group.add(pump)
  const roofGeo = track(new THREE.ConeGeometry(1.35, 0.55, 4))
  const roofMat = trackM(new THREE.MeshStandardMaterial({ color: 0x3f6fb5, roughness: 0.55 }))
  const pumpRoof = new THREE.Mesh(roofGeo, roofMat)
  pumpRoof.position.set(FIELD_LEN / 2 + 2.2, 1.5, -(FIELD_WID / 2) - 2.4)
  pumpRoof.rotation.y = Math.PI / 4
  pumpRoof.scale.set(1, 1, 0.62)
  pumpRoof.castShadow = true
  group.add(pumpRoof)
  const tankGeo = track(new THREE.CylinderGeometry(0.45, 0.45, 1.0, 12))
  const tankMat = trackM(new THREE.MeshStandardMaterial({ color: 0x3f7fbf, roughness: 0.45, metalness: 0.25 }))
  const tank = new THREE.Mesh(tankGeo, tankMat)
  tank.position.set(FIELD_LEN / 2 + 2.2, 0.5, -(FIELD_WID / 2) - 4.2)
  tank.castShadow = true
  group.add(tank)

  /* ---------- 稻草人（田中央偏南） ---------- */
  const scare = new THREE.Group()
  const spGeo = track(new THREE.CylinderGeometry(0.03, 0.04, 1.5, 6))
  const spMat = trackM(new THREE.MeshStandardMaterial({ color: 0x8a6a3c, roughness: 1 }))
  const spPost = new THREE.Mesh(spGeo, spMat)
  spPost.position.y = 0.75
  scare.add(spPost)
  const armGeo = track(new THREE.CylinderGeometry(0.025, 0.025, 0.9, 5))
  const arm = new THREE.Mesh(armGeo, spMat)
  arm.rotation.z = Math.PI / 2
  arm.position.y = 1.02
  scare.add(arm)
  const shirtGeo = track(new THREE.BoxGeometry(0.5, 0.42, 0.2))
  const shirtMat = trackM(new THREE.MeshStandardMaterial({ color: 0xc75b3a, roughness: 0.9 }))
  const shirt = new THREE.Mesh(shirtGeo, shirtMat)
  shirt.position.y = 0.88
  scare.add(shirt)
  const scHeadGeo = track(new THREE.SphereGeometry(0.13, 8, 7))
  const scHeadMat = trackM(new THREE.MeshStandardMaterial({ color: 0xd9a066, roughness: 0.9 }))
  const head = new THREE.Mesh(scHeadGeo, scHeadMat)
  head.position.y = 1.24
  scare.add(head)
  const hatGeo = track(new THREE.ConeGeometry(0.2, 0.16, 8))
  const hatMat = trackM(new THREE.MeshStandardMaterial({ color: 0x7a5c34, roughness: 1 }))
  const hat = new THREE.Mesh(hatGeo, hatMat)
  hat.position.y = 1.42
  scare.add(hat)
  scare.position.set(2.5, 0.3, 4.2)
  scare.rotation.y = -0.5
  group.add(scare)

  /* ---------- 灌溉主管（沿田块两侧） ---------- */
  const pipeGeo = track(new THREE.CylinderGeometry(0.045, 0.045, FIELD_LEN, 6))
  const pipeMat = trackM(new THREE.MeshStandardMaterial({ color: 0x2f3d46, roughness: 0.6, metalness: 0.3 }))
  for (const pz of [-(FIELD_WID / 2) - 0.5, FIELD_WID / 2 + 0.5]) {
    const pipe = new THREE.Mesh(pipeGeo, pipeMat)
    pipe.rotation.z = Math.PI / 2
    pipe.position.set(0, 0.12, pz)
    group.add(pipe)
  }

  /* ---------- 传感器立杆 ×4 ---------- */
  const post2Geo = track(new THREE.CylinderGeometry(0.03, 0.03, 1.6, 6))
  const post2Mat = trackM(new THREE.MeshStandardMaterial({ color: 0xe8eef2, roughness: 0.5 }))
  const headGeo = track(new THREE.BoxGeometry(0.16, 0.1, 0.1))
  const headMat = trackM(
    new THREE.MeshStandardMaterial({
      color: 0x35d0ba,
      emissive: 0x35d0ba,
      emissiveIntensity: 0.7,
    }),
  )
  for (const sx of [-FIELD_LEN / 3, FIELD_LEN / 3]) {
    for (const sz of [-3, 3]) {
      const post = new THREE.Mesh(post2Geo, post2Mat)
      post.position.set(sx, 1.1, sz)
      group.add(post)
      const head = new THREE.Mesh(headGeo, headMat)
      head.position.set(sx, 1.95, sz)
      group.add(head)
    }
  }

  /* ---------- 防风林（北侧一排 6 棵）+ 南侧 3 棵 ---------- */
  const trunkGeo = track(new THREE.CylinderGeometry(0.09, 0.12, 1.1, 6))
  const crownGeoLo = track(new THREE.SphereGeometry(0.62, 8, 7))
  const crownGeoHi = track(new THREE.SphereGeometry(0.42, 8, 7))
  const trunkMat = trackM(new THREE.MeshStandardMaterial({ color: 0x6d4c2c, roughness: 1 }))
  const crownMat = trackM(new THREE.MeshStandardMaterial({ color: 0x39702f, roughness: 1 }))
  for (let i = 0; i < 6; i++) {
    group.add(
      makeTree(
        trunkGeo,
        crownGeoLo,
        crownGeoHi,
        trunkMat,
        crownMat,
        -FIELD_LEN / 2 + 2 + i * 4.4,
        -(FIELD_WID / 2) - 5.5,
        1.15 + (i % 3) * 0.18,
      ),
    )
  }
  for (const [tx, tz] of [
    [-FIELD_LEN / 2 - 3.5, FIELD_WID / 2 + 3],
    [0, FIELD_WID / 2 + 3.5],
    [FIELD_LEN / 2 + 3.5, FIELD_WID / 2 + 3],
  ] as [number, number][]) {
    group.add(makeTree(trunkGeo, crownGeoLo, crownGeoHi, trunkMat, crownMat, tx, tz, 1.0))
  }

  /* ---------- 围栏（田区四周：立柱实例化 + 双横杆） ---------- */
  const fenceW = FIELD_LEN + 9
  const fenceD = FIELD_WID + 12
  const fpostGeo = track(new THREE.BoxGeometry(0.06, 0.85, 0.06))
  const fpostMat = trackM(new THREE.MeshStandardMaterial({ color: 0xdde2e6, roughness: 0.6 }))
  const frailGeo = track(new THREE.BoxGeometry(1, 0.045, 0.045))
  const frailMat = trackM(new THREE.MeshStandardMaterial({ color: 0xcfd6da, roughness: 0.6 }))
  const hw = fenceW / 2
  const hd = fenceD / 2
  const postsPerSide = 11
  const fpostCount = postsPerSide * 2 + (postsPerSide - 2) * 2
  const fposts = new THREE.InstancedMesh(fpostGeo, fpostMat, fpostCount)
  let fIdx = 0
  for (let i = 0; i < postsPerSide; i++) {
    const t = -hw + (i * fenceW) / (postsPerSide - 1)
    for (const fz of [-hd, hd]) {
      if (fIdx < fpostCount) {
        pos.set(t, 0.42, fz)
        m4.compose(pos, q, scl.set(1, 1, 1))
        fposts.setMatrixAt(fIdx++, m4)
      }
    }
  }
  for (let i = 1; i < postsPerSide - 1; i++) {
    const t = -hd + (i * fenceD) / (postsPerSide - 1)
    for (const fx of [-hw, hw]) {
      if (fIdx < fpostCount) {
        pos.set(fx, 0.42, t)
        m4.compose(pos, q, scl.set(1, 1, 1))
        fposts.setMatrixAt(fIdx++, m4)
      }
    }
  }
  group.add(fposts)
  for (const ry of [0.32, 0.68]) {
    for (const fz of [-hd, hd]) {
      const railX = new THREE.Mesh(frailGeo, frailMat)
      railX.scale.set(fenceW - 0.2, 1, 1)
      railX.position.set(0, ry, fz)
      group.add(railX)
    }
    for (const fx of [-hw, hw]) {
      const railZ = new THREE.Mesh(frailGeo, frailMat)
      railZ.scale.set(fenceD - 0.2, 1, 1)
      railZ.rotation.y = Math.PI / 2
      railZ.position.set(fx, ry, 0)
      group.add(railZ)
    }
  }

  /* ---------- 数据标签 ---------- */
  let drawName: (t: string) => void
  let drawTemp: (t: string) => void
  let drawHum: (t: string) => void
  let drawSoil: (t: string) => void

  /**
   * 应用数据到标签。
   * @param data 地块数据
   */
  function applyData(data: GreenhouseTwinData): void {
    drawName(data.name)
    drawTemp(`空气温度 ${data.tempText ?? '--'}`)
    drawHum(`空气湿度 ${data.humText ?? '--'}`)
    drawSoil(`土壤墒情 ${data.soilMoisture ?? '-'} %`)
  }

  drawName = addLabel('露天地块', '#ffffff', new THREE.Vector3(0, 4.6, 0), 7)
  drawTemp = addLabel('空气温度 --', '#7fe8d8', new THREE.Vector3(-FIELD_LEN / 3, 3.1, -3), 5)
  drawHum = addLabel('空气湿度 --', '#8fd0ff', new THREE.Vector3(FIELD_LEN / 3, 3.1, 3), 5)
  drawSoil = addLabel('土壤墒情 --', '#bfe8a8', new THREE.Vector3(0, 3.9, 0), 5.4)

  return {
    group,
    setData(data: GreenhouseTwinData): void {
      applyData(data)
    },
    update(elapsed: number): void {
      for (const f of liveLabels) {
        f.sprite.position.y = f.baseY + 0.08 * Math.sin(elapsed * 1.8 + f.phase)
      }
    },
    dispose(): void {
      for (const g of geometries) g.dispose()
      for (const m of materials) m.dispose()
      for (const t of textures) t.dispose()
    },
  }
}

/**
 * 露天地块半宽（土路定位用）。
 * @returns 半宽
 */
function FIELD_HALF_W(): number {
  return 17 / 2
}

/**
 * 按类型构建孪生场景（大棚 / 露天地块）。
 * @param kind 场景类型
 * @returns 场景句柄
 */
export function createTwinScene(kind: TwinSceneKind): GreenhouseTwinContent {
  return kind === 'open_field' ? createOpenFieldTwin() : createGreenhouseTwin()
}
