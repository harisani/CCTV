import assert from 'node:assert/strict'
import test from 'node:test'
import {
  formatNormalizedPoints,
  parseNormalizedPoints,
  topologyIndex,
  zonePath,
} from './topology.js'

test('normalized polygon coordinates round-trip', () => {
  const points = parseNormalizedPoints('0.1,0.2\n0.8,0.2\n0.8,0.9')
  assert.deepEqual(points, [
    { x: 0.1, y: 0.2 },
    { x: 0.8, y: 0.2 },
    { x: 0.8, y: 0.9 },
  ])
  assert.equal(formatNormalizedPoints(points), '0.1,0.2\n0.8,0.2\n0.8,0.9')
})

test('polygon parser rejects pixel values and incomplete geometry', () => {
  assert.throws(() => parseNormalizedPoints('120,200\n300,200\n300,400'), /0 sampai 1/)
  assert.throws(() => parseNormalizedPoints('0.1,0.2\n0.8,0.2'), /minimal tiga/)
})

test('zone path uses normalized building metadata', () => {
  const graph = {
    buildings: [{ id: 'b1', name: 'Produksi' }],
    zones: [{ id: 'z1', building_id: 'b1', name: 'Mixing', floor_name: 'L1' }],
  }
  const index = topologyIndex(graph)
  assert.equal(zonePath(graph.zones[0], index.buildings), 'Produksi · L1 · Mixing')
})
