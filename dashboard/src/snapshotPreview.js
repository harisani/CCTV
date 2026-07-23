export function createSnapshotPreviewManager({
  requestBlob,
  onPreview,
  onError,
  createObjectURL = blob => URL.createObjectURL(blob),
  revokeObjectURL = url => URL.revokeObjectURL(url),
}) {
  let activeController = null
  let currentObjectUrl = ''
  let generation = 0

  const revokeCurrentObjectUrl = () => {
    if (!currentObjectUrl) return
    revokeObjectURL(currentObjectUrl)
    currentObjectUrl = ''
  }

  const invalidate = () => {
    generation += 1
    activeController?.abort()
    activeController = null
    revokeCurrentObjectUrl()
    onPreview(null)
  }

  const open = async (snapshotId, token) => {
    if (!snapshotId) return
    invalidate()
    const requestGeneration = generation
    const controller = new AbortController()
    activeController = controller
    try {
      const blob = await requestBlob(snapshotId, token, controller.signal)
      if (requestGeneration !== generation || controller.signal.aborted) return
      currentObjectUrl = createObjectURL(blob)
      activeController = null
      onPreview(currentObjectUrl)
    } catch (error) {
      if (activeController === controller) activeController = null
      if (error?.name !== 'AbortError' && requestGeneration === generation) {
        onError(error)
      }
    }
  }

  return {
    open,
    invalidate,
    close: invalidate,
    dispose: invalidate,
  }
}
