// === Crypto Arbitrage Monitor Dashboard ===

const HEARTBEAT_TIMEOUT_MS = 10000; // 10 seconds without heartbeat = stale
const EXCHANGES = ["bithumb", "upbit", "binance", "gate.io", "bybit"];

// State
let lastHeartbeat = Date.now();
let heartbeatTimer = null;
let eventSource = null;
let currentSettingsVersion = 0;
let alertHistory = [];

// === SSE Connection ===

function connectSSE() {
    if (eventSource) {
        eventSource.close();
    }

    eventSource = new EventSource("/api/stream");

    eventSource.addEventListener("spread", (e) => {
        const data = JSON.parse(e.data);
        currentSettingsVersion = data.settings_version;
        renderSpreads(data.spreads);
    });

    eventSource.addEventListener("rate", (e) => {
        const data = JSON.parse(e.data);
        renderRate(data);
    });

    eventSource.addEventListener("status", (e) => {
        const data = JSON.parse(e.data);
        renderExchangeStatus(data.exchanges);
    });

    eventSource.addEventListener("alert", (e) => {
        const data = JSON.parse(e.data);
        handleAlert(data);
    });

    eventSource.addEventListener("heartbeat", (e) => {
        lastHeartbeat = Date.now();
        updateConnectionStatus(true);
    });

    eventSource.onerror = () => {
        updateConnectionStatus(false);
        eventSource.close();
        setTimeout(() => connectSSE(), 3000);
    };

    // Start heartbeat monitoring
    startHeartbeatMonitor();
}

function startHeartbeatMonitor() {
    if (heartbeatTimer) clearInterval(heartbeatTimer);
    heartbeatTimer = setInterval(() => {
        const elapsed = Date.now() - lastHeartbeat;
        if (elapsed > HEARTBEAT_TIMEOUT_MS) {
            updateConnectionStatus(false);
        }
    }, 2000);
}

function updateConnectionStatus(connected) {
    const statusEl = document.getElementById("connection-status");
    const bannerEl = document.getElementById("stale-banner");

    if (connected) {
        statusEl.textContent = "LIVE";
        statusEl.className = "connection-ok";
        bannerEl.classList.add("hidden");
    } else {
        statusEl.textContent = "STALE";
        statusEl.className = "connection-stale";
        bannerEl.classList.remove("hidden");
    }
}

// === Utility: XSS Prevention ===

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// === Render Functions ===

function renderSpreads(spreads) {
    const tbody = document.getElementById("spread-tbody");

    if (!spreads || spreads.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="no-data">임계값 이상의 스프레드 기회가 없습니다</td></tr>';
        return;
    }

    tbody.innerHTML = spreads.map((s) => {
        const spreadClass = s.spread_pct >= 1.0 ? "spread-high" :
                           s.spread_pct > 0 ? "spread-positive" : "spread-negative";
        const buyClass = isBuyDomestic(s.buy_exchange) ? "exchange-domestic" : "exchange-foreign";
        const sellClass = isBuyDomestic(s.sell_exchange) ? "exchange-domestic" : "exchange-foreign";
        const networks = (s.common_networks || []).map(n =>
            `<span class="network-badge">${escapeHtml(n)}</span>`
        ).join("") || '<span class="status-unknown">-</span>';
        const age = getRelativeTime(s.timestamp);

        return `<tr class="${s.spread_pct >= 1.0 ? 'highlight' : ''}">
            <td class="clickable" onclick="showCoinDetail('${escapeHtml(s.symbol)}')">${escapeHtml(s.symbol)}</td>
            <td class="${buyClass}">${escapeHtml(s.buy_exchange)}</td>
            <td class="${sellClass}">${escapeHtml(s.sell_exchange)}</td>
            <td class="price">${formatKRW(s.buy_ask_krw)}</td>
            <td class="price">${formatKRW(s.sell_bid_krw)}</td>
            <td class="${spreadClass}">${s.spread_pct.toFixed(2)}%</td>
            <td>${networks}</td>
            <td class="age">${age}</td>
        </tr>`;
    }).join("");
}

function renderRate(rate) {
    const rateEl = document.getElementById("exchange-rate");
    const ageEl = document.getElementById("rate-age");

    rateEl.textContent = `₩${formatNumber(rate.krw_per_usdt)}`;
    if (rate.is_stale) {
        rateEl.style.color = "#da3633";
        ageEl.textContent = "(stale)";
    } else {
        rateEl.style.color = "#f0883e";
        ageEl.textContent = `(${rate.source})`;
    }
}

function renderExchangeStatus(exchanges) {
    const container = document.getElementById("exchange-indicators");

    // Only render once, then update dots
    if (container.children.length === 0) {
        container.innerHTML = EXCHANGES.map(name => `
            <div class="exchange-indicator">
                <span class="indicator-dot" id="dot-${name}"></span>
                <span>${name}</span>
            </div>
        `).join("");
    }

    for (const name of EXCHANGES) {
        const dot = document.getElementById(`dot-${name}`);
        if (dot) {
            const status = exchanges[name];
            dot.className = `indicator-dot ${status === "connected" ? "connected" : ""}`;
        }
    }
}

function handleAlert(alert) {
    // Play sound
    playAlertSound();

    // Add to history
    alertHistory.unshift(alert);
    if (alertHistory.length > 50) alertHistory.pop();

    renderAlertLog();
}

function renderAlertLog() {
    const logEl = document.getElementById("alert-log");
    const countEl = document.getElementById("alert-count");

    countEl.textContent = `(${alertHistory.length})`;

    logEl.innerHTML = alertHistory.map(a => {
        const time = new Date(a.triggered_at).toLocaleTimeString("ko-KR");
        return `<div class="alert-item">
            <span>
                <span class="alert-symbol">${escapeHtml(a.symbol)}</span>
                ${escapeHtml(a.buy_exchange)} → ${escapeHtml(a.sell_exchange)}
            </span>
            <span class="alert-spread">${a.spread_pct.toFixed(2)}%</span>
            <span class="alert-time">${time}</span>
        </div>`;
    }).join("");
}

function playAlertSound() {
    try {
        const audio = document.getElementById("alert-sound");
        audio.currentTime = 0;
        audio.play().catch(() => {
            // Browser may block autoplay - user interaction needed first
        });
    } catch (e) {
        // Ignore audio errors
    }
}

// === Side Panel ===

async function showCoinDetail(symbol) {
    const panel = document.getElementById("side-panel");
    const title = document.getElementById("panel-title");
    const content = document.getElementById("panel-content");

    title.textContent = `${symbol} 상세`;
    panel.classList.remove("hidden");
    content.innerHTML = '<p class="no-data">로딩 중...</p>';

    try {
        // Fetch coin status
        const statusRes = await fetch(`/api/coin-status/${symbol}`);
        let statusHtml = "";

        if (statusRes.ok) {
            const statusData = await statusRes.json();
            statusHtml = renderCoinStatusPanel(statusData);
        } else {
            statusHtml = '<p class="status-unknown">입출금 데이터를 가져올 수 없습니다</p>';
        }

        // Fetch Gate.io loan info
        let loanHtml = "";
        try {
            const loanRes = await fetch("/api/gate-loans");
            if (loanRes.ok) {
                const loanData = await loanRes.json();
                const loan = loanData.loans.find(l => l.symbol === symbol);
                if (loan) {
                    loanHtml = `
                        <div class="panel-section">
                            <h4>Gate.io 마진 대출</h4>
                            <table class="status-table">
                                <tr><td>대출 가능</td><td class="${loan.loanable ? 'status-ok' : 'status-fail'}">${loan.loanable ? '가능' : '불가'}</td></tr>
                                ${loan.rate ? `<tr><td>이율</td><td>${(loan.rate * 100).toFixed(4)}%/일</td></tr>` : ""}
                            </table>
                        </div>`;
                } else {
                    loanHtml = `
                        <div class="panel-section">
                            <h4>Gate.io 마진 대출</h4>
                            <p class="status-unknown">${symbol}은(는) 대출 불가</p>
                        </div>`;
                }
            }
        } catch (e) {
            loanHtml = "";
        }

        content.innerHTML = statusHtml + loanHtml;
    } catch (e) {
        content.innerHTML = '<p class="status-unknown">데이터 로딩 실패</p>';
    }
}

function renderCoinStatusPanel(data) {
    let html = '<div class="panel-section"><h4>거래소 상태</h4><table class="status-table">';
    html += "<tr><th>거래소</th><th>입금</th><th>출금</th><th>네트워크</th></tr>";

    for (const [name, info] of Object.entries(data.exchanges)) {
        const dep = info.deposit_enabled === true ? '<span class="status-ok">가능</span>' :
                    info.deposit_enabled === false ? '<span class="status-fail">중지</span>' :
                    '<span class="status-unknown">미확인</span>';
        const wd = info.withdraw_enabled === true ? '<span class="status-ok">가능</span>' :
                   info.withdraw_enabled === false ? '<span class="status-fail">중지</span>' :
                   '<span class="status-unknown">미확인</span>';
        const nets = (info.networks || []).map(n => `<span class="network-badge">${escapeHtml(n)}</span>`).join("") || "-";

        html += `<tr><td>${escapeHtml(name)}</td><td>${dep}</td><td>${wd}</td><td>${nets}</td></tr>`;
    }

    html += "</table></div>";
    return html;
}

function closePanel() {
    document.getElementById("side-panel").classList.add("hidden");
}

// === Settings ===

function openSettings() {
    document.getElementById("settings-modal").classList.remove("hidden");

    // Load current settings
    fetch("/api/settings")
        .then(r => r.json())
        .then(s => {
            document.getElementById("setting-threshold").value = s.threshold_pct;
            document.getElementById("setting-deposit").checked = s.filter_deposit_withdraw;
            document.getElementById("setting-network").checked = s.filter_common_network;
        })
        .catch(() => {});
}

function closeSettings() {
    document.getElementById("settings-modal").classList.add("hidden");
}

async function saveSettings() {
    const body = {
        threshold_pct: parseFloat(document.getElementById("setting-threshold").value),
        filter_deposit_withdraw: document.getElementById("setting-deposit").checked,
        filter_common_network: document.getElementById("setting-network").checked,
    };

    try {
        const res = await fetch("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });

        if (res.ok) {
            const updated = await res.json();
            // Update inline controls
            document.getElementById("threshold-input").value = updated.threshold_pct;
            document.getElementById("filter-deposit").checked = updated.filter_deposit_withdraw;
            document.getElementById("filter-network").checked = updated.filter_common_network;
            closeSettings();
        }
    } catch (e) {
        alert("설정 저장에 실패했습니다. 다시 시도해주세요.");
    }
}

// Inline controls change handler
function setupInlineControls() {
    const thresholdInput = document.getElementById("threshold-input");
    const depositCheck = document.getElementById("filter-deposit");
    const networkCheck = document.getElementById("filter-network");

    let debounceTimer = null;

    function pushSettings() {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            fetch("/api/settings", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    threshold_pct: parseFloat(thresholdInput.value) || 0.5,
                    filter_deposit_withdraw: depositCheck.checked,
                    filter_common_network: networkCheck.checked,
                }),
            })
            .then(r => r.json())
            .then(s => {
                document.getElementById("setting-threshold").value = s.threshold_pct;
                document.getElementById("setting-deposit").checked = s.filter_deposit_withdraw;
                document.getElementById("setting-network").checked = s.filter_common_network;
            });
        }, 500);
    }

    thresholdInput.addEventListener("input", pushSettings);
    depositCheck.addEventListener("change", pushSettings);
    networkCheck.addEventListener("change", pushSettings);
}

// === Utility Functions ===

function formatKRW(value) {
    if (!value && value !== 0) return "-";
    return "₩" + Math.round(value).toLocaleString("ko-KR");
}

function formatNumber(value) {
    if (!value && value !== 0) return "-";
    return Math.round(value).toLocaleString("ko-KR");
}

function isBuyDomestic(name) {
    return ["bithumb", "upbit"].includes(name.toLowerCase());
}

function getRelativeTime(timestamp) {
    if (!timestamp) return "-";
    const now = Date.now();
    const then = new Date(timestamp).getTime();
    const diff = Math.floor((now - then) / 1000);

    if (diff < 5) return "방금";
    if (diff < 60) return `${diff}초 전`;
    if (diff < 3600) return `${Math.floor(diff / 60)}분 전`;
    return `${Math.floor(diff / 3600)}시간 전`;
}

// === Initialize ===

document.addEventListener("DOMContentLoaded", () => {
    connectSSE();
    setupInlineControls();

    // Load initial settings
    fetch("/api/settings")
        .then(r => r.json())
        .then(s => {
            document.getElementById("threshold-input").value = s.threshold_pct;
            document.getElementById("filter-deposit").checked = s.filter_deposit_withdraw;
            document.getElementById("filter-network").checked = s.filter_common_network;
        })
        .catch(() => {});
});
