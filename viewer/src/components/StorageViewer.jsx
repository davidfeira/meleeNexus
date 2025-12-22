import { useState, useEffect, useRef } from 'react'
import { io } from 'socket.io-client'
import './StorageViewer.css'
import './IsoBuilder.css'
import { DEFAULT_CHARACTERS } from '../defaultCharacters'

const API_URL = 'http://127.0.0.1:5000/api/mex'
const BACKEND_URL = 'http://127.0.0.1:5000'

const DAS_STAGES = [
  { code: 'GrOp', name: 'Dreamland', folder: 'dreamland', vanillaImage: `${BACKEND_URL}/vanilla/stages/dreamland.jpg` },
  { code: 'GrPs', name: 'Pokemon Stadium', folder: 'pokemon_stadium', vanillaImage: `${BACKEND_URL}/vanilla/stages/pokemon stadium.jpg` },
  { code: 'GrSt', name: "Yoshi's Story", folder: 'yoshis_story', vanillaImage: `${BACKEND_URL}/vanilla/stages/Yoshis story.jpg` },
  { code: 'GrNBa', name: 'Battlefield', folder: 'battlefield', vanillaImage: `${BACKEND_URL}/vanilla/stages/battlefield.jpg` },
  { code: 'GrIz', name: 'Fountain of Dreams', folder: 'fountain_of_dreams', vanillaImage: `${BACKEND_URL}/vanilla/stages/Fountain of Dreams.webp` },
  { code: 'GrNLa', name: 'Final Destination', folder: 'final_destination', vanillaImage: `${BACKEND_URL}/vanilla/stages/final destination.png` }
]

// Skeleton loading components
const SkeletonCard = () => (
  <div className="character-card skeleton-card">
    <div className="character-image-container">
      <div className="skeleton skeleton-image"></div>
    </div>
    <div className="skeleton skeleton-text" style={{ width: '70%', margin: '0.5rem auto' }}></div>
    <div className="skeleton skeleton-text" style={{ width: '40%', margin: '0 auto', height: '12px' }}></div>
  </div>
)

const SkeletonSkinCard = () => (
  <div className="skin-card skeleton-card">
    <div className="skin-image-container">
      <div className="skeleton skeleton-image"></div>
    </div>
    <div className="skeleton skeleton-text" style={{ width: '60%', margin: '0.5rem auto' }}></div>
  </div>
)

export default function StorageViewer({ metadata, onRefresh }) {
  const [mode, setMode] = useState('characters') // 'characters', 'stages', or 'patches'
  const [isLoading, setIsLoading] = useState(true)
  const [selectedCharacter, setSelectedCharacter] = useState(null)
  const [selectedStage, setSelectedStage] = useState(null)
  const [stageVariants, setStageVariants] = useState({})
  const [importing, setImporting] = useState(false)
  const [importMessage, setImportMessage] = useState('')

  // XDelta patches state
  const [xdeltaPatches, setXdeltaPatches] = useState([])
  const [showXdeltaImportModal, setShowXdeltaImportModal] = useState(false)
  const [xdeltaImportData, setXdeltaImportData] = useState({ name: '', description: '', file: null, image: null })
  const [importingXdelta, setImportingXdelta] = useState(false)
  const [showXdeltaEditModal, setShowXdeltaEditModal] = useState(false)
  const [editingXdelta, setEditingXdelta] = useState(null)

  // XDelta build modal state
  const [showXdeltaBuildModal, setShowXdeltaBuildModal] = useState(false)
  const [xdeltaBuildState, setXdeltaBuildState] = useState('idle') // 'idle', 'building', 'complete', 'error'
  const [xdeltaBuildPatch, setXdeltaBuildPatch] = useState(null)
  const [xdeltaBuildFilename, setXdeltaBuildFilename] = useState(null)
  const [xdeltaBuildError, setXdeltaBuildError] = useState(null)
  const [xdeltaBuildProgress, setXdeltaBuildProgress] = useState(0)
  const [xdeltaBuildMessage, setXdeltaBuildMessage] = useState('')
  const socketRef = useRef(null)

  // Slippi dialog state
  const [showSlippiDialog, setShowSlippiDialog] = useState(false)
  const [slippiDialogData, setSlippiDialogData] = useState(null)
  const [pendingFile, setPendingFile] = useState(null)
  const [retestingItem, setRetestingItem] = useState(null) // For retest dialog

  // Edit modal state
  const [showEditModal, setShowEditModal] = useState(false)
  const [editingItem, setEditingItem] = useState(null) // { type: 'costume'/'stage', data: {...} }
  const [editName, setEditName] = useState('')
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [newScreenshot, setNewScreenshot] = useState(null) // File object for new screenshot
  const [screenshotPreview, setScreenshotPreview] = useState(null) // Preview URL for new screenshot
  const [newCsp, setNewCsp] = useState(null) // File object for new CSP
  const [cspPreview, setCspPreview] = useState(null) // Preview URL for new CSP
  const [newStock, setNewStock] = useState(null) // File object for new stock
  const [stockPreview, setStockPreview] = useState(null) // Preview URL for new stock
  const [editSlippiSafe, setEditSlippiSafe] = useState(null) // Track slippi changes for stages
  const [lastImageUpdate, setLastImageUpdate] = useState(Date.now()) // For cache-busting images

  // Drag and drop state
  const [draggedItem, setDraggedItem] = useState(null) // { index, id }
  const [dragOverIndex, setDragOverIndex] = useState(null)
  const [reordering, setReordering] = useState(false)
  const [contextMenu, setContextMenu] = useState(null) // { x, y, type: 'skin'/'variant', item, index }
  const [previewOrder, setPreviewOrder] = useState(null) // Live preview of reordered items during drag

  // Fetch stage variants when in stages mode or when metadata changes
  useEffect(() => {
    if (mode === 'stages') {
      fetchStageVariants()
    }
  }, [mode, metadata])

  // Fetch xdelta patches when in patches mode
  useEffect(() => {
    if (mode === 'patches') {
      fetchXdeltaPatches()
    }
  }, [mode])

  // WebSocket connection for xdelta build progress
  useEffect(() => {
    const socket = io(BACKEND_URL)
    socketRef.current = socket

    socket.on('connect', () => {
      console.log('Connected to WebSocket for xdelta progress')
    })

    socket.on('xdelta_progress', (data) => {
      if (xdeltaBuildPatch && data.patch_id === xdeltaBuildPatch.id) {
        setXdeltaBuildProgress(data.percentage)
        setXdeltaBuildMessage(data.message)
      }
    })

    socket.on('xdelta_complete', (data) => {
      if (xdeltaBuildPatch && data.patch_id === xdeltaBuildPatch.id) {
        setXdeltaBuildProgress(100)
        setXdeltaBuildFilename(data.filename)
        setXdeltaBuildState('complete')
      }
    })

    socket.on('xdelta_error', (data) => {
      if (xdeltaBuildPatch && data.patch_id === xdeltaBuildPatch.id) {
        setXdeltaBuildError(data.error)
        setXdeltaBuildState('error')
      }
    })

    return () => {
      socket.disconnect()
    }
  }, [xdeltaBuildPatch])

  const fetchXdeltaPatches = async () => {
    try {
      const response = await fetch(`${API_URL}/xdelta/list`)
      if (!response.ok) {
        console.error('Failed to fetch xdelta patches: Server returned', response.status)
        return
      }
      const text = await response.text()
      if (!text || text.startsWith('<!')) {
        console.error('Failed to fetch xdelta patches: Server returned HTML instead of JSON')
        return
      }
      const data = JSON.parse(text)
      if (data.success) {
        setXdeltaPatches(data.patches)
      }
    } catch (err) {
      console.error('Failed to fetch xdelta patches:', err)
    }
  }

  const handleImportXdelta = async () => {
    if (!xdeltaImportData.file) {
      alert('Please select an xdelta file')
      return
    }

    setImportingXdelta(true)

    try {
      const formData = new FormData()
      formData.append('file', xdeltaImportData.file)
      formData.append('name', xdeltaImportData.name || xdeltaImportData.file.name.replace('.xdelta', ''))
      formData.append('description', xdeltaImportData.description)
      if (xdeltaImportData.image) {
        formData.append('image', xdeltaImportData.image)
      }

      const response = await fetch(`${API_URL}/xdelta/import`, {
        method: 'POST',
        body: formData
      })

      const data = await response.json()

      if (data.success) {
        setShowXdeltaImportModal(false)
        setXdeltaImportData({ name: '', description: '', file: null, image: null })
        await fetchXdeltaPatches()
      } else {
        alert(`Import failed: ${data.error}`)
      }
    } catch (err) {
      alert(`Import error: ${err.message}`)
    } finally {
      setImportingXdelta(false)
    }
  }

  const handleBuildXdeltaIso = async (patch) => {
    const vanillaIsoPath = localStorage.getItem('vanilla_iso_path')

    if (!vanillaIsoPath) {
      alert('No vanilla ISO path set. Please set it in Settings first.')
      return
    }

    // Open modal and set building state
    setXdeltaBuildPatch(patch)
    setXdeltaBuildState('building')
    setXdeltaBuildFilename(null)
    setXdeltaBuildError(null)
    setXdeltaBuildProgress(0)
    setXdeltaBuildMessage('Starting...')
    setShowXdeltaBuildModal(true)

    try {
      const response = await fetch(`${API_URL}/xdelta/build/${patch.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ vanillaIsoPath })
      })

      const data = await response.json()

      if (!data.success) {
        setXdeltaBuildError(data.error)
        setXdeltaBuildState('error')
      }
      // If success, we wait for WebSocket events for progress/complete
    } catch (err) {
      setXdeltaBuildError(err.message)
      setXdeltaBuildState('error')
    }
  }

  const handleDownloadXdeltaIso = () => {
    if (!xdeltaBuildFilename) return

    const link = document.createElement('a')
    link.href = `${API_URL}/xdelta/download/${xdeltaBuildFilename}`
    link.download = xdeltaBuildFilename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  const closeXdeltaBuildModal = () => {
    setShowXdeltaBuildModal(false)
    setXdeltaBuildState('idle')
    setXdeltaBuildPatch(null)
    setXdeltaBuildFilename(null)
    setXdeltaBuildError(null)
    setXdeltaBuildProgress(0)
    setXdeltaBuildMessage('')
  }

  const handleDeleteXdelta = async (patchId) => {
    if (!confirm('Are you sure you want to delete this patch?')) return

    try {
      const response = await fetch(`${API_URL}/xdelta/delete/${patchId}`, {
        method: 'POST'
      })

      const data = await response.json()

      if (data.success) {
        await fetchXdeltaPatches()
      } else {
        alert(`Delete failed: ${data.error}`)
      }
    } catch (err) {
      alert(`Delete error: ${err.message}`)
    }
  }

  const handleEditXdelta = (patch) => {
    setEditingXdelta({ ...patch })
    setShowXdeltaEditModal(true)
  }

  const handleSaveXdeltaEdit = async () => {
    if (!editingXdelta) return

    try {
      const response = await fetch(`${API_URL}/xdelta/update/${editingXdelta.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: editingXdelta.name,
          description: editingXdelta.description
        })
      })

      const data = await response.json()

      if (data.success) {
        setShowXdeltaEditModal(false)
        setEditingXdelta(null)
        await fetchXdeltaPatches()
      } else {
        alert(`Save failed: ${data.error}`)
      }
    } catch (err) {
      alert(`Save error: ${err.message}`)
    }
  }

  const handleUpdateXdeltaImage = async (e) => {
    if (!editingXdelta) return

    const file = e.target.files[0]
    if (!file) return

    const formData = new FormData()
    formData.append('image', file)

    try {
      const response = await fetch(`${API_URL}/xdelta/update-image/${editingXdelta.id}`, {
        method: 'POST',
        body: formData
      })

      const data = await response.json()

      if (data.success) {
        setEditingXdelta({ ...editingXdelta, imageUrl: data.imageUrl })
        await fetchXdeltaPatches()
      } else {
        alert(`Image update failed: ${data.error}`)
      }
    } catch (err) {
      alert(`Image update error: ${err.message}`)
    }
  }

  // Track loading state based on metadata
  useEffect(() => {
    if (metadata) {
      // Small delay for smooth transition
      const timer = setTimeout(() => setIsLoading(false), 300)
      return () => clearTimeout(timer)
    }
  }, [metadata])

  const fetchStageVariants = async () => {
    try {
      const response = await fetch(`${API_URL}/das/storage/variants`)
      const data = await response.json()

      if (data.success) {
        // Group variants by stage
        const grouped = {}
        data.variants.forEach(variant => {
          if (!grouped[variant.stageCode]) {
            grouped[variant.stageCode] = []
          }
          grouped[variant.stageCode].push(variant)
        })
        setStageVariants(grouped)
      }
    } catch (err) {
      console.error('Failed to fetch stage variants:', err)
    }
  }

  const handleFileImport = async (event, slippiAction = null) => {
    const file = slippiAction ? pendingFile : event.target.files[0]
    if (!file) return

    setImporting(true)
    setImportMessage('Uploading and detecting mod type...')

    try {
      const formData = new FormData()
      formData.append('file', file)
      if (slippiAction) {
        formData.append('slippi_action', slippiAction)
      }

      const response = await fetch(`${API_URL}/import/file`, {
        method: 'POST',
        body: formData,
      })
      const data = await response.json()

      // Check if we need to show slippi dialog
      if (data.type === 'slippi_dialog') {
        setSlippiDialogData(data)
        setPendingFile(file)
        setShowSlippiDialog(true)
        setImporting(false)
        setImportMessage('')
        if (event && event.target) event.target.value = null
        return
      }

      if (data.success) {
        const typeMsg = data.type === 'character'
          ? `${data.imported_count} costume(s)`
          : `${data.stage} stage`
        setImportMessage(`✓ Imported ${typeMsg}! Refreshing...`)

        // Refresh metadata
        await onRefresh()

        // If we imported a stage, also refresh stage variants
        if (data.type === 'stage' && mode === 'stages') {
          await fetchStageVariants()
        }

        setImportMessage(`✓ Successfully imported ${typeMsg}!`)
        setTimeout(() => {
          setImporting(false)
          setImportMessage('')
        }, 2000)
      } else {
        setImportMessage(`✗ Import failed: ${data.error}`)
        setTimeout(() => {
          setImporting(false)
          setImportMessage('')
        }, 5000)
      }
    } catch (err) {
      setImportMessage(`✗ Error: ${err.message}`)
      setTimeout(() => {
        setImporting(false)
        setImportMessage('')
      }, 5000)
    }

    // Reset file input
    if (event && event.target) event.target.value = null
  }

  const handleSlippiChoice = (choice) => {
    setShowSlippiDialog(false)
    if (choice === 'cancel') {
      setPendingFile(null)
      setSlippiDialogData(null)
      return
    }
    handleFileImport(null, choice)
  }

  const handleSlippiRetest = async (autoFix = false) => {
    if (!editingItem || editingItem.type !== 'costume') return

    try {
      const response = await fetch(`${API_URL}/storage/costumes/retest-slippi`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          character: editingItem.data.character,
          skinId: editingItem.data.id,
          autoFix: autoFix
        })
      })
      const data = await response.json()

      if (data.success) {
        // If not safe and not auto-fixing, show dialog
        if (!data.slippi_safe && !autoFix) {
          setRetestingItem(editingItem.data)
          setSlippiDialogData({
            unsafe_costumes: [{
              character: editingItem.data.character,
              color: editingItem.data.color
            }]
          })
          setShowSlippiDialog(true)
        } else {
          // Safe or just fixed - reload
          alert(data.message)
          window.location.reload()
        }
      } else {
        alert(`Error: ${data.error}`)
      }
    } catch (err) {
      alert(`Error: ${err.message}`)
    }
  }

  const handleRetestFixChoice = (choice) => {
    setShowSlippiDialog(false)
    if (choice === 'cancel') {
      setRetestingItem(null)
      setSlippiDialogData(null)
      return
    }
    if (choice === 'fix') {
      // Retest with auto-fix
      handleSlippiRetest(true)
    } else if (choice === 'import_as_is') {
      // Just reload to keep current status
      window.location.reload()
    }
    setRetestingItem(null)
  }

  const handleSlippiOverride = async () => {
    if (!editingItem || editingItem.type !== 'costume') return

    const currentStatus = editingItem.data.slippi_safe
    const newStatus = !currentStatus

    try {
      const response = await fetch(`${API_URL}/storage/costumes/override-slippi`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          character: editingItem.data.character,
          skinId: editingItem.data.id,
          slippiSafe: newStatus
        })
      })
      const data = await response.json()

      if (data.success) {
        alert(data.message)
        window.location.reload()
      } else {
        alert(`Error: ${data.error}`)
      }
    } catch (err) {
      alert(`Error: ${err.message}`)
    }
  }

  const handleEditClick = (type, data) => {
    const item = { type, data }
    const name = type === 'costume' ? data.color : data.name
    setEditingItem(item)
    setEditName(name)
    setSaving(false)
    setDeleting(false)
    setNewScreenshot(null)
    setScreenshotPreview(null)
    setNewCsp(null)
    setCspPreview(null)
    setNewStock(null)
    setStockPreview(null)
    setEditSlippiSafe(type === 'stage' ? data.slippi_safe : null)
    setShowEditModal(true)
  }

  const handleScreenshotChange = (e) => {
    const file = e.target.files[0]
    if (!file) return

    // Validate file type
    if (!file.type.startsWith('image/')) {
      alert('Please select an image file')
      return
    }

    setNewScreenshot(file)

    // Create preview URL
    const reader = new FileReader()
    reader.onload = (e) => {
      setScreenshotPreview(e.target.result)
    }
    reader.readAsDataURL(file)
  }

  const handleCspChange = (e) => {
    const file = e.target.files[0]
    if (!file) return

    // Validate file type
    if (!file.type.startsWith('image/')) {
      alert('Please select an image file')
      return
    }

    setNewCsp(file)

    // Create preview URL
    const reader = new FileReader()
    reader.onload = (e) => {
      setCspPreview(e.target.result)
    }
    reader.readAsDataURL(file)
  }

  const handleStockChange = (e) => {
    const file = e.target.files[0]
    if (!file) return

    // Validate file type
    if (!file.type.startsWith('image/')) {
      alert('Please select an image file')
      return
    }

    setNewStock(file)

    // Create preview URL
    const reader = new FileReader()
    reader.onload = (e) => {
      setStockPreview(e.target.result)
    }
    reader.readAsDataURL(file)
  }

  const handleSave = async () => {
    if (!editName.trim()) {
      alert('Name cannot be empty')
      return
    }

    setSaving(true)

    try {
      // Save name change
      const endpoint = editingItem.type === 'costume'
        ? `${API_URL}/storage/costumes/rename`
        : `${API_URL}/storage/stages/rename`

      const body = editingItem.type === 'costume'
        ? {
            character: editingItem.data.character,
            skinId: editingItem.data.id,
            newName: editName
          }
        : {
            stageFolder: editingItem.data.stageFolder,
            variantId: editingItem.data.id,
            newName: editName
          }

      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })

      const data = await response.json()

      if (!data.success) {
        alert(`Save failed: ${data.error}`)
        setSaving(false)
        return
      }

      // If this is a stage and there's a new screenshot, upload it
      if (editingItem.type === 'stage' && newScreenshot) {
        const formData = new FormData()
        formData.append('stageFolder', editingItem.data.stageFolder)
        formData.append('variantId', editingItem.data.id)
        formData.append('screenshot', newScreenshot)

        const screenshotResponse = await fetch(`${API_URL}/storage/stages/update-screenshot`, {
          method: 'POST',
          body: formData
        })

        const screenshotData = await screenshotResponse.json()

        if (!screenshotData.success) {
          alert(`Screenshot upload failed: ${screenshotData.error}`)
          setSaving(false)
          return
        }
      }

      // If this is a stage and slippi status changed, save it
      if (editingItem.type === 'stage' && editSlippiSafe !== editingItem.data.slippi_safe) {
        const slippiResponse = await fetch(`${API_URL}/storage/stages/set-slippi`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            stageName: editingItem.data.stageFolder,
            variantId: editingItem.data.id,
            slippiSafe: editSlippiSafe
          })
        })

        const slippiData = await slippiResponse.json()

        if (!slippiData.success) {
          alert(`Slippi status update failed: ${slippiData.error}`)
          setSaving(false)
          return
        }
      }

      // If this is a character costume and there's a new CSP, upload it
      if (editingItem.type === 'costume' && newCsp) {
        const formData = new FormData()
        formData.append('character', editingItem.data.character)
        formData.append('skinId', editingItem.data.id)
        formData.append('csp', newCsp)

        const cspResponse = await fetch(`${API_URL}/storage/costumes/update-csp`, {
          method: 'POST',
          body: formData
        })

        const cspData = await cspResponse.json()

        if (!cspData.success) {
          alert(`CSP upload failed: ${cspData.error}`)
          setSaving(false)
          return
        }
      }

      // If this is a character costume and there's a new stock icon, upload it
      if (editingItem.type === 'costume' && newStock) {
        const formData = new FormData()
        formData.append('character', editingItem.data.character)
        formData.append('skinId', editingItem.data.id)
        formData.append('stock', newStock)

        const stockResponse = await fetch(`${API_URL}/storage/costumes/update-stock`, {
          method: 'POST',
          body: formData
        })

        const stockData = await stockResponse.json()

        if (!stockData.success) {
          alert(`Stock icon upload failed: ${stockData.error}`)
          setSaving(false)
          return
        }
      }

      // Refetch data before closing modal
      if (editingItem.type === 'stage') {
        await fetchStageVariants()
      }

      // Always await metadata refresh for costumes (CSP/stock updates)
      await onRefresh()

      // If we uploaded a CSP or stock, update cache-busting timestamp to force image reload
      if (newCsp || newStock) {
        setLastImageUpdate(Date.now())
      }

      setShowEditModal(false)
      setEditingItem(null)
    } catch (err) {
      alert(`Save error: ${err.message}`)
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    const itemName = editingItem.type === 'costume'
      ? `${editingItem.data.character} - ${editingItem.data.color}`
      : editingItem.data.name

    if (!confirm(`Are you sure you want to delete "${itemName}"? This cannot be undone.`)) {
      return
    }

    setDeleting(true)

    try {
      const endpoint = editingItem.type === 'costume'
        ? `${API_URL}/storage/costumes/delete`
        : `${API_URL}/storage/stages/delete`

      const body = editingItem.type === 'costume'
        ? {
            character: editingItem.data.character,
            skinId: editingItem.data.id
          }
        : {
            stageFolder: editingItem.data.stageFolder,
            variantId: editingItem.data.id
          }

      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })

      const data = await response.json()

      if (data.success) {
        // Refetch data before closing modal
        if (editingItem.type === 'stage') {
          await fetchStageVariants()
        }

        // Always await metadata refresh for costumes
        await onRefresh()

        // Update cache-busting timestamp to force image reload after deletion
        if (editingItem.type === 'costume') {
          setLastImageUpdate(Date.now())
        }

        setShowEditModal(false)
        setEditingItem(null)
      } else {
        alert(`Delete failed: ${data.error}`)
      }
    } catch (err) {
      alert(`Delete error: ${err.message}`)
    } finally {
      setDeleting(false)
    }
  }

  const handleExport = async () => {
    setExporting(true)

    try {
      const endpoint = editingItem.type === 'costume'
        ? `${API_URL}/storage/costumes/export`
        : `${API_URL}/storage/stages/export`

      const body = editingItem.type === 'costume'
        ? {
            character: editingItem.data.character,
            skinId: editingItem.data.id,
            colorName: editingItem.data.color
          }
        : {
            stageCode: editingItem.data.stageCode,
            stageName: editingItem.data.stageName,
            variantId: editingItem.data.id,
            variantName: editingItem.data.name
          }

      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })

      const data = await response.json()

      if (data.success) {
        // Trigger download
        const downloadUrl = `${API_URL}/export/mod/${data.filename}`
        const link = document.createElement('a')
        link.href = downloadUrl
        link.download = data.filename
        document.body.appendChild(link)
        link.click()
        document.body.removeChild(link)
      } else {
        alert(`Export failed: ${data.error}`)
      }
    } catch (err) {
      alert(`Export error: ${err.message}`)
    } finally {
      setExporting(false)
    }
  }

  const handleCancel = () => {
    setShowEditModal(false)
    setEditingItem(null)
    setEditName('')
    setNewScreenshot(null)
    setScreenshotPreview(null)
    setNewCsp(null)
    setCspPreview(null)
    setNewStock(null)
    setStockPreview(null)
    setEditSlippiSafe(null)
  }

  // Drag and drop handlers
  const handleDragStart = (e, index, items) => {
    setDraggedItem({ index, id: items[index].id })
    e.dataTransfer.effectAllowed = 'move'
  }

  const handleDragOver = (e) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
  }

  const handleDragEnter = (e, index, items) => {
    e.preventDefault()
    if (!draggedItem || draggedItem.index === index) return

    // Only update if we've moved to a different position
    if (dragOverIndex !== index) {
      setDragOverIndex(index)

      // Calculate new preview order
      const currentOrder = previewOrder || [...items]

      // Find current position of dragged item in preview
      const draggedCurrentPos = currentOrder.findIndex(item => item.id === draggedItem.id)
      if (draggedCurrentPos === -1) return

      // Create new order with item moved to target position
      const newOrder = [...currentOrder]
      const [removed] = newOrder.splice(draggedCurrentPos, 1)
      newOrder.splice(index, 0, removed)

      setPreviewOrder(newOrder)
    }
  }

  const handleDragLeave = (e) => {
    // Only clear if leaving the container entirely
    if (e.currentTarget === e.target) {
      setDragOverIndex(null)
    }
  }

  const handleSkinDrop = async (e, toIndex) => {
    e.preventDefault()
    if (!draggedItem) return

    const fromIndex = draggedItem.index

    if (fromIndex === toIndex || !selectedCharacter) {
      setDraggedItem(null)
      setDragOverIndex(null)
      setPreviewOrder(null)
      return
    }

    setReordering(true)

    try {
      const response = await fetch(`${API_URL}/storage/costumes/reorder`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          character: selectedCharacter,
          fromIndex,
          toIndex
        })
      })

      const data = await response.json()

      if (data.success) {
        // Refresh metadata to get updated order
        await onRefresh()
      } else {
        alert(`Reorder failed: ${data.error}`)
      }
    } catch (err) {
      console.error('Reorder error:', err)
      alert(`Reorder error: ${err.message}`)
    } finally {
      setReordering(false)
      setDraggedItem(null)
      setDragOverIndex(null)
      setPreviewOrder(null)
    }
  }

  const handleVariantDrop = async (e, toIndex) => {
    e.preventDefault()
    if (!draggedItem) return

    const fromIndex = draggedItem.index

    if (fromIndex === toIndex || !selectedStage) {
      setDraggedItem(null)
      setDragOverIndex(null)
      setPreviewOrder(null)
      return
    }

    setReordering(true)

    try {
      const response = await fetch(`${API_URL}/storage/stages/reorder`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          stageFolder: selectedStage.folder,
          fromIndex,
          toIndex
        })
      })

      const data = await response.json()

      if (data.success) {
        // Refresh stage variants and metadata
        await fetchStageVariants()
        await onRefresh()
      } else {
        alert(`Reorder failed: ${data.error}`)
      }
    } catch (err) {
      console.error('Reorder error:', err)
      alert(`Reorder error: ${err.message}`)
    } finally {
      setReordering(false)
      setDraggedItem(null)
      setDragOverIndex(null)
      setPreviewOrder(null)
    }
  }

  const handleDragEnd = () => {
    setDraggedItem(null)
    setDragOverIndex(null)
    setPreviewOrder(null)
  }

  // Context menu handlers
  const handleSkinContextMenu = (e, skin, index) => {
    e.preventDefault()
    setContextMenu({
      x: e.clientX,
      y: e.clientY,
      type: 'skin',
      item: skin,
      index
    })
  }

  const handleVariantContextMenu = (e, variant, index) => {
    e.preventDefault()
    setContextMenu({
      x: e.clientX,
      y: e.clientY,
      type: 'variant',
      item: variant,
      index
    })
  }

  const handleMoveToTop = async () => {
    if (!contextMenu) return

    setReordering(true)

    try {
      const endpoint = contextMenu.type === 'skin'
        ? `${API_URL}/storage/costumes/move-to-top`
        : `${API_URL}/storage/stages/move-to-top`

      const body = contextMenu.type === 'skin'
        ? {
            character: selectedCharacter,
            skinId: contextMenu.item.id
          }
        : {
            stageFolder: selectedStage.folder,
            variantId: contextMenu.item.id
          }

      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })

      const data = await response.json()

      if (data.success) {
        // Refresh data
        if (contextMenu.type === 'skin') {
          await onRefresh()
        } else {
          await fetchStageVariants()
          await onRefresh()
        }
      } else {
        alert(`Move to top failed: ${data.error}`)
      }
    } catch (err) {
      console.error('Move to top error:', err)
      alert(`Move to top error: ${err.message}`)
    } finally {
      setReordering(false)
      setContextMenu(null)
    }
  }

  const handleMoveToBottom = async () => {
    if (!contextMenu) return

    setReordering(true)

    try {
      const endpoint = contextMenu.type === 'skin'
        ? `${API_URL}/storage/costumes/move-to-bottom`
        : `${API_URL}/storage/stages/move-to-bottom`

      const body = contextMenu.type === 'skin'
        ? {
            character: selectedCharacter,
            skinId: contextMenu.item.id
          }
        : {
            stageFolder: selectedStage.folder,
            variantId: contextMenu.item.id
          }

      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })

      const data = await response.json()

      if (data.success) {
        // Refresh data
        if (contextMenu.type === 'skin') {
          await onRefresh()
        } else {
          await fetchStageVariants()
          await onRefresh()
        }
      } else {
        alert(`Move to bottom failed: ${data.error}`)
      }
    } catch (err) {
      console.error('Move to bottom error:', err)
      alert(`Move to bottom error: ${err.message}`)
    } finally {
      setReordering(false)
      setContextMenu(null)
    }
  }

  const closeContextMenu = () => {
    setContextMenu(null)
  }

  // Click-outside listener for context menu
  useEffect(() => {
    if (contextMenu) {
      const handleClick = () => closeContextMenu()
      document.addEventListener('click', handleClick)
      return () => document.removeEventListener('click', handleClick)
    }
  }, [contextMenu])

  // Merge default characters with metadata
  // Always show all 26 vanilla characters, even if they don't have custom skins
  const allCharacters = { ...metadata?.characters }

  // Add any missing default characters with 0 skins
  Object.keys(DEFAULT_CHARACTERS).forEach(charName => {
    if (!allCharacters[charName]) {
      allCharacters[charName] = { skins: [] }
    }
  })

  const characters = Object.keys(allCharacters).sort()

  // Edit Modal Component (reusable)
  const renderEditModal = () => (
    <>
      {showEditModal && editingItem && (
        <div className="edit-modal-overlay" onClick={handleCancel}>
          <div className="edit-modal-content" onClick={(e) => e.stopPropagation()}>
            <h2>Edit {editingItem.type === 'costume' ? 'Costume' : 'Stage Variant'}</h2>

            {/* Preview Image */}
            <div className="edit-preview">
              {editingItem.type === 'costume' ? (
                <>
                  {/* CSP Preview and edit */}
                  <div style={{ position: 'relative', marginBottom: '1rem' }}>
                    <h4>CSP</h4>
                    {cspPreview ? (
                      <img
                        src={cspPreview}
                        alt="New CSP preview"
                        style={{ width: '100%', maxHeight: '300px', objectFit: 'contain' }}
                      />
                    ) : editingItem.data.has_csp ? (
                      <img
                        src={`${editingItem.data.cspUrl}?t=${lastImageUpdate}`}
                        alt="CSP"
                        style={{ width: '100%', maxHeight: '300px', objectFit: 'contain' }}
                        onError={(e) => e.target.style.display = 'none'}
                      />
                    ) : (
                      <div className="edit-placeholder">
                        <span>{editingItem.data.color[0]}</span>
                      </div>
                    )}
                    <input
                      type="file"
                      accept="image/*"
                      onChange={handleCspChange}
                      style={{ display: 'none' }}
                      id="csp-file-input"
                    />
                    <button
                      className="btn-edit-screenshot"
                      onClick={() => document.getElementById('csp-file-input').click()}
                      title="Replace CSP"
                      style={{ position: 'absolute', bottom: '10px', right: '10px' }}
                    >
                      ✎
                    </button>
                  </div>

                  {/* Stock Icon Preview and edit */}
                  <div style={{ position: 'relative' }}>
                    <h4>Stock Icon</h4>
                    {stockPreview ? (
                      <img
                        src={stockPreview}
                        alt="New stock preview"
                        style={{ width: '100px', height: 'auto', objectFit: 'contain' }}
                      />
                    ) : editingItem.data.has_stock ? (
                      <img
                        src={`${editingItem.data.stockUrl}?t=${lastImageUpdate}`}
                        alt="Stock"
                        style={{ width: '100px', height: 'auto', objectFit: 'contain' }}
                        onError={(e) => e.target.style.display = 'none'}
                      />
                    ) : (
                      <div className="edit-placeholder" style={{ width: '100px', height: '100px' }}>
                        <span>{editingItem.data.color[0]}</span>
                      </div>
                    )}
                    <input
                      type="file"
                      accept="image/*"
                      onChange={handleStockChange}
                      style={{ display: 'none' }}
                      id="stock-file-input"
                    />
                    <button
                      className="btn-edit-screenshot"
                      onClick={() => document.getElementById('stock-file-input').click()}
                      title="Replace stock icon"
                      style={{ position: 'absolute', bottom: '10px', right: '10px' }}
                    >
                      ✎
                    </button>
                  </div>
                </>
              ) : (
                <>
                  {/* Show new screenshot preview if selected, otherwise show current screenshot */}
                  {screenshotPreview ? (
                    <img
                      src={screenshotPreview}
                      alt="New screenshot preview"
                    />
                  ) : editingItem.data.hasScreenshot ? (
                    <img
                      src={editingItem.data.screenshotUrl}
                      alt="Preview"
                      onError={(e) => e.target.style.display = 'none'}
                    />
                  ) : (
                    <div className="edit-placeholder">
                      <span>{editingItem.data.name[0]}</span>
                    </div>
                  )}
                  {/* Hidden file input for screenshot replacement */}
                  <input
                    type="file"
                    accept="image/*"
                    onChange={handleScreenshotChange}
                    style={{ display: 'none' }}
                    id="screenshot-file-input"
                  />
                  {/* Pen button overlay for stage screenshots */}
                  <button
                    className="btn-edit-screenshot"
                    onClick={() => document.getElementById('screenshot-file-input').click()}
                    title="Replace screenshot"
                  >
                    ✎
                  </button>
                </>
              )}
            </div>

            {/* Name Input */}
            <div className="edit-field">
              <label>{editingItem.type === 'costume' ? 'Color Name:' : 'Variant Name:'}</label>
              <input
                type="text"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                placeholder="Enter name..."
                disabled={saving || deleting}
                autoFocus
              />
            </div>

            {/* Info */}
            <div className="edit-info">
              {editingItem.type === 'costume' ? (
                <>
                  <p><strong>Character:</strong> {editingItem.data.character}</p>
                  <p><strong>ID:</strong> {editingItem.data.id}</p>
                </>
              ) : (
                <>
                  <p><strong>Stage:</strong> {editingItem.data.stageName}</p>
                  <p><strong>ID:</strong> {editingItem.data.id}</p>
                </>
              )}
            </div>

            {/* Slippi Safety Controls */}
            <div className="slippi-controls" style={{
              padding: '1rem',
              margin: '1rem 0',
              borderRadius: '4px',
              backgroundColor: '#2a2a2a',
              border: '1px solid #444'
            }}>
              <h4 style={{ marginTop: 0, color: '#fff' }}>Slippi Safety</h4>

              {editingItem.type === 'costume' ? (
                <>
                  <div style={{ marginBottom: '0.75rem' }}>
                    <p style={{ marginBottom: '0.5rem', color: '#ccc' }}>
                      <strong>Current Status:</strong>{' '}
                      <span style={{
                        color: editingItem.data.slippi_safe ? '#4caf50' : '#f44336',
                        fontWeight: 'bold'
                      }}>
                        {editingItem.data.slippi_safe ? 'Slippi Safe' : 'Not Slippi Safe'}
                      </span>
                      {editingItem.data.slippi_manual_override && (
                        <span style={{ marginLeft: '0.5rem', fontSize: '0.85em', color: '#999' }}>
                          (Manual Override)
                        </span>
                      )}
                    </p>
                  </div>

                  <div style={{ marginBottom: '0.75rem' }}>
                    <button
                      className="btn-secondary"
                      onClick={() => handleSlippiRetest(false)}
                      disabled={saving || deleting}
                      style={{ width: '100%', marginBottom: '0.5rem' }}
                    >
                      Retest
                    </button>
                  </div>

                  <div style={{ marginTop: '0.75rem' }}>
                    <label style={{ display: 'block', marginBottom: '0.5rem', color: '#ccc', fontSize: '0.9em' }}>
                      Manual Override:
                    </label>
                    <select
                      value={editingItem.data.slippi_safe ? 'safe' : 'unsafe'}
                      onChange={(e) => {
                        const newStatus = e.target.value === 'safe'
                        if (newStatus !== editingItem.data.slippi_safe) {
                          handleSlippiOverride()
                        }
                      }}
                      disabled={saving || deleting}
                      style={{
                        width: '100%',
                        padding: '0.5rem',
                        borderRadius: '4px',
                        border: '1px solid #555',
                        backgroundColor: '#1a1a1a',
                        color: '#fff',
                        fontSize: '1rem'
                      }}
                    >
                      <option value="safe">Slippi Safe</option>
                      <option value="unsafe">Not Slippi Safe</option>
                    </select>
                  </div>
                </>
              ) : (
                <>
                  <p style={{ marginBottom: '0.5rem', color: '#ccc' }}>
                    <strong>Status:</strong>{' '}
                    <span style={{
                      color: editSlippiSafe === null
                        ? '#6c757d'
                        : (editSlippiSafe ? '#4caf50' : '#f44336'),
                      fontWeight: 'bold'
                    }}>
                      {editSlippiSafe === null
                        ? 'Unknown'
                        : (editSlippiSafe ? 'Slippi Safe' : 'Not Slippi Safe')}
                    </span>
                  </p>
                  <p style={{ fontSize: '0.9em', color: '#999', marginBottom: '0.75rem' }}>
                    Stages cannot be auto-tested. Set manually.
                  </p>
                  <div>
                    <label style={{ display: 'block', marginBottom: '0.5rem', color: '#ccc', fontSize: '0.9em' }}>
                      Manual Setting:
                    </label>
                    <select
                      value={editSlippiSafe === null
                        ? 'unknown'
                        : (editSlippiSafe ? 'safe' : 'unsafe')}
                      onChange={(e) => {
                        const newValue = e.target.value
                        if (newValue === 'unknown') {
                          setEditSlippiSafe(null)
                        } else {
                          setEditSlippiSafe(newValue === 'safe')
                        }
                      }}
                      disabled={saving || deleting}
                      style={{
                        width: '100%',
                        padding: '0.5rem',
                        borderRadius: '4px',
                        border: '1px solid #555',
                        backgroundColor: '#1a1a1a',
                        color: '#fff',
                        fontSize: '1rem'
                      }}
                    >
                      <option value="unknown">Unknown</option>
                      <option value="safe">Slippi Safe</option>
                      <option value="unsafe">Not Slippi Safe</option>
                    </select>
                  </div>
                </>
              )}
            </div>

            {/* Buttons */}
            <div className="edit-buttons">
              <button
                className="btn-save"
                onClick={handleSave}
                disabled={saving || deleting || exporting}
              >
                {saving ? 'Saving...' : 'Save'}
              </button>
              <button
                className="btn-cancel"
                onClick={handleCancel}
                disabled={saving || deleting || exporting}
              >
                Cancel
              </button>
              <button
                className="btn-export"
                onClick={handleExport}
                disabled={saving || deleting || exporting}
              >
                {exporting ? 'Exporting...' : 'Export'}
              </button>
              <button
                className="btn-delete-modal"
                onClick={handleDelete}
                disabled={saving || deleting || exporting}
              >
                {deleting ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )

  const renderSlippiDialog = () => {
    const isRetest = retestingItem !== null
    const handleChoice = isRetest ? handleRetestFixChoice : handleSlippiChoice

    return (
      <>
        {showSlippiDialog && slippiDialogData && (
          <div className="edit-modal-overlay" onClick={() => handleChoice('cancel')}>
            <div className="edit-modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '500px' }}>
              <h2>Slippi Safety Warning</h2>

              <div style={{ padding: '1rem 0' }}>
                <p style={{ marginBottom: '1rem' }}>
                  This costume is not Slippi safe. Choose an action:
                </p>

                {slippiDialogData.unsafe_costumes && (
                  <div style={{
                    backgroundColor: '#fff3cd',
                    border: '1px solid #ffc107',
                    borderRadius: '4px',
                    padding: '0.75rem',
                    marginBottom: '1rem'
                  }}>
                    <strong>Affected costumes:</strong>
                    <ul style={{ marginTop: '0.5rem', marginBottom: 0 }}>
                      {slippiDialogData.unsafe_costumes.map((costume, idx) => (
                        <li key={idx}>{costume.character} - {costume.color}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                <button
                  className="btn-save"
                  onClick={() => handleChoice('fix')}
                  style={{ width: '100%' }}
                >
                  {isRetest ? 'Fix' : 'Fix & Import'}
                </button>
                <button
                  className="btn-secondary"
                  onClick={() => handleChoice('import_as_is')}
                  style={{ width: '100%' }}
                >
                  {isRetest ? 'Keep As-Is' : 'Import As-Is'}
                </button>
                <button
                  className="btn-cancel"
                  onClick={() => handleChoice('cancel')}
                  style={{ width: '100%' }}
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        )}
      </>
    )
  }

  // Context menu component
  const renderContextMenu = () => {
    if (!contextMenu) return null

    return (
      <div
        className="context-menu"
        style={{ top: contextMenu.y, left: contextMenu.x }}
        onClick={(e) => e.stopPropagation()}
      >
        <button onClick={handleMoveToTop}>Move to Top</button>
        <button onClick={handleMoveToBottom}>Move to Bottom</button>
      </div>
    )
  }

  // If a stage is selected, show its variants
  if (selectedStage) {
    const stageInfo = selectedStage
    const variants = stageVariants[selectedStage.code] || []

    return (
      <div className="storage-viewer">
        <div className="character-detail">
          <button
            onClick={() => setSelectedStage(null)}
            className="back-button"
          >
            ← Back to Stages
          </button>

          <h2>{stageInfo?.name}</h2>
          <p className="skin-count">{variants.length} variant{variants.length !== 1 ? 's' : ''}</p>

          {variants.length === 0 ? (
            <div className="no-skins-message">
              <p>No stage variants yet. Add some to your storage!</p>
            </div>
          ) : (
            <div className="skins-grid">
              {(previewOrder || variants).map((variant, idx) => {
                const isDragging = draggedItem && variant.id === draggedItem.id
                return (
                  <div
                    key={variant.id}
                    className={`skin-card ${isDragging ? 'dragging' : ''}`}
                    draggable={!reordering}
                    onDragStart={(e) => handleDragStart(e, variants.findIndex(v => v.id === variant.id), variants)}
                    onDragOver={handleDragOver}
                    onDragEnter={(e) => handleDragEnter(e, idx, variants)}
                    onDragLeave={handleDragLeave}
                    onDrop={(e) => handleVariantDrop(e, idx)}
                    onDragEnd={handleDragEnd}
                    onContextMenu={(e) => handleVariantContextMenu(e, variant, idx)}
                    style={{ opacity: isDragging ? 0.5 : 1 }}
                  >
                  <div className="skin-images">
                    <div className="skin-image-container">
                      {variant.hasScreenshot ? (
                        <img
                          src={`${API_URL.replace('/api/mex', '')}${variant.screenshotUrl}`}
                          alt={variant.name}
                          className="skin-csp"
                          onError={(e) => {
                            e.target.style.display = 'none'
                            e.target.nextSibling.style.display = 'flex'
                          }}
                        />
                      ) : (
                        <div className="skin-placeholder" style={{ display: 'flex' }}>
                          <span className="skin-initial">{variant.name[0]}</span>
                        </div>
                      )}
                      {/* Slippi badge for stages - show unknown if not set */}
                      <div style={{
                        position: 'absolute',
                        top: '8px',
                        left: '8px',
                        backgroundColor: variant.slippi_tested
                          ? (variant.slippi_safe ? '#28a745' : '#dc3545')
                          : '#6c757d',
                        color: 'white',
                        padding: '4px 8px',
                        borderRadius: '4px',
                        fontSize: '0.75rem',
                        fontWeight: 'bold',
                        boxShadow: '0 2px 4px rgba(0,0,0,0.2)'
                      }}>
                        {variant.slippi_tested
                          ? (variant.slippi_safe ? 'Slippi Safe' : 'Not Slippi Safe')
                          : 'Unknown'}
                      </div>
                      <button
                        className="btn-edit"
                        onClick={(e) => {
                          e.stopPropagation()
                          e.preventDefault()
                          handleEditClick('stage', {
                            id: variant.id,  // ← Use the immutable ID for API calls
                            name: variant.name,  // ← Use the editable name for display
                            stageCode: stageInfo?.code,
                            stageFolder: stageInfo?.folder,
                            stageName: stageInfo?.name,
                            screenshotUrl: variant.screenshotUrl,
                            hasScreenshot: variant.hasScreenshot,
                            slippi_safe: variant.slippi_safe,
                            slippi_tested: variant.slippi_tested
                          })
                        }}
                        title="Edit variant"
                      >
                        ✎
                      </button>
                    </div>
                  </div>

                  <div className="skin-info">
                    <div className="skin-color">{variant.name}</div>
                  </div>
                </div>
              )
            })}
            </div>
          )}
        </div>
        {renderEditModal()}
        {renderSlippiDialog()}
        {renderContextMenu()}
      </div>
    )
  }

  // If a character is selected, show their skins
  if (selectedCharacter) {
    const charData = allCharacters[selectedCharacter]
    // Filter out hidden skins (e.g., Ice Climbers Nana entries)
    const visibleSkins = charData?.skins?.filter(skin => skin.visible !== false) || []
    const skinCount = visibleSkins.length

    return (
      <div className="storage-viewer">
        <div className="character-detail">
          <button
            onClick={() => setSelectedCharacter(null)}
            className="back-button"
          >
            ← Back to Characters
          </button>

          <h2>{selectedCharacter}</h2>
          <p className="skin-count">{skinCount} skin{skinCount !== 1 ? 's' : ''}</p>

          {skinCount === 0 ? (
            <div className="no-skins-message">
              <p>No custom skins yet. Add some using the intake system!</p>
            </div>
          ) : (
            <div className="skins-grid">
              {(previewOrder || visibleSkins).map((skin, idx) => {
                const isDragging = draggedItem && skin.id === draggedItem.id
                return (
                  <div
                    key={skin.id}
                    className={`skin-card ${isDragging ? 'dragging' : ''}`}
                    draggable={!reordering}
                    onDragStart={(e) => handleDragStart(e, visibleSkins.findIndex(s => s.id === skin.id), visibleSkins)}
                    onDragOver={handleDragOver}
                    onDragEnter={(e) => handleDragEnter(e, idx, visibleSkins)}
                    onDragLeave={handleDragLeave}
                    onDrop={(e) => handleSkinDrop(e, idx)}
                    onDragEnd={handleDragEnd}
                    onContextMenu={(e) => handleSkinContextMenu(e, skin, idx)}
                    style={{ opacity: isDragging ? 0.5 : 1 }}
                  >
                  <div className="skin-image-container">
                    {skin.has_csp ? (
                      <img
                        src={`${API_URL.replace('/api/mex', '')}/storage/${selectedCharacter}/${skin.id}_csp.png?t=${lastImageUpdate}`}
                        alt={`${selectedCharacter} - ${skin.color}`}
                        className="skin-csp"
                        onError={(e) => {
                          e.target.style.display = 'none'
                          e.target.nextSibling.style.display = 'flex'
                        }}
                      />
                    ) : null}
                    <div className="skin-placeholder" style={{ display: skin.has_csp ? 'none' : 'flex' }}>
                      <span className="skin-initial">{skin.color[0]}</span>
                    </div>
                    <button
                      className="btn-edit"
                      onClick={(e) => {
                        e.stopPropagation()
                        e.preventDefault()
                        handleEditClick('costume', {
                          id: skin.id,
                          character: selectedCharacter,
                          color: skin.color,
                          has_csp: skin.has_csp,
                          has_stock: skin.has_stock,
                          cspUrl: `${API_URL.replace('/api/mex', '')}/storage/${selectedCharacter}/${skin.id}_csp.png`,
                          stockUrl: skin.has_stock ? `${API_URL.replace('/api/mex', '')}/storage/${selectedCharacter}/${skin.id}_stc.png` : null,
                          slippi_safe: skin.slippi_safe,
                          slippi_tested: skin.slippi_tested,
                          slippi_manual_override: skin.slippi_manual_override
                        })
                      }}
                      title="Edit costume"
                    >
                      ✎
                    </button>
                  </div>

                  <div className="skin-badges-row">
                    {skin.has_stock && (
                      <div className="stock-icon-small">
                        <img
                          src={`${API_URL.replace('/api/mex', '')}/storage/${selectedCharacter}/${skin.id}_stc.png?t=${lastImageUpdate}`}
                          alt={`${selectedCharacter} stock`}
                          className="skin-stock"
                        />
                      </div>
                    )}
                    {skin.slippi_tested && (
                      <div className={`slippi-badge-small ${skin.slippi_safe ? 'safe' : 'unsafe'}`}>
                        {skin.slippi_safe ? 'Slippi Safe' : 'Not Slippi Safe'}
                      </div>
                    )}
                  </div>

                  <div className="skin-info">
                    <div className="skin-color">{skin.color}</div>
                  </div>
                </div>
              )
            })}
            </div>
          )}
        </div>
        {renderEditModal()}
        {renderSlippiDialog()}
        {renderContextMenu()}
      </div>
    )
  }

  // Character or Stage selection grid
  return (
    <div className="storage-viewer">
      {/* Mode Switcher */}
      <div className="mode-switcher">
        <button
          className={`mode-btn ${mode === 'characters' ? 'active' : ''}`}
          onClick={() => {
            setMode('characters')
            setSelectedStage(null)
          }}
        >
          Characters
        </button>
        <button
          className={`mode-btn ${mode === 'stages' ? 'active' : ''}`}
          onClick={() => {
            setMode('stages')
            setSelectedCharacter(null)
          }}
        >
          Stages
        </button>
        <button
          className={`mode-btn ${mode === 'patches' ? 'active' : ''}`}
          onClick={() => {
            setMode('patches')
            setSelectedCharacter(null)
            setSelectedStage(null)
          }}
        >
          Patches
        </button>
      </div>

      {/* Import File button - only for characters and stages */}
      {(mode === 'characters' || mode === 'stages') && (
        <div className="import-file-container">
          <label className="intake-import-btn" style={{ cursor: importing ? 'not-allowed' : 'pointer', opacity: importing ? 0.6 : 1 }}>
            {importing ? 'Importing...' : 'Import File'}
            <input
              type="file"
              accept=".zip,.7z"
              onChange={handleFileImport}
              disabled={importing}
              style={{ display: 'none' }}
            />
          </label>
          {importMessage && (
            <div className={`import-message ${importMessage.includes('failed') || importMessage.includes('Error') || importMessage.includes('✗') ? 'error' : 'success'}`}>
              {importMessage}
            </div>
          )}
        </div>
      )}

      {mode === 'characters' ? (
        <div className="characters-grid">
        {isLoading ? (
          // Skeleton loading for characters
          Array.from({ length: 12 }).map((_, idx) => (
            <SkeletonCard key={`skeleton-${idx}`} />
          ))
        ) : characters.map((characterName) => {
          const charData = allCharacters[characterName]
          // Only count visible skins (exclude hidden Ice Climbers Nana entries)
          const visibleSkins = charData?.skins?.filter(skin => skin.visible !== false) || []
          const skinCount = visibleSkins.length

          // ALWAYS use vanilla default costume code from DEFAULT_CHARACTERS
          const costumeCode = DEFAULT_CHARACTERS[characterName]?.defaultCostume

          // ALWAYS use vanilla CSP on homepage for consistency (like vanilla game)
          const vanillaCspPath = costumeCode
            ? `${BACKEND_URL}/vanilla/${characterName}/${costumeCode}/csp.png`
            : null

          return (
            <div
              key={characterName}
              className="character-card"
              onClick={() => setSelectedCharacter(characterName)}
            >
              <div className="character-image-container">
                {vanillaCspPath ? (
                  <img
                    src={vanillaCspPath}
                    alt={characterName}
                    className="character-csp"
                    onError={(e) => {
                      e.target.style.display = 'none'
                      e.target.nextSibling.style.display = 'flex'
                    }}
                  />
                ) : null}
                <div className="character-placeholder" style={{ display: vanillaCspPath ? 'none' : 'flex' }}>
                  <span className="character-initial">{characterName[0]}</span>
                </div>
              </div>

              <h3 className="character-name">{characterName}</h3>
              <p className="skin-count">{skinCount} skin{skinCount !== 1 ? 's' : ''}</p>
            </div>
          )
        })}
      </div>
      ) : mode === 'stages' ? (
        // Stages grid
        <div className="stages-grid">
          {isLoading ? (
            // Skeleton loading for stages
            Array.from({ length: 6 }).map((_, idx) => (
              <SkeletonCard key={`skeleton-stage-${idx}`} />
            ))
          ) : DAS_STAGES.map((stage) => {
            const variants = stageVariants[stage.code] || []
            const variantCount = variants.length

            // ALWAYS use vanilla stage screenshot (like how characters use vanilla CSPs)
            const vanillaImagePath = stage.vanillaImage

            return (
              <div
                key={stage.code}
                className="character-card"
                onClick={() => setSelectedStage(stage)}
              >
                <div className="character-image-container">
                  <img
                    src={vanillaImagePath}
                    alt={stage.name}
                    className="character-csp"
                    onError={(e) => {
                      e.target.style.display = 'none'
                      e.target.nextSibling.style.display = 'flex'
                    }}
                  />
                  <div className="character-placeholder" style={{ display: 'none' }}>
                    <span className="character-initial">{stage.name[0]}</span>
                  </div>
                </div>

                <h3 className="character-name">{stage.name}</h3>
                <p className="skin-count">{variantCount} variant{variantCount !== 1 ? 's' : ''}</p>
              </div>
            )
          })}
        </div>
      ) : (
        // Patches list
        <div className="patches-section">
          <div className="patches-header">
            <button
              className="intake-import-btn"
              onClick={() => setShowXdeltaImportModal(true)}
            >
              Import Patch
            </button>
          </div>

          {xdeltaPatches.length === 0 ? (
            <div className="no-patches-message">
              <p>No xdelta patches yet. Import a patch to get started!</p>
            </div>
          ) : (
            <div className="patches-list">
              {xdeltaPatches.map((patch) => (
                <div key={patch.id} className="patch-row">
                  <div className="patch-row-image">
                    {patch.imageUrl ? (
                      <img
                        src={`${BACKEND_URL}${patch.imageUrl}`}
                        alt={patch.name}
                        onError={(e) => {
                          e.target.style.display = 'none'
                          e.target.nextSibling.style.display = 'flex'
                        }}
                      />
                    ) : null}
                    <div className="patch-row-placeholder" style={{ display: patch.imageUrl ? 'none' : 'flex' }}>
                      {patch.name[0]}
                    </div>
                  </div>

                  <div className="patch-row-info">
                    <h4 className="patch-row-name">{patch.name}</h4>
                    {patch.description && (
                      <p className="patch-row-description">{patch.description}</p>
                    )}
                  </div>

                  <div className="patch-row-actions">
                    <button
                      className="btn-edit-small"
                      onClick={() => handleEditXdelta(patch)}
                      title="Edit"
                    >
                      ✎
                    </button>
                    <button
                      className="btn-build-iso"
                      onClick={() => handleBuildXdeltaIso(patch)}
                    >
                      Build ISO
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* XDelta Import Modal */}
          {showXdeltaImportModal && (
            <div className="edit-modal-overlay" onClick={() => setShowXdeltaImportModal(false)}>
              <div className="edit-modal-content" onClick={(e) => e.stopPropagation()}>
                <h2>Import XDelta Patch</h2>

                <div className="edit-field">
                  <label>XDelta File:</label>
                  <input
                    type="file"
                    accept=".xdelta"
                    onChange={(e) => setXdeltaImportData({
                      ...xdeltaImportData,
                      file: e.target.files[0],
                      name: xdeltaImportData.name || (e.target.files[0]?.name.replace('.xdelta', '') || '')
                    })}
                  />
                </div>

                <div className="edit-field">
                  <label>Name:</label>
                  <input
                    type="text"
                    value={xdeltaImportData.name}
                    onChange={(e) => setXdeltaImportData({ ...xdeltaImportData, name: e.target.value })}
                    placeholder="Patch name..."
                  />
                </div>

                <div className="edit-field">
                  <label>Description (optional):</label>
                  <textarea
                    value={xdeltaImportData.description}
                    onChange={(e) => setXdeltaImportData({ ...xdeltaImportData, description: e.target.value })}
                    placeholder="Description..."
                    rows={3}
                  />
                </div>

                <div className="edit-field">
                  <label>Image (optional):</label>
                  <input
                    type="file"
                    accept="image/*"
                    onChange={(e) => setXdeltaImportData({ ...xdeltaImportData, image: e.target.files[0] })}
                  />
                </div>

                <div className="edit-buttons">
                  <button
                    className="btn-save"
                    onClick={handleImportXdelta}
                    disabled={importingXdelta || !xdeltaImportData.file}
                  >
                    {importingXdelta ? 'Importing...' : 'Import'}
                  </button>
                  <button
                    className="btn-cancel"
                    onClick={() => {
                      setShowXdeltaImportModal(false)
                      setXdeltaImportData({ name: '', description: '', file: null, image: null })
                    }}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* XDelta Edit Modal */}
          {showXdeltaEditModal && editingXdelta && (
            <div className="edit-modal-overlay" onClick={() => {
              setShowXdeltaEditModal(false)
              setEditingXdelta(null)
            }}>
              <div className="edit-modal-content" onClick={(e) => e.stopPropagation()}>
                <h2>Edit Patch</h2>

                <div className="edit-preview">
                  {editingXdelta.imageUrl ? (
                    <img
                      src={`${BACKEND_URL}${editingXdelta.imageUrl}?t=${Date.now()}`}
                      alt={editingXdelta.name}
                    />
                  ) : (
                    <div className="edit-placeholder">
                      <span>{editingXdelta.name[0]}</span>
                    </div>
                  )}
                  <input
                    type="file"
                    accept="image/*"
                    onChange={handleUpdateXdeltaImage}
                    style={{ display: 'none' }}
                    id="xdelta-image-input"
                  />
                  <button
                    className="btn-edit-screenshot"
                    onClick={() => document.getElementById('xdelta-image-input').click()}
                    title="Replace image"
                  >
                    ✎
                  </button>
                </div>

                <div className="edit-field">
                  <label>Name:</label>
                  <input
                    type="text"
                    value={editingXdelta.name}
                    onChange={(e) => setEditingXdelta({ ...editingXdelta, name: e.target.value })}
                  />
                </div>

                <div className="edit-field">
                  <label>Description:</label>
                  <textarea
                    value={editingXdelta.description || ''}
                    onChange={(e) => setEditingXdelta({ ...editingXdelta, description: e.target.value })}
                    rows={3}
                  />
                </div>

                <div className="edit-buttons">
                  <button className="btn-save" onClick={handleSaveXdeltaEdit}>
                    Save
                  </button>
                  <button
                    className="btn-cancel"
                    onClick={() => {
                      setShowXdeltaEditModal(false)
                      setEditingXdelta(null)
                    }}
                  >
                    Cancel
                  </button>
                  <button
                    className="btn-delete-modal"
                    onClick={() => {
                      handleDeleteXdelta(editingXdelta.id)
                      setShowXdeltaEditModal(false)
                      setEditingXdelta(null)
                    }}
                  >
                    Delete
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {renderEditModal()}
      {renderSlippiDialog()}

      {/* XDelta Build Modal */}
      {showXdeltaBuildModal && (
        <div className="iso-builder-overlay">
          <div className="iso-builder-modal">
            <div className="modal-header">
              <h2>Build ISO</h2>
              {xdeltaBuildState !== 'building' && (
                <button className="close-btn" onClick={closeXdeltaBuildModal}>×</button>
              )}
            </div>

            <div className="modal-body">
              {xdeltaBuildState === 'building' && (
                <div className="export-progress">
                  <div className="progress-header">
                    <h3>Building ISO...</h3>
                    <span className="progress-percentage">{xdeltaBuildProgress}%</span>
                  </div>

                  <div className="progress-bar">
                    <div
                      className="progress-fill"
                      style={{ width: `${xdeltaBuildProgress}%` }}
                    ></div>
                  </div>

                  <p className="progress-message">
                    {xdeltaBuildMessage || `Applying patch: ${xdeltaBuildPatch?.name}`}
                  </p>

                  <div className="export-spinner">
                    <div className="spinner"></div>
                  </div>
                </div>
              )}

              {xdeltaBuildState === 'complete' && (
                <div className="export-complete">
                  <div className="success-icon">✓</div>
                  <h3>Build Complete!</h3>
                  <p>Your patched ISO is ready to download.</p>
                  <div className="complete-actions">
                    <button className="btn-download" onClick={handleDownloadXdeltaIso}>
                      Download {xdeltaBuildFilename}
                    </button>
                    <button className="btn-secondary" onClick={closeXdeltaBuildModal}>
                      Close
                    </button>
                  </div>
                </div>
              )}

              {xdeltaBuildState === 'error' && (
                <div className="export-error">
                  <div className="error-icon">✕</div>
                  <h3>Build Failed</h3>
                  <p className="error-message">{xdeltaBuildError}</p>
                  <button className="btn-secondary" onClick={closeXdeltaBuildModal}>
                    Close
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

