export const cameraRoleLabels = {
  IDENTITY_CAPTURE: 'Identity capture',
  TRANSITION: 'Transition',
  OVERVIEW: 'Overview',
  EVIDENCE: 'Evidence',
}

export function parseNormalizedPoints(value) {
  const text = value.trim()
  if (!text) return null
  const points = text
    .split(/\n|;/)
    .map(item => item.trim())
    .filter(Boolean)
    .map(item => {
      const [rawX, rawY, ...extra] = item.split(',').map(part => part.trim())
      const x = Number(rawX)
      const y = Number(rawY)
      if (extra.length || !Number.isFinite(x) || !Number.isFinite(y) || x < 0 || x > 1 || y < 0 || y > 1) {
        throw new Error('Titik harus ditulis x,y dengan nilai 0 sampai 1.')
      }
      return { x, y }
    })
  if (points.length < 3) throw new Error('Polygon memerlukan minimal tiga titik.')
  return points
}

export function formatNormalizedPoints(points) {
  return (points || []).map(point => `${point.x},${point.y}`).join('\n')
}

export function topologyIndex(graph) {
  const buildings = new Map(graph.buildings.map(item => [item.id, item]))
  const zones = new Map(graph.zones.map(item => [item.id, item]))
  return { buildings, zones }
}

export function zonePath(zone, buildings) {
  const building = buildings.get(zone.building_id)
  return [building?.name, zone.floor_name, zone.area_name, zone.room_name, zone.name]
    .filter(Boolean)
    .join(' · ')
}
