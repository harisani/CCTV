import { useEffect, useMemo, useRef } from 'react'
import { API_BASE } from './api'

export function useDashboardSocket(token, cameraIds, onMessage, onConnectionChange = () => {}) {
  const callback = useRef(onMessage)
  const connectionCallback = useRef(onConnectionChange)
  const selectedCameraIds = useRef([])
  const socketRef = useRef(null)
  callback.current = onMessage
  connectionCallback.current = onConnectionChange
  const subscriptionKey = useMemo(
    () => [...new Set(cameraIds)].sort().slice(0, 16).join(','),
    [cameraIds],
  )
  selectedCameraIds.current = subscriptionKey ? subscriptionKey.split(',') : []

  const sendSubscription = () => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ action: 'subscribe', camera_ids: selectedCameraIds.current }))
    }
  }

  useEffect(() => {
    if (!token) return undefined
    let socket
    let retry
    let disposed = false
    const connect = () => {
      const url = `${API_BASE.replace(/^http/, 'ws')}/ws/dashboard?token=${encodeURIComponent(token)}`
      socket = new WebSocket(url)
      socketRef.current = socket
      connectionCallback.current('connecting')
      socket.onopen = () => {
        connectionCallback.current('connected')
        sendSubscription()
      }
      socket.onmessage = event => {
        try { callback.current(JSON.parse(event.data)) } catch { /* Ignore malformed server messages. */ }
      }
      socket.onerror = () => connectionCallback.current('error')
      socket.onclose = () => {
        connectionCallback.current('disconnected')
        if (!disposed) retry = window.setTimeout(connect, 3000)
      }
    }
    connect()
    return () => {
      disposed = true
      window.clearTimeout(retry)
      socket?.close()
      socketRef.current = null
    }
  }, [token])

  useEffect(() => { sendSubscription() }, [subscriptionKey])
}
