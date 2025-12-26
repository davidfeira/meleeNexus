import { useState, useEffect, useRef } from 'react'
import './SkinCreator.css'

const API_URL = 'http://127.0.0.1:5000/api/mex'
const BACKEND_URL = 'http://127.0.0.1:5000'

export default function SkinCreator({
  isOpen,
  onClose,
  selectedCharacter,
  onSkinCreatorChange,
  onRefresh,
  initialCostume
}) {
  // State
  const [skinCreatorStep, setSkinCreatorStep] = useState('select') // 'select' or 'edit'
  const [vanillaCostumes, setVanillaCostumes] = useState([])
  const [selectedVanillaCostume, setSelectedVanillaCostume] = useState(null)
  const [skinCreatorLoading, setSkinCreatorLoading] = useState(false)
  const [skinCreatorError, setSkinCreatorError] = useState(null)
  const [viewerWs, setViewerWs] = useState(null)
  const [modelTextures, setModelTextures] = useState([])
  const [selectedTextureIndex, setSelectedTextureIndex] = useState(null)
  const skinCreatorCanvasRef = useRef(null)
  const paintCanvasRef = useRef(null)
  const [isDrawing, setIsDrawing] = useState(false)
  const lastDrawPos = useRef(null)
  const [editedTextures, setEditedTextures] = useState({}) // { [index]: dataUrl }
  const [isDirty, setIsDirty] = useState(false)
  const [showSaveModal, setShowSaveModal] = useState(false)
  const [skinName, setSkinName] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const [saveError, setSaveError] = useState(null)
  const [viewerDragging, setViewerDragging] = useState(false)
  const [viewerDragButton, setViewerDragButton] = useState(null)
  const viewerLastMousePos = useRef({ x: 0, y: 0 })
  const [skinCreatorReconnecting, setSkinCreatorReconnecting] = useState(false)
  const [skinCreatorReconnectAttempts, setSkinCreatorReconnectAttempts] = useState(0)
  const skinCreatorReconnectTimeoutRef = useRef(null)
  const skinCreatorMaxReconnectAttempts = 3

  // Notify parent when skin creator opens/closes
  useEffect(() => {
    onSkinCreatorChange?.(isOpen)
  }, [isOpen, onSkinCreatorChange])

  // Load costumes when opening
  useEffect(() => {
    if (isOpen && selectedCharacter && skinCreatorStep === 'select' && !initialCostume) {
      loadVanillaCostumes(selectedCharacter)
    }
  }, [isOpen, selectedCharacter, skinCreatorStep, initialCostume])

  // Handle initialCostume for "edit from vault" flow
  useEffect(() => {
    if (isOpen && initialCostume) {
      startSkinCreatorFromVault(initialCostume)
    }
  }, [isOpen, initialCostume])

  // Load vanilla costumes
  const loadVanillaCostumes = async (character) => {
    try {
      setSkinCreatorLoading(true)
      setSkinCreatorError(null)
      const response = await fetch(`${API_URL}/vanilla/costumes/${character}`)
      const data = await response.json()
      if (data.success) {
        setVanillaCostumes(data.costumes)
      } else {
        setSkinCreatorError(data.error)
      }
    } catch (err) {
      setSkinCreatorError(err.message)
    } finally {
      setSkinCreatorLoading(false)
    }
  }

  // Start viewer with selected costume
  const startSkinCreatorViewer = async (costume) => {
    try {
      setSkinCreatorLoading(true)
      setSkinCreatorError(null)
      setSelectedVanillaCostume(costume)

      const response = await fetch(`${API_URL}/viewer/start-vanilla`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          character: selectedCharacter,
          costumeCode: costume.code
        })
      })

      const data = await response.json()
      if (!data.success) {
        throw new Error(data.error)
      }

      // Connect WebSocket
      const ws = new WebSocket(data.wsUrl)
      ws.binaryType = 'blob'

      ws.onopen = () => {
        setSkinCreatorLoading(false)
        setSkinCreatorStep('edit')
        setSkinCreatorReconnecting(false)
        setSkinCreatorReconnectAttempts(0)
        ws.send(JSON.stringify({ type: 'getTextures' }))
      }

      ws.onmessage = async (event) => {
        if (event.data instanceof Blob) {
          const bitmap = await createImageBitmap(event.data)
          const canvas = skinCreatorCanvasRef.current
          if (canvas) {
            const ctx = canvas.getContext('2d')
            canvas.width = bitmap.width
            canvas.height = bitmap.height
            ctx.drawImage(bitmap, 0, 0)
          }
        } else {
          try {
            const msg = JSON.parse(event.data)
            if (msg.type === 'textureList') {
              setModelTextures(msg.textures || [])
              if (msg.textures?.length > 0) {
                setSelectedTextureIndex(0)
              }
            } else if (msg.type === 'fullTexture') {
              console.log('Received fullTexture', { index: msg.index, width: msg.width, height: msg.height })
              if (msg.error) return
              if (!msg.data) return
              const canvas = paintCanvasRef.current
              if (canvas) {
                const img = new Image()
                img.onload = () => {
                  canvas.width = msg.width
                  canvas.height = msg.height
                  const ctx = canvas.getContext('2d')
                  ctx.imageSmoothingEnabled = false
                  ctx.drawImage(img, 0, 0)

                  const largerDim = Math.max(msg.width, msg.height)
                  const targetDisplaySize = 600
                  const scale = targetDisplaySize / largerDim
                  canvas.style.transform = `scale(${scale})`
                  canvas.style.transformOrigin = 'center center'
                }
                img.src = `data:image/png;base64,${msg.data}`
              }
            } else if (msg.type === 'ping') {
              ws.send(JSON.stringify({ type: 'pong' }))
            }
          } catch (e) {
            console.error('Error parsing WebSocket message:', e)
          }
        }
      }

      ws.onerror = () => {
        setSkinCreatorError('WebSocket connection failed')
        setSkinCreatorLoading(false)
      }

      ws.onclose = () => {
        setViewerWs(null)
        if (!skinCreatorError) {
          setSkinCreatorError('Connection lost. Click Retry to reconnect.')
        }
        setSkinCreatorReconnecting(false)
      }

      setViewerWs(ws)

    } catch (err) {
      setSkinCreatorError(err.message)
      setSkinCreatorLoading(false)
    }
  }

  // Start from vault costume (for editing existing costumes)
  const startSkinCreatorFromVault = async (costume) => {
    try {
      const character = costume.character || selectedCharacter
      if (!character) {
        throw new Error('No character specified')
      }

      setSkinCreatorLoading(true)
      setSkinCreatorError(null)
      setSelectedVanillaCostume({ code: costume.id, colorName: costume.color })

      const response = await fetch(`${API_URL}/viewer/start-vault`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          character: character,
          costumeId: costume.id
        })
      })

      const data = await response.json()
      if (!data.success) {
        throw new Error(data.error)
      }

      const ws = new WebSocket(data.wsUrl)
      ws.binaryType = 'blob'

      ws.onopen = () => {
        setSkinCreatorLoading(false)
        setSkinCreatorStep('edit')
        setSkinCreatorReconnecting(false)
        setSkinCreatorReconnectAttempts(0)
        ws.send(JSON.stringify({ type: 'getTextures' }))
      }

      ws.onmessage = async (event) => {
        if (event.data instanceof Blob) {
          const bitmap = await createImageBitmap(event.data)
          const canvas = skinCreatorCanvasRef.current
          if (canvas) {
            const ctx = canvas.getContext('2d')
            canvas.width = bitmap.width
            canvas.height = bitmap.height
            ctx.drawImage(bitmap, 0, 0)
          }
        } else {
          try {
            const msg = JSON.parse(event.data)
            if (msg.type === 'textureList') {
              setModelTextures(msg.textures || [])
              if (msg.textures?.length > 0) {
                setSelectedTextureIndex(0)
              }
            } else if (msg.type === 'fullTexture') {
              if (msg.error) return
              if (!msg.data) return
              const canvas = paintCanvasRef.current
              if (canvas) {
                const img = new Image()
                img.onload = () => {
                  canvas.width = msg.width
                  canvas.height = msg.height
                  const ctx = canvas.getContext('2d')
                  ctx.imageSmoothingEnabled = false
                  ctx.drawImage(img, 0, 0)

                  const largerDim = Math.max(msg.width, msg.height)
                  const targetDisplaySize = 600
                  const scale = targetDisplaySize / largerDim
                  canvas.style.transform = `scale(${scale})`
                  canvas.style.transformOrigin = 'center center'
                }
                img.src = `data:image/png;base64,${msg.data}`
              }
            } else if (msg.type === 'ping') {
              ws.send(JSON.stringify({ type: 'pong' }))
            }
          } catch (e) {
            console.error('Error parsing WebSocket message:', e)
          }
        }
      }

      ws.onerror = () => {
        setSkinCreatorError('WebSocket connection failed')
        setSkinCreatorLoading(false)
      }

      ws.onclose = () => {
        setViewerWs(null)
        if (!skinCreatorError) {
          setSkinCreatorError('Connection lost. Click Retry to reconnect.')
        }
        setSkinCreatorReconnecting(false)
      }

      setViewerWs(ws)

    } catch (err) {
      setSkinCreatorError(err.message)
      setSkinCreatorLoading(false)
    }
  }

  // Close and cleanup
  const closeSkinCreator = async (force = false) => {
    if (isDirty && !force) {
      const confirmed = window.confirm('You have unsaved changes. Are you sure you want to close?')
      if (!confirmed) return
    }

    if (skinCreatorReconnectTimeoutRef.current) {
      clearTimeout(skinCreatorReconnectTimeoutRef.current)
      skinCreatorReconnectTimeoutRef.current = null
    }

    setSkinCreatorError('closing')

    if (viewerWs) {
      viewerWs.close()
      setViewerWs(null)
    }

    try {
      await fetch(`${API_URL}/viewer/stop`, { method: 'POST' })
    } catch (e) {
      // Ignore errors on cleanup
    }

    // Reset state
    setSkinCreatorStep('select')
    setVanillaCostumes([])
    setSelectedVanillaCostume(null)
    setSkinCreatorError(null)
    setModelTextures([])
    setSelectedTextureIndex(null)
    setEditedTextures({})
    setIsDirty(false)
    setSkinCreatorReconnecting(false)
    setSkinCreatorReconnectAttempts(0)

    onClose?.()
  }

  // Camera controls
  const sendViewerCamera = (deltas) => {
    if (viewerWs && viewerWs.readyState === WebSocket.OPEN) {
      viewerWs.send(JSON.stringify({ type: 'camera', ...deltas }))
    }
  }

  const handleViewerMouseDown = (e) => {
    e.preventDefault()
    setViewerDragging(true)
    setViewerDragButton(e.button)
    viewerLastMousePos.current = { x: e.clientX, y: e.clientY }
  }

  const handleViewerMouseMove = (e) => {
    if (!viewerDragging) return

    const deltaX = e.clientX - viewerLastMousePos.current.x
    const deltaY = e.clientY - viewerLastMousePos.current.y
    viewerLastMousePos.current = { x: e.clientX, y: e.clientY }

    if (viewerDragButton === 2) {
      sendViewerCamera({ deltaX: -deltaX * 0.1, deltaY: deltaY * 0.1 })
    } else {
      sendViewerCamera({ deltaRotX: deltaY * 0.5, deltaRotY: deltaX * 0.5 })
    }
  }

  const handleViewerMouseUp = () => {
    setViewerDragging(false)
    setViewerDragButton(null)
  }

  const handleViewerWheel = (e) => {
    e.preventDefault()
    const zoomFactor = e.deltaY > 0 ? -0.1 : 0.1
    sendViewerCamera({ deltaZoom: zoomFactor })
  }

  const handleViewerContextMenu = (e) => {
    e.preventDefault()
  }

  // Load texture onto paint canvas when selected
  useEffect(() => {
    if (selectedTextureIndex === null || !modelTextures[selectedTextureIndex]) return

    const tex = modelTextures[selectedTextureIndex]
    const canvas = paintCanvasRef.current
    if (!canvas) return

    const editedData = editedTextures[selectedTextureIndex]
    const imgSrc = editedData || (tex.thumbnail ? `data:image/png;base64,${tex.thumbnail}` : null)

    if (!imgSrc) return

    const img = new Image()
    img.onload = () => {
      canvas.width = tex.width
      canvas.height = tex.height
      const ctx = canvas.getContext('2d')
      ctx.imageSmoothingEnabled = false
      ctx.drawImage(img, 0, 0, tex.width, tex.height)

      const largerDim = Math.max(tex.width, tex.height)
      const targetDisplaySize = 600
      const scale = targetDisplaySize / largerDim
      canvas.style.transform = `scale(${scale})`
      canvas.style.transformOrigin = 'center center'
    }
    img.src = imgSrc
  }, [selectedTextureIndex, modelTextures, editedTextures])

  // Warn before leaving with unsaved changes
  useEffect(() => {
    const handleBeforeUnload = (e) => {
      if (isDirty) {
        e.preventDefault()
        e.returnValue = 'You have unsaved changes. Are you sure you want to leave?'
      }
    }
    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [isDirty])

  // Paint canvas mouse handlers
  const getCanvasCoords = (e) => {
    const canvas = paintCanvasRef.current
    if (!canvas) return null
    const rect = canvas.getBoundingClientRect()
    const scaleX = canvas.width / rect.width
    const scaleY = canvas.height / rect.height
    return {
      x: Math.floor((e.clientX - rect.left) * scaleX),
      y: Math.floor((e.clientY - rect.top) * scaleY)
    }
  }

  const drawPixel = (x, y) => {
    const canvas = paintCanvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    ctx.fillStyle = '#ff0000'
    ctx.fillRect(x, y, 1, 1)
  }

  const drawLine = (x0, y0, x1, y1) => {
    const dx = Math.abs(x1 - x0)
    const dy = Math.abs(y1 - y0)
    const sx = x0 < x1 ? 1 : -1
    const sy = y0 < y1 ? 1 : -1
    let err = dx - dy

    while (true) {
      drawPixel(x0, y0)
      if (x0 === x1 && y0 === y1) break
      const e2 = 2 * err
      if (e2 > -dy) { err -= dy; x0 += sx }
      if (e2 < dx) { err += dx; y0 += sy }
    }
  }

  const handlePaintMouseDown = (e) => {
    if (e.button !== 0) return
    setIsDrawing(true)
    const coords = getCanvasCoords(e)
    if (coords) {
      drawPixel(coords.x, coords.y)
      lastDrawPos.current = coords
    }
  }

  const handlePaintMouseMove = (e) => {
    if (!isDrawing) return
    const coords = getCanvasCoords(e)
    if (coords) {
      if (lastDrawPos.current) {
        drawLine(lastDrawPos.current.x, lastDrawPos.current.y, coords.x, coords.y)
      } else {
        drawPixel(coords.x, coords.y)
      }
      lastDrawPos.current = coords
    }
  }

  const handlePaintMouseUp = () => {
    if (isDrawing) {
      setIsDrawing(false)
      lastDrawPos.current = null
      sendTextureUpdate()
    }
  }

  const sendTextureUpdate = () => {
    const canvas = paintCanvasRef.current
    if (!canvas || !viewerWs || viewerWs.readyState !== WebSocket.OPEN) return
    if (selectedTextureIndex === null) return

    const ctx = canvas.getContext('2d')
    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height)

    const tempCanvas = document.createElement('canvas')
    tempCanvas.width = canvas.width
    tempCanvas.height = canvas.height
    const tempCtx = tempCanvas.getContext('2d')
    tempCtx.putImageData(imageData, 0, 0)

    const dataUrl = tempCanvas.toDataURL('image/png')
    const base64 = dataUrl.replace('data:image/png;base64,', '')

    try {
      viewerWs.send(JSON.stringify({
        type: 'updateTexture',
        index: selectedTextureIndex,
        data: base64
      }))

      setEditedTextures(prev => ({ ...prev, [selectedTextureIndex]: dataUrl }))
      setIsDirty(true)
    } catch (err) {
      console.error('Error sending updateTexture:', err)
    }
  }

  // Open save modal
  const openSaveModal = () => {
    const defaultName = `${selectedCharacter} Custom`
    setSkinName(defaultName)
    setSaveError(null)
    setShowSaveModal(true)
  }

  // Save to vault
  const handleSaveToVault = async () => {
    if (!skinName.trim()) {
      setSaveError('Please enter a name')
      return
    }

    setIsSaving(true)
    setSaveError(null)

    try {
      const datPromise = new Promise((resolve, reject) => {
        const handleMessage = (event) => {
          if (event.data instanceof Blob) return
          try {
            const msg = JSON.parse(event.data)
            if (msg.type === 'exportDat') {
              viewerWs.removeEventListener('message', handleMessage)
              if (msg.success) {
                resolve(msg.data)
              } else {
                reject(new Error(msg.error || 'Export failed'))
              }
            }
          } catch {}
        }
        viewerWs.addEventListener('message', handleMessage)
        viewerWs.send(JSON.stringify({ type: 'exportDat' }))

        setTimeout(() => {
          viewerWs.removeEventListener('message', handleMessage)
          reject(new Error('Export timed out'))
        }, 30000)
      })

      const base64Data = await datPromise

      const byteCharacters = atob(base64Data)
      const byteNumbers = new Array(byteCharacters.length)
      for (let i = 0; i < byteCharacters.length; i++) {
        byteNumbers[i] = byteCharacters.charCodeAt(i)
      }
      const byteArray = new Uint8Array(byteNumbers)
      const datBlob = new Blob([byteArray], { type: 'application/octet-stream' })

      const { default: JSZip } = await import('jszip')
      const zip = new JSZip()
      zip.file(`${skinName.trim()}.dat`, datBlob)
      const zipBlob = await zip.generateAsync({ type: 'blob' })

      const formData = new FormData()
      formData.append('file', new File([zipBlob], `${skinName.trim()}.zip`))
      formData.append('custom_title', skinName.trim())

      const response = await fetch(`${API_URL}/import/file`, {
        method: 'POST',
        body: formData
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.error || 'Import failed')
      }

      setShowSaveModal(false)
      setIsDirty(false)
      setSkinName('')

      onRefresh?.()

      alert(`Skin "${skinName}" saved to vault!`)
    } catch (error) {
      console.error('Save error:', error)
      setSaveError(error.message)
    } finally {
      setIsSaving(false)
    }
  }

  // Download DAT file
  const handleDownloadDat = async () => {
    if (!viewerWs || viewerWs.readyState !== WebSocket.OPEN) {
      alert('Not connected to viewer')
      return
    }

    try {
      const datPromise = new Promise((resolve, reject) => {
        const handleMessage = (event) => {
          if (event.data instanceof Blob) return
          try {
            const msg = JSON.parse(event.data)
            if (msg.type === 'exportDat') {
              viewerWs.removeEventListener('message', handleMessage)
              if (msg.success) {
                resolve(msg.data)
              } else {
                reject(new Error(msg.error || 'Export failed'))
              }
            }
          } catch {}
        }
        viewerWs.addEventListener('message', handleMessage)
        viewerWs.send(JSON.stringify({ type: 'exportDat' }))

        setTimeout(() => {
          viewerWs.removeEventListener('message', handleMessage)
          reject(new Error('Export timed out'))
        }, 30000)
      })

      const base64Data = await datPromise

      const byteCharacters = atob(base64Data)
      const byteNumbers = new Array(byteCharacters.length)
      for (let i = 0; i < byteCharacters.length; i++) {
        byteNumbers[i] = byteCharacters.charCodeAt(i)
      }
      const byteArray = new Uint8Array(byteNumbers)
      const datBlob = new Blob([byteArray], { type: 'application/octet-stream' })

      const url = URL.createObjectURL(datBlob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${selectedCharacter}_${selectedVanillaCostume?.colorName || 'custom'}.dat`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (error) {
      console.error('Download error:', error)
      alert('Failed to download: ' + error.message)
    }
  }

  if (!isOpen) return null

  return (
    <>
      <div className="skin-creator-overlay">
        <div className="skin-creator-modal">
          {/* Header */}
          <div className="skin-creator-header">
            <div className="skin-creator-title">
              <h1>Skin Creator</h1>
              <span className="skin-creator-character">{selectedCharacter}</span>
              {selectedVanillaCostume && (
                <span className="skin-creator-costume">{selectedVanillaCostume.colorName}</span>
              )}
              {isDirty && <span className="skin-creator-dirty">*</span>}
            </div>
            <div className="skin-creator-header-buttons">
              {skinCreatorStep === 'edit' && (
                <>
                  <button
                    className="skin-creator-save"
                    onClick={openSaveModal}
                    title="Save to Vault"
                  >
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path>
                      <polyline points="17 21 17 13 7 13 7 21"></polyline>
                      <polyline points="7 3 7 8 15 8"></polyline>
                    </svg>
                    <span>Save</span>
                  </button>
                  <button
                    className="skin-creator-export"
                    onClick={handleDownloadDat}
                    title="Download DAT file"
                  >
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                      <polyline points="7 10 12 15 17 10"></polyline>
                      <line x1="12" y1="15" x2="12" y2="3"></line>
                    </svg>
                    <span>Download</span>
                  </button>
                </>
              )}
              <button
                className="skin-creator-close"
                onClick={() => closeSkinCreator()}
                title="Close (Esc)"
              >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="18" y1="6" x2="6" y2="18"></line>
                  <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
                <span>Close</span>
              </button>
            </div>
          </div>

          {/* Costume Selection Step */}
          {skinCreatorStep === 'select' && (
            <div className="skin-creator-select">
              <h2>Select a base costume</h2>
              <p>Choose a vanilla costume to use as your starting point</p>

              {skinCreatorLoading && (
                <div className="skin-creator-loading">Loading costumes...</div>
              )}

              {skinCreatorReconnecting && (
                <div className="skin-creator-reconnecting">
                  Reconnecting... (attempt {skinCreatorReconnectAttempts}/{skinCreatorMaxReconnectAttempts})
                </div>
              )}

              {skinCreatorError && skinCreatorError !== 'closing' && (
                <div className="skin-creator-error">{skinCreatorError}</div>
              )}

              <div className="skin-creator-costume-grid">
                {vanillaCostumes.map(costume => (
                  <div
                    key={costume.code}
                    className="skin-creator-costume-card"
                    onClick={() => startSkinCreatorViewer(costume)}
                  >
                    <div className="costume-preview">
                      {costume.hasCsp ? (
                        <img
                          src={`${BACKEND_URL}/vanilla/${selectedCharacter}/${costume.code}/csp.png`}
                          alt={costume.colorName}
                        />
                      ) : (
                        <div className="costume-placeholder">{costume.colorCode}</div>
                      )}
                    </div>
                    <div className="costume-name">{costume.colorName}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Editor Step */}
          {skinCreatorStep === 'edit' && (
            <div className="skin-creator-body">
              {/* Main area: Canvas + Right Panel */}
              <div className="skin-creator-main">
                {/* Center - Paint Canvas */}
                <div className="skin-creator-canvas-area">
                  <div className="skin-creator-toolbar">
                    <input type="color" className="color-picker" defaultValue="#ff0000" title="Color" />
                    <div className="toolbar-separator"></div>
                    <input type="range" className="brush-size" min="1" max="50" defaultValue="5" title="Brush Size" />
                  </div>
                  <div
                    className="skin-creator-canvas"
                    onMouseDown={handlePaintMouseDown}
                    onMouseMove={handlePaintMouseMove}
                    onMouseUp={handlePaintMouseUp}
                    onMouseLeave={handlePaintMouseUp}
                  >
                    {selectedTextureIndex === null ? (
                      <div className="canvas-placeholder">
                        <span>Paint Canvas</span>
                        <p>Select a texture to start editing</p>
                      </div>
                    ) : (
                      <canvas ref={paintCanvasRef} className="paint-canvas" />
                    )}
                  </div>
                </div>

                {/* Right Panel - 3D Preview + Tool Palette */}
                <div className="skin-creator-right-panel">
                  {/* 3D Preview (square) */}
                  <div className="skin-creator-3d-container">
                    <div className="skin-creator-panel-header">3D Preview</div>
                    <div
                      className="skin-creator-3d"
                      onMouseDown={handleViewerMouseDown}
                      onMouseMove={handleViewerMouseMove}
                      onMouseUp={handleViewerMouseUp}
                      onMouseLeave={handleViewerMouseUp}
                      onWheel={handleViewerWheel}
                      onContextMenu={handleViewerContextMenu}
                    >
                      {skinCreatorLoading ? (
                        <div className="viewer-placeholder">
                          <span>Loading...</span>
                        </div>
                      ) : skinCreatorReconnecting ? (
                        <div className="viewer-placeholder reconnecting">
                          <span>Reconnecting...</span>
                          <p>Attempt {skinCreatorReconnectAttempts}/{skinCreatorMaxReconnectAttempts}</p>
                        </div>
                      ) : (
                        <canvas ref={skinCreatorCanvasRef} className="viewer-canvas" />
                      )}
                    </div>
                  </div>

                  {/* Tool Palette */}
                  <div className="skin-creator-tool-palette">
                    <div className="skin-creator-panel-header">Tools</div>
                    <div className="tool-palette-content">
                      <div className="tool-palette-section">
                        <div className="tool-palette-section-title">Drawing</div>
                        <div className="tool-palette-tools">
                          <button className="tool-btn active" title="Pencil">✏️</button>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Bottom - Texture Strip */}
              <div className="skin-creator-texture-strip">
                <div className="skin-creator-panel-header">Textures ({modelTextures.length})</div>
                <div className="skin-creator-texture-list">
                  {modelTextures.length === 0 ? (
                    <div className="texture-loading">Loading textures...</div>
                  ) : (
                    modelTextures.map((tex, idx) => (
                      <div
                        key={idx}
                        className={`skin-creator-texture-item ${selectedTextureIndex === idx ? 'selected' : ''} ${editedTextures[idx] ? 'edited' : ''}`}
                        onClick={() => setSelectedTextureIndex(idx)}
                      >
                        <div className="texture-thumbnail">
                          {editedTextures[idx] ? (
                            <img
                              src={editedTextures[idx]}
                              alt={tex.name}
                              style={{
                                aspectRatio: `${tex.width} / ${tex.height}`
                              }}
                            />
                          ) : tex.thumbnail && (
                            <img
                              src={`data:image/png;base64,${tex.thumbnail}`}
                              alt={tex.name}
                              style={{
                                aspectRatio: `${tex.width} / ${tex.height}`
                              }}
                            />
                          )}
                        </div>
                        <div className="texture-info">
                          <span className="texture-name">{tex.name}{editedTextures[idx] && ' *'}</span>
                          <span className="texture-size">{tex.width}x{tex.height}</span>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Save Modal */}
      {showSaveModal && (
        <div className="skin-creator-save-overlay" onClick={() => !isSaving && setShowSaveModal(false)}>
          <div className="skin-creator-save-modal" onClick={(e) => e.stopPropagation()}>
            <h2>Save to Vault</h2>
            <p>Enter a name for your custom skin:</p>
            <input
              type="text"
              className="skin-name-input"
              value={skinName}
              onChange={(e) => setSkinName(e.target.value)}
              placeholder="Skin name..."
              disabled={isSaving}
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !isSaving) handleSaveToVault()
                if (e.key === 'Escape' && !isSaving) setShowSaveModal(false)
              }}
            />
            {saveError && <div className="save-error">{saveError}</div>}
            <div className="save-modal-buttons">
              <button
                className="save-cancel"
                onClick={() => setShowSaveModal(false)}
                disabled={isSaving}
              >
                Cancel
              </button>
              <button
                className="save-confirm"
                onClick={handleSaveToVault}
                disabled={isSaving || !skinName.trim()}
              >
                {isSaving ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
