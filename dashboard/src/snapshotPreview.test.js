import assert from 'node:assert/strict'
import test from 'node:test'

import { createSnapshotPreviewManager } from './snapshotPreview.js'

const deferred = () => {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

const makeManager = requestBlob => {
  const previews = []
  const errors = []
  const revoked = []
  const manager = createSnapshotPreviewManager({
    requestBlob,
    createObjectURL: blob => `blob:${blob}`,
    revokeObjectURL: url => revoked.push(url),
    onPreview: value => previews.push(value),
    onError: error => errors.push(error.message),
  })
  return { manager, previews, errors, revoked }
}

test('starting a newer request aborts and invalidates the older response', async () => {
  const requests = []
  const requestBlob = (snapshotId, token, signal) => {
    const result = deferred()
    requests.push({ snapshotId, token, signal, ...result })
    return result.promise
  }
  const { manager, previews, revoked } = makeManager(requestBlob)

  const first = manager.open('snapshot-1', 'token-1')
  const second = manager.open('snapshot-2', 'token-1')
  assert.equal(requests[0].signal.aborted, true)

  requests[0].resolve('old')
  await first
  assert.equal(previews.includes('blob:old'), false)

  requests[1].resolve('new')
  await second
  assert.equal(previews.at(-1), 'blob:new')
  assert.deepEqual(revoked, [])
})

test('authentication transition aborts work, clears preview, and revokes object URL', async () => {
  const pending = deferred()
  let requestCount = 0
  let activeSignal
  const requestBlob = async (_snapshotId, _token, signal) => {
    requestCount += 1
    activeSignal = signal
    return requestCount === 1 ? 'current' : pending.promise
  }
  const { manager, previews, revoked } = makeManager(requestBlob)

  await manager.open('snapshot-1', 'token-1')
  const inflight = manager.open('snapshot-2', 'token-1')
  manager.invalidate()

  assert.equal(activeSignal.aborted, true)
  assert.equal(previews.at(-1), null)
  assert.deepEqual(revoked, ['blob:current'])
  pending.resolve('stale')
  await inflight
  assert.equal(previews.includes('blob:stale'), false)
})

test('close and dispose revoke the current object URL', async () => {
  const { manager, revoked } = makeManager(async snapshotId => snapshotId)

  await manager.open('snapshot-1', 'token')
  manager.close()
  await manager.open('snapshot-2', 'token')
  manager.dispose()

  assert.deepEqual(revoked, ['blob:snapshot-1', 'blob:snapshot-2'])
})

test('AbortError is ignored while real failures remain visible', async () => {
  let attempt = 0
  const { manager, errors } = makeManager(async () => {
    attempt += 1
    if (attempt === 1) throw new DOMException('cancelled', 'AbortError')
    throw new Error('network failed')
  })

  await manager.open('snapshot-1', 'token')
  await manager.open('snapshot-2', 'token')

  assert.deepEqual(errors, ['network failed'])
})
