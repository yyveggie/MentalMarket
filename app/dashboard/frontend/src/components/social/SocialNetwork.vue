<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import * as d3 from 'd3'
import { useMarketStore } from '@/stores/marketStore'

const store = useMarketStore()
const svgRef = ref<SVGSVGElement>()

const graph = computed(() => store.socialGraph || {})
const stats = computed(() => ({
  totalFollows: graph.value.total_follows ?? 0,
  avgFollowing: graph.value.avg_following ?? 0,
  kolCount: graph.value.kol_count ?? 0,
  kolThreshold: graph.value.kol_threshold ?? 0,
}))

const filterMode = ref<'all' | 'kol' | 'tom0' | 'tom1' | 'tom2'>('all')

interface GNode extends d3.SimulationNodeDatum {
  id: number
  tom: number
  followers: number
  influence: number
  is_kol: boolean
}

const TOM_COLORS: Record<number, string> = { 0: '#78909c', 1: '#0288d1', 2: '#7c4dff' }

let currentZoom: d3.ZoomBehavior<SVGSVGElement, unknown> | null = null

function zoomIn() {
  if (!svgRef.value || !currentZoom) return
  d3.select(svgRef.value).transition().duration(300).call(currentZoom.scaleBy, 1.3)
}
function zoomOut() {
  if (!svgRef.value || !currentZoom) return
  d3.select(svgRef.value).transition().duration(300).call(currentZoom.scaleBy, 0.7)
}
function zoomReset() {
  if (!svgRef.value || !currentZoom) return
  d3.select(svgRef.value).transition().duration(300).call(currentZoom.transform, d3.zoomIdentity)
}

let lastNodeCount = -1
let lastEdgeCount = -1
let lastRenderTime = 0
const MIN_RENDER_INTERVAL = 30000
const savedPositions = new Map<number, { x: number; y: number }>()

function render() {
  const nodes = graph.value.graph_nodes || []
  const edges = graph.value.graph_edges || []
  const now = Date.now()
  const countsChanged = nodes.length !== lastNodeCount || edges.length !== lastEdgeCount
  const firstRender = lastNodeCount === -1
  if (!firstRender && (!countsChanged || now - lastRenderTime < MIN_RENDER_INTERVAL)) return
  lastNodeCount = nodes.length
  lastEdgeCount = edges.length
  lastRenderTime = now
  doRender()
}

function doRender() {
  if (!svgRef.value) return
  const svg = d3.select(svgRef.value)
  svg.selectAll('*').remove()

  const allNodes: GNode[] = (graph.value.graph_nodes || []).map((n: any) => ({ ...n }))
  const allEdges: Array<{ source: number; target: number }> = graph.value.graph_edges || []

  if (!allNodes.length) return

  let filteredIds: Set<number> | null = null
  if (filterMode.value === 'kol') {
    const kolIds = new Set(allNodes.filter((n) => n.is_kol).map((n) => n.id))
    const neighbors = new Set<number>()
    for (const e of allEdges) {
      if (kolIds.has(e.source)) neighbors.add(e.target)
      if (kolIds.has(e.target)) neighbors.add(e.source)
    }
    filteredIds = new Set([...kolIds, ...neighbors])
  } else if (filterMode.value.startsWith('tom')) {
    const level = parseInt(filterMode.value.replace('tom', ''))
    filteredIds = new Set(allNodes.filter((n) => n.tom === level).map((n) => n.id))
  }

  const nodes = filteredIds ? allNodes.filter((n) => filteredIds!.has(n.id)) : allNodes
  const nodeIdSet = new Set(nodes.map((n) => n.id))
  const edges = allEdges.filter((e) => nodeIdSet.has(e.source) && nodeIdSet.has(e.target))

  if (!nodes.length) return

  const rect = svgRef.value.getBoundingClientRect()
  const width = rect.width
  const height = rect.height

  const nodeMap = new Map(nodes.map((n) => [n.id, n]))
  const links = edges
    .filter((e) => nodeMap.has(e.source) && nodeMap.has(e.target))
    .map((e) => ({ source: nodeMap.get(e.source)!, target: nodeMap.get(e.target)! }))

  const maxInfluence = Math.max(...nodes.map((n) => n.influence), 1)
  const rScale = d3.scaleSqrt().domain([0, maxInfluence]).range([4, 16])

  nodes.forEach((n, i) => {
    const saved = savedPositions.get(n.id)
    if (saved) {
      n.x = saved.x
      n.y = saved.y
    } else {
      const angle = (2 * Math.PI * i) / nodes.length
      const r = Math.min(width, height) * 0.35
      n.x = width / 2 + r * Math.cos(angle)
      n.y = height / 2 + r * Math.sin(angle)
    }
  })

  const sim = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links).id((d: any) => d.id).distance(100).strength(0.3))
    .force('charge', d3.forceManyBody().strength(-500))
    .force('x', d3.forceX(width / 2).strength(0.03))
    .force('y', d3.forceY(height / 2).strength(0.03))
    .force('collision', d3.forceCollide().radius((d: any) => rScale(d.influence) + 6))
    .alphaDecay(0.02)

  const g = svg.append('g')

  const zoom = d3.zoom<SVGSVGElement, unknown>()
    .scaleExtent([0.3, 4])
    .filter((event) => event.type !== 'wheel')
    .on('zoom', (event) => g.attr('transform', event.transform))
  svg.call(zoom)
  currentZoom = zoom

  const link = g.append('g')
    .selectAll('line')
    .data(links)
    .join('line')
    .attr('stroke', '#b2b5be')
    .attr('stroke-width', 1)
    .attr('stroke-opacity', 0.6)
    .attr('marker-end', 'url(#arrow)')

  const defs = svg.append('defs')
  defs.append('marker')
    .attr('id', 'arrow')
    .attr('viewBox', '0 -3 6 6')
    .attr('refX', 12).attr('refY', 0)
    .attr('markerWidth', 4).attr('markerHeight', 4)
    .attr('orient', 'auto')
    .append('path').attr('d', 'M0,-3L6,0L0,3').attr('fill', '#b2b5be')

  const node = g.append('g')
    .selectAll('circle')
    .data(nodes)
    .join('circle')
    .attr('r', (d) => rScale(d.influence))
    .attr('fill', (d) => TOM_COLORS[d.tom] ?? '#78909c')
    .attr('fill-opacity', 0.85)
    .attr('stroke', (d) => d.is_kol ? '#ff9800' : '#fff')
    .attr('stroke-width', (d) => d.is_kol ? 2.5 : 1)
    .style('cursor', 'pointer')

  node.append('title').text((d) => `A${d.id} | ToM${d.tom} | ${d.followers}粉丝 | 影响力${d.influence}`)

  const labelGroup = g.append('g')
    .selectAll('g')
    .data(nodes)
    .join('g')
    .attr('text-anchor', 'middle')
    .style('pointer-events', 'none')

  labelGroup.append('text')
    .attr('font-size', '9px')
    .attr('font-weight', '600')
    .attr('fill', '#131722')
    .attr('dy', (d) => -rScale(d.influence) - 6)
    .text((d) => `A${d.id}`)

  labelGroup.append('text')
    .attr('font-size', '7px')
    .attr('fill', '#787b86')
    .attr('dy', (d) => -rScale(d.influence) + 2)
    .text((d) => `${d.followers}粉`)

  sim.on('tick', () => {
    link
      .attr('x1', (d: any) => d.source.x)
      .attr('y1', (d: any) => d.source.y)
      .attr('x2', (d: any) => d.target.x)
      .attr('y2', (d: any) => d.target.y)
    node
      .attr('cx', (d: any) => d.x)
      .attr('cy', (d: any) => d.y)
    labelGroup
      .attr('transform', (d: any) => `translate(${d.x},${d.y})`)
  })

  sim.on('end', () => {
    nodes.forEach((n) => { if (n.x != null && n.y != null) savedPositions.set(n.id, { x: n.x, y: n.y }) })
  })

  const hasRestoredPositions = nodes.some((n) => savedPositions.has(n.id))
  sim.alpha(hasRestoredPositions ? 0.3 : 1).restart()
  setTimeout(() => {
    nodes.forEach((n) => { if (n.x != null && n.y != null) savedPositions.set(n.id, { x: n.x, y: n.y }) })
    sim.stop()
  }, 5000)
}

let resizeObs: ResizeObserver | null = null
onMounted(() => {
  render()
  if (svgRef.value) {
    resizeObs = new ResizeObserver(() => render())
    resizeObs.observe(svgRef.value)
  }
})
onUnmounted(() => resizeObs?.disconnect())
watch(() => store.socialGraph, render, { deep: true })
</script>

<template>
  <div class="social-network card">
    <div class="card-title">
      社交网络
      <div class="zoom-btns">
        <button class="zoom-btn" @click="zoomIn">+</button>
        <button class="zoom-btn" @click="zoomOut">−</button>
        <button class="zoom-btn" @click="zoomReset">↻</button>
      </div>
    </div>
    <div class="sn-controls">
      <div class="sn-stats">
        <span>{{ stats.totalFollows.toLocaleString() }} 关注</span>
        <span>关注数（平均） {{ stats.avgFollowing }}</span>
        <span>{{ stats.kolCount }} KOL</span>
      </div>
      <div class="sn-filters">
        <button class="filter-btn" :class="{ active: filterMode === 'all' }" @click="filterMode = 'all'; doRender()">全部</button>
        <button class="filter-btn" :class="{ active: filterMode === 'kol' }" @click="filterMode = 'kol'; doRender()">KOL</button>
        <button class="filter-btn" :class="{ active: filterMode === 'tom0' }" @click="filterMode = 'tom0'; doRender()" style="color: #78909c">T0</button>
        <button class="filter-btn" :class="{ active: filterMode === 'tom1' }" @click="filterMode = 'tom1'; doRender()" style="color: #0288d1">T1</button>
        <button class="filter-btn" :class="{ active: filterMode === 'tom2' }" @click="filterMode = 'tom2'; doRender()" style="color: #7c4dff">T2</button>
      </div>
    </div>
    <svg ref="svgRef" class="graph-svg" />
    <div class="legend">
      <span class="dot" style="background: #78909c" /> ToM0
      <span class="dot" style="background: #0288d1" /> ToM1
      <span class="dot" style="background: #7c4dff" /> ToM2
      <span class="dot kol-dot" /> KOL
    </div>

  </div>
</template>

<style scoped>
.sn-controls {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  flex-wrap: wrap;
  gap: 8px;
}

.sn-stats {
  display: flex;
  gap: 16px;
  font-size: 11px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}

.sn-filters {
  display: flex;
  gap: 2px;
}

.filter-btn {
  padding: 3px 8px;
  border: 1px solid var(--border);
  border-radius: 3px;
  background: var(--surface-1);
  color: var(--text-muted);
  font-size: 10px;
  font-weight: 600;
  font-family: var(--font-mono);
  cursor: pointer;
  transition: all 0.15s;
}

.filter-btn:hover {
  background: var(--surface-2);
}

.filter-btn.active {
  background: var(--accent-soft);
  border-color: var(--accent);
  color: var(--accent);
}

.graph-svg {
  width: 100%;
  height: 400px;
  cursor: grab;
}

.graph-svg:active {
  cursor: grabbing;
}

.legend {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 10px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  margin-top: 4px;
}

.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.zoom-btns {
  display: flex;
  gap: 4px;
  margin-left: auto;
}

.zoom-btn {
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 4px;
  background: var(--surface-1);
  color: var(--text-muted);
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}

.zoom-btn:hover {
  background: var(--surface-2);
  color: var(--heading);
}

.kol-dot {
  background: #78909c;
  border: 2px solid #ff9800;
  width: 10px;
  height: 10px;
}


</style>
