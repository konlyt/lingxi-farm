/**
 * 文件说明：三维园区沙盘引擎组合式函数。
 * 职责：renderer/相机/轨道控制/泛光后处理/渲染循环（锁 30fps）/可见性暂停/
 * 点击拾取与镜头聚焦/资源释放。场景内容见 @/three/scene/park。
 */
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js'
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js'
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js'
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js'
import { createParkScene } from '@/three/scene/park'
import type { ParkPlotInput } from '@/three/scene/park'

/** 渲染帧间隔（约 30fps） */
const FRAME_INTERVAL = 1000 / 30

/** 用户操作后恢复自动巡游的静默时长（毫秒） */
const IDLE_RESUME_MS = 30000

/** 总览默认机位 */
const OVERVIEW_POS = new THREE.Vector3(0, 26, 46)

/** 聚焦地块时的目标距离 */
const FOCUS_DIST = 17

/**
 * 园区沙盘引擎句柄。
 */
export interface ParkSceneHandle {
  /**
   * 初始化并启动渲染（WebGL 不可用时返回 false，调用方应回退 2D）。
   * @param canvas 画布元素
   * @param container 尺寸参照容器
   * @returns 是否初始化成功
   */
  init(canvas: HTMLCanvasElement, container: HTMLElement): boolean
  /** 全量同步地块数据（增量更新状态） */
  setPlots(plots: ParkPlotInput[]): void
  /** 注册地块点击回调 */
  onSelect(cb: (plotId: number) => void): void
  /** 镜头平滑聚焦到地块并展示三维详情层（不影响用户后续拖拽） */
  focusPlot(plotId: number): void
  /** 退出聚焦：关闭详情层，镜头回到总览机位 */
  exitFocus(): void
  /** 释放全部资源并停止渲染 */
  dispose(): void
}

/**
 * 创建园区沙盘引擎。
 * @returns 引擎句柄
 */
export function useParkScene(): ParkSceneHandle {
  let renderer: THREE.WebGLRenderer | null = null
  let composer: EffectComposer | null = null
  let camera: THREE.PerspectiveCamera | null = null
  let controls: OrbitControls | null = null
  let content: ReturnType<typeof createParkScene> | null = null
  let container: HTMLElement | null = null
  let resizeObserver: ResizeObserver | null = null
  let raycaster: THREE.Raycaster | null = null
  let selectCb: ((plotId: number) => void) | null = null
  let focusTarget: THREE.Vector3 | null = null
  /** 相机推近目标位置（缓动用） */
  let dollyPos: THREE.Vector3 | null = null
  let lastFrame = 0
  let idleTimer: number | undefined
  let canvasEl: HTMLCanvasElement | null = null
  let disposed = false

  /** 指针按下位置（区分拖拽与点击） */
  let downPos = { x: 0, y: 0, t: 0 }

  /**
   * 重置自动巡游静默计时。
   */
  function scheduleAutoRotate(): void {
    if (!controls) return
    controls.autoRotate = false
    if (idleTimer !== undefined) window.clearTimeout(idleTimer)
    idleTimer = window.setTimeout(() => {
      if (controls && !disposed) controls.autoRotate = true
    }, IDLE_RESUME_MS)
  }

  /**
   * 容器尺寸变化时同步相机与渲染尺寸。
   */
  function handleResize(): void {
    if (!renderer || !camera || !composer || !container) return
    const w = container.clientWidth
    const h = container.clientHeight
    if (w === 0 || h === 0) return
    camera.aspect = w / h
    camera.updateProjectionMatrix()
    renderer.setSize(w, h, false)
    composer.setSize(w, h)
  }

  /**
   * 页面可见性变化：隐藏时暂停渲染循环，恢复时重启。
   */
  function handleVisibility(): void {
    if (!renderer) return
    if (document.hidden) {
      renderer.setAnimationLoop(null)
    } else {
      lastFrame = 0
      renderer.setAnimationLoop(frame)
    }
  }

  /**
   * 渲染循环（锁帧）。
   * @param now 高精度时间戳（毫秒）
   */
  function frame(now: number): void {
    if (!renderer || !composer || !controls || !content) return
    if (now - lastFrame < FRAME_INTERVAL) return
    lastFrame = now
    const elapsed = now / 1000
    // 镜头聚焦缓动
    if (focusTarget) {
      controls.target.lerp(focusTarget, 0.08)
      if (controls.target.distanceToSquared(focusTarget) < 0.01) focusTarget = null
    }
    // 相机推近缓动
    if (dollyPos && camera) {
      camera.position.lerp(dollyPos, 0.06)
      if (camera.position.distanceToSquared(dollyPos) < 0.05) dollyPos = null
    }
    controls.update()
    content.update(elapsed)
    composer.render()
  }

  /**
   * 指针按下记录起点。
   * @param ev 指针事件
   */
  function onPointerDown(ev: PointerEvent): void {
    downPos = { x: ev.clientX, y: ev.clientY, t: Date.now() }
  }

  /**
   * 指针抬起：位移与时长都在阈值内视为点击，做地块拾取。
   * @param ev 指针事件
   */
  function onPointerUp(ev: PointerEvent): void {
    if (!renderer || !camera || !raycaster || !content || !selectCb || !canvasEl) return
    const dx = ev.clientX - downPos.x
    const dy = ev.clientY - downPos.y
    if (Math.hypot(dx, dy) > 6 || Date.now() - downPos.t > 400) return
    const rect = canvasEl.getBoundingClientRect()
    const ndc = new THREE.Vector2(
      ((ev.clientX - rect.left) / rect.width) * 2 - 1,
      -((ev.clientY - rect.top) / rect.height) * 2 + 1,
    )
    raycaster.setFromCamera(ndc, camera)
    const hits = raycaster.intersectObjects(content.pickables(), false)
    const plotId = hits[0]?.object.userData.plotId
    if (typeof plotId === 'number') selectCb(plotId)
  }

  return {
    init(canvas, host) {
      if (disposed) return false
      try {
        renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' })
      } catch {
        return false
      }
      canvasEl = canvas
      container = host
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75))
      renderer.shadowMap.enabled = true
      renderer.shadowMap.type = THREE.PCFSoftShadowMap
      renderer.toneMapping = THREE.ACESFilmicToneMapping
      renderer.toneMappingExposure = 1.05

      const scene = new THREE.Scene()
      /* 夜空：竖向渐变（深空 → 地平线微亮）+ 星点 */
      const skyCanvas = document.createElement('canvas')
      skyCanvas.width = 512
      skyCanvas.height = 256
      const sctx = skyCanvas.getContext('2d')
      if (sctx) {
        const grad = sctx.createLinearGradient(0, 0, 0, 256)
        grad.addColorStop(0, '#020817')
        grad.addColorStop(0.6, '#0a1e3a')
        grad.addColorStop(1, '#12304f')
        sctx.fillStyle = grad
        sctx.fillRect(0, 0, 512, 256)
        for (let i = 0; i < 170; i++) {
          const x = Math.random() * 512
          const y = Math.random() * 160
          const a = 0.25 + Math.random() * 0.65
          sctx.fillStyle = `rgba(214, 235, 255, ${a})`
          sctx.fillRect(x, y, Math.random() > 0.85 ? 2 : 1, Math.random() > 0.85 ? 2 : 1)
        }
      }
      const skyTex = new THREE.CanvasTexture(skyCanvas)
      skyTex.colorSpace = THREE.SRGBColorSpace
      scene.background = skyTex
      scene.fog = new THREE.FogExp2(0x081222, 0.0042)

      camera = new THREE.PerspectiveCamera(50, 1, 0.1, 500)
      camera.position.set(0, 26, 46)

      /* 灯光：夜幕科技风，冷色天光 + 月光阴影 + 园区中心青色补光 */
      const hemi = new THREE.HemisphereLight(0x3d6ea8, 0x0a1420, 0.6)
      const dir = new THREE.DirectionalLight(0xa8c8e8, 0.85)
      dir.position.set(40, 60, 25)
      dir.castShadow = true
      dir.shadow.mapSize.set(2048, 2048)
      dir.shadow.camera.left = -70
      dir.shadow.camera.right = 70
      dir.shadow.camera.top = 70
      dir.shadow.camera.bottom = -70
      dir.shadow.camera.far = 200
      dir.shadow.bias = -0.0004
      const glow = new THREE.PointLight(0x35d0ba, 320, 0, 2)
      glow.position.set(0, 20, 0)
      scene.add(hemi, dir, glow)

      /* 场景内容 */
      content = createParkScene()
      scene.add(content.group)

      /* 轨道控制：阻尼 + 自动巡游 */
      controls = new OrbitControls(camera, canvas)
      controls.enableDamping = true
      controls.dampingFactor = 0.08
      controls.autoRotate = true
      controls.autoRotateSpeed = 0.6
      controls.minDistance = 16
      controls.maxDistance = 95
      controls.maxPolarAngle = 1.32
      controls.enablePan = false
      controls.addEventListener('start', scheduleAutoRotate)

      /* 后处理：科技夜景主打泛光（数据发光元素） */
      composer = new EffectComposer(renderer)
      composer.addPass(new RenderPass(scene, camera))
      const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.7, 0.45, 0.45)
      composer.addPass(bloom)
      composer.addPass(new OutputPass())

      /* 交互 */
      raycaster = new THREE.Raycaster()
      canvas.addEventListener('pointerdown', onPointerDown)
      canvas.addEventListener('pointerup', onPointerUp)

      /* 尺寸与可见性 */
      resizeObserver = new ResizeObserver(handleResize)
      resizeObserver.observe(host)
      handleResize()
      document.addEventListener('visibilitychange', handleVisibility)
      renderer.setAnimationLoop(frame)
      return true
    },
    setPlots(plots) {
      content?.setPlots(plots)
    },
    onSelect(cb) {
      selectCb = cb
    },
    focusPlot(plotId) {
      const center = content?.plotCenter(plotId)
      if (!center || !camera) return
      content?.showDetail(plotId)
      focusTarget = center.clone()
      // 保持当前方位角推近，并抬高视角避免贴地
      const dir = camera.position.clone().sub(center)
      dir.y = Math.max(dir.y, dir.length() * 0.5)
      dir.normalize()
      dollyPos = center.clone().add(dir.multiplyScalar(FOCUS_DIST))
      scheduleAutoRotate()
    },
    exitFocus() {
      content?.showDetail(null)
      focusTarget = new THREE.Vector3(0, 0, 0)
      dollyPos = OVERVIEW_POS.clone()
      scheduleAutoRotate()
    },
    dispose() {
      disposed = true
      if (idleTimer !== undefined) window.clearTimeout(idleTimer)
      document.removeEventListener('visibilitychange', handleVisibility)
      resizeObserver?.disconnect()
      if (canvasEl) {
        canvasEl.removeEventListener('pointerdown', onPointerDown)
        canvasEl.removeEventListener('pointerup', onPointerUp)
      }
      controls?.dispose()
      content?.dispose()
      composer?.dispose()
      renderer?.dispose()
      renderer = null
      composer = null
      camera = null
      controls = null
      content = null
      raycaster = null
    },
  }
}
