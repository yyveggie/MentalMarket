import { Container, Graphics, Text, TextStyle } from 'pixi.js'
import type { AgentVisual } from '@/types/market'

const TOM_COLORS: Record<number, number> = {
  0: 0x7a7d85,
  1: 0x5ea4b8,
  2: 0x9b7ec8,
}

const TOM_GLOW_COLORS: Record<number, number> = {
  0: 0x7a7d85,
  1: 0x5ea4b8,
  2: 0x9b7ec8,
}

const EMOTION_MAP: Record<string, string> = {
  neutral: '😐',
  happy: '😊',
  worried: '😰',
  thinking: '🤔',
  scheming: '😈',
}

const AVATAR_RADIUS = 18
const GLOW_RADIUS = 24

export class AgentSprite extends Container {
  readonly agentId: number

  private outerGlow: Graphics
  private ring: Graphics
  private emojiText: Text
  private idLabel: Text
  private actionLabel: Text
  private pulsePhase = 0
  private actionFadeAlpha = 0
  private actionFadeY = 0
  private _visual: AgentVisual
  private _hovered = false

  constructor(visual: AgentVisual) {
    super()
    this.agentId = visual.id
    this._visual = visual
    this.eventMode = 'static'
    this.cursor = 'pointer'
    this.hitArea = { contains: (x: number, y: number) => x * x + y * y <= (AVATAR_RADIUS + 6) ** 2 }

    const tomColor = TOM_COLORS[visual.tomLevel] ?? 0x7f8fa6

    this.outerGlow = new Graphics()
    this.addChild(this.outerGlow)

    this.ring = new Graphics()
    this.drawRing(tomColor, 1.0)
    this.addChild(this.ring)

    const emojiStyle = new TextStyle({
      fontSize: 18,
      align: 'center',
    })
    this.emojiText = new Text({ text: EMOTION_MAP[visual.emotion] ?? '😐', style: emojiStyle })
    this.emojiText.anchor.set(0.5, 0.5)
    this.emojiText.position.set(0, -1)
    this.addChild(this.emojiText)

    const idStyle = new TextStyle({
      fontSize: 8,
      fontWeight: 'bold',
      fontFamily: 'monospace',
      fill: tomColor,
      align: 'center',
    })
    this.idLabel = new Text({ text: `A${visual.id}`, style: idStyle })
    this.idLabel.anchor.set(0.5, 0)
    this.idLabel.position.set(0, AVATAR_RADIUS + 3)
    this.addChild(this.idLabel)

    const actionStyle = new TextStyle({
      fontSize: 10,
      fontWeight: 'bold',
      fontFamily: 'monospace',
      fill: 0xffffff,
      align: 'center',
    })
    this.actionLabel = new Text({ text: '', style: actionStyle })
    this.actionLabel.anchor.set(0.5, 1)
    this.actionLabel.position.set(0, -(AVATAR_RADIUS + 8))
    this.actionLabel.alpha = 0
    this.addChild(this.actionLabel)

    this.on('pointerenter', () => { this._hovered = true })
    this.on('pointerleave', () => { this._hovered = false })
  }

  private drawRing(color: number, alpha: number) {
    this.ring.clear()
    this.ring.circle(0, 0, AVATAR_RADIUS)
    this.ring.fill({ color: 0x0e1520, alpha: 0.85 })
    this.ring.circle(0, 0, AVATAR_RADIUS)
    this.ring.stroke({ color, width: 2, alpha })
  }

  private drawGlow(color: number, alpha: number) {
    this.outerGlow.clear()
    if (alpha <= 0.01) return
    this.outerGlow.circle(0, 0, GLOW_RADIUS)
    this.outerGlow.fill({ color, alpha: alpha * 0.15 })
    this.outerGlow.circle(0, 0, GLOW_RADIUS + 4)
    this.outerGlow.fill({ color, alpha: alpha * 0.05 })
  }

  update(visual: AgentVisual) {
    this._visual = visual
    const tomColor = TOM_COLORS[visual.tomLevel] ?? 0x7f8fa6
    const glowColor = TOM_GLOW_COLORS[visual.tomLevel] ?? 0x7f8fa6

    this.emojiText.text = EMOTION_MAP[visual.emotion] ?? '😐'
    this.idLabel.style.fill = tomColor

    if (visual.phase === 'thinking') {
      this.pulsePhase += 0.06
      const pulse = 0.5 + Math.sin(this.pulsePhase) * 0.5
      this.drawRing(tomColor, 0.5 + pulse * 0.5)
      this.drawGlow(glowColor, pulse)
      this.scale.set(1 + Math.sin(this.pulsePhase * 0.5) * 0.03)
    } else if (visual.phase === 'trading') {
      this.drawRing(visual.lastAction === 'buy' ? 0x26a69a : 0xef5350, 1.0)
      this.drawGlow(visual.lastAction === 'buy' ? 0x26a69a : 0xef5350, 0.6)
      this.scale.set(1)
    } else {
      this.drawRing(tomColor, this._hovered ? 1.0 : 0.7)
      this.drawGlow(glowColor, this._hovered ? 0.5 : 0)
      this.scale.set(this._hovered ? 1.08 : 1.0)
    }

    if (this.actionFadeAlpha > 0) {
      this.actionFadeAlpha -= 0.015
      this.actionFadeY -= 0.3
      this.actionLabel.alpha = Math.max(0, this.actionFadeAlpha)
      this.actionLabel.position.y = this.actionFadeY
    }
  }

  showAction(action: string) {
    const isBuy = action.toLowerCase() === 'buy'
    this.actionLabel.text = isBuy ? '▲ BUY' : action.toLowerCase() === 'sell' ? '▼ SELL' : action.toUpperCase()
    this.actionLabel.style.fill = isBuy ? 0x26a69a : 0xef5350
    this.actionFadeAlpha = 1.0
    this.actionFadeY = -(AVATAR_RADIUS + 8)
    this.actionLabel.alpha = 1
    this.actionLabel.position.y = this.actionFadeY
  }

  get visual(): AgentVisual {
    return this._visual
  }
}
