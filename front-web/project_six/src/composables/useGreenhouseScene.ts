/**
 * 文件说明：单棚数字孪生引擎组合式函数。
 * 自由轨道相机（旋转/平移/缩放）、昼夜时间轴光照、自主巡检（自动环绕）、
 * 资源释放。场景内容见 @/three/scene/greenhouse。
 */
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { createTwinScene } from '@/three/scene/greenhouse'
import type { GreenhouseTwinData, GreenhouseTwinContent, TwinSceneKind } from '@/three/scene/greenhouse'

/** 渲染帧间隔（约 30fps） */
const FRAME_INTERVAL = 1000 / 30

/** 单棚孪生引擎句柄 */
export interface GreenhouseSceneHandle {
  /**
   * 初始化渲染循环（失败返回 false）。
   * @param canvas 画布
   * @param container 尺寸参照
   */
  init(canvas: HTMLCanvasElement, container: HTMLElement): boolean
  /** 同步棚体数据标签 */
  setData(data: GreenhouseTwinData): void
  /**
   * 切换孪生主体（大棚 ↔ 露天地块），重建场景内容。
   * @param kind 场景类型
   */
  setScene(kind: TwinSceneKind): void
  /**
   * 时间轴联动（0-24 小时）：调整太阳角度/光色/天色。
   * @param hour 小时
   */
  setTimeOfDay(hour: number): void
  /** 自主巡检（自动环绕）开关 */
  setAutoRotate(on: boolean): void
  /**
   * 停止渲染并释放场景资源（可再次 init 复用，用于视图临时切换）。
   */
  stop(): void
  /** 释放资源（终态，dispose 后不可再 init） */
  dispose(): void
}

/** 昼夜关键色 */
const SKY_NIGHT = new THREE.Color(0x0a1428)
const SKY_DUSK = new THREE.Color(0xc97a4e)
const SKY_DAY = new THREE.Color(0x87b5e0)

/**
 * 创建单棚孪生引擎。
 * @returns 引擎句柄
 */
export function useGreenhouseScene(): GreenhouseSceneHandle {
  let renderer: THREE.WebGLRenderer | null = null
  let camera: THREE.PerspectiveCamera | null = null
  let controls: OrbitControls | null = null
  let content: GreenhouseTwinContent | null = null
  let container: HTMLElement | null = null
  let resizeObserver: ResizeObserver | null = null
  let dirLight: THREE.DirectionalLight | null = null
  let hemiLight: THREE.HemisphereLight | null = null
  let lastFrame = 0
  let disposed = false

  /**
   * 容器尺寸变化时同步相机与渲染尺寸。
   */
  function handleResize(): void {
    if (!renderer || !camera || !container) return
    const w = container.clientWidth
    const h = container.clientHeight
    if (w === 0 || h === 0) return
    camera.aspect = w / h
    camera.updateProjectionMatrix()
    renderer.setSize(w, h, false)
  }

  /**
   * 渲染循环（锁帧）。
   * @param now 时间戳
   */
  function frame(now: number): void {
    if (!renderer || !content || !controls || !camera || !sceneRef) return
    if (now - lastFrame < FRAME_INTERVAL) return
    lastFrame = now
    controls.update()
    content.update(now / 1000)
    renderer.render(sceneRef, camera)
  }

  /** 场景引用（frame 内渲染用） */
  let sceneRef: THREE.Scene | null = null

  return {
    init(canvas, host) {
      if (disposed) return false
      try {
        renderer = new THREE.WebGLRenderer({ canvas, antialias: true })
      } catch {
        return false
      }
      container = host
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
      renderer.shadowMap.enabled = true
      renderer.shadowMap.type = THREE.PCFSoftShadowMap
      renderer.toneMapping = THREE.ACESFilmicToneMapping
      renderer.toneMappingExposure = 1.0

      const scene = new THREE.Scene()
      sceneRef = scene
      scene.background = SKY_DAY.clone()
      scene.fog = new THREE.Fog(0xdfe9f0, 70, 180)

      camera = new THREE.PerspectiveCamera(50, 1, 0.1, 400)
      camera.position.set(13, 9, 15)

      hemiLight = new THREE.HemisphereLight(0xcfe5ff, 0x51703f, 0.8)
      dirLight = new THREE.DirectionalLight(0xfff2d9, 1.6)
      dirLight.position.set(24, 34, 16)
      dirLight.castShadow = true
      dirLight.shadow.mapSize.set(2048, 2048)
      dirLight.shadow.camera.left = -34
      dirLight.shadow.camera.right = 34
      dirLight.shadow.camera.top = 34
      dirLight.shadow.camera.bottom = -34
      dirLight.shadow.camera.far = 140
      dirLight.shadow.bias = -0.0004
      scene.add(hemiLight, dirLight)

      content = createTwinScene('greenhouse')
      scene.add(content.group)

      controls = new OrbitControls(camera, canvas)
      controls.target.set(0, 1.8, 0)
      controls.enableDamping = true
      controls.dampingFactor = 0.08
      controls.enablePan = true
      controls.screenSpacePanning = false
      controls.minDistance = 4
      controls.maxDistance = 70
      controls.maxPolarAngle = 1.52
      controls.autoRotateSpeed = 0.8

      resizeObserver = new ResizeObserver(handleResize)
      resizeObserver.observe(host)
      handleResize()
      renderer.setAnimationLoop(frame)
      return true
    },
    setData(data) {
      content?.setData(data)
    },
    setScene(kind) {
      if (!sceneRef || !content) return
      sceneRef.remove(content.group)
      content.dispose()
      content = createTwinScene(kind)
      sceneRef.add(content.group)
      /* 切换主体后回到默认观察位 */
      if (camera && controls) {
        camera.position.set(13, 9, 15)
        controls.target.set(0, 1.8, 0)
        controls.update()
      }
    },
    setTimeOfDay(hour) {
      if (!dirLight || !hemiLight || !sceneRef) return
      const rad = ((hour - 6) / 12) * Math.PI
      const dayFactor = Math.max(0, Math.sin(rad))
      dirLight.position.set(Math.cos(rad) * 40, Math.max(Math.sin(rad), 0.05) * 45 + 3, 18)
      dirLight.intensity = 0.12 + 1.55 * dayFactor
      hemiLight.intensity = 0.28 + 0.55 * dayFactor
      /* 天色：夜 → 晨昏 → 昼 三段插值 */
      const sky = sceneRef.background as THREE.Color
      if (dayFactor > 0.35) {
        sky.copy(SKY_DUSK).lerp(SKY_DAY, Math.min((dayFactor - 0.35) / 0.5, 1))
      } else {
        sky.copy(SKY_NIGHT).lerp(SKY_DUSK, Math.min(dayFactor / 0.35, 1))
      }
      const fog = sceneRef.fog
      if (fog instanceof THREE.Fog) {
        fog.color.copy(sky).lerp(new THREE.Color(0xffffff), 0.25)
      }
    },
    setAutoRotate(on) {
      if (controls) controls.autoRotate = on
    },
    stop() {
      resizeObserver?.disconnect()
      controls?.dispose()
      content?.dispose()
      renderer?.dispose()
      renderer = null
      camera = null
      controls = null
      content = null
      sceneRef = null
      dirLight = null
      hemiLight = null
    },
    dispose() {
      disposed = true
      stop()
    },
  }
}
