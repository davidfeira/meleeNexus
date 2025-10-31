import React, { useState, useEffect } from 'react';
import './MexPanel.css';
import IsoBuilder from './IsoBuilder';

const DAS_STAGES = [
  { code: 'GrNBa', name: 'Battlefield', folder: 'battlefield', vanillaImage: '/vanilla/stages/battlefield.jpg' },
  { code: 'GrNLa', name: 'Final Destination', folder: 'final_destination', vanillaImage: '/vanilla/stages/final destination.png' },
  { code: 'GrSt', name: "Yoshi's Story", folder: 'yoshis_story', vanillaImage: '/vanilla/stages/Yoshis story.jpg' },
  { code: 'GrOp', name: 'Dreamland', folder: 'dreamland', vanillaImage: '/vanilla/stages/dreamland.jpg' },
  { code: 'GrPs', name: 'Pokemon Stadium', folder: 'pokemon_stadium', vanillaImage: '/vanilla/stages/pokemon stadium.jpg' },
  { code: 'GrIz', name: 'Fountain of Dreams', folder: 'fountain_of_dreams', vanillaImage: '/vanilla/stages/Fountain of Dreams.webp' }
];

const MexPanel = () => {
  const [mode, setMode] = useState('characters'); // 'characters' or 'stages'
  const [mexStatus, setMexStatus] = useState(null);
  const [fighters, setFighters] = useState([]);
  const [selectedFighter, setSelectedFighter] = useState(null);
  const [storageCostumes, setStorageCostumes] = useState([]);
  const [mexCostumes, setMexCostumes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [projectLoaded, setProjectLoaded] = useState(false);
  const [openingProject, setOpeningProject] = useState(false);
  const [creatingProject, setCreatingProject] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importingCostume, setImportingCostume] = useState(null);
  const [removing, setRemoving] = useState(false);
  const [removingCostume, setRemovingCostume] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [showIsoBuilder, setShowIsoBuilder] = useState(false);
  const [showProjectModal, setShowProjectModal] = useState(false);
  const [recentProjects, setRecentProjects] = useState([]);
  const [selectedCostumes, setSelectedCostumes] = useState(new Set());
  const [batchImporting, setBatchImporting] = useState(false);
  const [batchProgress, setBatchProgress] = useState({ current: 0, total: 0 });

  // DAS state
  const [dasInstalled, setDasInstalled] = useState(false);
  const [dasChecking, setDasChecking] = useState(false);
  const [selectedStage, setSelectedStage] = useState(null);
  const [storageVariants, setStorageVariants] = useState([]);
  const [mexVariants, setMexVariants] = useState([]);
  const [mexVariantCounts, setMexVariantCounts] = useState({}); // { stageCode: count }

  const API_URL = 'http://127.0.0.1:5000/api/mex';

  // Recent projects management
  const loadRecentProjects = () => {
    try {
      const stored = localStorage.getItem('mex_recent_projects');
      if (stored) {
        const projects = JSON.parse(stored);
        setRecentProjects(projects);
      }
    } catch (err) {
      console.error('Failed to load recent projects:', err);
    }
  };

  const addToRecentProjects = (projectPath, projectName) => {
    try {
      const stored = localStorage.getItem('mex_recent_projects');
      let projects = stored ? JSON.parse(stored) : [];

      // Remove if already exists
      projects = projects.filter(p => p.path !== projectPath);

      // Add to front
      projects.unshift({
        path: projectPath,
        name: projectName,
        timestamp: Date.now()
      });

      // Keep only 5 most recent
      projects = projects.slice(0, 5);

      localStorage.setItem('mex_recent_projects', JSON.stringify(projects));
      setRecentProjects(projects);
    } catch (err) {
      console.error('Failed to save recent project:', err);
    }
  };

  useEffect(() => {
    fetchMexStatus();
    loadRecentProjects();
  }, []);

  useEffect(() => {
    if (projectLoaded) {
      fetchFighters();
      fetchStorageCostumes();
    }
  }, [projectLoaded]);

  useEffect(() => {
    if (selectedFighter) {
      fetchMexCostumes(selectedFighter.name);
    }
  }, [selectedFighter]);

  useEffect(() => {
    if (mode === 'stages') {
      checkDASInstallation();
      fetchStorageVariants();
      fetchAllMexVariantCounts();
    }
  }, [mode]);

  useEffect(() => {
    if (selectedStage && dasInstalled) {
      fetchMexVariants(selectedStage.code);
    }
  }, [selectedStage, dasInstalled]);

  const fetchMexStatus = async () => {
    try {
      const response = await fetch(`${API_URL}/status`);
      const data = await response.json();
      setMexStatus(data);
      setProjectLoaded(data.projectLoaded || false);
      setLoading(false);
    } catch (err) {
      setError('Failed to connect to MEX API');
      console.error(err);
      setLoading(false);
    }
  };

  const fetchFighters = async () => {
    try {
      const response = await fetch(`${API_URL}/fighters`);
      const data = await response.json();
      if (data.success) {
        setFighters(data.fighters);
      }
    } catch (err) {
      console.error('Failed to fetch fighters:', err);
    } finally {
      setLoading(false);
    }
  };

  const fetchStorageCostumes = async () => {
    try {
      const response = await fetch(`${API_URL}/storage/costumes`);
      const data = await response.json();
      if (data.success) {
        setStorageCostumes(data.costumes);
      }
    } catch (err) {
      console.error('Failed to fetch storage costumes:', err);
    }
  };

  const fetchMexCostumes = async (fighterName) => {
    try {
      const response = await fetch(`${API_URL}/fighters/${encodeURIComponent(fighterName)}/costumes`);
      const data = await response.json();
      if (data.success) {
        setMexCostumes(data.costumes || []);
      }
    } catch (err) {
      console.error('Failed to fetch MEX costumes:', err);
      setMexCostumes([]);
    }
  };

  const handleImportCostume = async (costume) => {
    // Prevent multiple simultaneous imports
    if (importing || importingCostume) {
      console.log('Import already in progress, ignoring click');
      return;
    }

    console.log(`=== IMPORT REQUEST ===`);
    console.log(`Costume:`, costume);
    console.log(`Fighter: ${costume.character}`);
    console.log(`Zip Path: ${costume.zipPath}`);

    setImporting(true);
    setImportingCostume(costume.zipPath);

    try {
      // Ice Climbers: Auto-import paired Nana when Popo is selected
      if (costume.isPopo && costume.pairedNanaId) {
        console.log('Ice Climbers Popo detected - will auto-import paired Nana');

        // Find paired Nana costume in storage
        const nanaCostume = storageCostumes.find(c => c.folder === costume.pairedNanaId);

        if (!nanaCostume) {
          console.error('Paired Nana costume not found:', costume.pairedNanaId);
          alert('Paired Nana costume not found in storage');
          return;
        }

        // Import Popo first (MEX calls it "Ice Climbers")
        const popoResponse = await fetch(`${API_URL}/import`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            fighter: 'Ice Climbers',
            costumePath: costume.zipPath
          })
        });

        const popoData = await popoResponse.json();
        console.log('Popo import response:', popoData);

        if (!popoData.success) {
          alert(`Popo import failed: ${popoData.error}`);
          return;
        }

        // Import Nana second - find Nana fighter (ID 11, could be named "Nana" or "Popo")
        const nanaFighter = fighters.find(f => f.internalId === 11);

        if (!nanaFighter) {
          alert(`Popo imported but could not find Nana fighter (ID 11) in project`);
          return;
        }

        console.log(`Importing Nana to fighter: ${nanaFighter.name}`);

        const nanaResponse = await fetch(`${API_URL}/import`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            fighter: nanaFighter.name, // Use actual fighter name (could be "Nana" or "Popo")
            costumePath: nanaCostume.zipPath
          })
        });

        const nanaData = await nanaResponse.json();
        console.log('Nana import response:', nanaData);

        if (!nanaData.success) {
          alert(`Nana import failed: ${nanaData.error}`);
          return;
        }

        console.log(`✓ Successfully imported Ice Climbers pair (Popo + Nana)`);

        // Refresh fighters list
        setRefreshing(true);
        await Promise.all([
          fetchFighters(),
          selectedFighter ? fetchMexCostumes(selectedFighter.name) : Promise.resolve()
        ]);
        setRefreshing(false);

      } else {
        // Normal single costume import
        const requestBody = {
          fighter: costume.character,
          costumePath: costume.zipPath
        };

        console.log('Sending import request:', requestBody);

        const response = await fetch(`${API_URL}/import`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(requestBody)
        });

        const data = await response.json();
        console.log('Import response:', data);

        if (data.success) {
          console.log(`✓ Successfully imported ${data.result.costumesImported} costume(s) to ${costume.character}`);

          // Immediately refresh to show updated data
          setRefreshing(true);
          await Promise.all([
            fetchFighters(),
            selectedFighter ? fetchMexCostumes(selectedFighter.name) : Promise.resolve()
          ]);
          setRefreshing(false);
        } else {
          alert(`Import failed: ${data.error}`);
        }
      }
    } catch (err) {
      console.error('Import error:', err);
      alert(`Import error: ${err.message}`);
    } finally {
      setImporting(false);
      setImportingCostume(null);
    }
  };

  const handleRemoveCostume = async (fighterName, costumeIndex, costumeName) => {
    // Prevent multiple simultaneous removals
    if (removing || removingCostume !== null) {
      console.log('Remove already in progress, ignoring click');
      return;
    }

    // Ice Climbers: Mention paired removal in confirmation
    const isIceClimbers = fighterName === 'Ice Climbers';
    const confirmMessage = isIceClimbers
      ? `Are you sure you want to remove "${costumeName}" (and paired Nana) from Ice Climbers?`
      : `Are you sure you want to remove "${costumeName}" from ${fighterName}?`;

    if (!confirm(confirmMessage)) {
      return;
    }

    console.log(`=== REMOVE REQUEST ===`);
    console.log(`Fighter: ${fighterName}`);
    console.log(`Costume Index: ${costumeIndex}`);
    console.log(`Costume Name: ${costumeName}`);
    if (isIceClimbers) {
      console.log(`Will also remove paired Nana at index ${costumeIndex}`);
    }

    setRemoving(true);
    setRemovingCostume(costumeIndex);

    try {
      // Remove Popo (or regular character)
      const requestBody = {
        fighter: fighterName,
        costumeIndex: costumeIndex
      };

      console.log('Sending remove request:', requestBody);

      const response = await fetch(`${API_URL}/remove`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestBody)
      });

      const data = await response.json();
      console.log('Remove response:', data);

      if (!data.success) {
        alert(`Remove failed: ${data.error}`);
        return;
      }

      console.log(`✓ Successfully removed "${costumeName}" from ${fighterName}`);

      // Ice Climbers: Also remove paired Nana at same index
      if (isIceClimbers) {
        console.log(`Removing paired Nana at index ${costumeIndex}...`);

        // Find Nana fighter (internal ID 11) - could be named "Nana" or "Popo"
        const nanaFighter = fighters.find(f => f.internalId === 11);

        if (!nanaFighter) {
          console.warn('Nana fighter (ID 11) not found in project');
          alert(`Popo removed but could not find Nana fighter in project`);
        } else {
          console.log(`Found Nana fighter named: ${nanaFighter.name}`);

          const nanaRequestBody = {
            fighter: nanaFighter.name, // Use actual fighter name (could be "Nana" or "Popo")
            costumeIndex: costumeIndex
          };

          const nanaResponse = await fetch(`${API_URL}/remove`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify(nanaRequestBody)
          });

          const nanaData = await nanaResponse.json();
          console.log('Nana remove response:', nanaData);

          if (!nanaData.success) {
            alert(`Popo removed but Nana removal failed: ${nanaData.error}`);
          } else {
            console.log(`✓ Successfully removed paired Nana from ${nanaFighter.name}`);
          }
        }
      }

      // Immediately refresh to show updated data
      setRefreshing(true);
      await Promise.all([
        fetchFighters(),
        selectedFighter ? fetchMexCostumes(selectedFighter.name) : Promise.resolve()
      ]);
      setRefreshing(false);

    } catch (err) {
      console.error('Remove error:', err);
      alert(`Remove error: ${err.message}`);
    } finally {
      setRemoving(false);
      setRemovingCostume(null);
    }
  };

  const getCostumesForFighter = (fighterName) => {
    // Filter out Nana costumes (they're auto-imported with Popo)
    return storageCostumes.filter(c => c.character === fighterName && !c.isNana);
  };

  // DAS Functions
  const checkDASInstallation = async () => {
    setDasChecking(true);
    try {
      const response = await fetch(`${API_URL}/das/status`);
      const data = await response.json();
      if (data.success) {
        setDasInstalled(data.installed);
      }
    } catch (err) {
      console.error('Failed to check DAS status:', err);
    } finally {
      setDasChecking(false);
    }
  };

  const installDAS = async () => {
    if (!confirm('Install Dynamic Alternate Stages framework? This will modify stage files in your MEX project.')) {
      return;
    }

    setDasChecking(true);
    try {
      const response = await fetch(`${API_URL}/das/install`, {
        method: 'POST'
      });
      const data = await response.json();

      if (data.success) {
        alert('DAS framework installed successfully!');
        setDasInstalled(true);
        fetchStorageVariants();
      } else {
        alert(`DAS installation failed: ${data.error}`);
      }
    } catch (err) {
      console.error('DAS installation error:', err);
      alert(`DAS installation error: ${err.message}`);
    } finally {
      setDasChecking(false);
    }
  };

  const fetchStorageVariants = async () => {
    try {
      const response = await fetch(`${API_URL}/das/storage/variants`);
      const data = await response.json();
      if (data.success) {
        setStorageVariants(data.variants);
      }
    } catch (err) {
      console.error('Failed to fetch storage variants:', err);
    }
  };

  const fetchMexVariants = async (stageCode) => {
    try {
      const response = await fetch(`${API_URL}/das/stages/${stageCode}/variants`);
      const data = await response.json();
      if (data.success) {
        setMexVariants(data.variants || []);
      }
    } catch (err) {
      console.error('Failed to fetch MEX variants:', err);
      setMexVariants([]);
    }
  };

  const fetchAllMexVariantCounts = async () => {
    try {
      const counts = {};
      await Promise.all(
        DAS_STAGES.map(async (stage) => {
          const response = await fetch(`${API_URL}/das/stages/${stage.code}/variants`);
          const data = await response.json();
          if (data.success) {
            counts[stage.code] = data.variants?.length || 0;
          }
        })
      );
      setMexVariantCounts(counts);
    } catch (err) {
      console.error('Failed to fetch MEX variant counts:', err);
    }
  };

  const handleImportVariant = async (variant) => {
    if (importing) return;

    setImporting(true);
    setImportingCostume(variant.zipPath);

    try {
      const response = await fetch(`${API_URL}/das/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          stageCode: variant.stageCode,
          variantPath: variant.zipPath
        })
      });

      const data = await response.json();

      if (data.success) {
        console.log(`✓ Successfully imported variant to ${variant.stageName}`);
        setRefreshing(true);
        await fetchMexVariants(selectedStage.code);
        await fetchAllMexVariantCounts();
        setRefreshing(false);
      } else {
        alert(`Import failed: ${data.error}`);
      }
    } catch (err) {
      console.error('Import error:', err);
      alert(`Import error: ${err.message}`);
    } finally {
      setImporting(false);
      setImportingCostume(null);
    }
  };

  const handleRemoveVariant = async (stageCode, variantName) => {
    if (removing) return;

    if (!confirm(`Are you sure you want to remove "${variantName}"?`)) {
      return;
    }

    setRemoving(true);

    try {
      const response = await fetch(`${API_URL}/das/remove`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          stageCode: stageCode,
          variantName: variantName
        })
      });

      const data = await response.json();

      if (data.success) {
        console.log(`✓ Successfully removed "${variantName}"`);
        setRefreshing(true);
        await fetchMexVariants(selectedStage.code);
        await fetchAllMexVariantCounts();
        setRefreshing(false);
      } else {
        alert(`Remove failed: ${data.error}`);
      }
    } catch (err) {
      console.error('Remove error:', err);
      alert(`Remove error: ${err.message}`);
    } finally {
      setRemoving(false);
    }
  };

  const getVariantsForStage = (stageCode) => {
    return storageVariants.filter(v => v.stageCode === stageCode);
  };

  const handleOpenProjectFromPath = async (projectPath) => {
    setOpeningProject(true);

    try {
      console.log('Opening project:', projectPath);

      // Send path to backend
      const response = await fetch(`${API_URL}/project/open`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ projectPath: projectPath })
      });

      const data = await response.json();

      if (data.success) {
        console.log('✓ Project opened:', data.project.name);
        addToRecentProjects(projectPath, data.project.name);
        await fetchMexStatus();
        setShowProjectModal(false); // Close modal on success
      } else {
        alert(`Failed to open project: ${data.error}`);
      }
    } catch (err) {
      alert(`Error opening project: ${err.message}`);
    } finally {
      setOpeningProject(false);
    }
  };

  const handleOpenProject = async () => {
    // Check if Electron API is available
    if (!window.electron) {
      alert('Electron API not available. Please run this app in Electron mode.');
      return;
    }

    setOpeningProject(true);

    try {
      // Open native file picker dialog
      const filePath = await window.electron.openProjectDialog();

      if (!filePath) {
        // User canceled
        setOpeningProject(false);
        return;
      }

      console.log('Selected project:', filePath);

      // Send path to backend
      const response = await fetch(`${API_URL}/project/open`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ projectPath: filePath })
      });

      const data = await response.json();

      if (data.success) {
        console.log('✓ Project opened:', data.project.name);
        addToRecentProjects(filePath, data.project.name);
        await fetchMexStatus();
        setShowProjectModal(false); // Close modal on success
      } else {
        alert(`Failed to open project: ${data.error}`);
      }
    } catch (err) {
      alert(`Error opening project: ${err.message}`);
    } finally {
      setOpeningProject(false);
    }
  };

  const handleCreateProject = async () => {
    // Check if Electron API is available
    if (!window.electron) {
      alert('Electron API not available. Please run this app in Electron mode.');
      return;
    }

    setCreatingProject(true);

    try {
      // Step 1: Select vanilla ISO
      const isoPath = await window.electron.openIsoDialog();

      if (!isoPath) {
        // User canceled
        setCreatingProject(false);
        return;
      }

      console.log('Selected ISO:', isoPath);

      // Step 2: Select project folder
      const projectDir = await window.electron.selectDirectory();

      if (!projectDir) {
        // User canceled
        setCreatingProject(false);
        return;
      }

      console.log('Selected project directory:', projectDir);

      // Step 3: Use default project name
      const projectName = 'MexProject';
      console.log('Project name:', projectName);

      // Step 4: Call backend to create project
      const response = await fetch(`${API_URL}/project/create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          isoPath: isoPath,
          projectDir: projectDir,
          projectName: projectName
        })
      });

      const data = await response.json();

      if (data.success) {
        console.log('✓ Project created:', data.projectPath);

        // Step 5: Auto-open the newly created project
        const openResponse = await fetch(`${API_URL}/project/open`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ projectPath: data.projectPath })
        });

        const openData = await openResponse.json();

        if (openData.success) {
          console.log('✓ Project opened:', openData.project.name);
          addToRecentProjects(data.projectPath, openData.project.name);
          await fetchMexStatus();
          setShowProjectModal(false); // Close modal on success
        } else {
          alert(`Project created but failed to open: ${openData.error}`);
        }
      } else {
        alert(`Failed to create project: ${data.error}`);
      }
    } catch (err) {
      alert(`Error creating project: ${err.message}`);
    } finally {
      setCreatingProject(false);
    }
  };

  if (loading) {
    return <div className="mex-panel loading">Loading MEX Manager...</div>;
  }

  if (error) {
    return (
      <div className="mex-panel error">
        <h2>MEX Connection Error</h2>
        <p>{error}</p>
        <p>Make sure the backend is running:</p>
        <code>python backend/mex_api.py</code>
      </div>
    );
  }

  // Show project selection screen if no project is loaded
  if (!projectLoaded) {
    return (
      <div className="mex-panel">
        <div className="project-selection">
          <h1>MEX Manager</h1>
          <p className="subtitle">Select a project to get started</p>

          {/* Recent Projects */}
          {recentProjects.length > 0 && (
            <div className="recent-projects">
              <h3>Recent Projects</h3>
              <div className="recent-projects-list">
                {recentProjects.map((project, idx) => (
                  <div
                    key={idx}
                    className="recent-project-item"
                    onClick={() => handleOpenProjectFromPath(project.path)}
                  >
                    <div className="recent-project-name">{project.name}</div>
                    <div className="recent-project-path">{project.path}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="project-options">
            {/* Open existing project */}
            <div className="project-option">
              <h3>Open Existing Project</h3>
              <p>Select a .mexproj file to continue working on an existing MEX mod</p>
              <button
                className="project-btn"
                onClick={handleOpenProject}
                disabled={openingProject}
              >
                {openingProject ? 'Opening...' : 'Browse for .mexproj'}
              </button>
            </div>

            {/* Create new project */}
            <div className="project-option">
              <h3>Create New Project</h3>
              <p>Provide a vanilla Melee ISO to create a new MEX mod project</p>
              <button
                className="project-btn"
                onClick={handleCreateProject}
                disabled={creatingProject}
              >
                {creatingProject ? 'Creating Project...' : 'Create from Vanilla ISO'}
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="mex-panel">
      <div className="mex-header">
        <h2>MEX Manager</h2>
        {mexStatus?.connected && (
          <div className="mex-status connected">
            <span className="status-dot"></span>
            <span>{mexStatus.project.name} v{mexStatus.project.version}</span>
          </div>
        )}
      </div>

      <div className="mex-actions">
        <button
          className="btn-primary"
          onClick={() => setShowIsoBuilder(true)}
        >
          Export ISO
        </button>
        <button
          className="btn-secondary"
          onClick={() => setShowProjectModal(true)}
        >
          Switch Project
        </button>
        <button
          className="btn-secondary"
          onClick={fetchFighters}
        >
          Refresh
        </button>
      </div>

      {/* Mode Switcher */}
      <div className="mode-switcher">
        <button
          className={`mode-btn ${mode === 'characters' ? 'active' : ''}`}
          onClick={() => {
            setMode('characters');
            setSelectedStage(null);
          }}
        >
          Characters
        </button>
        <button
          className={`mode-btn ${mode === 'stages' ? 'active' : ''}`}
          onClick={() => {
            setMode('stages');
            setSelectedFighter(null);
          }}
        >
          Stages
        </button>
      </div>

      {mode === 'characters' ? (
        <div className="mex-content">
        <div className="fighters-list">
          <h3>Fighters ({fighters.length})</h3>
          <div className="fighter-items">
            {fighters.map(fighter => {
              const availableCostumes = getCostumesForFighter(fighter.name);
              return (
                <div
                  key={fighter.internalId}
                  className={`fighter-item ${selectedFighter?.internalId === fighter.internalId ? 'selected' : ''}`}
                  onClick={() => setSelectedFighter(fighter)}
                >
                  <div className="fighter-name">{fighter.name}</div>
                  <div className="fighter-info">
                    <span className="costume-count">{fighter.costumeCount} in MEX</span>
                    {availableCostumes.length > 0 && (
                      <span className="available-count">{availableCostumes.length} available</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className={`costumes-panel ${refreshing ? 'refreshing' : ''}`}>
          {selectedFighter ? (
            <>
              <div className="costumes-section">
                <h3>Already in MEX ({mexCostumes.length})</h3>
                <div className="costume-list existing">
                  {mexCostumes.map((costume, idx) => (
                    <div key={idx} className="costume-card existing-costume">
                      {costume.cspUrl && (
                        <div className="costume-preview">
                          <img
                            src={`${API_URL}${costume.cspUrl}`}
                            alt={costume.name}
                            onError={(e) => e.target.style.display = 'none'}
                          />
                          <button
                            className="btn-remove"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleRemoveCostume(selectedFighter.name, idx, costume.name);
                            }}
                            disabled={removing}
                            title="Remove costume"
                          >
                            ×
                          </button>
                        </div>
                      )}
                      <div className="costume-info">
                        <h4>{costume.name}</h4>
                        <p className="costume-file">{costume.fileName}</p>
                        {costume.iconUrl && (
                          <div className="costume-assets">
                            <div className="stock-icon">
                              <img
                                src={`${API_URL}${costume.iconUrl}`}
                                alt="Stock"
                                onError={(e) => e.target.style.display = 'none'}
                              />
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                  {mexCostumes.length === 0 && (
                    <div className="no-costumes">
                      <p>No costumes in MEX yet</p>
                    </div>
                  )}
                </div>
              </div>

              <div className="costumes-section">
                <h3>Available to Import</h3>
                <div className="costume-list">
                  {getCostumesForFighter(selectedFighter.name).map((costume, idx) => (
                    <div key={idx} className="costume-card">
                      <div className="costume-preview">
                        {costume.cspUrl && (
                          <img
                            src={costume.cspUrl}
                            alt={costume.name}
                            onError={(e) => e.target.style.display = 'none'}
                          />
                        )}
                      </div>
                      <div className="costume-info">
                        <h4>{costume.name}</h4>
                        <p className="costume-code">{costume.costumeCode}</p>
                        <div className="costume-assets">
                          {costume.stockUrl && (
                            <div className="stock-icon">
                              <img
                                src={costume.stockUrl}
                                alt="Stock"
                                onError={(e) => e.target.style.display = 'none'}
                              />
                            </div>
                          )}
                          {costume.slippiSafe && (
                            <div className="slippi-badge" title="Slippi Safe">
                              ✓
                            </div>
                          )}
                        </div>
                        <button
                          className="btn-add"
                          onClick={() => handleImportCostume(costume)}
                          disabled={importing}
                        >
                          {importingCostume === costume.zipPath ? 'Importing...' : importing ? 'Wait...' : 'Add to MEX'}
                        </button>
                      </div>
                    </div>
                  ))}
                  {getCostumesForFighter(selectedFighter.name).length === 0 && (
                    <div className="no-costumes">
                      <p>No costumes available in storage for {selectedFighter.name}</p>
                    </div>
                  )}
                </div>
              </div>
            </>
          ) : (
            <div className="no-selection">
              <p>Select a fighter to view costumes</p>
            </div>
          )}
        </div>
      </div>
      ) : (
        // Stages Mode
        <div className="mex-content">
          {!dasInstalled ? (
            <div className="das-install-prompt">
              <h3>Dynamic Alternate Stages Not Installed</h3>
              <p>Install the DAS framework to manage alternate stage variants for your 6 competitive stages.</p>
              <button
                className="btn-primary"
                onClick={installDAS}
                disabled={dasChecking}
              >
                {dasChecking ? 'Installing...' : 'Install DAS Framework'}
              </button>
            </div>
          ) : (
            <>
              <div className="fighters-list">
                <h3>Stages ({DAS_STAGES.length})</h3>
                <div className="fighter-items">
                  {DAS_STAGES.map(stage => {
                    const availableVariants = getVariantsForStage(stage.code);
                    const mexCount = mexVariantCounts[stage.code] || 0;
                    return (
                      <div
                        key={stage.code}
                        className={`fighter-item ${selectedStage?.code === stage.code ? 'selected' : ''}`}
                        onClick={() => setSelectedStage(stage)}
                      >
                        <div className="fighter-name">{stage.name}</div>
                        <div className="fighter-info">
                          <span className="costume-count">{mexCount} in MEX</span>
                          {availableVariants.length > 0 && (
                            <span className="available-count">{availableVariants.length} available</span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className={`costumes-panel ${refreshing ? 'refreshing' : ''}`}>
                {selectedStage ? (
                  <>
                    <div className="costumes-section">
                      <h3>Already in MEX ({mexVariants.length})</h3>
                      <div className="costume-list existing">
                        {mexVariants.map((variant, idx) => (
                          <div key={idx} className="costume-card existing-costume">
                            <div className="costume-preview">
                              {variant.hasScreenshot && (
                                <img
                                  src={variant.screenshotUrl}
                                  alt={variant.name}
                                  onError={(e) => e.target.style.display = 'none'}
                                />
                              )}
                              <button
                                className="btn-remove"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleRemoveVariant(selectedStage.code, variant.name);
                                }}
                                disabled={removing}
                                title="Remove variant"
                              >
                                ×
                              </button>
                            </div>
                            <div className="costume-info">
                              <h4>{variant.name}</h4>
                              <p className="costume-file">{variant.filename}</p>
                            </div>
                          </div>
                        ))}
                        {mexVariants.length === 0 && (
                          <div className="no-costumes">
                            <p>No variants in MEX yet</p>
                          </div>
                        )}
                      </div>
                    </div>

                    <div className="costumes-section">
                      <h3>Available to Import</h3>
                      <div className="costume-list">
                        {getVariantsForStage(selectedStage.code).map((variant, idx) => (
                          <div key={idx} className="costume-card">
                            <div className="costume-preview">
                              {variant.hasScreenshot && (
                                <img
                                  src={variant.screenshotUrl}
                                  alt={variant.name}
                                  onError={(e) => e.target.style.display = 'none'}
                                />
                              )}
                            </div>
                            <div className="costume-info">
                              <h4>{variant.name}</h4>
                              <p className="costume-code">{selectedStage.name}</p>
                              <button
                                className="btn-add"
                                onClick={() => handleImportVariant(variant)}
                                disabled={importing}
                              >
                                {importingCostume === variant.zipPath ? 'Importing...' : importing ? 'Wait...' : 'Add to MEX'}
                              </button>
                            </div>
                          </div>
                        ))}
                        {getVariantsForStage(selectedStage.code).length === 0 && (
                          <div className="no-costumes">
                            <p>No variants available in storage for {selectedStage.name}</p>
                          </div>
                        )}
                      </div>
                    </div>
                  </>
                ) : (
                  <div className="no-selection">
                    <p>Select a stage to view variants</p>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      )}

      {showIsoBuilder && (
        <IsoBuilder onClose={() => setShowIsoBuilder(false)} />
      )}

      {/* Project Selection Modal */}
      {showProjectModal && (
        <div className="project-modal-overlay" onClick={() => setShowProjectModal(false)}>
          <div className="project-modal-content" onClick={(e) => e.stopPropagation()}>
            <h2>Switch Project</h2>
            <p className="modal-subtitle">Select a different project or create a new one</p>

            {/* Recent Projects in Modal */}
            {recentProjects.length > 0 && (
              <div className="recent-projects-modal">
                <h3>Recent Projects</h3>
                <div className="recent-projects-list-modal">
                  {recentProjects.map((project, idx) => (
                    <div
                      key={idx}
                      className="recent-project-item-modal"
                      onClick={() => handleOpenProjectFromPath(project.path)}
                    >
                      <div className="recent-project-name">{project.name}</div>
                      <div className="recent-project-path">{project.path}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="project-options-modal">
              {/* Open existing project */}
              <div className="project-option-modal">
                <h3>Open Existing Project</h3>
                <p>Select a .mexproj file to switch to a different MEX mod</p>
                <button
                  className="project-btn"
                  onClick={handleOpenProject}
                  disabled={openingProject}
                >
                  {openingProject ? 'Opening...' : 'Browse for .mexproj'}
                </button>
              </div>

              {/* Create new project */}
              <div className="project-option-modal">
                <h3>Create New Project</h3>
                <p>Provide a vanilla Melee ISO to create a new MEX mod project</p>
                <button
                  className="project-btn"
                  onClick={handleCreateProject}
                  disabled={creatingProject}
                >
                  {creatingProject ? 'Creating Project...' : 'Create from Vanilla ISO'}
                </button>
              </div>
            </div>

            <button
              className="btn-cancel-modal"
              onClick={() => setShowProjectModal(false)}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default MexPanel;
