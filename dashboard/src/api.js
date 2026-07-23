export const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1'

export async function api(path, token, options = {}) {
  const isForm = typeof FormData !== 'undefined' && options.body instanceof FormData
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...(options.body && !isForm ? { 'Content-Type': 'application/json' } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}), ...options.headers },
  })
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || 'Request failed')
  return response.status === 204 ? null : response.json()
}

export async function apiBlob(path, token) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || 'Request failed')
  return response.blob()
}

export async function login(username, password) {
  const body = new URLSearchParams({ username, password })
  const response = await fetch(`${API_BASE}/auth/token`, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body })
  if (!response.ok) throw new Error('Username atau password salah')
  return response.json()
}

export async function requestSnapshotUrl(snapshotId, token) {
  if (!snapshotId) throw new Error('Snapshot tidak tersedia')
  const grant = await api(`/evidence/snapshots/${snapshotId}/access`, token, {
    method: 'POST',
  })
  return new URL(grant.content_url, API_BASE).toString()
}
