import { useState, useEffect } from 'react'
import './StorageViewer.css'
import { DEFAULT_CHARACTERS } from '../defaultCharacters'

const API_URL = 'http://127.0.0.1:5000/api/mex'

const DAS_STAGES = [
  { code: 'GrOp', name: 'Dreamland', folder: 'dreamland', vanillaImage: '/vanilla/stages/dreamland.jpg' },
  { code: 'GrPs', name: 'Pokemon Stadium', folder: 'pokemon_stadium', vanillaImage: '/vanilla/stages/pokemon stadium.jpg' },
  { code: 'GrSt', name: "Yoshi's Story", folder: 'yoshis_story', vanillaImage: '/vanilla/stages/Yoshis story.jpg' },
  { code: 'GrNBa', name: 'Battlefield', folder: 'battlefield', vanillaImage: '/vanilla/stages/battlefield.jpg' },
  { code: 'GrIz', name: 'Fountain of Dreams', folder: 'fountain_of_dreams', vanillaImage: '/vanilla/stages/Fountain of Dreams.webp' },
  { code: 'GrNLa', name: 'Final Destination', folder: 'final_destination', vanillaImage: '/vanilla/stages/final destination.png' }
]

export default function StorageViewer({ metadata, onRefresh }) {
  const [mode, setMode] = useState('characters') // 'characters' or 'stages'
  const [selectedCharacter, setSelectedCharacter] = useState(null)
  const [selectedStage, setSelectedStage] = useState(null)
  const [stageVariants, setStageVariants] = useState({})
  const [importing, setImporting] = useState(false)
  const [importMessage, setImportMessage] = useState('')

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
  const [newScreenshot, setNewScreenshot] = useState(null) // File object for new screenshot
  const [screenshotPreview, setScreenshotPreview] = useState(null) // Preview URL for new screenshot
  const [newCsp, setNewCsp] = useState(null) // File object for new CSP
  const [cspPreview, setCspPreview] = useState(null) // Preview URL for new CSP
  const [newStock, setNewStock] = useState(null) // File object for new stock
  const [stockPreview, setStockPreview] = useState(null) // Preview URL for new stock

  // Fetch stage variants when in stages mode
  useEffect(() => {
    if (mode === 'stages') {
      fetchStageVariants()
    }
  }, [mode])

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
        setTimeout(() => {
          window.location.reload()
        }, 1500)
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

  const handleStageSlippiToggle = async (newStatus) => {
    if (!editingItem || editingItem.type !== 'stage') return

    try {
      const response = await fetch(`${API_URL}/storage/stages/set-slippi`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          stageName: editingItem.data.stageFolder,  // Use folder name, not display name
          variantId: editingItem.data.id,
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

      setShowEditModal(false)
      setEditingItem(null)
      onRefresh()
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
        setShowEditModal(false)
        setEditingItem(null)
        onRefresh()
      } else {
        alert(`Delete failed: ${data.error}`)
      }
    } catch (err) {
      alert(`Delete error: ${err.message}`)
    } finally {
      setDeleting(false)
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
  }

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
                        src={editingItem.data.cspUrl}
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
                        src={editingItem.data.stockUrl}
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
                      color: editingItem.data.slippi_tested
                        ? (editingItem.data.slippi_safe ? '#4caf50' : '#f44336')
                        : '#6c757d',
                      fontWeight: 'bold'
                    }}>
                      {editingItem.data.slippi_tested
                        ? (editingItem.data.slippi_safe ? 'Slippi Safe' : 'Not Slippi Safe')
                        : 'Unknown'}
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
                      value={editingItem.data.slippi_tested
                        ? (editingItem.data.slippi_safe ? 'safe' : 'unsafe')
                        : 'unknown'}
                      onChange={(e) => {
                        const newValue = e.target.value
                        if (newValue !== 'unknown') {
                          const newStatus = newValue === 'safe'
                          if (!editingItem.data.slippi_tested || newStatus !== editingItem.data.slippi_safe) {
                            handleStageSlippiToggle(newStatus)
                          }
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
                disabled={saving || deleting}
              >
                {saving ? 'Saving...' : 'Save'}
              </button>
              <button
                className="btn-cancel"
                onClick={handleCancel}
                disabled={saving || deleting}
              >
                Cancel
              </button>
              <button
                className="btn-delete-modal"
                onClick={handleDelete}
                disabled={saving || deleting}
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

  // If a stage is selected, show its variants
  if (selectedStage) {
    const stageInfo = DAS_STAGES.find(s => s.code === selectedStage)
    const variants = stageVariants[selectedStage] || []

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
              {variants.map((variant) => (
                <div key={variant.id} className="skin-card">
                  <div className="skin-header">
                    <h4 className="skin-title">{variant.name}</h4>
                  </div>

                  <div className="skin-images">
                    <div className="skin-image-container">
                      {variant.hasScreenshot ? (
                        <img
                          src={variant.screenshotUrl}
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
                    <div className="skin-id">{variant.id}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
        {renderEditModal()}
        {renderSlippiDialog()}
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
              {visibleSkins.map((skin) => (
                <div key={skin.id} className="skin-card">
                  <div className="skin-image-container">
                    {skin.has_csp ? (
                      <img
                        src={`/storage/${selectedCharacter}/${skin.id}_csp.png`}
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
                          cspUrl: `/storage/${selectedCharacter}/${skin.id}_csp.png`,
                          stockUrl: skin.has_stock ? `/storage/${selectedCharacter}/${skin.id}_stc.png` : null,
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
                          src={`/storage/${selectedCharacter}/${skin.id}_stc.png`}
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
                    <div className="skin-id">{skin.id}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
        {renderEditModal()}
        {renderSlippiDialog()}
      </div>
    )
  }

  // Character or Stage selection grid
  return (
    <div className="storage-viewer">
      <div className="storage-header">
        <div className="storage-actions">
          <label className="intake-import-btn" style={{ cursor: importing ? 'not-allowed' : 'pointer', opacity: importing ? 0.6 : 1 }}>
            {importing ? 'Importing...' : 'Import File'}
            <input
              type="file"
              accept=".zip"
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
      </div>

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
      </div>

      {mode === 'characters' ? (
        <div className="characters-grid">
        {characters.map((characterName) => {
          const charData = allCharacters[characterName]
          // Only count visible skins (exclude hidden Ice Climbers Nana entries)
          const visibleSkins = charData?.skins?.filter(skin => skin.visible !== false) || []
          const skinCount = visibleSkins.length

          // ALWAYS use vanilla default costume code from DEFAULT_CHARACTERS
          const costumeCode = DEFAULT_CHARACTERS[characterName]?.defaultCostume

          // ALWAYS use vanilla CSP on homepage for consistency (like vanilla game)
          const vanillaCspPath = costumeCode
            ? `/vanilla/${characterName}/${costumeCode}/csp.png`
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
      ) : (
        // Stages grid
        <div className="stages-grid">
          {DAS_STAGES.map((stage) => {
            const variants = stageVariants[stage.code] || []
            const variantCount = variants.length

            // ALWAYS use vanilla stage screenshot (like how characters use vanilla CSPs)
            const vanillaImagePath = stage.vanillaImage

            return (
              <div
                key={stage.code}
                className="character-card"
                onClick={() => setSelectedStage(stage.code)}
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
      )}

      {renderEditModal()}
      {renderSlippiDialog()}
    </div>
  )
}
