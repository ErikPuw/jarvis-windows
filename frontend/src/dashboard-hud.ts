export function generateResourcesHTML(cpuPct: number, ramPct: number, ramUsed: string, ramTotal: string, gpuHtml: string): string {
  return `
    <div class="hud-label">Resources</div>
    <div class="hud-row" id="hud-cpu-row"><span>CPU</span><span class="hud-val">${cpuPct}%</span></div>
    <div class="hud-row" id="hud-ram-row"><span>RAM</span><span class="hud-val">${ramPct}% · ${ramUsed}/${ramTotal}GB</span></div>
    ${gpuHtml}
  `;
}

export function generateSystemsHTML(intelligenceCoreOk: boolean, serverEngineOk: boolean, llmServerOk: boolean, ttsServerOk: boolean): string {
  return `
    <div class="hud-label">Systems</div>
    <div class="hud-row"><span>Core Engine</span><div class="hud-dot ${intelligenceCoreOk ? 'active' : 'error'}"></div></div>
    <div class="hud-row"><span>Engine Server</span><div class="hud-dot ${serverEngineOk ? 'active' : 'error'}"></div></div>
    <div class="hud-row"><span>LLM Server</span><div class="hud-dot ${llmServerOk ? 'active' : 'error'}"></div></div>
    <div class="hud-row"><span>TTS Server</span><div class="hud-dot ${ttsServerOk ? 'active' : 'error'}"></div></div>
  `;
}
