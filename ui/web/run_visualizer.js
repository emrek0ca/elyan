/**
 * Run Visualizer — Interactive Gantt, Waterfall, and Performance Charts
 * Provides advanced visualization of run execution timelines and metrics
 */

class RunVisualizer {
  constructor(containerId) {
    this.containerId = containerId;
    this.container = document.getElementById(containerId);
    this.runData = null;
    this.selectedStep = null;
    this.zoomLevel = 1;
  }

  /**
   * Load and render run visualization
   */
  async loadRun(runId) {
    try {
      const response = await fetch(`http://localhost:18789/api/v1/runs/${runId}/timeline`);
      const data = await response.json();

      if (!data.success || !data.timeline) {
        this.container.innerHTML = `<p style="color: #dc2626;">Error: ${data.error || "Run not found"}</p>`;
        return;
      }

      this.runData = data.timeline;
      this.render();
    } catch (error) {
      this.container.innerHTML = `<p style="color: #dc2626;">Failed to load run: ${error.message}</p>`;
    }
  }

  /**
   * Render all visualizations
   */
  render() {
    if (!this.runData || !this.runData.steps || this.runData.steps.length === 0) {
      this.container.innerHTML = `
        <div style="background: #f0f9ff; border: 1px solid #bfdbfe; border-radius: 8px; padding: 40px 20px; text-align: center;">
          <p style="color: #0c4a6e;">No steps recorded for this run</p>
        </div>
      `;
      return;
    }

    const isMobile = window.innerWidth < 768;
    const buttonStyle = isMobile ?
      "padding: 10px 12px; font-size: 13px; min-height: 44px; flex: 1;" :
      "padding: 8px 16px; font-size: 14px;";

    let html = `
      <div style="display: flex; gap: ${isMobile ? '8px' : '12px'}; margin-bottom: 16px; flex-wrap: wrap;">
        <button onclick="visualizer.showGanttChart()" style="${buttonStyle} background: #3b82f6; color: white; border: none; border-radius: 4px; cursor: pointer;">
          📊 Gantt
        </button>
        <button onclick="visualizer.showWaterfallChart()" style="${buttonStyle} background: #8b5cf6; color: white; border: none; border-radius: 4px; cursor: pointer;">
          🌊 Waterfall
        </button>
        <button onclick="visualizer.showPerformanceChart()" style="${buttonStyle} background: #10b981; color: white; border: none; border-radius: 4px; cursor: pointer;">
          ⚡ Performance
        </button>
        <button onclick="visualizer.showStepDetails()" style="${buttonStyle} background: #f97316; color: white; border: none; border-radius: 4px; cursor: pointer;">
          📋 Details
        </button>
      </div>
      <div id="visualizer-content" style="background: rgba(15,23,42,0.7); border: 1px solid rgba(148,163,184,0.2); border-radius: 12px; padding: 12px; backdrop-filter: blur(20px); min-height: 300px; overflow-x: auto;"></div>
    `;

    this.container.innerHTML = html;
    this.showGanttChart();
  }

  /**
   * Render interactive Gantt chart
   */
  showGanttChart() {
    const content = document.getElementById("visualizer-content");
    const steps = this.runData.steps;

    if (!steps || steps.length === 0) {
      content.innerHTML = "<p>No steps to display</p>";
      return;
    }

    // Calculate timeline bounds
    const minStart = Math.min(...steps.map(s => s.start));
    const maxEnd = Math.max(...steps.map(s => s.start + s.duration));
    const totalDuration = maxEnd - minStart;

    // Mobile optimization: adjust pixels per second based on screen width
    const isMobile = window.innerWidth < 768;
    const basePixelsPerSecond = isMobile ? 40 : 60;
    const pixelsPerSecond = basePixelsPerSecond / this.zoomLevel;

    let html = `
      <div style="overflow-x: auto;">
        <svg width="${Math.max(600, totalDuration * pixelsPerSecond + 100)}" height="${50 + steps.length * 50}" style="background: rgba(255,255,255,0.05);">
          <!-- Timeline axis -->
          <line x1="50" y1="30" x2="${totalDuration * pixelsPerSecond + 50}" y2="30" stroke="#94a3b8" stroke-width="1"/>

          <!-- Time labels -->`;

    for (let t = 0; t <= totalDuration; t += Math.ceil(totalDuration / 10)) {
      const x = 50 + t * pixelsPerSecond;
      html += `
        <text x="${x}" y="25" font-size="11" fill="#94a3b8" text-anchor="middle">${t}s</text>
        <line x1="${x}" y1="28" x2="${x}" y2="32" stroke="#94a3b8"/>`;
    }

    html += `
          <!-- Steps -->`;

    steps.forEach((step, index) => {
      const y = 50 + index * 50;
      const x = 50 + (step.start - minStart) * pixelsPerSecond;
      const width = step.duration * pixelsPerSecond;
      const statusColor = this.getStatusColor(step.status);

      html += `
        <g class="step-bar" onclick="visualizer.selectStep('${step.step_id}')" style="cursor: pointer;">
          <rect x="${x}" y="${y}" width="${Math.max(width, 2)}" height="30" fill="${statusColor}" opacity="0.7" stroke="#94a3b8" stroke-width="1"/>
          <text x="${x + 5}" y="${y + 20}" font-size="12" fill="white" font-weight="600">${step.name}</text>
          <title>${step.name} (${step.duration.toFixed(1)}s)</title>
        </g>`;

      // Step label
      html += `<text x="10" y="${y + 20}" font-size="12" fill="#cbd5e1" text-anchor="end">${step.step_id}</text>`;
    });

    // Critical path highlight
    if (this.runData.critical_path && this.runData.critical_path.length > 0) {
      html += `<!-- Critical path indicator -->`;
      this.runData.critical_path.forEach(stepId => {
        const step = steps.find(s => s.step_id === stepId);
        if (step) {
          const stepIndex = steps.indexOf(step);
          const y = 50 + stepIndex * 50;
          const x = 50 + (step.start - minStart) * pixelsPerSecond;
          html += `<rect x="${x - 2}" y="${y - 2}" width="${Math.max(step.duration * pixelsPerSecond + 4, 6)}" height="34" fill="none" stroke="#fbbf24" stroke-width="2" stroke-dasharray="5,5"/>`;
        }
      });
    }

    html += `
        </svg>
      </div>
      <div style="margin-top: 16px; color: #94a3b8; font-size: 12px;">
        <p><strong>Total Duration:</strong> ${this.runData.total_duration?.toFixed(2) || 'N/A'}s</p>
        <p><strong>Steps:</strong> ${steps.length}</p>
        <p><strong>Critical Path:</strong> ${this.runData.critical_path?.length || 0} steps</p>
        <p style="color: #fbbf24;">⬛ Yellow border = Critical path (determines total duration)</p>
      </div>`;

    content.innerHTML = html;
  }

  /**
   * Render waterfall diagram
   */
  showWaterfallChart() {
    const content = document.getElementById("visualizer-content");
    const steps = this.runData.steps;

    if (!steps || steps.length === 0) {
      content.innerHTML = "<p>No steps to display</p>";
      return;
    }

    // Group steps by start time to show parallelism
    const timelineMap = {};
    steps.forEach(step => {
      const bucket = Math.round(step.start * 10) / 10; // Round to 0.1s
      if (!timelineMap[bucket]) {
        timelineMap[bucket] = [];
      }
      timelineMap[bucket].push(step);
    });

    const sortedTimes = Object.keys(timelineMap).map(Number).sort((a, b) => a - b);
    let cumulativeY = 0;
    let html = `<div style="font-size: 13px;">`;

    sortedTimes.forEach((time, timeIndex) => {
      const stepsAtTime = timelineMap[time];
      const maxDuration = Math.max(...stepsAtTime.map(s => s.duration));
      const parallelCount = stepsAtTime.length;

      html += `
        <div style="margin-bottom: 20px;">
          <div style="color: #94a3b8; font-size: 11px; margin-bottom: 6px;">T+${time.toFixed(2)}s (${parallelCount} parallel)</div>
          <div style="display: flex; gap: 4px; flex-wrap: wrap;">`;

      stepsAtTime.forEach(step => {
        const widthPx = Math.max(step.duration * 40, 80);
        const statusColor = this.getStatusColor(step.status);
        html += `
          <div style="
            min-width: ${widthPx}px;
            padding: 8px;
            background: ${statusColor};
            opacity: 0.8;
            border-radius: 4px;
            color: white;
            font-size: 11px;
            text-align: center;
            cursor: pointer;
          " onclick="visualizer.selectStep('${step.step_id}')">
            <div style="font-weight: 600;">${step.name}</div>
            <div style="font-size: 10px;">${step.duration.toFixed(2)}s</div>
          </div>`;
      });

      html += `</div></div>`;
    });

    html += `
        <div style="margin-top: 20px; padding: 12px; background: rgba(59,130,246,0.2); border-radius: 4px; border-left: 3px solid #3b82f6;">
          <p style="color: #60a5fa; font-size: 12px;">
            <strong>Waterfall Overview:</strong> Shows steps in execution order. Parallel steps (same start time) are shown side-by-side.
          </p>
        </div>
      </div>`;

    content.innerHTML = html;
  }

  /**
   * Render performance metrics chart
   */
  showPerformanceChart() {
    const content = document.getElementById("visualizer-content");
    const steps = this.runData.steps;

    if (!steps || steps.length === 0) {
      content.innerHTML = "<p>No steps to display</p>";
      return;
    }

    // Calculate metrics per step
    const metrics = steps.map(step => ({
      name: step.name,
      duration: step.duration,
      status: step.status,
      durationMs: (step.duration * 1000).toFixed(0)
    }));

    // Sort by duration descending
    const sorted = [...metrics].sort((a, b) => b.duration - a.duration);
    const maxDuration = Math.max(...metrics.map(m => m.duration));

    let html = `
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
        <div>
          <h4 style="color: #cbd5e1; margin-bottom: 12px;">⏱️ Step Duration Breakdown</h4>
          <div style="display: flex; flex-direction: column; gap: 8px;">`;

    sorted.forEach(metric => {
      const barWidth = (metric.duration / maxDuration) * 100;
      const statusColor = this.getStatusColor(metric.status);
      html += `
        <div>
          <div style="display: flex; justify-content: space-between; margin-bottom: 4px; font-size: 12px;">
            <span style="color: #cbd5e1;">${metric.name}</span>
            <span style="color: #60a5fa; font-weight: 600;">${metric.durationMs}ms</span>
          </div>
          <div style="background: rgba(148,163,184,0.2); border-radius: 2px; overflow: hidden; height: 16px;">
            <div style="width: ${barWidth}%; height: 100%; background: ${statusColor}; transition: width 0.2s;"></div>
          </div>
        </div>`;
    });

    html += `
          </div>
        </div>

        <div>
          <h4 style="color: #cbd5e1; margin-bottom: 12px;">📊 Key Metrics</h4>
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
            <div style="background: rgba(59,130,246,0.2); padding: 12px; border-radius: 4px; border-left: 3px solid #3b82f6;">
              <div style="font-size: 11px; color: #94a3b8;">Total Duration</div>
              <div style="font-size: 20px; font-weight: 700; color: #60a5fa;">${this.runData.total_duration?.toFixed(2) || 'N/A'}s</div>
            </div>

            <div style="background: rgba(16,185,129,0.2); padding: 12px; border-radius: 4px; border-left: 3px solid #10b981;">
              <div style="font-size: 11px; color: #94a3b8;">Total Steps</div>
              <div style="font-size: 20px; font-weight: 700; color: #10b981;">${steps.length}</div>
            </div>

            <div style="background: rgba(249,115,22,0.2); padding: 12px; border-radius: 4px; border-left: 3px solid #f97316;">
              <div style="font-size: 11px; color: #94a3b8;">Avg Step Duration</div>
              <div style="font-size: 20px; font-weight: 700; color: #f97316;">${(this.runData.total_duration / steps.length).toFixed(2)}s</div>
            </div>

            <div style="background: rgba(139,92,246,0.2); padding: 12px; border-radius: 4px; border-left: 3px solid #8b5cf6;">
              <div style="font-size: 11px; color: #94a3b8;">Slowest Step</div>
              <div style="font-size: 20px; font-weight: 700; color: #8b5cf6;">${maxDuration.toFixed(2)}s</div>
            </div>
          </div>
        </div>
      </div>`;

    content.innerHTML = html;
  }

  /**
   * Show detailed step information
   */
  showStepDetails() {
    const content = document.getElementById("visualizer-content");
    const steps = this.runData.steps;

    if (!steps || steps.length === 0) {
      content.innerHTML = "<p>No steps to display</p>";
      return;
    }

    let html = `
      <div style="display: grid; gap: 12px; max-height: 500px; overflow-y: auto;">`;

    steps.forEach(step => {
      const statusColor = this.getStatusColor(step.status);
      const statusBg = {
        'completed': 'rgba(16,185,129,0.2)',
        'running': 'rgba(59,130,246,0.2)',
        'error': 'rgba(220,38,38,0.2)',
        'pending': 'rgba(148,163,184,0.2)',
        'skipped': 'rgba(107,114,128,0.2)'
      }[step.status] || 'rgba(148,163,184,0.2)';

      html += `
        <div style="
          background: ${statusBg};
          border: 1px solid rgba(148,163,184,0.3);
          border-left: 3px solid ${statusColor};
          border-radius: 4px;
          padding: 12px;
          cursor: pointer;
          transition: transform 0.2s;
        " onclick="visualizer.selectStep('${step.step_id}')" onmouseover="this.style.transform='translateX(4px)'" onmouseout="this.style.transform='translateX(0)'">

          <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 8px;">
            <div>
              <div style="font-weight: 600; color: #cbd5e1;">${step.name}</div>
              <div style="font-size: 11px; color: #94a3b8;">${step.step_id}</div>
            </div>
            <span style="
              background: ${statusColor};
              color: white;
              padding: 4px 8px;
              border-radius: 3px;
              font-size: 10px;
              font-weight: 600;
            ">${step.status.toUpperCase()}</span>
          </div>

          <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; font-size: 11px;">
            <div><span style="color: #94a3b8;">Start:</span> <span style="color: #cbd5e1;">+${step.start.toFixed(2)}s</span></div>
            <div><span style="color: #94a3b8;">Duration:</span> <span style="color: #cbd5e1;">${step.duration.toFixed(2)}s</span></div>
            <div><span style="color: #94a3b8;">Dependencies:</span> <span style="color: #cbd5e1;">${step.dependencies?.length || 0}</span></div>
          </div>

          ${step.error ? `
            <div style="margin-top: 8px; padding: 8px; background: rgba(220,38,38,0.3); border-radius: 3px; color: #fca5a5; font-size: 11px;">
              ⚠️ ${step.error}
            </div>
          ` : ''}

          ${step.dependencies && step.dependencies.length > 0 ? `
            <div style="margin-top: 8px; font-size: 11px; color: #94a3b8;">
              Depends on: <span style="color: #cbd5e1;">${step.dependencies.join(', ')}</span>
            </div>
          ` : ''}
        </div>`;
    });

    html += `</div>`;
    content.innerHTML = html;
  }

  /**
   * Helper: Get color for status
   */
  getStatusColor(status) {
    const colors = {
      'completed': '#10b981',
      'running': '#3b82f6',
      'error': '#dc2626',
      'pending': '#94a3b8',
      'skipped': '#6b7280'
    };
    return colors[status] || '#94a3b8';
  }

  /**
   * Select and highlight a step
   */
  selectStep(stepId) {
    this.selectedStep = stepId;
    // Could add highlighting or detail modal here
    console.log('Selected step:', stepId);
  }
}

// Global instance
var visualizer = null;
function initRunVisualizer(containerId, runId) {
  visualizer = new RunVisualizer(containerId);
  visualizer.loadRun(runId);
}
