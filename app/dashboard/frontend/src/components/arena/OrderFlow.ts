import { Container, Graphics } from 'pixi.js'

interface FlowParticle {
  gfx: Graphics
  sx: number
  sy: number
  tx: number
  ty: number
  progress: number
  speed: number
  color: number
}

const BUY_COLOR = 0x26a69a
const SELL_COLOR = 0xef5350

export class OrderFlowManager {
  private container: Container
  private particles: FlowParticle[] = []
  private centerX = 0
  private centerY = 0

  constructor(parent: Container) {
    this.container = new Container()
    parent.addChild(this.container)
  }

  setCenter(x: number, y: number) {
    this.centerX = x
    this.centerY = y
  }

  emit(fromX: number, fromY: number, action: 'buy' | 'sell', quantity: number) {
    const count = Math.min(Math.max(1, Math.floor(quantity / 10)), 5)
    const color = action === 'buy' ? BUY_COLOR : SELL_COLOR

    for (let i = 0; i < count; i++) {
      const gfx = new Graphics()
      gfx.circle(0, 0, 2 + Math.random() * 2)
      gfx.fill({ color, alpha: 0.8 })
      gfx.position.set(fromX, fromY)
      this.container.addChild(gfx)

      this.particles.push({
        gfx,
        sx: fromX + (Math.random() - 0.5) * 10,
        sy: fromY + (Math.random() - 0.5) * 10,
        tx: this.centerX + (Math.random() - 0.5) * 20,
        ty: this.centerY + (Math.random() - 0.5) * 20,
        progress: -(i * 0.08),
        speed: 0.015 + Math.random() * 0.01,
        color,
      })
    }
  }

  emitTradeExplosion(price: number) {
    const burstCount = 8
    for (let i = 0; i < burstCount; i++) {
      const angle = (i / burstCount) * Math.PI * 2
      const radius = 15 + Math.random() * 10
      const gfx = new Graphics()
      gfx.circle(0, 0, 1.5)
      gfx.fill({ color: 0xfeca57, alpha: 0.9 })
      gfx.position.set(this.centerX, this.centerY)
      this.container.addChild(gfx)

      this.particles.push({
        gfx,
        sx: this.centerX,
        sy: this.centerY,
        tx: this.centerX + Math.cos(angle) * radius,
        ty: this.centerY + Math.sin(angle) * radius,
        progress: 0,
        speed: 0.04 + Math.random() * 0.02,
        color: 0xfeca57,
      })
    }
  }

  tick() {
    const toRemove: number[] = []

    for (let i = 0; i < this.particles.length; i++) {
      const p = this.particles[i]
      p.progress += p.speed

      if (p.progress < 0) {
        p.gfx.alpha = 0
        continue
      }

      const t = Math.min(p.progress, 1)
      const ease = t * t * (3 - 2 * t)
      p.gfx.position.set(
        p.sx + (p.tx - p.sx) * ease,
        p.sy + (p.ty - p.sy) * ease,
      )
      p.gfx.alpha = t < 0.8 ? 0.8 : (1 - t) * 4

      if (t >= 1) {
        toRemove.push(i)
      }
    }

    for (let i = toRemove.length - 1; i >= 0; i--) {
      const idx = toRemove[i]
      this.container.removeChild(this.particles[idx].gfx)
      this.particles[idx].gfx.destroy()
      this.particles.splice(idx, 1)
    }
  }

  destroy() {
    for (const p of this.particles) {
      p.gfx.destroy()
    }
    this.particles.length = 0
    this.container.destroy({ children: true })
  }
}
