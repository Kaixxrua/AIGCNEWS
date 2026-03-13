declare module 'vanta/dist/vanta.fog.min' {
  interface VantaFogOptions {
    el: HTMLElement
    THREE: unknown
    mouseControls?: boolean
    touchControls?: boolean
    gyroControls?: boolean
    minHeight?: number
    minWidth?: number
    highlightColor?: number
    midtoneColor?: number
    lowlightColor?: number
    baseColor?: number
    blurFactor?: number
    speed?: number
    zoom?: number
  }

  interface VantaEffect {
    destroy: () => void
    setOptions: (options: Partial<VantaFogOptions>) => void
    resize: () => void
  }

  function FOG(options: VantaFogOptions): VantaEffect
  export default FOG
}
