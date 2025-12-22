import { useState, useEffect } from 'react'
import './Settings.css'

const API_URL = 'http://127.0.0.1:5000/api/mex'

export default function Settings({ metadata }) {
  const [showConfirmModal, setShowConfirmModal] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [message, setMessage] = useState({ text: '', type: '' }) // type: 'success' | 'error'

  // Backup/Restore state
  const [backingUp, setBackingUp] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const [showRestoreModal, setShowRestoreModal] = useState(false)
  const [restoreFile, setRestoreFile] = useState(null)
  const [restoreMode, setRestoreMode] = useState('replace') // 'replace' or 'merge'
  const [backupMessage, setBackupMessage] = useState({ text: '', type: '' })

  // Vanilla ISO path state
  const [vanillaIsoPath, setVanillaIsoPath] = useState('')
  const [isoMessage, setIsoMessage] = useState({ text: '', type: '' })
  const [isoVerified, setIsoVerified] = useState(null) // null = not checked, true = valid, false = invalid
  const [verifyingIso, setVerifyingIso] = useState(false)

  // Load vanilla ISO path from localStorage on mount and verify it
  useEffect(() => {
    const savedPath = localStorage.getItem('vanilla_iso_path')
    if (savedPath) {
      setVanillaIsoPath(savedPath)
      // Verify on load
      verifyIso(savedPath)
    }
  }, [])

  const verifyIso = async (isoPath) => {
    setVerifyingIso(true)
    setIsoVerified(null)

    try {
      const response = await fetch(`${API_URL}/verify-iso`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ isoPath })
      })

      const data = await response.json()

      if (data.success) {
        setIsoVerified(data.valid)
        if (!data.valid) {
          setIsoMessage({
            text: `Invalid ISO (MD5: ${data.md5.substring(0, 8)}...). Need vanilla Melee 1.02`,
            type: 'error'
          })
        }
      } else {
        setIsoVerified(false)
        setIsoMessage({ text: data.error, type: 'error' })
      }
    } catch (err) {
      setIsoVerified(false)
      setIsoMessage({ text: `Verification failed: ${err.message}`, type: 'error' })
    } finally {
      setVerifyingIso(false)
    }
  }

  const handleBrowseIso = async () => {
    if (!window.electron) {
      setIsoMessage({ text: 'Electron API not available', type: 'error' })
      return
    }

    try {
      const isoPath = await window.electron.openIsoDialog()
      if (isoPath) {
        setVanillaIsoPath(isoPath)
        setIsoMessage({ text: 'Verifying ISO...', type: '' })

        // Verify the ISO
        setVerifyingIso(true)
        const response = await fetch(`${API_URL}/verify-iso`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ isoPath })
        })

        const data = await response.json()

        if (data.success && data.valid) {
          localStorage.setItem('vanilla_iso_path', isoPath)
          setIsoVerified(true)
          setIsoMessage({ text: 'Valid vanilla Melee 1.02 ISO!', type: 'success' })
          setTimeout(() => setIsoMessage({ text: '', type: '' }), 3000)
        } else {
          setIsoVerified(false)
          setIsoMessage({
            text: `Invalid ISO. This is not a vanilla Melee 1.02 ISO.`,
            type: 'error'
          })
          // Don't save invalid ISO
          setVanillaIsoPath('')
        }
        setVerifyingIso(false)
      }
    } catch (err) {
      setIsoMessage({ text: `Error: ${err.message}`, type: 'error' })
      setVerifyingIso(false)
    }
  }

  const handleClearIsoPath = () => {
    localStorage.removeItem('vanilla_iso_path')
    setVanillaIsoPath('')
    setIsoVerified(null)
    setIsoMessage({ text: 'Vanilla ISO path cleared', type: 'success' })
    setTimeout(() => setIsoMessage({ text: '', type: '' }), 3000)
  }

  // Calculate storage statistics
  const getStorageStats = () => {
    if (!metadata) return { characterCount: 0, stageCount: 0, costumeCount: 0 }

    const characterCount = Object.keys(metadata.characters || {}).length
    let costumeCount = 0

    Object.values(metadata.characters || {}).forEach(char => {
      costumeCount += (char.skins || []).length
    })

    let stageCount = 0
    Object.values(metadata.stages || {}).forEach(stage => {
      stageCount += (stage.variants || []).length
    })

    return { characterCount, stageCount, costumeCount }
  }

  const stats = getStorageStats()

  const handleClearStorage = () => {
    setShowConfirmModal(true)
  }

  const confirmClear = async () => {
    setShowConfirmModal(false)
    setClearing(true)
    setMessage({ text: 'Clearing storage...', type: '' })

    try {
      const response = await fetch(`${API_URL}/storage/clear`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({}),
      })

      const data = await response.json()

      if (data.success) {
        setMessage({ text: 'Storage cleared successfully!', type: 'success' })
        // Reload page after 1.5 seconds to refresh metadata
        setTimeout(() => {
          window.location.reload()
        }, 1500)
      } else {
        setMessage({ text: `Failed to clear storage: ${data.error}`, type: 'error' })
        setClearing(false)
      }
    } catch (err) {
      setMessage({ text: `Error: ${err.message}`, type: 'error' })
      setClearing(false)
    }
  }

  const cancelClear = () => {
    setShowConfirmModal(false)
  }

  const handleBackupVault = async () => {
    setBackingUp(true)
    setBackupMessage({ text: 'Creating backup...', type: '' })

    try {
      const response = await fetch(`${API_URL}/storage/backup`, {
        method: 'POST',
      })

      const data = await response.json()

      if (data.success) {
        setBackupMessage({ text: 'Backup created! Downloading...', type: 'success' })

        // Download the backup file
        const downloadUrl = `${API_URL}/storage/backup/download/${data.filename}`
        const link = document.createElement('a')
        link.href = downloadUrl
        link.download = data.filename
        document.body.appendChild(link)
        link.click()
        document.body.removeChild(link)

        setTimeout(() => {
          setBackupMessage({ text: '', type: '' })
        }, 3000)
      } else {
        setBackupMessage({ text: `Backup failed: ${data.error}`, type: 'error' })
      }
    } catch (err) {
      setBackupMessage({ text: `Error: ${err.message}`, type: 'error' })
    } finally {
      setBackingUp(false)
    }
  }

  const handleRestoreClick = () => {
    setShowRestoreModal(true)
  }

  const handleRestoreFileSelect = (e) => {
    const file = e.target.files[0]
    if (file) {
      setRestoreFile(file)
    }
  }

  const confirmRestore = async () => {
    if (!restoreFile) return

    setShowRestoreModal(false)
    setRestoring(true)
    setBackupMessage({ text: 'Restoring vault...', type: '' })

    try {
      const formData = new FormData()
      formData.append('file', restoreFile)
      formData.append('mode', restoreMode)

      const response = await fetch(`${API_URL}/storage/restore`, {
        method: 'POST',
        body: formData,
      })

      const data = await response.json()

      if (data.success) {
        setBackupMessage({ text: 'Vault restored successfully!', type: 'success' })
        // Reload page after 1.5 seconds to refresh metadata
        setTimeout(() => {
          window.location.reload()
        }, 1500)
      } else {
        setBackupMessage({ text: `Restore failed: ${data.error}`, type: 'error' })
        setRestoring(false)
      }
    } catch (err) {
      setBackupMessage({ text: `Error: ${err.message}`, type: 'error' })
      setRestoring(false)
    }
  }

  const cancelRestore = () => {
    setShowRestoreModal(false)
    setRestoreFile(null)
    setRestoreMode('replace')
  }

  return (
    <div className="settings-container">
      <div className="settings-content">
        <h2>Settings</h2>

        {/* Vanilla ISO Path */}
        <section className="settings-section">
          <h3>Vanilla ISO</h3>
          <p className="section-description">
            Set the path to your vanilla Melee ISO. This is required for applying xdelta patches.
          </p>

          <div className="iso-path-container">
            {vanillaIsoPath ? (
              <div className={`iso-path-display ${isoVerified === true ? 'verified' : isoVerified === false ? 'invalid' : ''}`}>
                <span className="iso-status-icon">
                  {verifyingIso ? '...' : isoVerified === true ? '✓' : isoVerified === false ? '✕' : '?'}
                </span>
                <span className="iso-path-text" title={vanillaIsoPath}>{vanillaIsoPath}</span>
                <button
                  className="iso-clear-button"
                  onClick={handleClearIsoPath}
                  title="Clear ISO path"
                >
                  ×
                </button>
              </div>
            ) : (
              <div className="iso-path-empty">No ISO path set</div>
            )}
            <button
              className="iso-browse-button"
              onClick={handleBrowseIso}
              disabled={verifyingIso}
            >
              {verifyingIso ? 'Verifying...' : vanillaIsoPath ? 'Change' : 'Browse'}
            </button>
          </div>

          {isoMessage.text && (
            <div className={`message ${isoMessage.type}`}>
              {isoMessage.text}
            </div>
          )}
        </section>

        {/* Storage Statistics */}
        <section className="settings-section">
          <h3>Storage Statistics</h3>
          <div className="stats-grid">
            <div className="stat-item">
              <div className="stat-value">{stats.costumeCount}</div>
              <div className="stat-label">Costumes</div>
            </div>
            <div className="stat-item">
              <div className="stat-value">{stats.stageCount}</div>
              <div className="stat-label">Stage Variants</div>
            </div>
          </div>
        </section>

        {/* Vault Backup & Restore Section */}
        <section className="settings-section">
          <h3>Vault Backup & Restore</h3>
          <p className="section-description">
            Create a backup of your entire vault collection or restore from a previous backup.
          </p>

          <div className="backup-buttons">
            <button
              className="backup-button"
              onClick={handleBackupVault}
              disabled={backingUp || restoring}
            >
              {backingUp ? 'Creating Backup...' : 'Export Vault'}
            </button>

            <button
              className="restore-button"
              onClick={handleRestoreClick}
              disabled={backingUp || restoring}
            >
              {restoring ? 'Restoring...' : 'Import Vault'}
            </button>
          </div>

          {backupMessage.text && (
            <div className={`message ${backupMessage.type}`}>
              {backupMessage.text}
            </div>
          )}
        </section>

        {/* Clear Storage Section */}
        <section className="settings-section">
          <h3>Clear Storage</h3>
          <p className="section-description">
            Remove all character costumes and stage variants from storage. This action cannot be undone.
          </p>

          <button
            className="clear-button"
            onClick={handleClearStorage}
            disabled={clearing}
          >
            {clearing ? 'Clearing...' : 'Clear Storage'}
          </button>

          {message.text && (
            <div className={`message ${message.type}`}>
              {message.text}
            </div>
          )}
        </section>
      </div>

      {/* Confirmation Modal */}
      {showConfirmModal && (
        <div className="modal-overlay" onClick={cancelClear}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h3>Confirm Clear Storage</h3>
            <p>
              Are you sure you want to clear all storage? This will remove:
            </p>
            <ul>
              <li>All character costumes ({stats.costumeCount} items)</li>
              <li>All stage variants ({stats.stageCount} items)</li>
              <li>Storage metadata</li>
            </ul>
            <p className="warning-text">
              This action cannot be undone!
            </p>
            <div className="modal-actions">
              <button className="btn-cancel" onClick={cancelClear}>
                Cancel
              </button>
              <button className="btn-confirm" onClick={confirmClear}>
                Clear Storage
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Restore Modal */}
      {showRestoreModal && (
        <div className="modal-overlay" onClick={cancelRestore}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h3>Restore Vault from Backup</h3>
            <p>
              Select a backup file to restore your vault collection.
            </p>

            <div className="file-input-container">
              <label htmlFor="restore-file-input" className="file-input-label">
                {restoreFile ? restoreFile.name : 'Choose backup file...'}
              </label>
              <input
                id="restore-file-input"
                type="file"
                accept=".zip"
                onChange={handleRestoreFileSelect}
                style={{ display: 'none' }}
              />
            </div>

            <div className="restore-mode-options">
              <label className="radio-label">
                <input
                  type="radio"
                  value="replace"
                  checked={restoreMode === 'replace'}
                  onChange={(e) => setRestoreMode(e.target.value)}
                />
                <div>
                  <strong>Replace All</strong>
                  <p className="radio-description">Delete current vault and restore from backup</p>
                </div>
              </label>

              <label className="radio-label">
                <input
                  type="radio"
                  value="merge"
                  checked={restoreMode === 'merge'}
                  onChange={(e) => setRestoreMode(e.target.value)}
                />
                <div>
                  <strong>Merge</strong>
                  <p className="radio-description">Keep current items and add backup items</p>
                </div>
              </label>
            </div>

            {restoreMode === 'replace' && (
              <p className="warning-text">
                Warning: This will delete all current vault items!
              </p>
            )}

            <div className="modal-actions">
              <button className="btn-cancel" onClick={cancelRestore}>
                Cancel
              </button>
              <button
                className="btn-confirm"
                onClick={confirmRestore}
                disabled={!restoreFile}
              >
                Restore Vault
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
