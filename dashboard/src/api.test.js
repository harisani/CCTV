import assert from 'node:assert/strict'
import test from 'node:test'

import { requestSnapshotBlob, resolveApiUrl } from './api.js'

test('relative API bases resolve against the dashboard origin', () => {
  assert.equal(
    resolveApiUrl(
      '/api/v1/evidence/snapshots/snapshot-1/content',
      '/api/v1',
      'https://dashboard.example.test',
    ),
    'https://dashboard.example.test/api/v1/evidence/snapshots/snapshot-1/content',
  )
})

test('snapshot content uses separate bearer credential and never puts it in a URL', async t => {
  const originalFetch = globalThis.fetch
  const calls = []
  const signal = new AbortController().signal
  const expectedBlob = { kind: 'snapshot-blob' }
  globalThis.fetch = async (url, options) => {
    calls.push({ url: String(url), options })
    if (calls.length === 1) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          access_token: 'short-lived-evidence-token',
          content_url: '/api/v1/evidence/snapshots/snapshot-1/content',
        }),
      }
    }
    return {
      ok: true,
      status: 200,
      blob: async () => expectedBlob,
    }
  }
  t.after(() => { globalThis.fetch = originalFetch })

  const blob = await requestSnapshotBlob('snapshot-1', 'user-jwt', signal)

  assert.equal(blob, expectedBlob)
  assert.equal(calls.length, 2)
  assert.equal(calls[0].options.headers.Authorization, 'Bearer user-jwt')
  assert.equal(calls[0].options.signal, signal)
  assert.equal(
    calls[1].url,
    'http://localhost:8000/api/v1/evidence/snapshots/snapshot-1/content',
  )
  assert.equal(
    calls[1].options.headers.Authorization,
    'Bearer short-lived-evidence-token',
  )
  assert.equal(calls[1].options.signal, signal)
  assert.equal(calls[1].url.includes('short-lived-evidence-token'), false)
  assert.equal(calls[1].url.includes('access_token'), false)
})
