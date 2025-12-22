import { useState, useEffect, useRef, useCallback } from 'react'

const API_URL = '/api'

// Module-level flag to prevent double-start from React StrictMode
let viewerStarting = false

/**
 * 3D Model Viewer Component
 * Streams rendered frames from HSDRawViewer via WebSocket
 */
const ModelViewer = ({ character, skinId, onClose }) => {
  const canvasRef = useRef(null)
  const wsRef = useRef(null)
  const [isConnected, setIsConnected] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState(null)
  const [viewerInfo, setViewerInfo] = useState(null)

  // Camera state
  const [isDragging, setIsDragging] = useState(false)
  const [dragButton, setDragButton] = useState(null) // 0 = left (rotate), 2 = right (pan)
  const lastMousePos = useRef({ x: 0, y: 0 })

  // Start the viewer backend
  const startViewer = useCallback(async () => {
    // Prevent double-start from React StrictMode
    if (viewerStarting) {
      console.log('Viewer already starting, skipping')
      return
    }
    viewerStarting = true

    try {
      setIsLoading(true)
      setError(null)

      const response = await fetch(`${API_URL}/viewer/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ character, skinId })
      })

      const data = await response.json()
      console.log('Viewer start response:', data)

      if (!data.success) {
        throw new Error(data.error || 'Failed to start viewer')
      }

      // Connect to WebSocket
      console.log('Connecting to WebSocket:', data.wsUrl)
      const ws = new WebSocket(data.wsUrl)
      wsRef.current = ws

      ws.binaryType = 'blob'

      ws.onopen = () => {
        console.log('WebSocket connected to viewer')
        setIsConnected(true)
        setIsLoading(false)
      }

      ws.onmessage = async (event) => {
        if (event.data instanceof Blob) {
          // Binary frame data - render to canvas
          const bitmap = await createImageBitmap(event.data)
          const canvas = canvasRef.current
          if (canvas) {
            const ctx = canvas.getContext('2d')
            canvas.width = bitmap.width
            canvas.height = bitmap.height
            ctx.drawImage(bitmap, 0, 0)
          }
        } else {
          // JSON message
          try {
            const msg = JSON.parse(event.data)
            if (msg.type === 'info') {
              setViewerInfo(msg)
            }
          } catch (e) {
            console.log('Non-JSON message:', event.data)
          }
        }
      }

      ws.onerror = (event) => {
        console.error('WebSocket error:', event)
        setError('Connection error')
      }

      ws.onclose = () => {
        console.log('WebSocket closed')
        setIsConnected(false)
      }

    } catch (err) {
      console.error('Failed to start viewer:', err)
      setError(err.message)
      setIsLoading(false)
      viewerStarting = false // Allow retry
    }
  }, [character, skinId])

  // Stop the viewer
  const stopViewer = useCallback(async () => {
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }

    try {
      await fetch(`${API_URL}/viewer/stop`, { method: 'POST' })
    } catch (err) {
      console.error('Error stopping viewer:', err)
    }

    // Reset flag after stop completes so re-opening works
    viewerStarting = false
  }, [])

  // Send delta-based camera update to viewer
  const sendCameraUpdate = useCallback((deltas) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'camera',
        ...deltas
      }))
    }
  }, [])

  // Mouse handlers for camera control
  const handleMouseDown = useCallback((e) => {
    e.preventDefault()
    setIsDragging(true)
    setDragButton(e.button) // 0 = left, 2 = right
    lastMousePos.current = { x: e.clientX, y: e.clientY }
  }, [])

  const handleMouseMove = useCallback((e) => {
    if (!isDragging) return

    const deltaX = e.clientX - lastMousePos.current.x
    const deltaY = e.clientY - lastMousePos.current.y
    lastMousePos.current = { x: e.clientX, y: e.clientY }

    if (dragButton === 2) {
      // Right-click: Pan
      const panSpeed = 0.1
      sendCameraUpdate({
        deltaX: -deltaX * panSpeed,
        deltaY: deltaY * panSpeed
      })
    } else {
      // Left-click: Rotate (0.5 degrees per pixel)
      sendCameraUpdate({
        deltaRotX: deltaY * 0.5,
        deltaRotY: deltaX * 0.5
      })
    }
  }, [isDragging, dragButton, sendCameraUpdate])

  const handleMouseUp = useCallback(() => {
    setIsDragging(false)
    setDragButton(null)
  }, [])

  const handleWheel = useCallback((e) => {
    e.preventDefault()

    // Zoom - use multiplicative factor
    // Scroll up (negative deltaY) = zoom in (positive factor)
    // Scroll down (positive deltaY) = zoom out (negative factor)
    const zoomFactor = e.deltaY > 0 ? -0.1 : 0.1
    sendCameraUpdate({ deltaZoom: zoomFactor })
  }, [sendCameraUpdate])

  // Prevent context menu on right-click
  const handleContextMenu = useCallback((e) => {
    e.preventDefault()
  }, [])

  // Block scroll on the overlay when viewer is open
  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = ''
    }
  }, [])

  // Handle close
  const handleClose = useCallback(async () => {
    await stopViewer()
    onClose()
  }, [stopViewer, onClose])

  // Start viewer on mount
  useEffect(() => {
    startViewer()

    return () => {
      stopViewer()
    }
  }, [startViewer, stopViewer])

  // Global mouse up handler
  useEffect(() => {
    const handleGlobalMouseUp = () => setIsDragging(false)
    window.addEventListener('mouseup', handleGlobalMouseUp)
    return () => window.removeEventListener('mouseup', handleGlobalMouseUp)
  }, [])

  return (
    <div className="model-viewer-overlay" onClick={handleClose}>
      <div
        className="model-viewer-container"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="model-viewer-header">
          <h3>3D Model Viewer</h3>
          <button className="model-viewer-close" onClick={handleClose}>
            &times;
          </button>
        </div>

        <div className="model-viewer-content">
          {isLoading && (
            <div className="model-viewer-loading">
              <div className="spinner"></div>
              <p>Loading model...</p>
            </div>
          )}

          {error && (
            <div className="model-viewer-error">
              <p>Error: {error}</p>
              <button onClick={() => {
                viewerStarting = false
                setError(null)
                startViewer()
              }}>Retry</button>
            </div>
          )}

          {!isLoading && !error && (
            <canvas
              ref={canvasRef}
              className="model-viewer-canvas"
              onMouseDown={handleMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
              onWheel={handleWheel}
              onContextMenu={handleContextMenu}
              style={{ cursor: isDragging ? 'grabbing' : 'grab' }}
            />
          )}
        </div>

        <div className="model-viewer-footer">
          <span className={`status-indicator ${isConnected ? 'connected' : 'disconnected'}`}>
            {isConnected ? 'Connected' : 'Disconnected'}
          </span>
          {viewerInfo && (
            <span className="viewer-info">
              {viewerInfo.width}x{viewerInfo.height} @ {viewerInfo.fps}fps
            </span>
          )}
          <span className="controls-hint">
            Left-drag: rotate | Right-drag: pan | Scroll: zoom
          </span>
        </div>
      </div>
    </div>
  )
}

export default ModelViewer
