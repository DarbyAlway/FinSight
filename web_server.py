from flask import Flask, render_template_string, jsonify
from monitoring import init_db, get_all_turns

app = Flask(__name__)
init_db()

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Agent Monitoring Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
            background: #f0f2f5;
            padding: 24px;
            color: #333;
        }

        .container { max-width: 1100px; margin: 0 auto; }

        h1 { font-size: 24px; font-weight: 700; margin-bottom: 20px; color: #1a1a2e; }

        .toolbar {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 20px;
        }

        .btn {
            background: #4361ee;
            color: white;
            padding: 8px 18px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 13px;
            font-weight: 500;
        }
        .btn:hover { background: #3a0ca3; }

        .turn-list { display: flex; flex-direction: column; gap: 10px; }

        .turn-card {
            background: white;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }

        .turn-summary {
            padding: 14px 18px;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
            transition: background 0.15s;
        }
        .turn-summary:hover { background: #f7f8ff; }

        .turn-left { flex: 1; }
        .turn-ts { font-size: 11px; color: #888; margin-bottom: 4px; }
        .turn-query { font-weight: 600; font-size: 14px; color: #1a1a2e; margin-bottom: 6px; }
        .turn-pills { display: flex; gap: 8px; flex-wrap: wrap; }

        .pill {
            font-size: 11px;
            padding: 2px 8px;
            border-radius: 12px;
            font-weight: 500;
        }
        .pill-blue { background: #e8f0fe; color: #4361ee; }
        .pill-green { background: #e8f5e9; color: #2e7d32; }
        .pill-gray { background: #f0f0f0; color: #666; }
        .pill-orange { background: #fff3e0; color: #e65100; font-weight: 600; }

        .token-badge {
            display: inline-block;
            background: #fff3e0;
            color: #e65100;
            font-size: 10px;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 10px;
            margin-left: 6px;
        }

        .token-breakdown {
            display: flex;
            gap: 16px;
            flex-wrap: wrap;
            margin-top: 6px;
        }

        .token-stat {
            display: flex;
            flex-direction: column;
            align-items: center;
            background: #fff8f0;
            border: 1px solid #ffe0b2;
            border-radius: 6px;
            padding: 8px 14px;
            min-width: 90px;
        }

        .token-stat-value {
            font-size: 18px;
            font-weight: 700;
            color: #e65100;
        }

        .token-stat-label {
            font-size: 10px;
            color: #999;
            text-transform: uppercase;
            margin-top: 2px;
        }

        .toggle-icon { font-size: 12px; color: #aaa; transition: transform 0.2s; }
        .toggle-icon.open { transform: rotate(90deg); }

        .turn-details { display: none; border-top: 1px solid #f0f0f0; }
        .turn-details.active { display: block; }

        .detail-section { padding: 16px 18px; border-bottom: 1px solid #f5f5f5; }
        .detail-section:last-child { border-bottom: none; }

        .section-label {
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #888;
            margin-bottom: 8px;
        }

        .code-block {
            background: #f8f9fa;
            border: 1px solid #e8e8e8;
            border-radius: 6px;
            padding: 12px;
            font-family: 'Courier New', monospace;
            font-size: 12px;
            line-height: 1.5;
            white-space: pre-wrap;
            word-break: break-word;
            max-height: 300px;
            overflow-y: auto;
        }

        .agent-block {
            border: 1px solid #e0e0e0;
            border-radius: 6px;
            margin-bottom: 10px;
            overflow: hidden;
        }

        .agent-header {
            background: #f5f7ff;
            padding: 10px 14px;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .agent-header:hover { background: #edf0ff; }

        .agent-name { font-weight: 600; font-size: 13px; color: #4361ee; }
        .agent-meta { font-size: 11px; color: #999; }

        .agent-body { display: none; padding: 14px; border-top: 1px solid #e8e8e8; }
        .agent-body.active { display: block; }

        .subsection-label {
            font-size: 11px;
            font-weight: 600;
            color: #666;
            margin: 12px 0 6px;
        }
        .subsection-label:first-child { margin-top: 0; }

        .tool-block {
            border: 1px solid #eee;
            border-radius: 4px;
            margin-bottom: 6px;
            overflow: hidden;
        }

        .tool-header {
            background: #fafafa;
            padding: 8px 12px;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 12px;
        }
        .tool-header:hover { background: #f0f0f0; }

        .tool-name { font-weight: 600; color: #333; }
        .tool-meta { color: #999; font-size: 11px; }

        .tool-body { display: none; padding: 10px 12px; border-top: 1px solid #eee; }
        .tool-body.active { display: block; }

        .tool-args {
            background: #f8f9fa;
            border-radius: 4px;
            padding: 8px;
            font-family: 'Courier New', monospace;
            font-size: 11px;
            line-height: 1.4;
            white-space: pre-wrap;
            word-break: break-word;
            max-height: 150px;
            overflow-y: auto;
        }

        .error-text { color: #c62828; font-size: 11px; margin-top: 6px; }
        .cache-badge { color: #2e7d32; font-weight: 500; }
        .uncache-badge { color: #888; }

        .empty {
            text-align: center;
            padding: 60px 20px;
            color: #aaa;
            font-size: 15px;
        }
    </style>
</head>
<body>
<div class="container">
    <h1>Agent Monitoring Dashboard</h1>
    <div class="toolbar">
        <button class="btn" onclick="location.reload()">&#8635; Refresh</button>
        <span id="turn-count" style="font-size: 13px; color: #888;"></span>
    </div>
    <div id="turns-container" class="turn-list"></div>
    <div id="empty-state" class="empty" style="display:none;">
        No turns recorded yet. Ask a question in the stock assistant and refresh.
    </div>
</div>

<script>
function esc(str) {
    if (!str) return '';
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

function fmt_ms(ms) {
    if (ms == null) return 'N/A';
    return (ms / 1000).toFixed(2) + 's';
}

function toggle(id, icon) {
    const el = document.getElementById(id);
    el.classList.toggle('active');
    if (icon) icon.classList.toggle('open');
    return false;
}

async function loadTurns() {
    const res = await fetch('/api/turns');
    const turns = await res.json();

    const container = document.getElementById('turns-container');
    const empty = document.getElementById('empty-state');
    const countEl = document.getElementById('turn-count');

    if (!turns.length) {
        container.style.display = 'none';
        empty.style.display = 'block';
        return;
    }

    countEl.textContent = turns.length + ' turn' + (turns.length !== 1 ? 's' : '');

    container.innerHTML = turns.map((turn, i) => {
        const agentNames = (turn.agents_called || []).join(', ') || 'none';
        const agentCount = (turn.agents || []).length;

        const agentsHtml = (turn.agents || []).map((agent, ai) => {
            const toolsHtml = (agent.tools || []).map((tool, ti) => {
                const tid = `tool-${i}-${ai}-${ti}`;
                const cacheLabel = tool.cache_hit
                    ? '<span class="cache-badge">&#10003; cached</span>'
                    : '<span class="uncache-badge">uncached</span>';
                return `
                    <div class="tool-block">
                        <div class="tool-header" onclick="toggle('${tid}', this.querySelector('.toggle-icon'))">
                            <span class="tool-name">${esc(tool.tool_name)}</span>
                            <span style="display:flex;gap:10px;align-items:center;">
                                <span class="tool-meta">${fmt_ms(tool.duration_ms)} &bull; ${cacheLabel}${tool.error ? ' &bull; <span style="color:#c62828">error</span>' : ''}</span>
                                <span class="toggle-icon">&#9658;</span>
                            </span>
                        </div>
                        <div class="tool-body" id="${tid}">
                            <div style="font-size:11px;font-weight:600;color:#666;margin-bottom:4px;">Arguments</div>
                            <div class="tool-args">${esc(JSON.stringify(tool.arguments, null, 2))}</div>
                            ${tool.result ? `
                                <div style="font-size:11px;font-weight:600;color:#666;margin:8px 0 4px;">Response</div>
                                <div class="tool-args" style="max-height:200px;border-left:3px solid #4361ee;">${esc(tool.result)}</div>
                            ` : ''}
                            ${tool.error ? `<div class="error-text">Error: ${esc(tool.error)}</div>` : ''}
                        </div>
                    </div>`;
            }).join('');

            const abid = `agent-${i}-${ai}`;
            return `
                <div class="agent-block">
                    <div class="agent-header" onclick="toggle('${abid}', this.querySelector('.toggle-icon'))">
                        <div>
                            <span class="agent-name">${esc(agent.agent_name)}</span>
                            <span class="agent-meta" style="margin-left:10px;">
                                ${fmt_ms(agent.duration_ms)}
                                &bull; ${(agent.tools || []).length} tools
                            </span>
                            ${agent.tokens ? `<span class="token-badge">${agent.tokens.toLocaleString()} tok</span>` : ''}
                        </div>
                        <span class="toggle-icon">&#9658;</span>
                    </div>
                    <div class="agent-body" id="${abid}">
                        ${agent.output ? `
                            <div class="subsection-label">Output</div>
                            <div class="code-block">${esc(agent.output)}</div>
                        ` : '<div style="color:#aaa;font-size:12px;">No output</div>'}
                        ${toolsHtml ? `
                            <div class="subsection-label" style="margin-top:14px;">Tools Called</div>
                            ${toolsHtml}
                        ` : ''}
                    </div>
                </div>`;
        }).join('');

        const did = `details-${i}`;
        const iid = `icon-${i}`;
        return `
            <div class="turn-card">
                <div class="turn-summary" onclick="toggle('${did}', document.getElementById('${iid}'))">
                    <div class="turn-left">
                        <div class="turn-ts">${new Date(turn.timestamp + 'Z').toLocaleString()}</div>
                        <div class="turn-query">${esc(turn.user_query.substring(0, 120))}${turn.user_query.length > 120 ? '...' : ''}</div>
                        <div class="turn-pills">
                            <span class="pill pill-blue">${agentCount} agent${agentCount !== 1 ? 's' : ''}</span>
                            <span class="pill pill-green">${fmt_ms(turn.total_duration_ms)}</span>
                            ${turn.total_tokens ? `<span class="pill pill-orange">${turn.total_tokens.toLocaleString()} tokens</span>` : ''}
                        </div>
                    </div>
                    <span class="toggle-icon" id="${iid}">&#9658;</span>
                </div>

                <div class="turn-details" id="${did}">
                    <div class="detail-section">
                        <div class="section-label">User Query</div>
                        <div class="code-block">${esc(turn.user_query)}</div>
                    </div>

                    ${turn.orchestrator_plan ? `
                        <div class="detail-section">
                            <div class="section-label">Orchestrator Plan</div>
                            <div class="code-block">${esc(turn.orchestrator_plan)}</div>
                        </div>
                    ` : ''}

                    <div class="detail-section">
                        <div class="section-label">Agents (${agentCount})</div>
                        ${agentsHtml || '<div style="color:#aaa;font-size:12px;">No agents called</div>'}
                    </div>

                    ${(turn.total_tokens || (turn.agents || []).some(a => a.tokens)) ? `
                        <div class="detail-section">
                            <div class="section-label">Token Usage</div>
                            <div class="token-breakdown">
                                ${(turn.agents || []).filter(a => a.tokens).map(a => `
                                    <div class="token-stat">
                                        <div class="token-stat-value">${a.tokens.toLocaleString()}</div>
                                        <div class="token-stat-label">${esc(a.agent_name)}</div>
                                    </div>
                                `).join('')}
                                ${turn.total_tokens ? `
                                    <div class="token-stat" style="border-color:#ff8f00;background:#fff3e0;">
                                        <div class="token-stat-value">${turn.total_tokens.toLocaleString()}</div>
                                        <div class="token-stat-label">Total</div>
                                    </div>
                                ` : ''}
                            </div>
                        </div>
                    ` : ''}

                    ${turn.synthesis_output ? `
                        <div class="detail-section">
                            <div class="section-label">Synthesis Output</div>
                            <div class="code-block">${esc(turn.synthesis_output)}</div>
                        </div>
                    ` : ''}
                </div>
            </div>`;
    }).join('');
}

loadTurns();
</script>
</body>
</html>
"""


@app.route('/')
def dashboard():
    return render_template_string(DASHBOARD_HTML)


@app.route('/api/turns')
def api_turns():
    turns = get_all_turns()
    return jsonify([dict(t) for t in turns])


if __name__ == '__main__':
    print("Agent Monitoring Dashboard → http://localhost:5000")
    app.run(debug=False, port=5000, host='127.0.0.1')
